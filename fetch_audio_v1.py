"""
Fetch human pronunciation audio from Lingua Libre (Wikimedia Commons)
for Macedonian words/phrases. No AI required — looks up the Cyrillic word
directly via the Wikimedia API and downloads the WAV file.

Usage:
    python fetch_audio.py                                  # uses latest enriched CSV
    python fetch_audio.py output/my_export.csv             # explicit file
    python fetch_audio.py --word вода                       # single word lookup
    python fetch_audio.py --dry-run                         # show matches without downloading

Source: Lingua Libre / Wikimedia Commons
License: CC-BY-SA 4.0
"""

import csv
import json
import os
import sys
import subprocess
import time
import urllib.request
import urllib.parse
import urllib.error
from pathlib import Path
from datetime import datetime

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------

OUTPUT_DIR = Path(__file__).parent / "output"
AUDIO_DIR = Path(__file__).parent / "audio"

# Wikimedia requires a descriptive User-Agent per their robot policy
USER_AGENT = (
    "MacedonianVocabLearner/1.0 "
    "(personal language learning project; "
    "https://github.com/viktorciroski/Macedonian-Notion-Updates)"
)

# Known Lingua Libre speakers for Macedonian (mkd)
# The API query code is Q9296 (Wikidata language code for Macedonian)
SPEAKERS = ["Bjankuloski06", "Jovan.kostov"]

WIKIMEDIA_API = "https://commons.wikimedia.org/w/api.php"


# ---------------------------------------------------------------------------
# Wikimedia Commons API helpers
# ---------------------------------------------------------------------------

def _api_request(params: dict) -> dict:
    """Make a request to the Wikimedia Commons API with rate limiting."""
    params["format"] = "json"
    url = f"{WIKIMEDIA_API}?{urllib.parse.urlencode(params)}"
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    for attempt in range(4):
        try:
            time.sleep(0.3)  # Respect Wikimedia rate limits
            resp = urllib.request.urlopen(req)
            return json.loads(resp.read().decode())
        except urllib.error.HTTPError as e:
            if e.code == 429:
                wait = 2 ** attempt
                print(f"    Rate limited, waiting {wait}s...")
                time.sleep(wait)
            else:
                raise
    raise RuntimeError(f"Wikimedia API request failed after retries: {url}")


def lookup_audio(word: str) -> dict | None:
    """Look up a Lingua Libre audio file for a Macedonian word.

    Returns dict with 'url', 'speaker', 'filename', 'size' if found, else None.
    """
    for speaker in SPEAKERS:
        filename = f"LL-Q9296 (mkd)-{speaker}-{word}.wav"
        data = _api_request({
            "action": "query",
            "titles": f"File:{filename}",
            "prop": "imageinfo",
            "iiprop": "url|size|mime",
        })
        pages = data.get("query", {}).get("pages", {})
        for page_id, page in pages.items():
            if int(page_id) != -1:
                info = page.get("imageinfo", [{}])[0]
                url = info.get("url", "")
                if url:
                    return {
                        "url": url,
                        "speaker": speaker,
                        "filename": filename,
                        "size": info.get("size", 0),
                    }
    return None


def download_audio(url: str, out_path: Path) -> int:
    """Download an audio file using curl (handles Wikimedia's robot policy).

    Returns file size in bytes, or 0 on failure.
    """
    out_path.parent.mkdir(parents=True, exist_ok=True)
    result = subprocess.run(
        ["curl", "-L", "-s", "-o", str(out_path), "-H", f"User-Agent: {USER_AGENT}", url],
        capture_output=True,
    )
    if out_path.exists():
        size = out_path.stat().st_size
        # Wikimedia returns a small text error if blocked
        if size < 500:
            out_path.unlink()
            return 0
        return size
    return 0


# ---------------------------------------------------------------------------
# CSV helpers
# ---------------------------------------------------------------------------

def latest_enriched() -> Path:
    """Find the most recent enriched CSV in output/."""
    candidates = sorted(OUTPUT_DIR.glob("notion_enriched_*.csv"))
    if not candidates:
        # Fall back to export files
        candidates = sorted(OUTPUT_DIR.glob("notion_export_*.csv"))
    if not candidates:
        raise FileNotFoundError(f"No CSV files found in {OUTPUT_DIR}")
    return candidates[-1]


def get_macedonian_word(row: dict) -> str:
    """Extract the Macedonian Cyrillic word from a CSV row."""
    # Try Notion export column names
    for key in ["Macedonian (Cyrillic) ", "Macedonian (Cyrillic)", "Macedonian"]:
        val = (row.get(key) or "").strip()
        if val:
            return val
    return ""


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    import argparse
    parser = argparse.ArgumentParser(
        description="Fetch Macedonian pronunciation audio from Lingua Libre"
    )
    parser.add_argument("input", nargs="?", default=None,
                        help="Input CSV file (default: latest enriched CSV)")
    parser.add_argument("--word", type=str, default=None,
                        help="Look up a single word instead of processing a CSV")
    parser.add_argument("--dry-run", action="store_true",
                        help="Check availability without downloading")
    args = parser.parse_args()

    # --- Single word mode ---
    if args.word:
        word = args.word.strip()
        print(f"Looking up: {word}")
        result = lookup_audio(word)
        if result:
            print(f"  Found! Speaker: {result['speaker']}, Size: {result['size']:,} bytes")
            print(f"  URL: {result['url']}")
            if not args.dry_run:
                out_path = AUDIO_DIR / f"{word}.wav"
                size = download_audio(result["url"], out_path)
                if size > 0:
                    print(f"  Saved: {out_path} ({size:,} bytes)")
                else:
                    print("  Download failed.")
        else:
            print("  Not found in Lingua Libre.")
        return

    # --- CSV batch mode ---
    input_path = Path(args.input) if args.input else latest_enriched()
    print(f"Input:  {input_path}")
    print(f"Audio:  {AUDIO_DIR}/")
    if args.dry_run:
        print("Mode:   DRY RUN (no downloads)")
    print()

    rows = []
    with open(input_path, newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        fieldnames = list(reader.fieldnames)
        rows = list(reader)

    # Ensure audio columns exist
    for col in ["Audio File", "Audio Source", "Audio Speaker", "Audio License"]:
        if col not in fieldnames:
            fieldnames.append(col)

    found = 0
    already_has = 0
    not_found = 0
    downloaded = 0
    attribution_rows = []

    try:
      for i, row in enumerate(rows, 1):
        word = get_macedonian_word(row)
        if not word:
            continue

        # Skip if audio already fetched
        existing_audio = (row.get("Audio File") or "").strip()
        if existing_audio:
            already_has += 1
            continue

        result = lookup_audio(word)

        if result:
            found += 1
            rel_path = f"audio/{word}.wav"
            row["Audio File"] = rel_path
            row["Audio Source"] = "Lingua Libre / Wikimedia Commons"
            row["Audio Speaker"] = result["speaker"]
            row["Audio License"] = "CC-BY-SA 4.0"

            attribution_rows.append({
                "word": word,
                "source": "Lingua Libre / Wikimedia Commons",
                "speaker": result["speaker"],
                "license": "CC-BY-SA 4.0",
                "original_filename": result["filename"],
                "url": result["url"],
            })

            if not args.dry_run:
                out_path = AUDIO_DIR / f"{word}.wav"
                if not out_path.exists():
                    size = download_audio(result["url"], out_path)
                    if size > 0:
                        downloaded += 1
                        print(f"  [{i:>3}] OK    {word:<30} {size:>8,} bytes  (speaker: {result['speaker']})")
                    else:
                        print(f"  [{i:>3}] FAIL  {word:<30} download failed")
                        row["Audio File"] = ""
                else:
                    print(f"  [{i:>3}] EXIST {word:<30} already on disk")
                    downloaded += 1
            else:
                print(f"  [{i:>3}] MATCH {word:<30} {result['size']:>8,} bytes  (speaker: {result['speaker']})")
        else:
            not_found += 1

    except KeyboardInterrupt:
        print(f"\n\nInterrupted! Saving progress ({found} audio matches found)...")
    except Exception as e:
        print(f"\n\nError: {e}")
        print(f"Saving progress ({found} audio matches found)...")

    # Save updated CSV
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    out_csv = OUTPUT_DIR / f"notion_enriched_{stamp}.csv"
    with open(out_csv, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)

    # Save/append attribution log
    attr_path = AUDIO_DIR / "attribution.csv"
    write_header = not attr_path.exists()
    if attribution_rows:
        attr_path.parent.mkdir(parents=True, exist_ok=True)
        with open(attr_path, "a", newline="", encoding="utf-8") as f:
            w = csv.DictWriter(f, fieldnames=[
                "word", "source", "speaker", "license", "original_filename", "url"
            ])
            if write_header:
                w.writeheader()
            w.writerows(attribution_rows)

    print(f"\n{'DRY RUN — ' if args.dry_run else ''}Summary:")
    print(f"  Total rows:      {len(rows)}")
    print(f"  Audio found:     {found}")
    print(f"  Already had:     {already_has}")
    print(f"  Not in LL:       {not_found}")
    if not args.dry_run:
        print(f"  Downloaded:      {downloaded}")
    print(f"  CSV saved:       {out_csv}")
    print(f"  Attribution log: {attr_path}")


if __name__ == "__main__":
    main()
