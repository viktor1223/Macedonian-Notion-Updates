"""
Detect duplicate entries in the Notion vocabulary database.

Checks for:
  1. Exact Cyrillic duplicates
  2. Cyrillic vs Latin transliteration collisions
  3. Inflected-form duplicates (same lemma/root)
  4. Same-English-meaning duplicates

Outputs a deduplication report CSV with suggested actions.

Usage:
    python deduplicate.py                              # uses latest enriched CSV
    python deduplicate.py output/my_export.csv        # explicit file
"""

from __future__ import annotations

import csv
import re
import sys
from collections import defaultdict
from datetime import datetime
from pathlib import Path

OUTPUT_DIR = Path(__file__).parent / "output"

# Macedonian Latin-to-Cyrillic transliteration for normalization
LATIN_DIGRAPHS = [
    ("dzh", "џ"), ("dz", "ѕ"), ("gj", "ѓ"), ("kj", "ќ"),
    ("lj", "љ"), ("nj", "њ"), ("zh", "ж"), ("ch", "ч"), ("sh", "ш"),
]
LATIN_CHAR_MAP = {
    "a": "а", "b": "б", "v": "в", "g": "г", "d": "д", "e": "е",
    "z": "з", "i": "и", "j": "ј", "k": "к", "l": "л", "m": "м",
    "n": "н", "o": "о", "p": "п", "r": "р", "s": "с", "t": "т",
    "u": "у", "f": "ф", "h": "х", "c": "ц",
}
CYRILLIC_RE = re.compile(r"[а-шѓќѕџјљњ]", re.IGNORECASE)

# Suffix patterns for lemma-based dedup
INFLECTION_SUFFIXES = [
    "ите", "овите", "евите", "ата", "ото", "ува", "ував",
    "увавме", "уваат", "аат", "еат", "ат", "ме", "те",
    "ови", "еви", "та", "то", "от", "на", "но",
    "ен", "на", "но", "ни", "ска", "ско", "ски",
    "иот", "ата", "ото", "ите",
    "ов", "ев", "ам", "еш", "е", "а", "и", "о",
]


def latin_to_cyrillic(token: str) -> str:
    value = token.lower().strip()
    for src, dst in LATIN_DIGRAPHS:
        value = value.replace(src, dst)
    out = []
    for char in value:
        if CYRILLIC_RE.match(char):
            out.append(char)
        else:
            out.append(LATIN_CHAR_MAP.get(char, char))
    return "".join(out)


def normalize_for_comparison(text: str) -> str:
    """Lowercase, strip accents/punctuation, normalize to Cyrillic."""
    text = text.lower().strip()
    text = re.sub(r"[^\w\s]", "", text)
    text = re.sub(r"\s+", " ", text).strip()
    # If mostly Latin, convert to Cyrillic
    if not CYRILLIC_RE.search(text):
        text = latin_to_cyrillic(text)
    # Remove accent marks (ѐ → е)
    text = text.replace("\u0300", "").replace("\u0301", "")
    return text


def guess_stem(word: str) -> str:
    """Heuristic stem by removing known Macedonian suffixes."""
    for suffix in sorted(INFLECTION_SUFFIXES, key=len, reverse=True):
        if word.endswith(suffix) and len(word) > len(suffix) + 2:
            return word[: -len(suffix)]
    return word


def latest_enriched() -> Path:
    files = sorted(OUTPUT_DIR.glob("notion_enriched_*.csv"))
    if not files:
        raise FileNotFoundError("No notion_enriched_*.csv found in output/")
    return files[-1]


def detect_duplicates(rows: list[dict]) -> list[dict]:
    findings: list[dict] = []
    row_index: dict[int, dict] = {i: row for i, row in enumerate(rows)}

    # --- 1. Exact Cyrillic duplicates ---
    cyr_groups: dict[str, list[int]] = defaultdict(list)
    for i, row in enumerate(rows):
        cyr = (row.get("Macedonian (Cyrillic) ") or row.get("Macedonian (Cyrillic)") or "").strip().lower()
        if cyr:
            cyr_groups[cyr].append(i)

    for word, indices in cyr_groups.items():
        if len(indices) > 1:
            for idx in indices[1:]:
                findings.append({
                    "Duplicate Type": "Exact Cyrillic",
                    "Word": rows[indices[0]].get("Macedonian (Cyrillic) ", "").strip(),
                    "Duplicate Of": rows[indices[0]].get("Macedonian (Cyrillic) ", "").strip(),
                    "Page ID": rows[idx].get("id", ""),
                    "Primary Page ID": rows[indices[0]].get("id", ""),
                    "English (this)": rows[idx].get("English", ""),
                    "English (primary)": rows[indices[0]].get("English", ""),
                    "Confidence": "High",
                    "Suggested Action": "Remove duplicate",
                })

    # --- 2. Transliteration collisions (Latin normalization) ---
    norm_groups: dict[str, list[int]] = defaultdict(list)
    for i, row in enumerate(rows):
        cyr = (row.get("Macedonian (Cyrillic) ") or row.get("Macedonian (Cyrillic)") or "").strip()
        if cyr:
            normalized = normalize_for_comparison(cyr)
            norm_groups[normalized].append(i)

    for norm, indices in norm_groups.items():
        if len(indices) > 1:
            words = [rows[i].get("Macedonian (Cyrillic) ", "").strip() for i in indices]
            # Only flag if the original forms are actually different
            if len(set(w.lower() for w in words)) > 1:
                primary = indices[0]
                for idx in indices[1:]:
                    findings.append({
                        "Duplicate Type": "Transliteration Collision",
                        "Word": rows[idx].get("Macedonian (Cyrillic) ", "").strip(),
                        "Duplicate Of": rows[primary].get("Macedonian (Cyrillic) ", "").strip(),
                        "Page ID": rows[idx].get("id", ""),
                        "Primary Page ID": rows[primary].get("id", ""),
                        "English (this)": rows[idx].get("English", ""),
                        "English (primary)": rows[primary].get("English", ""),
                        "Confidence": "Medium",
                        "Suggested Action": "Review — may be accent variant",
                    })

    # --- 3. Inflected-form duplicates (same stem) ---
    stem_groups: dict[str, list[int]] = defaultdict(list)
    for i, row in enumerate(rows):
        cyr = (row.get("Macedonian (Cyrillic) ") or row.get("Macedonian (Cyrillic)") or "").strip().lower()
        if cyr and len(cyr) > 3:
            stem = guess_stem(normalize_for_comparison(cyr))
            if len(stem) >= 3:
                stem_groups[stem].append(i)

    for stem, indices in stem_groups.items():
        if len(indices) > 1:
            words = [rows[i].get("Macedonian (Cyrillic) ", "").strip() for i in indices]
            # Only flag if the words are actually different
            unique_words = set(w.lower() for w in words)
            if len(unique_words) > 1:
                primary = indices[0]
                for idx in indices[1:]:
                    word_this = rows[idx].get("Macedonian (Cyrillic) ", "").strip()
                    word_primary = rows[primary].get("Macedonian (Cyrillic) ", "").strip()
                    # Don't double-report if already caught by exact/transliteration
                    if word_this.lower() == word_primary.lower():
                        continue
                    findings.append({
                        "Duplicate Type": "Inflected Form",
                        "Word": word_this,
                        "Duplicate Of": word_primary,
                        "Page ID": rows[idx].get("id", ""),
                        "Primary Page ID": rows[primary].get("id", ""),
                        "English (this)": rows[idx].get("English", ""),
                        "English (primary)": rows[primary].get("English", ""),
                        "Confidence": "Low",
                        "Suggested Action": "Review — may be same lemma (keep both or merge)",
                    })

    # --- 4. Same English meaning duplicates ---
    eng_groups: dict[str, list[int]] = defaultdict(list)
    for i, row in enumerate(rows):
        eng = (row.get("English") or "").strip().lower()
        if eng and len(eng) > 1:
            eng_groups[eng].append(i)

    for eng, indices in eng_groups.items():
        if len(indices) > 1:
            words = [rows[i].get("Macedonian (Cyrillic) ", "").strip() for i in indices]
            unique_words = set(w.lower() for w in words)
            if len(unique_words) > 1:
                primary = indices[0]
                for idx in indices[1:]:
                    word_this = rows[idx].get("Macedonian (Cyrillic) ", "").strip()
                    word_primary = rows[primary].get("Macedonian (Cyrillic) ", "").strip()
                    if word_this.lower() == word_primary.lower():
                        continue
                    findings.append({
                        "Duplicate Type": "Same English Meaning",
                        "Word": word_this,
                        "Duplicate Of": word_primary,
                        "Page ID": rows[idx].get("id", ""),
                        "Primary Page ID": rows[primary].get("id", ""),
                        "English (this)": rows[idx].get("English", ""),
                        "English (primary)": rows[primary].get("English", ""),
                        "Confidence": "Medium",
                        "Suggested Action": "Review — synonyms or inflections",
                    })

    return findings


def main() -> None:
    input_path = Path(sys.argv[1]) if len(sys.argv) > 1 else latest_enriched()
    print(f"Input: {input_path}")

    with open(input_path, newline="", encoding="utf-8") as f:
        rows = list(csv.DictReader(f))
    print(f"Total rows: {len(rows)}")

    findings = detect_duplicates(rows)

    # Deduplicate findings (same pair reported by multiple checks)
    seen_pairs: set[tuple[str, str]] = set()
    unique_findings: list[dict] = []
    for f_item in findings:
        pair = (f_item["Page ID"], f_item["Primary Page ID"])
        if pair not in seen_pairs:
            seen_pairs.add(pair)
            unique_findings.append(f_item)

    # Sort by confidence (High > Medium > Low) then by type
    confidence_order = {"High": 0, "Medium": 1, "Low": 2}
    unique_findings.sort(key=lambda x: (confidence_order.get(x["Confidence"], 9), x["Duplicate Type"]))

    # Summary
    by_type = defaultdict(int)
    by_confidence = defaultdict(int)
    for f_item in unique_findings:
        by_type[f_item["Duplicate Type"]] += 1
        by_confidence[f_item["Confidence"]] += 1

    print(f"\nDuplicate findings: {len(unique_findings)}")
    print("  By type:")
    for dtype, count in sorted(by_type.items()):
        print(f"    {dtype:<30} {count}")
    print("  By confidence:")
    for conf, count in sorted(by_confidence.items(), key=lambda x: confidence_order.get(x[0], 9)):
        print(f"    {conf:<10} {count}")

    # Save report
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    report_path = OUTPUT_DIR / f"dedup_report_{stamp}.csv"

    fieldnames = [
        "Duplicate Type", "Word", "Duplicate Of",
        "English (this)", "English (primary)",
        "Confidence", "Suggested Action",
        "Page ID", "Primary Page ID",
    ]
    with open(report_path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(unique_findings)

    print(f"\nReport saved → {report_path}")

    # Print top findings
    if unique_findings:
        print(f"\nTop 20 findings:")
        for item in unique_findings[:20]:
            print(f"  [{item['Confidence']:<6}] {item['Duplicate Type']:<25} "
                  f"{item['Word']:<18} ↔ {item['Duplicate Of']:<18} "
                  f"({item['English (this)'][:15]} / {item['English (primary)'][:15]})")


if __name__ == "__main__":
    main()
