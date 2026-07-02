"""
Assign Lexical Frequency Bands using the OpenSubtitles Macedonian frequency list
(Hermit Dave / FrequencyWords project, CC BY-SA 4.0).

This replaces the homemade frequency list with a professional 50k+ word list
derived from actual Macedonian subtitle usage (spoken everyday language).

Source: https://github.com/hermitdave/FrequencyWords
License: CC BY-SA 4.0

Usage:
    python assign_frequency_bands.py                          # uses latest enriched CSV
    python assign_frequency_bands.py output/my_export.csv    # explicit file
"""

from __future__ import annotations

import csv
import re
import sys
from datetime import datetime
from pathlib import Path

ROOT_DIR = Path(__file__).parent
OUTPUT_DIR = ROOT_DIR / "output"
FREQ_LIST_PATH = ROOT_DIR / "sources" / "frequency_lists" / "opensubtitles_mk_50k.txt"

CYRILLIC_RE = re.compile(r"[а-шА-ШѓќѕџЃЌЅЏјљњЈЉЊ]")
TOKEN_RE = re.compile(r"[а-шА-ШѓќѕџЃЌЅЏјљњЈЉЊ]+", re.UNICODE)


def load_frequency_ranks(freq_path: Path) -> dict[str, int]:
    """Load the OpenSubtitles frequency list: word → rank (1-based)."""
    ranks: dict[str, int] = {}
    with open(freq_path, encoding="utf-8") as f:
        for rank, line in enumerate(f, start=1):
            parts = line.strip().split()
            if parts:
                word = parts[0].lower()
                if word not in ranks:  # keep first occurrence (highest rank)
                    ranks[word] = rank
    return ranks


def rank_to_band(rank: int | None) -> str:
    if rank is None:
        return "Unknown"
    if rank <= 100:
        return "Top 100"
    if rank <= 500:
        return "Top 500"
    if rank <= 1000:
        return "Top 1000"
    if rank <= 2000:
        return "Top 2000"
    if rank <= 5000:
        return "Top 5000"
    return "Outside Core"


def get_best_rank(text: str, freq_ranks: dict[str, int]) -> int | None:
    """Find the best (lowest) rank among all Cyrillic tokens in text."""
    tokens = TOKEN_RE.findall(text.lower())
    if not tokens:
        return None

    best_rank = None
    for token in tokens:
        rank = freq_ranks.get(token)
        if rank is not None:
            if best_rank is None or rank < best_rank:
                best_rank = rank
    return best_rank


def latest_enriched() -> Path:
    files = sorted(OUTPUT_DIR.glob("notion_enriched_*.csv"))
    if not files:
        raise FileNotFoundError("No notion_enriched_*.csv found in output/")
    return files[-1]


def main() -> None:
    input_path = Path(sys.argv[1]) if len(sys.argv) > 1 else latest_enriched()
    print(f"Input:     {input_path}")
    print(f"Freq list: {FREQ_LIST_PATH}")

    if not FREQ_LIST_PATH.exists():
        raise FileNotFoundError(
            f"Frequency list not found: {FREQ_LIST_PATH}\n"
            "Download it: curl -sL https://raw.githubusercontent.com/hermitdave/FrequencyWords/master/content/2018/mk/mk_50k.txt "
            "-o sources/frequency_lists/opensubtitles_mk_50k.txt"
        )

    freq_ranks = load_frequency_ranks(FREQ_LIST_PATH)
    print(f"Loaded {len(freq_ranks)} frequency entries")

    with open(input_path, newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        fieldnames = list(reader.fieldnames or [])
        rows = list(reader)

    if "Lexical Frequency Band" not in fieldnames:
        fieldnames.append("Lexical Frequency Band")

    # Assign bands
    band_counts = {"Top 100": 0, "Top 500": 0, "Top 1000": 0, "Top 2000": 0, "Top 5000": 0, "Outside Core": 0, "Unknown": 0}
    for row in rows:
        cyr = (row.get("Macedonian (Cyrillic) ") or row.get("Macedonian (Cyrillic)") or "").strip()
        rank = get_best_rank(cyr, freq_ranks)
        band = rank_to_band(rank)
        row["Lexical Frequency Band"] = band
        band_counts[band] += 1

    # Save
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    out_path = OUTPUT_DIR / f"notion_banded_{stamp}.csv"
    with open(out_path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)

    print(f"\nBand distribution:")
    for band in ["Top 100", "Top 500", "Top 1000", "Top 2000", "Top 5000", "Outside Core", "Unknown"]:
        print(f"  {band:<14} {band_counts[band]}")
    print(f"\nTotal: {len(rows)} rows")
    print(f"Output: {out_path}")


if __name__ == "__main__":
    main()
