"""
Build a Macedonian core vocabulary frequency list from open/reusable sources,
assign lexical frequency bands, and export Notion-ready CSV files.

Usage examples:

  # 1) Build only source metadata manifest
  python build_frequency_bands.py --export-manifest-only

  # 2) Build frequencies from one or more source/path pairs
  python build_frequency_bands.py \
    --source-input learner_owned_tutor_vocab=output/notion_export_20260624_214530.csv

  # 3) Multiple corpora (file, directory, or glob)
  python build_frequency_bands.py \
    --source-input mk_wikipedia_dump=corpora/wiki_mk.txt \
    --source-input mozilla_common_voice_mk='corpora/common_voice/mk/*.tsv'
"""

from __future__ import annotations

import argparse
import csv
import gzip
import json
import re
from collections import Counter, defaultdict
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable

OUTPUT_DIR = Path(__file__).parent / "output"
DEFAULT_DICTIONARY_GLOB = "sources/dictionaries/*.txt"


@dataclass(frozen=True)
class SourceMeta:
    source_id: str
    source_name: str
    license: str
    attribution_requirement: str
    download_url: str
    language: str
    redistribution_allowed: bool
    approved_for_use: bool


# Curated, reproducible source registry. Use only approved entries for production.
SOURCE_REGISTRY = {
    "mk_wikipedia_dump": SourceMeta(
        source_id="mk_wikipedia_dump",
        source_name="Macedonian Wikipedia Dump",
        license="CC BY-SA 4.0",
        attribution_requirement="Required (CC BY-SA 4.0 attribution and share-alike)",
        download_url="https://dumps.wikimedia.org/mkwiki/latest/",
        language="mk",
        redistribution_allowed=True,
        approved_for_use=True,
    ),
    "mozilla_common_voice_mk": SourceMeta(
        source_id="mozilla_common_voice_mk",
        source_name="Mozilla Common Voice (Macedonian)",
        license="CC0-1.0",
        attribution_requirement="No attribution required (recommended to mention source)",
        download_url="https://commonvoice.mozilla.org/en/datasets",
        language="mk",
        redistribution_allowed=True,
        approved_for_use=True,
    ),
    "open_subtitles_mk": SourceMeta(
        source_id="open_subtitles_mk",
        source_name="OpenSubtitles (Macedonian)",
        license="Check dataset-specific terms before reuse",
        attribution_requirement="Depends on release/rights holder",
        download_url="https://opus.nlpl.eu/OpenSubtitles.php",
        language="mk",
        redistribution_allowed=False,
        approved_for_use=False,
    ),
    "learner_owned_tutor_vocab": SourceMeta(
        source_id="learner_owned_tutor_vocab",
        source_name="Learner-owned Tutor Vocabulary",
        license="Owner controlled",
        attribution_requirement="As specified by owner",
        download_url="local/owned-content",
        language="mk",
        redistribution_allowed=True,
        approved_for_use=True,
    ),
    "open_macedonian_books": SourceMeta(
        source_id="open_macedonian_books",
        source_name="Open Macedonian Books/Readers",
        license="Varies by book",
        attribution_requirement="Depends on specific text license",
        download_url="Provide per-book source URL",
        language="mk",
        redistribution_allowed=False,
        approved_for_use=False,
    ),
}

FREQ_BANDS = [
    (1, 100, "Top 100"),
    (101, 500, "Top 500"),
    (501, 1000, "Top 1000"),
    (1001, 2000, "Top 2000"),
    (2001, 5000, "Top 5000"),
]

TOKEN_RE = re.compile(r"[\u0400-\u04FF]+", re.UNICODE)

# A lightweight Macedonian heuristic for document-level language filtering.
MK_HINT_WORDS = {
    "и",
    "во",
    "не",
    "се",
    "на",
    "што",
    "јас",
    "ти",
    "тој",
    "таа",
    "ние",
    "вие",
    "ова",
    "како",
    "со",
    "за",
    "сум",
}
MK_DISTINCT_CHARS = set("ѓќѕџљњј")

# Lightweight suffix list for heuristic lemma recovery.
LEMMA_SUFFIXES = [
    "ите",
    "овите",
    "евите",
    "ува",
    "ував",
    "увавме",
    "увавте",
    "уваат",
    "аме",
    "ете",
    "ови",
    "еви",
    "ови",
    "та",
    "то",
    "те",
    "ов",
    "ев",
    "ам",
    "еш",
    "е",
    "а",
    "и",
    "у",
]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Build Macedonian lexical frequency bands")
    parser.add_argument(
        "--source-input",
        action="append",
        default=[],
        help="SOURCE_ID=PATH (file, directory, or glob). Repeat for multiple sources.",
    )
    parser.add_argument(
        "--output-prefix",
        default="mk_frequency",
        help="Prefix used for generated output files.",
    )
    parser.add_argument(
        "--min-token-length",
        type=int,
        default=2,
        help="Minimum token length to keep (default: 2).",
    )
    parser.add_argument(
        "--export-manifest-only",
        action="store_true",
        help="Export source metadata only, then exit.",
    )
    parser.add_argument(
        "--dictionary",
        action="append",
        default=[],
        help=(
            "Dictionary file or glob for Macedonian word validation. "
            "Repeat for multiple files. Defaults to sources/dictionaries/*.txt"
        ),
    )
    return parser.parse_args()


def utc_now_str() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d")


def export_source_manifest(stamp: str) -> tuple[Path, Path]:
    OUTPUT_DIR.mkdir(exist_ok=True)
    rows = []
    for source in SOURCE_REGISTRY.values():
        rows.append(
            {
                "Source ID": source.source_id,
                "Source Name": source.source_name,
                "License": source.license,
                "Attribution Requirement": source.attribution_requirement,
                "Download URL": source.download_url,
                "Download Date": stamp,
                "Language": source.language,
                "Redistribution Allowed": "Yes" if source.redistribution_allowed else "No",
                "Approved for Use": "Yes" if source.approved_for_use else "No",
            }
        )

    csv_path = OUTPUT_DIR / "mk_source_manifest.csv"
    json_path = OUTPUT_DIR / "mk_source_manifest.json"

    with open(csv_path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
        writer.writeheader()
        writer.writerows(rows)

    with open(json_path, "w", encoding="utf-8") as f:
        json.dump(rows, f, ensure_ascii=False, indent=2)

    return csv_path, json_path


def parse_source_inputs(items: list[str]) -> list[tuple[str, str]]:
    parsed: list[tuple[str, str]] = []
    for item in items:
        if "=" not in item:
            raise ValueError(f"Invalid --source-input '{item}'. Expected SOURCE_ID=PATH")
        source_id, path_expr = item.split("=", 1)
        source_id = source_id.strip()
        path_expr = path_expr.strip()
        if not source_id or not path_expr:
            raise ValueError(f"Invalid --source-input '{item}'. Expected SOURCE_ID=PATH")
        if source_id not in SOURCE_REGISTRY:
            valid = ", ".join(sorted(SOURCE_REGISTRY.keys()))
            raise ValueError(f"Unknown source id '{source_id}'. Valid source IDs: {valid}")
        parsed.append((source_id, path_expr))
    return parsed


def resolve_paths(path_expr: str) -> list[Path]:
    p = Path(path_expr)
    if p.exists():
        if p.is_file():
            return [p]
        return sorted(x for x in p.rglob("*") if x.is_file())

    # Treat as glob relative to project root.
    root = Path(__file__).parent
    return sorted(root.glob(path_expr))


def load_dictionary_words(path_exprs: list[str]) -> tuple[set[str], list[str]]:
    dictionary_words: set[str] = set()
    loaded_files: list[str] = []

    for expr in path_exprs:
        for path in resolve_paths(expr):
            loaded_files.append(str(path))
            lower = path.name.lower()

            if lower.endswith(".csv") or lower.endswith(".tsv"):
                delimiter = "\t" if lower.endswith(".tsv") else ","
                with open(path, newline="", encoding="utf-8", errors="ignore") as f:
                    reader = csv.DictReader(f, delimiter=delimiter)
                    for row in reader:
                        for key in ("word", "lemma", "Macedonian", "mk", "token"):
                            value = row.get(key)
                            if value:
                                token = value.strip().lower()
                                if token:
                                    dictionary_words.add(token)
                                break
                continue

            with open(path, encoding="utf-8", errors="ignore") as f:
                for line in f:
                    token = line.strip().lower()
                    if token and not token.startswith("#"):
                        dictionary_words.add(token)

    return dictionary_words, loaded_files


def guess_lemma(token: str) -> str:
    for suffix in sorted(LEMMA_SUFFIXES, key=len, reverse=True):
        if token.endswith(suffix) and len(token) > len(suffix) + 1:
            return token[: -len(suffix)]
    return token


def validate_token(token: str, dictionary_words: set[str]) -> tuple[str, str, str]:
    if not dictionary_words:
        return "Unknown", "", "No dictionary loaded"

    if token in dictionary_words:
        return "Confirmed", token, "Dictionary direct match"

    lemma = guess_lemma(token)
    if lemma in dictionary_words:
        return "Probable", lemma, "Lemma heuristic matched dictionary"

    return "Unknown", lemma if lemma != token else "", "No dictionary hit"


def read_text_from_file(path: Path) -> Iterable[str]:
    lower = path.name.lower()

    if lower.endswith(".txt"):
        with open(path, encoding="utf-8", errors="ignore") as f:
            for line in f:
                text = line.strip()
                if text:
                    yield text
        return

    if lower.endswith(".gz"):
        with gzip.open(path, "rt", encoding="utf-8", errors="ignore") as f:
            for line in f:
                text = line.strip()
                if text:
                    yield text
        return

    if lower.endswith(".jsonl"):
        with open(path, encoding="utf-8", errors="ignore") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                obj = json.loads(line)
                for candidate in (
                    obj.get("sentence"),
                    obj.get("text"),
                    obj.get("content"),
                    obj.get("mk"),
                    obj.get("Macedonian (Cyrillic)"),
                ):
                    if isinstance(candidate, str) and candidate.strip():
                        yield candidate.strip()
                        break
        return

    if lower.endswith(".json"):
        with open(path, encoding="utf-8", errors="ignore") as f:
            obj = json.load(f)
        if isinstance(obj, list):
            for row in obj:
                if isinstance(row, dict):
                    for candidate in (
                        row.get("sentence"),
                        row.get("text"),
                        row.get("content"),
                        row.get("mk"),
                        row.get("Macedonian (Cyrillic)"),
                    ):
                        if isinstance(candidate, str) and candidate.strip():
                            yield candidate.strip()
                            break
                elif isinstance(row, str) and row.strip():
                    yield row.strip()
        return

    if lower.endswith(".csv") or lower.endswith(".tsv"):
        delimiter = "\t" if lower.endswith(".tsv") else ","
        with open(path, newline="", encoding="utf-8", errors="ignore") as f:
            reader = csv.DictReader(f, delimiter=delimiter)
            for row in reader:
                for key in (
                    "sentence",
                    "text",
                    "mk",
                    "Macedonian (Cyrillic)",
                    "Macedonian (Cyrillic) ",
                    "Macedonian",
                    "content",
                ):
                    value = row.get(key)
                    if value and value.strip():
                        yield value.strip()
                        break
        return


def normalize_text(text: str) -> str:
    # Lowercase and normalize common punctuation/spacing artifacts.
    text = text.lower().replace("’", "'")
    text = re.sub(r"\s+", " ", text)
    return text.strip()


def extract_tokens(text: str, min_token_length: int) -> list[str]:
    tokens = TOKEN_RE.findall(text)
    return [t for t in tokens if len(t) >= min_token_length]


def is_probably_macedonian(text: str) -> bool:
    clean = normalize_text(text)
    if not clean:
        return False

    cyrillic_chars = [c for c in clean if "\u0400" <= c <= "\u04FF"]
    if not cyrillic_chars:
        return False

    cyr_ratio = len(cyrillic_chars) / max(1, len(clean.replace(" ", "")))
    tokens = TOKEN_RE.findall(clean)
    if not tokens:
        return False

    hint_hits = sum(1 for t in tokens if t in MK_HINT_WORDS)
    distinct_hits = sum(1 for c in set(clean) if c in MK_DISTINCT_CHARS)

    # Balanced heuristic: script dominance + either common function words or
    # distinct Macedonian graphemes.
    return cyr_ratio >= 0.55 and (hint_hits >= 1 or distinct_hits >= 1)


def band_for_rank(rank: int) -> str:
    for start, end, label in FREQ_BANDS:
        if start <= rank <= end:
            return label
    return "Outside Core"


def build_frequency(
    source_inputs: list[tuple[str, str]],
    min_token_length: int,
    dictionary_words: set[str],
) -> tuple[list[dict], dict]:
    counter: Counter[str] = Counter()
    token_sources: dict[str, set[str]] = defaultdict(set)
    stats = {
        "documents_total": 0,
        "documents_accepted_mk": 0,
        "documents_rejected_non_mk": 0,
        "sources_used": [],
        "sources_skipped": [],
        "dictionary_loaded": bool(dictionary_words),
        "dictionary_size": len(dictionary_words),
    }

    for source_id, path_expr in source_inputs:
        source_meta = SOURCE_REGISTRY[source_id]
        if not source_meta.approved_for_use:
            stats["sources_skipped"].append(
                {
                    "source_id": source_id,
                    "reason": "Not approved for use based on current license policy",
                }
            )
            continue

        paths = resolve_paths(path_expr)
        if not paths:
            stats["sources_skipped"].append(
                {
                    "source_id": source_id,
                    "reason": f"No files matched path expression: {path_expr}",
                }
            )
            continue

        stats["sources_used"].append({"source_id": source_id, "files": len(paths)})

        for path in paths:
            for text in read_text_from_file(path):
                stats["documents_total"] += 1
                if not is_probably_macedonian(text):
                    stats["documents_rejected_non_mk"] += 1
                    continue

                stats["documents_accepted_mk"] += 1
                normalized = normalize_text(text)
                tokens = extract_tokens(normalized, min_token_length)
                for token in tokens:
                    counter[token] += 1
                    token_sources[token].add(source_id)

    ranked = []
    for rank, (token, freq) in enumerate(counter.most_common(), start=1):
        validation_confidence, lemma_candidate, validation_notes = validate_token(token, dictionary_words)
        ranked.append(
            {
                "Rank": rank,
                "Macedonian": token,
                "Frequency": freq,
                "Lexical Frequency Band": band_for_rank(rank),
                "Source": ", ".join(sorted(token_sources[token])),
                "Dictionary Match": "Yes" if validation_confidence == "Confirmed" else "No",
                "Lemma Candidate": lemma_candidate,
                "Validation Confidence": validation_confidence,
                "Validation Notes": validation_notes,
            }
        )

    stats["validated_confirmed"] = sum(1 for row in ranked if row["Validation Confidence"] == "Confirmed")
    stats["validated_probable"] = sum(1 for row in ranked if row["Validation Confidence"] == "Probable")
    stats["validated_unknown"] = sum(1 for row in ranked if row["Validation Confidence"] == "Unknown")

    return ranked, stats


def export_ranked_vocab(prefix: str, ranked: list[dict]) -> Path:
    path = OUTPUT_DIR / f"{prefix}_vocab.csv"
    with open(path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(
            f,
            fieldnames=[
                "Frequency Rank",
                "Macedonian",
                "Frequency Count",
                "Lexical Frequency Band",
                "Source",
                "Dictionary Match",
                "Lemma Candidate",
                "Validation Confidence",
                "Validation Notes",
            ],
        )
        writer.writeheader()
        for row in ranked:
            writer.writerow(
                {
                    "Frequency Rank": row["Rank"],
                    "Macedonian": row["Macedonian"],
                    "Frequency Count": row["Frequency"],
                    "Lexical Frequency Band": row["Lexical Frequency Band"],
                    "Source": row["Source"],
                    "Dictionary Match": row["Dictionary Match"],
                    "Lemma Candidate": row["Lemma Candidate"],
                    "Validation Confidence": row["Validation Confidence"],
                    "Validation Notes": row["Validation Notes"],
                }
            )
    return path


def export_notion_import(prefix: str, ranked: list[dict]) -> Path:
    path = OUTPUT_DIR / f"{prefix}_notion_import.csv"
    rows = []
    for item in ranked:
        rows.append(
            {
                # Required fields
                "Macedonian": item["Macedonian"],
                "English": "",
                "Lexical Frequency Band": item["Lexical Frequency Band"],
                "Source": item["Source"],
                "Review Status": "Pending Review",
                "Part of Speech": "",
                "Notes": f"Rank={item['Rank']}; Frequency={item['Frequency']}",
                # Optional fields
                "Lemma": item["Macedonian"],
                "Example Sentence": "",
                "Audio Status": "",
                "Duplicate Status": "",
                "Anki Status": "",
                "Frequency Rank": item["Rank"],
                "Frequency Count": item["Frequency"],
                "Dictionary Match": item["Dictionary Match"],
                "Lemma Candidate": item["Lemma Candidate"],
                "Validation Confidence": item["Validation Confidence"],
                "Validation Notes": item["Validation Notes"],
            }
        )

    with open(path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(
            f,
            fieldnames=[
                "Macedonian",
                "English",
                "Lexical Frequency Band",
                "Source",
                "Review Status",
                "Part of Speech",
                "Notes",
                "Lemma",
                "Example Sentence",
                "Audio Status",
                "Duplicate Status",
                "Anki Status",
                "Frequency Rank",
                "Frequency Count",
                "Dictionary Match",
                "Lemma Candidate",
                "Validation Confidence",
                "Validation Notes",
            ],
        )
        writer.writeheader()
        writer.writerows(rows)

    return path


def export_stats(prefix: str, stats: dict) -> Path:
    path = OUTPUT_DIR / f"{prefix}_build_stats.json"
    with open(path, "w", encoding="utf-8") as f:
        json.dump(stats, f, ensure_ascii=False, indent=2)
    return path


def main() -> None:
    args = parse_args()
    OUTPUT_DIR.mkdir(exist_ok=True)

    stamp = utc_now_str()
    manifest_csv, manifest_json = export_source_manifest(stamp)
    print(f"Source manifest CSV:  {manifest_csv}")
    print(f"Source manifest JSON: {manifest_json}")

    if args.export_manifest_only:
        print("Exported manifest only. Done.")
        return

    dictionary_inputs = args.dictionary or [DEFAULT_DICTIONARY_GLOB]
    dictionary_words, loaded_dict_files = load_dictionary_words(dictionary_inputs)
    print(
        f"Dictionary words loaded: {len(dictionary_words)} "
        f"from {len(loaded_dict_files)} file(s)"
    )

    source_inputs = parse_source_inputs(args.source_input)
    if not source_inputs:
        raise ValueError(
            "No source input provided. Use --source-input SOURCE_ID=PATH at least once."
        )

    ranked, stats = build_frequency(source_inputs, args.min_token_length, dictionary_words)
    stats["dictionary_inputs"] = dictionary_inputs
    stats["dictionary_files"] = loaded_dict_files

    ranked_path = export_ranked_vocab(args.output_prefix, ranked)
    notion_path = export_notion_import(args.output_prefix, ranked)
    stats_path = export_stats(args.output_prefix, stats)

    print(f"Ranked vocabulary:    {ranked_path}")
    print(f"Notion import CSV:    {notion_path}")
    print(f"Build stats JSON:     {stats_path}")
    print(
        "Summary: "
        f"docs_total={stats['documents_total']}, "
        f"mk_docs={stats['documents_accepted_mk']}, "
        f"rejected_non_mk={stats['documents_rejected_non_mk']}, "
        f"vocab_size={len(ranked)}, "
        f"confirmed={stats['validated_confirmed']}, "
        f"probable={stats['validated_probable']}, "
        f"unknown={stats['validated_unknown']}"
    )


if __name__ == "__main__":
    main()
