"""
Download the kaikki.org Macedonian dictionary (from English Wiktionary) and build
a compact JSON lookup for the enrichment pipeline.

Source: https://kaikki.org/dictionary/Macedonian/
License: CC BY-SA 3.0 (Wiktionary content)

The output file (sources/dictionaries/mk_kaikki_dictionary.json) provides:
  - POS (part of speech)
  - Gender (for nouns)
  - Aspect + perfective/imperfective pair (for verbs)
  - English gloss(es)
  - Romanization (Latin transliteration)
  - Key forms: indefinite, definite, plural, diminutive, etc.

Usage:
    python build_dictionary.py              # download + build
    python build_dictionary.py --no-download  # rebuild from cached JSONL
"""

from __future__ import annotations

import gzip
import json
import os
import shutil
import urllib.request
from pathlib import Path

DOWNLOAD_URL = "https://kaikki.org/dictionary/Macedonian/kaikki.org-dictionary-Macedonian.jsonl"
CACHE_DIR = Path(__file__).parent / "corpora" / "kaikki"
JSONL_PATH = CACHE_DIR / "kaikki.org-dictionary-Macedonian.jsonl"
OUTPUT_PATH = Path(__file__).parent / "sources" / "dictionaries" / "mk_kaikki_dictionary.json"

USER_AGENT = "Macedonian-Core-Vocab-Builder/1.0 (language-learning project)"

# Map kaikki POS codes to our pipeline's "Position in a sentence" values
POS_MAP = {
    "noun": "Noun",
    "verb": "Verb",
    "adj": "Adjective",
    "adv": "Adverb",
    "pron": "Pronoun",
    "conj": "Conjunction",
    "prep": "Preposition",
    "intj": "Interjection",
    "particle": "Particle",
    "num": "Number",
    "det": "Pronoun",       # determiners → Pronoun in our schema
    "phrase": "Expression",
    "proverb": "Expression",
    "name": "Noun",         # proper nouns
}


def download_jsonl() -> None:
    """Download the Macedonian JSONL from kaikki.org."""
    CACHE_DIR.mkdir(parents=True, exist_ok=True)

    if JSONL_PATH.exists():
        size_mb = JSONL_PATH.stat().st_size / 1024 / 1024
        print(f"  Cache exists: {JSONL_PATH} ({size_mb:.1f} MB)")
        return

    print(f"  Downloading {DOWNLOAD_URL} ...")
    req = urllib.request.Request(DOWNLOAD_URL, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(req, timeout=120) as resp:
        with open(JSONL_PATH, "wb") as f:
            shutil.copyfileobj(resp, f)

    size_mb = JSONL_PATH.stat().st_size / 1024 / 1024
    print(f"  Downloaded: {size_mb:.1f} MB")


def extract_entry(data: dict) -> dict | None:
    """Extract the fields we need from a single kaikki entry."""
    word = data.get("word", "").strip()
    pos_raw = data.get("pos", "").strip()
    if not word or not pos_raw:
        return None

    pos = POS_MAP.get(pos_raw)
    if not pos:
        return None

    entry: dict = {"pos": pos}

    # --- Gender (nouns) ---
    tags = []
    for ht in data.get("head_templates", []):
        args = ht.get("args", {})
        # Gender is often in arg "1" for nouns: "m", "f", "n"
        g = args.get("1", "")
        if g in ("m", "f", "n"):
            gender_map = {"m": "masculine", "f": "feminine", "n": "neuter"}
            entry["gender"] = gender_map[g]
        # Aspect for verbs
        if pos == "Verb":
            if g in ("impf", "pf"):
                entry["aspect"] = "imperfective" if g == "impf" else "perfective"
            pf = args.get("pf", "")
            impf = args.get("impf", "")
            if pf:
                entry["perfective"] = pf
            if impf:
                entry["imperfective"] = impf

    # Also check top-level tags for gender
    for form in data.get("forms", []):
        ftags = form.get("tags", [])
        if "masculine" in ftags and "gender" not in entry:
            entry["gender"] = "masculine"
        elif "feminine" in ftags and "gender" not in entry:
            entry["gender"] = "feminine"
        elif "neuter" in ftags and "gender" not in entry:
            entry["gender"] = "neuter"

    # Check head_templates for gender in tags format
    for sense in data.get("senses", []):
        for stag in sense.get("tags", []):
            if stag in ("masculine", "feminine", "neuter") and "gender" not in entry:
                entry["gender"] = stag

    # --- Romanization ---
    for form in data.get("forms", []):
        ftags = form.get("tags", [])
        if "romanization" in ftags:
            entry["roman"] = form["form"]
            break

    # --- English glosses ---
    glosses = []
    for sense in data.get("senses", []):
        for g in sense.get("glosses", []):
            if g and g not in glosses:
                glosses.append(g)
    if glosses:
        entry["english"] = glosses[0] if len(glosses) == 1 else glosses[:3]

    # --- Key forms (from declension/conjugation tables) ---
    forms_out = {}
    for form in data.get("forms", []):
        ftags = set(form.get("tags", []))
        source = form.get("source", "")
        f_val = form.get("form", "")
        f_roman = form.get("roman", "")

        if not f_val or f_val in ("no-table-tags", "-"):
            continue
        if "inflection-template" in ftags or "table-tags" in ftags:
            continue

        # Nouns: definite/indefinite/plural
        if pos == "Noun" and source == "declension":
            if "indefinite" in ftags and "singular" in ftags:
                forms_out.setdefault("indefinite_sg", f_val)
            elif "indefinite" in ftags and "plural" in ftags:
                forms_out.setdefault("indefinite_pl", f_val)
            elif "definite" in ftags and "singular" in ftags and "unspecified" in ftags:
                forms_out.setdefault("definite_sg", f_val)
            elif "definite" in ftags and "plural" in ftags and "unspecified" in ftags:
                forms_out.setdefault("definite_pl", f_val)
            elif "vocative" in ftags and "singular" in ftags:
                forms_out.setdefault("vocative_sg", f_val)

        # Also collect non-declension forms
        if "plural" in ftags and source != "declension" and "indefinite_pl" not in forms_out:
            forms_out.setdefault("plural", f_val)
        if "diminutive" in ftags and "diminutive" not in forms_out:
            forms_out.setdefault("diminutive", f_val)

        # Verbs: key conjugation forms
        if pos == "Verb":
            if "first-person" in ftags and "singular" in ftags and "present" in ftags:
                forms_out.setdefault("1sg_present", f_val)
            elif "third-person" in ftags and "singular" in ftags and "present" in ftags:
                forms_out.setdefault("3sg_present", f_val)
            elif "masculine" in ftags and ("imperfect" in ftags or "past" in ftags) and "l-participle" not in forms_out:
                forms_out.setdefault("l_participle_m", f_val)
            elif "adverbial" in ftags and "participle" in ftags:
                forms_out.setdefault("adverbial_participle", f_val)
            elif "noun-from-verb" in ftags:
                forms_out.setdefault("verbal_noun", f_val)

    if forms_out:
        entry["forms"] = forms_out

    return entry


ENGLISH_INDEX_PATH = Path(__file__).parent / "sources" / "dictionaries" / "mk_english_reverse_index.json"


def build_english_index(flat_dict: dict) -> None:
    """Build English→Macedonian reverse lookup from the main dictionary.

    Maps normalized English glosses to Macedonian word + POS.
    Only keeps the first (most common) Macedonian match per English word.
    """
    print(f"\n  Building English reverse index...")
    eng_index: dict[str, dict] = {}

    for mk_word, entries in flat_dict.items():
        if isinstance(entries, dict):
            entries = [entries]
        for entry in entries:
            english = entry.get("english")
            if not english:
                continue
            glosses = english if isinstance(english, list) else [english]
            for gloss in glosses:
                # Normalize: "to speak" → "speak"; "dog (animal)" → "dog"
                normalized = _normalize_english(gloss)
                if not normalized or len(normalized) < 2:
                    continue
                if normalized not in eng_index:
                    eng_index[normalized] = {
                        "mk": mk_word,
                        "pos": entry.get("pos"),
                    }
                    gender = entry.get("gender")
                    if gender:
                        eng_index[normalized]["gender"] = gender

    with open(ENGLISH_INDEX_PATH, "w", encoding="utf-8") as f:
        json.dump(eng_index, f, ensure_ascii=False, separators=(",", ":"))

    size_mb = ENGLISH_INDEX_PATH.stat().st_size / 1024 / 1024
    print(f"  English reverse index: {len(eng_index)} entries ({size_mb:.1f} MB)")
    print(f"  Saved → {ENGLISH_INDEX_PATH}")


def _normalize_english(gloss: str) -> str:
    """Normalize an English gloss for lookup.

    - Strip "to " prefix (verbs)
    - Strip parenthetical qualifiers
    - Lowercase
    - Take first meaning if comma-separated
    """
    import re
    g = gloss.strip().lower()
    # Remove parenthetical: "dog (animal)" → "dog"
    g = re.sub(r"\s*\([^)]*\)", "", g)
    # Strip "to " for verbs: "to speak" → "speak"
    if g.startswith("to "):
        g = g[3:]
    # Take first meaning: "beautiful, pretty" → "beautiful"
    if ", " in g:
        g = g.split(", ")[0]
    return g.strip()


def build_dictionary() -> None:
    """Parse the JSONL and build a word→entry lookup."""
    print(f"  Parsing {JSONL_PATH} ...")

    dictionary: dict[str, list[dict]] = {}
    count = 0

    with open(JSONL_PATH, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                data = json.loads(line)
            except json.JSONDecodeError:
                continue

            # Only Macedonian entries
            if data.get("lang_code") != "mk" and data.get("lang") != "Macedonian":
                continue

            entry = extract_entry(data)
            if entry is None:
                continue

            word = data["word"].strip().lower()
            if word not in dictionary:
                dictionary[word] = []

            # Avoid duplicate POS entries for same word
            existing_pos = [e["pos"] for e in dictionary[word]]
            if entry["pos"] not in existing_pos:
                dictionary[word].append(entry)
            else:
                # Merge: prefer entry with more info
                idx = existing_pos.index(entry["pos"])
                old = dictionary[word][idx]
                if len(json.dumps(entry)) > len(json.dumps(old)):
                    dictionary[word][idx] = entry

            count += 1

    # Flatten single-entry words for compactness
    flat_dict = {}
    for word, entries in dictionary.items():
        if len(entries) == 1:
            flat_dict[word] = entries[0]
        else:
            flat_dict[word] = entries

    OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    with open(OUTPUT_PATH, "w", encoding="utf-8") as f:
        json.dump(flat_dict, f, ensure_ascii=False, separators=(",", ":"))

    size_mb = OUTPUT_PATH.stat().st_size / 1024 / 1024
    print(f"  Built dictionary: {len(flat_dict)} words ({size_mb:.1f} MB)")
    print(f"  Saved → {OUTPUT_PATH}")

    # Build English → Macedonian reverse index
    build_english_index(flat_dict)

    # Print some stats
    pos_counts: dict[str, int] = {}
    gender_count = 0
    for entries in flat_dict.values():
        if isinstance(entries, dict):
            entries = [entries]
        for e in entries:
            pos_counts[e["pos"]] = pos_counts.get(e["pos"], 0) + 1
            if "gender" in e:
                gender_count += 1

    print(f"\n  POS breakdown:")
    for pos, cnt in sorted(pos_counts.items(), key=lambda x: -x[1]):
        print(f"    {pos:<15} {cnt:>6}")
    print(f"    {'(with gender)':<15} {gender_count:>6}")


def main():
    import argparse
    parser = argparse.ArgumentParser(description="Build Macedonian dictionary from kaikki.org")
    parser.add_argument("--no-download", action="store_true",
                        help="Skip download, use cached JSONL")
    args = parser.parse_args()

    print("Building Macedonian dictionary from kaikki.org (Wiktionary)")
    print("=" * 60)

    if not args.no_download:
        download_jsonl()
    else:
        if not JSONL_PATH.exists():
            raise FileNotFoundError(f"No cached JSONL at {JSONL_PATH}. Run without --no-download first.")

    build_dictionary()
    print("\nDone!")


if __name__ == "__main__":
    main()
