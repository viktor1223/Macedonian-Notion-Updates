"""
Enrich Notion CSV export by filling in 'Position in a sentence', 'Category',
and other fields for each row, then save an updated CSV ready for push-to-Notion.

Strategy:
  1. Dictionary lookup (kaikki.org Macedonian Wiktionary extract) — provides
     POS, gender, English gloss, romanization, and forms with ZERO API calls.
  2. LLM fallback (GPT-4o) — only used for Category, Level, and words not
     found in the dictionary.

Requirements:
    pip install openai python-dotenv

Usage:
    python enrich_csv.py                          # uses latest export in output/
    python enrich_csv.py output/my_export.csv     # explicit file
    python enrich_csv.py --no-ai                  # dictionary-only, skip LLM
"""

import csv
import json
import os
import sys
import subprocess
from pathlib import Path
from datetime import datetime

from dotenv import load_dotenv
from openai import OpenAI

load_dotenv()

# ---------------------------------------------------------------------------
# Dictionary lookup (kaikki.org — no API calls)
# ---------------------------------------------------------------------------

DICTIONARY_PATH = Path(__file__).parent / "sources" / "dictionaries" / "mk_kaikki_dictionary.json"
ENGLISH_INDEX_PATH = Path(__file__).parent / "sources" / "dictionaries" / "mk_english_reverse_index.json"

_dictionary_cache: dict | None = None
_english_index_cache: dict | None = None


def load_english_index() -> dict:
    """Load English→Macedonian reverse index (lazy, cached)."""
    global _english_index_cache
    if _english_index_cache is not None:
        return _english_index_cache

    if not ENGLISH_INDEX_PATH.exists():
        print("  ⚠ English reverse index not found. Run: python build_dictionary.py")
        _english_index_cache = {}
        return _english_index_cache

    with open(ENGLISH_INDEX_PATH, "r", encoding="utf-8") as f:
        _english_index_cache = json.load(f)

    print(f"  English index loaded: {len(_english_index_cache)} entries")
    return _english_index_cache


def english_lookup(english: str) -> dict | None:
    """Look up an English word/phrase in the reverse index.

    Returns dict with keys: mk, pos, gender (if applicable).
    Returns None if not found.
    """
    idx = load_english_index()
    if not idx:
        return None

    import re
    key = english.strip().lower()
    # Normalize same way as build_dictionary
    key = re.sub(r"\s*\([^)]*\)", "", key)
    if key.startswith("to "):
        key = key[3:]
    if ", " in key:
        key = key.split(", ")[0]
    key = key.strip()

    return idx.get(key)


def load_dictionary() -> dict:
    """Load the kaikki.org dictionary into memory (lazy, cached)."""
    global _dictionary_cache
    if _dictionary_cache is not None:
        return _dictionary_cache

    if not DICTIONARY_PATH.exists():
        print("  ⚠ Dictionary not found. Run: python build_dictionary.py")
        _dictionary_cache = {}
        return _dictionary_cache

    with open(DICTIONARY_PATH, "r", encoding="utf-8") as f:
        _dictionary_cache = json.load(f)

    print(f"  Dictionary loaded: {len(_dictionary_cache)} words")
    return _dictionary_cache


def dict_lookup(word: str) -> dict | None:
    """Look up a Macedonian word in the dictionary.

    Tries exact match first, then strips common inflections (definite articles,
    verb conjugation) to find the lemma.

    Returns dict with keys: pos, gender, english, roman, forms, aspect, etc.
    Returns None if word not found.
    """
    d = load_dictionary()
    if not d:
        return None

    key = word.strip().lower()
    entry = d.get(key)
    if entry is not None:
        if isinstance(entry, list):
            return entry[0]
        return entry

    # Try desinflection for single words too
    lemma_entry, _ = _try_desinflect(key, d)
    return lemma_entry


# Function words to ignore when extracting head word from phrases.
# These don't contribute to POS classification.
_MK_STOP_WORDS = {
    # Particles
    "ќе", "не", "да", "се", "си", "ли", "ни", "ми", "ти", "му", "ѝ",
    "го", "ја", "ги", "нè", "ве",
    # Prepositions
    "на", "во", "со", "за", "од", "до", "по", "при", "без", "над",
    "под", "меѓу", "кон", "низ", "пред", "зад", "покрај",
    # Demonstratives / determiners
    "овој", "оваа", "ова", "овие", "тој", "таа", "тоа", "тие",
    "оној", "онаа", "она", "оние",
    # Conjunctions
    "и", "или", "но", "а", "ни", "ниту",
    # Common modifiers that don't change the head-word POS
    "многу", "малку", "повеќе", "помалку",
    # Possessives
    "мој", "моја", "мое", "мои", "твој", "твоја", "твое", "твои",
    "негов", "нејзин", "наш", "ваш", "нивен",
    # "To be" forms
    "сум", "си", "е", "сме", "сте", "се",
    # Question words (these ARE meaningful but for phrase POS extraction we skip them)
    "што", "кој", "која", "кое", "кои", "каде", "кога", "како", "зошто", "колку",
}


def phrase_lookup(phrase: str) -> tuple[dict | None, str | None]:
    """Look up a multi-word phrase by extracting the head (content) word.

    Strategy:
      1. Try the full phrase as-is in the dictionary.
      2. Strip stop words (articles, particles, prepositions, etc.)
      3. Look up remaining words right-to-left (head noun is usually last).
      4. If a word isn't found, try stripping common Macedonian suffixes
         (definite articles, verb conjugation endings).

    Returns (entry, head_word) or (None, None).
    """
    d = load_dictionary()
    if not d:
        return None, None

    # Try full phrase first
    key = phrase.strip().lower()
    entry = d.get(key)
    if entry:
        if isinstance(entry, list):
            entry = entry[0]
        return entry, key

    # Split and filter stop words
    words = key.split()
    if len(words) < 2:
        return None, None

    content_words = [w for w in words if w not in _MK_STOP_WORDS]
    if not content_words:
        return None, None

    # Look up right-to-left (Macedonian head noun tends to be rightmost)
    for w in reversed(content_words):
        entry = d.get(w)
        if entry:
            if isinstance(entry, list):
                entry = entry[0]
            return entry, w
        # Try stripping inflections to find lemma
        lemma_entry, lemma = _try_desinflect(w, d)
        if lemma_entry:
            return lemma_entry, lemma

    return None, None


# Common Macedonian suffixes to strip (ordered longest-first for greedy match)
_DEFINITE_SUFFIXES = [
    # Definite article suffixes (noun/adjective)
    "ата", "ото", "ите", "ава", "ово", "иве", "ана", "оно", "ине",
    "от", "та", "то", "те", "ов", "ва", "во", "ве", "он", "на", "но", "не",
]
_VERB_SUFFIXES = [
    # Present tense endings
    "ам", "аш", "а", "аме", "ате", "ат",
    "ам", "иш", "и", "име", "ите", "ат",
    "ем", "еш", "е", "еме", "ете", "ат",
]


def _try_desinflect(word: str, d: dict) -> tuple[dict | None, str | None]:
    """Try to strip common suffixes to find the lemma in the dictionary."""
    # Try definite suffixes (e.g., часот → час)
    for suffix in _DEFINITE_SUFFIXES:
        if word.endswith(suffix) and len(word) > len(suffix) + 1:
            stem = word[:-len(suffix)]
            entry = d.get(stem)
            if entry:
                if isinstance(entry, list):
                    entry = entry[0]
                return entry, stem

    # Try verb endings → look for common verb base forms
    for suffix in _VERB_SUFFIXES:
        if word.endswith(suffix) and len(word) > len(suffix) + 1:
            stem = word[:-len(suffix)]
            # Try stem + common infinitive-like endings
            for base_suffix in ["а", "и", "е", ""]:
                candidate = stem + base_suffix
                entry = d.get(candidate)
                if entry:
                    if isinstance(entry, list):
                        entry = entry[0]
                    if entry.get("pos") == "Verb":
                        return entry, candidate

    return None, None

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------

# ---------------------------------------------------------------------------
# Schema — keep in sync with update_notion_schema.py
# ---------------------------------------------------------------------------

VALID_POSITIONS = [
    "Noun",
    "Pronoun",
    "Verb",
    "Adjective",
    "Adverb",
    "Expression",
    "Question words",
    "Number",
    "Particle",
    "Conjunction",
    "Preposition",
    "Interjection",
]

VALID_CATEGORIES = [
    # Core conversation
    "Greetings & Farewells",
    "Introductions",
    "Questions",
    "Common Phrases",
    # Numbers & counting
    "Numbers & Quantities",
    # Time (granular — assign as many as fit)
    "Months",
    "Days of the Week",
    "Seasons",
    "Time of Day",
    "Time Expressions",
    "Dates & Calendar",
    # Describing the world
    "Colors",
    "Size & Shape",
    "Quantity & Amount",
    "Weather",
    "Nature & Animals",
    # People & identity
    "Family & Relationships",
    "Body & Health",
    "Feelings & Emotions",
    "Personality & Character",
    "Age & Life Stages",
    # Daily life
    "Food & Drink",
    "Home & Housing",
    "Clothing & Appearance",
    "Shopping & Money",
    "Work & Jobs",
    "School & Education",
    "Daily Routine",
    # Getting around
    "Transport & Travel",
    "Directions & Places",
    "Countries & Nationalities",
    "City & Neighborhood",
    # Communication & media
    "Music & Arts",
    "Technology & Internet",
    "Reading & Writing",
    # Language building blocks
    "Core Verbs",
    "Conjunctions & Connectors",
    "Pronouns & Determiners",
    "Prepositions & Location",
    "Adverbs & Frequency",
]

VALID_LEVELS = ["A1", "A2", "B1", "B2", "C1"]

SYSTEM_PROMPT = f"""You are a Macedonian-language teaching assistant.
Given an English phrase and/or its Macedonian translation (Cyrillic or Latin),
return the best grammatical position(s), thematic category/categories, CEFR
difficulty level, English translation, and Latin transliteration from the
lists below.

VALID POSITIONS (pick 1-3, most specific first):
{json.dumps(VALID_POSITIONS, indent=2)}

VALID CATEGORIES (pick 1-5, assign ALL that apply — be generous):
{json.dumps(VALID_CATEGORIES, indent=2)}

Category assignment guidance:
- Months (јануари, февруари, etc.) → ["Months", "Dates & Calendar"]
- Days of the week (понеделник, вторник, etc.) → ["Days of the Week", "Dates & Calendar"]
- Seasons (пролет, лето, etc.) → ["Seasons", "Nature & Animals"]
- Time words (утре, вчера, рано, доцна, etc.) → ["Time Expressions"]
- Time of day (утро, вечер, ноќ, etc.) → ["Time of Day", "Time Expressions"]
- Weather (дожд, сонце, ветер, etc.) → ["Weather", "Nature & Animals"]
- Animals → ["Nature & Animals"]
- Frequency adverbs (секогаш, понекогаш, etc.) → ["Adverbs & Frequency", "Time Expressions"]
- Verbs → always include "Core Verbs" alongside any thematic category
- Assign MULTIPLE categories when a word fits more than one lesson topic

VALID LEVELS — CEFR scale (pick exactly 1):
  A1 = absolute beginner: numbers, basic colors, hello/bye, I am ___
  A2 = beginner: simple past, shopping, food, family
  B1 = intermediate: opinions, travel, health, work
  B2 = upper-intermediate: abstract topics, nuance
  C1 = advanced: idioms, complex grammar

Rules:
- Only return values from the VALID POSITIONS and VALID CATEGORIES lists — no other values for those fields.
- Return a JSON object with exactly five keys:
    "position": [list of chosen positions]
    "category": [list of chosen categories]
    "level": "A1" | "A2" | "B1" | "B2" | "C1"
    "english": "English translation of the word/phrase"
    "latin": "Macedonian word written in Latin script transliteration"
- If the English is already provided, return it as-is in the "english" field.
- If the Latin transliteration is already provided, return it as-is in the "latin" field.
- For transliteration use standard Macedonian romanization (e.g. ш=sh, ч=ch, ж=zh, ѓ=gj, ќ=kj, ѕ=dz, џ=dzh, љ=lj, њ=nj, ј=j).
- Do not include explanations.
"""

OUTPUT_DIR = Path(__file__).parent / "output"


# ---------------------------------------------------------------------------
# AI Client — prefers Azure OpenAI, falls back to GitHub Models
# ---------------------------------------------------------------------------

def get_github_token() -> str:
    token = os.getenv("GITHUB_TOKEN")
    if token:
        return token
    result = subprocess.run(
        ["gh", "auth", "token"], capture_output=True, text=True
    )
    if result.returncode == 0:
        return result.stdout.strip()
    raise EnvironmentError(
        "Could not obtain a GitHub token. Run `gh auth login` or set GITHUB_TOKEN."
    )


def build_client(token: str) -> OpenAI:
    """Build OpenAI client — uses Azure OpenAI if configured, else GitHub Models."""
    account_name = os.getenv("AZURE_OPENAI_ACCOUNT_NAME")
    resource_group = os.getenv("AZURE_OPENAI_RESOURCE_GROUP")

    if account_name and resource_group:
        from openai import AzureOpenAI

        # Fetch endpoint dynamically
        endpoint_result = subprocess.run(
            ["az", "cognitiveservices", "account", "show",
             "--name", account_name,
             "--resource-group", resource_group,
             "--query", "properties.endpoint", "-o", "tsv"],
            capture_output=True, text=True
        )
        if endpoint_result.returncode != 0:
            raise EnvironmentError(
                f"Failed to get Azure OpenAI endpoint. Run `az login` first.\n"
                f"  Error: {endpoint_result.stderr.strip()}"
            )
        azure_endpoint = endpoint_result.stdout.strip()

        # Fetch API key dynamically (never stored on disk)
        key_result = subprocess.run(
            ["az", "cognitiveservices", "account", "keys", "list",
             "--name", account_name,
             "--resource-group", resource_group,
             "--query", "key1", "-o", "tsv"],
            capture_output=True, text=True
        )
        if key_result.returncode != 0:
            raise EnvironmentError(
                f"Failed to get Azure OpenAI key. Run `az login` first.\n"
                f"  Error: {key_result.stderr.strip()}"
            )
        azure_key = key_result.stdout.strip()

        print(f"Using Azure OpenAI: {account_name} (key fetched via az CLI)")
        return AzureOpenAI(
            azure_endpoint=azure_endpoint,
            api_key=azure_key,
            api_version="2024-12-01-preview",
        )

    print("Using GitHub Models endpoint (450 calls/day limit)")
    return OpenAI(
        base_url="https://models.inference.ai.azure.com",
        api_key=token,
    )


def get_model_name() -> str:
    """Return the deployment/model name to use."""
    deployment = os.getenv("AZURE_OPENAI_DEPLOYMENT")
    if deployment and os.getenv("AZURE_OPENAI_ENDPOINT"):
        return deployment
    return "gpt-4o-mini"


# ---------------------------------------------------------------------------
# Classification
# ---------------------------------------------------------------------------

def classify(client: OpenAI, english: str, macedonian: str) -> dict:
    """Ask the model for position + category + level, return parsed dict."""
    if english and macedonian:
        user_msg = f'English: "{english}"\nMacedonian: "{macedonian}"'
    elif english:
        user_msg = f'English: "{english}"'
    else:
        user_msg = f'Macedonian: "{macedonian}"'
    response = client.chat.completions.create(
        model=get_model_name(),
        messages=[
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": user_msg},
        ],
        response_format={"type": "json_object"},
        temperature=0,
    )
    raw = response.choices[0].message.content
    return json.loads(raw)


# ---------------------------------------------------------------------------
# CSV helpers
# ---------------------------------------------------------------------------

def latest_export() -> Path:
    exports = sorted(OUTPUT_DIR.glob("notion_export_*.csv"))
    if not exports:
        raise FileNotFoundError(f"No notion_export_*.csv found in {OUTPUT_DIR}")
    return exports[-1]


def list_to_notion_string(items: list) -> str:
    """Join list values the same way the original CSV uses (', ' separated)."""
    return ", ".join(str(i) for i in items)


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("input", nargs="?", default=None, help="Input CSV file")
    parser.add_argument("--force-recategorize", action="store_true",
                        help="Re-enrich all rows even if already enriched (useful after category changes)")
    parser.add_argument("--no-ai", action="store_true",
                        help="Dictionary-only mode: fill POS/English/Latin from dictionary, skip LLM")
    args = parser.parse_args()

    input_path = Path(args.input) if args.input else latest_export()
    force = args.force_recategorize
    no_ai = args.no_ai
    print(f"Input:  {input_path}")
    if force:
        print("Mode:   FORCE RECATEGORIZE (all rows will be re-enriched)")
    if no_ai:
        print("Mode:   NO-AI (dictionary lookup only, no LLM calls)")

    # Load dictionary
    load_dictionary()

    client = None
    token = None
    if not no_ai:
        token = get_github_token()
        client = build_client(token)

    rows = []
    with open(input_path, newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        fieldnames = reader.fieldnames
        rows = list(reader)

    print(f"Loaded {len(rows)} rows. Enriching …\n")

    # Ensure Level column exists in fieldnames
    if "Level" not in fieldnames:
        fieldnames = list(fieldnames) + ["Level"]

    updated = 0
    dict_hits = 0
    ai_calls = 0
    skipped_already_enriched = 0
    try:
      for i, row in enumerate(rows, 1):
        english = (row.get("English") or "").strip()
        macedonian = (row.get("Macedonian (Latin)") or "").strip()
        macedonian_cyr = (row.get("Macedonian (Cyrillic) ") or row.get("Macedonian (Cyrillic)") or "").strip()

        # Use whatever text is available for classification
        classify_english = english
        classify_macedonian = macedonian or macedonian_cyr

        if not classify_english and not classify_macedonian:
            print(f"  [{i:>3}] SKIP  — no English or Macedonian text")
            continue

        # Skip rows that already have ALL enrichment fields populated (unless forcing)
        if not force:
            existing_pos = (row.get("Position in a sentence") or "").strip()
            existing_cat = (row.get("Category") or "").strip()
            existing_lvl = (row.get("Level") or "").strip()
            existing_eng = (row.get("English") or "").strip()
            existing_lat = (row.get("Macedonian (Latin)") or "").strip()
            if existing_pos and existing_cat and existing_lvl and existing_eng and existing_lat:
                skipped_already_enriched += 1
                print(f"  [{i:>3}] SKIP  — already enriched ({(english or macedonian_cyr)[:35]})")
                continue

        # ---- Step 1: Dictionary lookup (Cyrillic → dictionary) ----
        lookup_word = macedonian_cyr or macedonian
        dict_entry = dict_lookup(lookup_word) if lookup_word else None
        head_word = None

        # If single-word lookup missed, try phrase extraction
        if not dict_entry and lookup_word and " " in lookup_word:
            dict_entry, head_word = phrase_lookup(lookup_word)

        # ---- Step 1b: English reverse-index fallback ----
        eng_fallback = None
        if not dict_entry and english:
            eng_fallback = english_lookup(english)

        dict_pos = None
        dict_english = None
        dict_roman = None

        if dict_entry:
            dict_hits += 1
            dict_pos = dict_entry.get("pos")
            # Multi-word phrases with 3+ words → tag as Expression
            if lookup_word and " " in lookup_word and len(lookup_word.split()) >= 3:
                dict_pos = "Expression"
            raw_english = dict_entry.get("english")
            if isinstance(raw_english, list):
                dict_english = raw_english[0]
            else:
                dict_english = raw_english
            dict_roman = dict_entry.get("roman")
        elif eng_fallback:
            dict_hits += 1
            dict_pos = eng_fallback.get("pos")

        # ---- Step 2: Determine what we still need from AI ----
        need_pos = not dict_pos
        need_english = not english and not dict_english
        need_latin = not macedonian and not dict_roman
        # Category and Level: preserve existing, only need AI if missing AND not no-ai
        existing_cat = (row.get("Category") or "").strip()
        existing_lvl = (row.get("Level") or "").strip()
        need_category = (not existing_cat) and (not no_ai) or force
        need_level = (not existing_lvl) and (not no_ai) or force

        # If no-ai mode, fill what we can from dictionary and move on
        if no_ai:
            if dict_pos:
                row["Position in a sentence"] = dict_pos
            if not english and dict_english:
                row["English"] = dict_english
            if not macedonian and dict_roman:
                row["Macedonian (Latin)"] = dict_roman
            if dict_pos or dict_english or dict_roman:
                updated += 1
                display = (english or dict_english or macedonian_cyr)[:40]
                if eng_fallback and not dict_entry:
                    src_note = f" (via eng '{english[:15]}')"
                elif head_word:
                    src_note = f" (via '{head_word}')"
                else:
                    src_note = ""
                print(f"  [{i:>3}] {display:<40} | DICT{src_note}: pos={dict_pos}")
            else:
                print(f"  [{i:>3}] SKIP  — not in dictionary ({(classify_english or classify_macedonian)[:35]})")
            continue

        # ---- Step 3: Call AI only if needed for category/level or missing fields ----
        if need_category or need_level or need_pos or need_english or need_latin:
            ai_calls += 1
            result = classify(client, classify_english, classify_macedonian)

            new_pos = dict_pos or list_to_notion_string(result.get("position", []))
            new_cat = list_to_notion_string(result.get("category", []))
            new_lvl = result.get("level", "A1")
            new_eng = result.get("english", "").strip()
            new_lat = result.get("latin", "").strip()
        else:
            # Everything available from dict + existing data
            new_pos = dict_pos or (row.get("Position in a sentence") or "")
            new_cat = existing_cat
            new_lvl = existing_lvl
            new_eng = dict_english or ""
            new_lat = dict_roman or ""

        old_pos = (row.get("Position in a sentence") or "").strip()
        old_cat = (row.get("Category") or "").strip()
        old_lvl = (row.get("Level") or "").strip()

        row["Position in a sentence"] = new_pos
        row["Category"] = new_cat
        row["Level"] = new_lvl

        # Only fill English and Latin if not already present
        if not english:
            row["English"] = dict_english or new_eng or english
        if not macedonian:
            row["Macedonian (Latin)"] = dict_roman or new_lat or macedonian

        updated += 1

        display_label = (english or new_eng or dict_english or macedonian_cyr)[:40]
        src = "DICT" if dict_entry else "AI"
        changed_pos = f"{old_pos!r} → {new_pos!r}" if old_pos != new_pos else f"(=) {new_pos!r}"
        changed_cat = f"{old_cat!r} → {new_cat!r}" if old_cat != new_cat else f"(=) {new_cat!r}"
        changed_lvl = f"{old_lvl!r} → {new_lvl!r}" if old_lvl != new_lvl else f"(=) {new_lvl!r}"
        print(f"  [{i:>3}] {display_label:<40} | [{src}] {changed_pos} | {changed_cat} | lvl: {changed_lvl}")

    except KeyboardInterrupt:
        print(f"\n\nInterrupted! Saving progress ({updated} rows enriched so far)...")
    except Exception as e:
        print(f"\n\nError: {e}")
        print(f"Saving progress ({updated} rows enriched so far)...")

    # Save enriched CSV (always save, even on partial run)
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    out_path = OUTPUT_DIR / f"notion_enriched_{stamp}.csv"
    with open(out_path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)

    print(f"\nUpdated {updated}/{len(rows)} rows.")
    print(f"  Dictionary hits: {dict_hits} | AI calls: {ai_calls} | Skipped: {skipped_already_enriched}")
    print(f"Saved  → {out_path}")


if __name__ == "__main__":
    main()
