"""
Fetch human pronunciation audio for Macedonian words using a multi-pass
source resolution strategy defined in audio_sources.yaml.

Resolution order (configurable via YAML):
    Pass 1: Exact word → each source in priority order
    Pass 2: Lemma of word → each source in priority order
    Pass 3: Flag as missing

Source types supported:
    - api_lookup:      Direct API download (e.g. Lingua Libre)
    - index_extract:   Forced alignment from sentence corpus (e.g. Common Voice)
    - local_directory: Check if file already on disk

No AI tokens needed. MFCC cross-source verification runs automatically
when a word has audio from 2+ sources.

Usage:
    python fetch_audio.py                              # uses latest enriched CSV
    python fetch_audio.py output/my_enriched.csv       # explicit file
    python fetch_audio.py --dry-run                    # check coverage, no downloads
    python fetch_audio.py --word вода                   # single word test
"""

import csv
import json
import os
import subprocess
import sys
import time
import urllib.parse
import urllib.request
import urllib.error
import yaml
from datetime import datetime
from pathlib import Path

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------

OUTPUT_DIR = Path(__file__).parent / "output"
AUDIO_DIR = Path(__file__).parent / "audio"
SOURCES_YAML = Path(__file__).parent / "audio_sources.yaml"

USER_AGENT = (
    "MacedonianVocabLearner/1.0 "
    "(personal language learning project; "
    "https://github.com/viktorciroski/Macedonian-Notion-Updates)"
)


def load_sources_config() -> dict:
    """Load audio_sources.yaml. Falls back to defaults if missing."""
    if SOURCES_YAML.exists():
        with open(SOURCES_YAML, encoding="utf-8") as f:
            return yaml.safe_load(f)
    # Fallback: hardcoded defaults
    return {
        "sources": [
            {"name": "Lingua Libre", "type": "api_lookup", "enabled": True,
             "priority": 1, "license": "CC-BY-SA 4.0",
             "output_dir": "audio/words",
             "config": {"speakers": ["Bjankuloski06", "Jovan.kostov"],
                        "filename_pattern": "LL-Q9296 (mkd)-{speaker}-{word}.wav",
                        "api_url": "https://commons.wikimedia.org/w/api.php",
                        "min_file_size": 500, "request_delay": 1.5,
                        "download_delay": 0.5}},
            {"name": "Common Voice", "type": "index_extract", "enabled": True,
             "priority": 2, "license": "CC-0",
             "output_dir": "audio/clips",
             "config": {"index_file": "audio/common_voice_word_index.csv",
                        "word_column": "word", "min_confidence": 0.4}},
        ],
        "lemmatization": {"enabled": True, "strategy": "suffix_strip",
                          "suffixes": LEMMA_SUFFIXES},
    }


_CONFIG = None  # lazy-loaded


def get_config() -> dict:
    """Get cached config."""
    global _CONFIG
    if _CONFIG is None:
        _CONFIG = load_sources_config()
    return _CONFIG


def get_enabled_sources() -> list[dict]:
    """Return enabled sources sorted by priority."""
    cfg = get_config()
    sources = [s for s in cfg.get("sources", []) if s.get("enabled", True)]
    return sorted(sources, key=lambda s: s.get("priority", 99))


# Derive legacy constants from config for backward compatibility
_cfg_loaded = load_sources_config()
_ll_src = next((s for s in _cfg_loaded.get("sources", [])
                if s["name"] == "Lingua Libre"), None)
SPEAKERS = (_ll_src or {}).get("config", {}).get("speakers", ["Bjankuloski06", "Jovan.kostov"])
WIKIMEDIA_API = (_ll_src or {}).get("config", {}).get("api_url",
                                                      "https://commons.wikimedia.org/w/api.php")
BATCH_SIZE = 10
REQUEST_DELAY = (_ll_src or {}).get("config", {}).get("request_delay", 1.5)
DOWNLOAD_DELAY = (_ll_src or {}).get("config", {}).get("download_delay", 0.5)

# Common Voice word index
CV_INDEX = AUDIO_DIR / "common_voice_word_index.csv"

# Lemmatization suffixes from config
_lem_cfg = _cfg_loaded.get("lemmatization", {})
LEMMA_SUFFIXES = _lem_cfg.get("suffixes", [
    "увавме", "увавте", "уваат", "овите", "евите",
    "ував", "ите", "ува", "аме", "ете",
    "ови", "еви", "та", "то", "те",
    "ов", "ев", "ам", "еш", "е", "а", "и", "у",
])


def guess_lemma(word: str) -> str:
    """Heuristic lemma: strip longest matching Macedonian suffix."""
    for suffix in LEMMA_SUFFIXES:
        if word.endswith(suffix) and len(word) > len(suffix) + 1:
            return word[: -len(suffix)]
    return word


def load_cv_index() -> dict[str, dict]:
    """
    Load Common Voice word index.
    Returns: {word: {sentence, audio_path, source, license, status}}
    """
    if not CV_INDEX.exists():
        return {}
    index = {}
    with open(CV_INDEX, newline="", encoding="utf-8") as f:
        for row in csv.DictReader(f):
            w = row.get("word", "").strip().lower()
            if w and w not in index:
                index[w] = row
    return index


# ---------------------------------------------------------------------------
# Multi-pass audio resolution
# ---------------------------------------------------------------------------

def _check_local(word: str, output_dir: str) -> Path | None:
    """Check if audio file already exists on disk for this word."""
    out_path = Path(__file__).parent / output_dir / f"{word}.wav"
    if out_path.exists() and out_path.stat().st_size > 500:
        return out_path
    # Check suffixed variants
    for sfx in ("_extracted", "_cv", "_aligned"):
        alt = Path(__file__).parent / output_dir / f"{word}{sfx}.wav"
        if alt.exists() and alt.stat().st_size > 500:
            return alt
    return None


def _check_source(word: str, source: dict) -> dict | None:
    """
    Check if a word is available in a given source.
    Returns resolution info dict or None.

    Does NOT download — just checks availability.
    """
    src_type = source["type"]
    src_config = source.get("config", {})
    output_dir = source.get("output_dir", "audio/words")

    # Always check local cache first
    local = _check_local(word, output_dir)
    if local:
        return {
            "word": word,
            "source": source["name"],
            "license": source.get("license", "unknown"),
            "path": str(local),
            "cached": True,
        }

    if src_type == "api_lookup":
        # Lingua Libre style: check Wikimedia API
        speakers = src_config.get("speakers", SPEAKERS)
        pattern = src_config.get("filename_pattern",
                                 "LL-Q9296 (mkd)-{speaker}-{word}.wav")
        for speaker in speakers:
            filename = pattern.format(speaker=speaker, word=word)
            data = _api_request({
                "action": "query",
                "titles": f"File:{filename}",
                "prop": "imageinfo",
                "iiprop": "url|size",
            })
            pages = data.get("query", {}).get("pages", {})
            for pid, page in pages.items():
                if int(pid) != -1 and "imageinfo" in page:
                    info = page["imageinfo"][0]
                    min_size = src_config.get("min_file_size", 500)
                    if info.get("size", 0) > min_size:
                        return {
                            "word": word,
                            "source": source["name"],
                            "license": source.get("license", "unknown"),
                            "speaker": speaker,
                            "filename": filename,
                            "url": info["url"],
                            "size": info["size"],
                            "output_dir": output_dir,
                            "cached": False,
                        }
        return None

    elif src_type == "index_extract":
        # Common Voice style: check if word is in the sentence index
        index_file = src_config.get("index_file", "audio/common_voice_word_index.csv")
        index_path = Path(__file__).parent / index_file
        if not index_path.exists():
            return None
        # Scan index for the word (lazy — could cache, but fine for now)
        word_col = src_config.get("word_column", "word")
        with open(index_path, newline="", encoding="utf-8") as f:
            for row in csv.DictReader(f):
                if row.get(word_col, "").strip().lower() == word.lower():
                    return {
                        "word": word,
                        "source": source["name"],
                        "license": source.get("license", "unknown"),
                        "index_row": row,
                        "output_dir": output_dir,
                        "needs_extraction": True,
                        "cached": False,
                    }
        return None

    elif src_type == "local_directory":
        # Just check disk
        return None  # _check_local already ran above

    return None


def resolve_word_audio(word: str, lemma: str | None = None) -> dict:
    """
    Multi-pass audio resolution for a single word.

    Returns:
        {
            "word": str,
            "match_word": str,        # word or lemma that was found
            "match_type": str,        # "exact" | "lemma"
            "source": str,            # source name
            "license": str,
            "resolution": dict|None,  # full resolution info
            "status": str,            # "found" | "needs_extraction" | "not_found"
        }
    """
    sources = get_enabled_sources()
    cfg = get_config()
    lem_cfg = cfg.get("lemmatization", {})

    # Pass 1: Exact word through all sources
    for src in sources:
        result = _check_source(word, src)
        if result:
            status = "needs_extraction" if result.get("needs_extraction") else "found"
            return {
                "word": word,
                "match_word": word,
                "match_type": "exact",
                "source": result["source"],
                "license": result["license"],
                "resolution": result,
                "status": status,
            }

    # Pass 2: Lemma fallback (only if enabled and lemma differs from word)
    if lem_cfg.get("enabled", True):
        if lemma is None:
            lemma = guess_lemma(word)
        if lemma and lemma != word:
            for src in sources:
                result = _check_source(lemma, src)
                if result:
                    status = "needs_extraction" if result.get("needs_extraction") else "found"
                    return {
                        "word": word,
                        "match_word": lemma,
                        "match_type": "lemma",
                        "source": result["source"],
                        "license": result["license"],
                        "resolution": result,
                        "status": status,
                    }

    # Not found anywhere
    return {
        "word": word,
        "match_word": None,
        "match_type": None,
        "source": None,
        "license": None,
        "resolution": None,
        "status": "not_found",
    }


# ---------------------------------------------------------------------------
# Wikimedia Commons API
# ---------------------------------------------------------------------------

def _api_request(params: dict) -> dict:
    """Make a request to the Wikimedia Commons API with retry on rate limit."""
    params["format"] = "json"
    url = f"{WIKIMEDIA_API}?{urllib.parse.urlencode(params)}"
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    for attempt in range(4):
        try:
            resp = urllib.request.urlopen(req)
            return json.loads(resp.read().decode())
        except urllib.error.HTTPError as e:
            if e.code == 429:
                wait = 2 ** (attempt + 1)
                print(f"    Rate limited, waiting {wait}s...")
                time.sleep(wait)
            else:
                raise
    raise RuntimeError(f"Wikimedia API failed after retries: {url}")


def batch_check_with_urls(filenames: list[str]) -> dict[str, dict]:
    """
    Check multiple files and return those with actual download URLs.
    Returns: {filename: {"url": ..., "size": ...}}
    """
    titles = "|".join(f"File:{f}" for f in filenames)
    data = _api_request({
        "action": "query",
        "titles": titles,
        "prop": "imageinfo",
        "iiprop": "url|size",
    })
    pages = data.get("query", {}).get("pages", {})
    results = {}
    for pid, page in pages.items():
        if int(pid) != -1 and "imageinfo" in page:
            title = page.get("title", "").replace("File:", "")
            info = page["imageinfo"][0]
            if info.get("size", 0) > 500:
                results[title] = {"url": info["url"], "size": info["size"]}
    return results


def find_audio_batch(words: list[str]) -> dict[str, dict]:
    """
    Check a batch of words across all speakers.
    Returns: {word: {"speaker", "filename", "url", "size"}}
    """
    results = {}
    for speaker in SPEAKERS:
        remaining = [w for w in words if w not in results]
        if not remaining:
            break
        filenames = [f"LL-Q9296 (mkd)-{speaker}-{w}.wav" for w in remaining]
        found = batch_check_with_urls(filenames)
        for i, w in enumerate(remaining):
            fname = filenames[i]
            if fname in found:
                results[w] = {
                    "speaker": speaker,
                    "filename": fname,
                    "url": found[fname]["url"],
                    "size": found[fname]["size"],
                }
    return results


def lookup_single(word: str) -> dict | None:
    """Look up audio for one word. Returns info dict or None."""
    for speaker in SPEAKERS:
        filename = f"LL-Q9296 (mkd)-{speaker}-{word}.wav"
        data = _api_request({
            "action": "query",
            "titles": f"File:{filename}",
            "prop": "imageinfo",
            "iiprop": "url|size",
        })
        pages = data.get("query", {}).get("pages", {})
        for pid, page in pages.items():
            if int(pid) != -1 and "imageinfo" in page:
                info = page["imageinfo"][0]
                if info.get("size", 0) > 500:
                    return {
                        "speaker": speaker,
                        "filename": filename,
                        "url": info["url"],
                        "size": info["size"],
                    }
    return None


def download_audio(url: str, out_path: Path) -> bool:
    """Download audio file using curl. Returns True on success."""
    out_path.parent.mkdir(parents=True, exist_ok=True)
    subprocess.run(
        ["curl", "-L", "-s", "-o", str(out_path), "-H", f"User-Agent: {USER_AGENT}", url],
        capture_output=True,
    )
    if out_path.exists() and out_path.stat().st_size > 500:
        return True
    if out_path.exists():
        out_path.unlink()
    return False


# ---------------------------------------------------------------------------
# CSV helpers
# ---------------------------------------------------------------------------

def find_latest_enriched() -> Path:
    """Find the most recent enriched CSV in output/."""
    candidates = sorted(OUTPUT_DIR.glob("notion_enriched_*.csv"), reverse=True)
    if not candidates:
        candidates = sorted(OUTPUT_DIR.glob("notion_export_*.csv"), reverse=True)
    if not candidates:
        raise FileNotFoundError(f"No CSV files found in {OUTPUT_DIR}")
    return candidates[0]


def get_cyrillic(row: dict) -> str:
    """Extract Macedonian Cyrillic word from a CSV row."""
    for key in ["Macedonian (Cyrillic) ", "Macedonian (Cyrillic)", "Macedonian"]:
        val = (row.get(key) or "").strip()
        if val:
            return val
    return ""


def get_lemma(row: dict) -> str:
    """Extract lemma from a CSV row."""
    for key in ["Lemma Family", "Lemma", "Lemma Candidate"]:
        val = (row.get(key) or "").strip()
        if val:
            return val
    return ""


# ---------------------------------------------------------------------------
# Main pipeline
# ---------------------------------------------------------------------------

def run_single(word: str, dry_run: bool = False):
    """Look up and optionally download audio for a single word."""
    print(f"Looking up: {word}")
    result = lookup_single(word)
    if result:
        print(f"  Found! Speaker: {result['speaker']}, Size: {result['size']:,} bytes")
        print(f"  URL: {result['url']}")
        if not dry_run:
            out_path = AUDIO_DIR / "words" / f"{word}.wav"
            if download_audio(result["url"], out_path):
                print(f"  Saved: {out_path}")
            else:
                print("  Download failed.")
    else:
        print("  Not found in Lingua Libre.")


def run_batch(csv_path: str = None, dry_run: bool = False):
    """Full batch pipeline with Option C lemma fallback."""
    if csv_path is None:
        csv_path = str(find_latest_enriched())

    print(f"=" * 60)
    print(f"AUDIO FETCH PIPELINE (Option C: Hybrid Lemma Strategy)")
    print(f"=" * 60)
    print(f"  Source: {csv_path}")
    print(f"  Mode:   {'DRY RUN' if dry_run else 'DOWNLOAD'}")
    print()

    # Load CSV
    with open(csv_path, newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        fieldnames = list(reader.fieldnames)
        rows = list(reader)

    # Ensure output columns exist
    new_cols = ["Lemma Family", "Audio File", "Audio URL", "Lemma Audio File",
                "Audio Source", "Audio Speaker", "Audio License"]
    for col in new_cols:
        if col not in fieldnames:
            fieldnames.append(col)

    # Build word → lemma map and deduplicate
    word_data = {}  # {cyrillic: {"lemma": ..., "row_indices": [...]}}
    for i, row in enumerate(rows):
        word = get_cyrillic(row)
        if not word:
            continue
        lemma = get_lemma(row) or word  # default lemma = word itself
        if word not in word_data:
            word_data[word] = {"lemma": lemma, "row_indices": []}
        word_data[word]["row_indices"].append(i)

    unique_words = list(word_data.keys())
    unique_lemmas = set(d["lemma"] for d in word_data.values() if d["lemma"] != unique_words[0])
    print(f"  Total rows: {len(rows)}")
    print(f"  Unique words: {len(unique_words)}")
    print()

    # ----- PHASE 1: Exact word matches -----
    print("Phase 1: Checking exact word matches...")
    exact_matches = {}  # word → audio info
    checked = 0

    for i in range(0, len(unique_words), BATCH_SIZE):
        batch = unique_words[i:i + BATCH_SIZE]
        found = find_audio_batch(batch)
        exact_matches.update(found)
        checked += len(batch)
        time.sleep(REQUEST_DELAY)
        print(f"  [{checked}/{len(unique_words)}] {len(exact_matches)} exact matches found", end="\r")

    print(f"\n  Exact matches: {len(exact_matches)}/{len(unique_words)}"
          f" ({100 * len(exact_matches) // max(len(unique_words), 1)}%)")
    print()

    # ----- PHASE 2: Lemma fallbacks -----
    print("Phase 2: Checking lemma fallbacks for unmatched words...")
    words_without_exact = [w for w in unique_words if w not in exact_matches]
    lemmas_to_check = list(set(
        word_data[w]["lemma"] for w in words_without_exact
        if word_data[w]["lemma"] and word_data[w]["lemma"] != w
    ))

    lemma_audio = {}  # lemma → audio info
    for i in range(0, len(lemmas_to_check), BATCH_SIZE):
        batch = lemmas_to_check[i:i + BATCH_SIZE]
        found = find_audio_batch(batch)
        lemma_audio.update(found)
        time.sleep(REQUEST_DELAY)

    # Map lemma audio back to words
    lemma_matches = {}  # word → audio info (via its lemma)
    for w in words_without_exact:
        lemma = word_data[w]["lemma"]
        if lemma in lemma_audio:
            lemma_matches[w] = lemma_audio[lemma]
        elif lemma in exact_matches:
            # The lemma itself was found in Phase 1
            lemma_matches[w] = exact_matches[lemma]

    print(f"  Lemma fallbacks: {len(lemma_matches)}"
          f" (checked {len(lemmas_to_check)} unique lemmas)")
    print()

    # ----- SUMMARY -----
    no_audio = [w for w in unique_words if w not in exact_matches and w not in lemma_matches]
    total_covered = len(exact_matches) + len(lemma_matches)

    print("=" * 60)
    print("COVERAGE SUMMARY")
    print(f"  Exact word audio:   {len(exact_matches):>4} words")
    print(f"  Lemma fallback:     {len(lemma_matches):>4} words")
    print(f"  TOTAL covered:      {total_covered:>4} / {len(unique_words)}"
          f" ({100 * total_covered // max(len(unique_words), 1)}%)")
    print(f"  No audio available: {len(no_audio):>4} words")
    print("=" * 60)

    if no_audio and len(no_audio) <= 40:
        print("\n  Words without any audio:")
        for w in no_audio:
            print(f"    • {w} (lemma: {word_data[w]['lemma']})")
    elif no_audio:
        print(f"\n  First 30 words without audio:")
        for w in no_audio[:30]:
            print(f"    • {w} (lemma: {word_data[w]['lemma']})")
        print(f"    ... and {len(no_audio) - 30} more")

    if dry_run:
        print("\n[DRY RUN] No files downloaded. Run without --dry-run to download.")
        return

    # ----- PHASE 3: Download -----
    print(f"\nPhase 3: Downloading audio files...")
    words_dir = AUDIO_DIR / "words"
    lemmas_dir = AUDIO_DIR / "lemmas"
    words_dir.mkdir(parents=True, exist_ok=True)
    lemmas_dir.mkdir(parents=True, exist_ok=True)

    downloaded = 0
    failed = 0
    skipped = 0

    # Download exact matches
    for word, info in exact_matches.items():
        out_path = words_dir / f"{word}.wav"
        if out_path.exists():
            skipped += 1
        else:
            if download_audio(info["url"], out_path):
                downloaded += 1
            else:
                failed += 1
            time.sleep(DOWNLOAD_DELAY)

        # Update CSV rows
        for idx in word_data[word]["row_indices"]:
            rows[idx]["Audio File"] = f"audio/words/{word}.wav"
            rows[idx]["Audio URL"] = info["url"]
            rows[idx]["Audio Source"] = "Lingua Libre / Wikimedia Commons"
            rows[idx]["Audio Speaker"] = info["speaker"]
            rows[idx]["Audio License"] = "CC-BY-SA 4.0"
            rows[idx]["Lemma Family"] = word_data[word]["lemma"]

        if (downloaded + skipped) % 20 == 0:
            print(f"  Progress: {downloaded} downloaded, {skipped} cached, {failed} failed", end="\r")

    # Download lemma fallbacks (each lemma only once)
    downloaded_lemmas = set()
    for word, info in lemma_matches.items():
        lemma = word_data[word]["lemma"]
        out_path = lemmas_dir / f"{lemma}.wav"

        if lemma not in downloaded_lemmas:
            if out_path.exists():
                skipped += 1
            else:
                if download_audio(info["url"], out_path):
                    downloaded += 1
                else:
                    failed += 1
                time.sleep(DOWNLOAD_DELAY)
            downloaded_lemmas.add(lemma)

        # Update CSV rows — no exact audio, but lemma audio available
        for idx in word_data[word]["row_indices"]:
            rows[idx]["Lemma Audio File"] = f"audio/lemmas/{lemma}.wav"
            rows[idx]["Audio Source"] = "Lingua Libre / Wikimedia Commons"
            rows[idx]["Audio Speaker"] = info["speaker"]
            rows[idx]["Audio License"] = "CC-BY-SA 4.0"
            rows[idx]["Lemma Family"] = lemma

    # Update Lemma Family for all rows (even those with exact audio)
    for word in unique_words:
        lemma = word_data[word]["lemma"]
        for idx in word_data[word]["row_indices"]:
            if not rows[idx].get("Lemma Family"):
                rows[idx]["Lemma Family"] = lemma

    print(f"\n  Downloaded: {downloaded}")
    print(f"  Cached (already on disk): {skipped}")
    print(f"  Failed: {failed}")

    # ----- Save outputs -----
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")

    # Updated CSV with audio columns
    out_csv = OUTPUT_DIR / f"notion_enriched_{ts}.csv"
    with open(out_csv, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)
    print(f"\n  Updated CSV: {out_csv}")

    # Attribution manifest
    manifest_path = AUDIO_DIR / f"audio_manifest_{ts}.csv"
    manifest_fields = ["word", "audio_word", "match_type", "source",
                       "speaker", "license", "filename", "url", "size_bytes"]
    with open(manifest_path, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=manifest_fields)
        w.writeheader()
        for word, info in exact_matches.items():
            w.writerow({
                "word": word, "audio_word": word, "match_type": "exact",
                "source": "Lingua Libre / Wikimedia Commons",
                "speaker": info["speaker"], "license": "CC-BY-SA 4.0",
                "filename": info["filename"], "url": info["url"],
                "size_bytes": info["size"],
            })
        for word, info in lemma_matches.items():
            lemma = word_data[word]["lemma"]
            w.writerow({
                "word": word, "audio_word": lemma, "match_type": "lemma_fallback",
                "source": "Lingua Libre / Wikimedia Commons",
                "speaker": info["speaker"], "license": "CC-BY-SA 4.0",
                "filename": info["filename"], "url": info["url"],
                "size_bytes": info["size"],
            })
    print(f"  Manifest: {manifest_path}")

    # Gap report
    if no_audio:
        gap_path = AUDIO_DIR / f"audio_gaps_{ts}.csv"
        with open(gap_path, "w", newline="", encoding="utf-8") as f:
            w = csv.writer(f)
            w.writerow(["word", "lemma", "notes"])
            for word in no_audio:
                w.writerow([word, word_data[word]["lemma"],
                           "No audio in Lingua Libre (needs Common Voice or recording)"])
        print(f"  Gap report: {gap_path}")

    print(f"\nDone!")


# ---------------------------------------------------------------------------
# Index builder (for sentence-based sources like FLEURS, VoxPopuli)
# ---------------------------------------------------------------------------

def build_source_index(source_name: str, limit: int = 0):
    """
    Build a word→sentence index for a HuggingFace dataset source.
    Reads audio_sources.yaml for the dataset details.

    Usage:
        python fetch_audio.py --build-index FLEURS
        python fetch_audio.py --build-index FLEURS --index-limit 100
    """
    cfg = get_config()
    source = None
    for s in cfg.get("sources", []):
        if s["name"].lower() == source_name.lower():
            source = s
            break

    if not source:
        print(f"Error: Source '{source_name}' not found in audio_sources.yaml")
        print(f"Available: {[s['name'] for s in cfg['sources']]}")
        sys.exit(1)

    if source["type"] != "index_extract":
        print(f"Error: Source '{source_name}' is type '{source['type']}', not 'index_extract'")
        sys.exit(1)

    src_cfg = source.get("config", {})
    dataset_name = src_cfg.get("dataset")
    dataset_config = src_cfg.get("dataset_config")
    index_file = src_cfg.get("index_file")
    sentence_col = src_cfg.get("sentence_column", "sentence")

    if not dataset_name:
        print(f"Error: No 'dataset' configured for source '{source_name}'")
        sys.exit(1)

    print(f"{'=' * 60}")
    print(f"BUILDING WORD INDEX: {source_name}")
    print(f"{'=' * 60}")
    print(f"  Dataset: {dataset_name} ({dataset_config})")
    print(f"  Output:  {index_file}")
    print(f"  License: {source.get('license', '?')}")
    if limit:
        print(f"  Limit:   {limit} sentences")
    print()

    # Stream the dataset (disable audio decoding — we only need text for indexing)
    from datasets import load_dataset, Audio
    ds = load_dataset(dataset_name, dataset_config, split="train",
                      streaming=True, trust_remote_code=True)
    # Cast audio column to not decode (saves bandwidth + avoids librosa dep)
    try:
        ds = ds.cast_column("audio", Audio(decode=False))
    except Exception:
        pass  # dataset may not have an audio column in expected format

    # Build word index: for each unique word, store the first sentence containing it
    word_index = {}  # word → {sentence, audio_path}
    processed = 0

    print("  Scanning sentences for unique words...")
    for sample in ds:
        transcript = sample.get(sentence_col, sample.get("transcription", ""))
        if not transcript:
            continue

        # Get audio path identifier
        audio_path = ""
        if "path" in sample:
            audio_path = sample["path"]
        elif "audio" in sample and isinstance(sample["audio"], dict):
            audio_path = sample["audio"].get("path", f"sample_{processed}")
        else:
            audio_path = f"sample_{processed}"

        # Extract words from sentence
        words = set()
        for w in transcript.lower().split():
            cleaned = w.strip(".,!?;:()\"\"„\"–—«»")
            if cleaned and any(c.isalpha() for c in cleaned):
                words.add(cleaned)

        for word in words:
            if word not in word_index:
                word_index[word] = {
                    "word": word,
                    "sentence": transcript,
                    "audio_path": audio_path,
                    "source": f"{source['name']} ({dataset_name})",
                    "license": source.get("license", "unknown"),
                    "status": "needs_alignment",
                }

        processed += 1
        if processed % 100 == 0:
            print(f"    {processed} sentences → {len(word_index)} unique words", end="\r")

        if limit and processed >= limit:
            break

    print(f"\n  Done: {processed} sentences → {len(word_index)} unique words")

    # Write index
    out_path = Path(__file__).parent / index_file
    out_path.parent.mkdir(parents=True, exist_ok=True)

    fieldnames = ["word", "sentence", "audio_path", "source", "license", "status"]
    with open(out_path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        for word in sorted(word_index.keys()):
            writer.writerow(word_index[word])

    print(f"  Saved: {out_path} ({len(word_index)} entries)")
    print(f"\n  To enable this source, ensure 'enabled: true' in audio_sources.yaml")


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(
        description="Fetch Macedonian pronunciation audio (multi-source, YAML-driven)"
    )
    parser.add_argument("input", nargs="?", default=None,
                        help="Input CSV file (default: latest enriched CSV)")
    parser.add_argument("--word", type=str, default=None,
                        help="Look up a single word")
    parser.add_argument("--dry-run", action="store_true",
                        help="Check coverage without downloading")
    parser.add_argument("--build-index", type=str, default=None,
                        metavar="SOURCE_NAME",
                        help="Build word index for a source (e.g. 'FLEURS')")
    parser.add_argument("--index-limit", type=int, default=0,
                        help="Max sentences to index (0=all)")
    args = parser.parse_args()

    if args.build_index:
        build_source_index(args.build_index, limit=args.index_limit)
    elif args.word:
        run_single(args.word, dry_run=args.dry_run)
    else:
        run_batch(csv_path=args.input, dry_run=args.dry_run)
