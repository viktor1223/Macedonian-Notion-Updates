"""
Apply Lexical Frequency Band values to a Notion export/enriched CSV.

Usage:
    python apply_frequency_band_to_export.py
    python apply_frequency_band_to_export.py output/notion_enriched_*.csv output/mk_frequency_vocab_*.csv
"""

from __future__ import annotations

import csv
import re
import sys
from datetime import datetime
from pathlib import Path


ROOT_DIR = Path(__file__).parent
OUTPUT_DIR = ROOT_DIR / "output"

TOKEN_PATTERN = re.compile(r"[a-zA-Zа-шА-ШѓќѕџЃЌЅЏјљњЈЉЊ]+", re.UNICODE)


def latest_matching(pattern: str) -> Path:
    matches = sorted(OUTPUT_DIR.glob(pattern))
    if not matches:
        raise FileNotFoundError(f"No files matched: {pattern}")
    return matches[-1]


def parse_rank(value: str) -> int:
    try:
        return int(str(value).strip())
    except Exception:
        return 10**9


def rank_to_band(rank: int) -> str:
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


def tokenize(value: str) -> list[str]:
    return [tok.lower() for tok in TOKEN_PATTERN.findall(value or "") if tok]


def load_frequency_index(freq_csv_path: Path) -> tuple[dict[str, int], dict[str, str]]:
    by_rank: dict[str, int] = {}
    by_band: dict[str, str] = {}
    with open(freq_csv_path, newline="", encoding="utf-8") as handle:
        for row in csv.DictReader(handle):
            word = (row.get("Macedonian") or "").strip().lower()
            if not word:
                continue
            rank = parse_rank(row.get("Frequency Rank", ""))
            band = (row.get("Lexical Frequency Band") or "").strip() or rank_to_band(rank)

            existing = by_rank.get(word)
            if existing is None or rank < existing:
                by_rank[word] = rank
                by_band[word] = band
    return by_rank, by_band


def resolve_row_band(row: dict[str, str], rank_index: dict[str, int], band_index: dict[str, str]) -> str:
    candidates = []
    cyr_text = (row.get("Macedonian (Cyrillic) ") or "").strip()
    latin_text = (row.get("Macedonian (Latin)") or "").strip()
    raw_text = cyr_text or latin_text

    for token in tokenize(raw_text):
        rank = rank_index.get(token)
        if rank is not None:
            candidates.append((rank, token))

    if not candidates:
        return "Unknown"

    best_rank, best_token = min(candidates, key=lambda item: item[0])
    return band_index.get(best_token, rank_to_band(best_rank))


def main() -> None:
    input_csv = Path(sys.argv[1]) if len(sys.argv) > 1 else latest_matching("notion_enriched_*.csv")
    freq_csv = Path(sys.argv[2]) if len(sys.argv) > 2 else latest_matching("mk_frequency_vocab_*.csv")

    input_csv = input_csv.expanduser().resolve()
    freq_csv = freq_csv.expanduser().resolve()

    rank_index, band_index = load_frequency_index(freq_csv)

    with open(input_csv, newline="", encoding="utf-8") as handle:
        reader = csv.DictReader(handle)
        fieldnames = list(reader.fieldnames or [])
        rows = list(reader)

    if "Lexical Frequency Band" not in fieldnames:
        fieldnames.append("Lexical Frequency Band")

    assigned = 0
    for row in rows:
        band = resolve_row_band(row, rank_index, band_index)
        row["Lexical Frequency Band"] = band
        assigned += 1

    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    out_path = OUTPUT_DIR / f"notion_banded_{stamp}.csv"
    with open(out_path, "w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)

    print(f"Input rows: {len(rows)}")
    print(f"Assigned:   {assigned}")
    print(f"Output:     {out_path}")


if __name__ == "__main__":
    main()