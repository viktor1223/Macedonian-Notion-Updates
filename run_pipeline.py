"""
Full pipeline: Fetch from Notion → Enrich (dictionary-first) → Fetch Audio → Output

Runs the entire enrichment + audio pipeline with ZERO LLM calls:
  1. Pull current data from Notion (preserves existing Category/Level)
  2. Enrich with dictionary: POS, English, Latin, Gender, Forms
  3. Fetch pronunciation audio (Lingua Libre + Common Voice)
  4. Output a single CSV ready for push_to_notion.py

Usage:
    python run_pipeline.py                   # full pipeline
    python run_pipeline.py --skip-fetch      # skip Notion fetch, use latest export
    python run_pipeline.py --skip-audio      # skip audio download
    python run_pipeline.py --dry-run         # no downloads, just report coverage
"""

from __future__ import annotations

import csv
import subprocess
import sys
from datetime import datetime
from pathlib import Path

OUTPUT_DIR = Path(__file__).parent / "output"


def run_step(description: str, cmd: list[str]) -> int:
    """Run a pipeline step, print header, return exit code."""
    print()
    print("=" * 60)
    print(f"  {description}")
    print("=" * 60)
    result = subprocess.run(cmd, cwd=Path(__file__).parent)
    return result.returncode


def latest_file(pattern: str) -> Path | None:
    """Find the most recent file matching a glob pattern."""
    files = sorted(OUTPUT_DIR.glob(pattern), reverse=True)
    return files[0] if files else None


def main():
    import argparse
    parser = argparse.ArgumentParser(description="Full Macedonian vocab pipeline (no AI)")
    parser.add_argument("--skip-fetch", action="store_true",
                        help="Skip Notion fetch, use latest existing export")
    parser.add_argument("--skip-audio", action="store_true",
                        help="Skip audio fetching")
    parser.add_argument("--dry-run", action="store_true",
                        help="Report what would happen without downloading anything")
    parser.add_argument("--input", type=str, default=None,
                        help="Explicit input CSV (skips Notion fetch)")
    args = parser.parse_args()

    print("╔══════════════════════════════════════════════════════════╗")
    print("║  MACEDONIAN VOCAB PIPELINE (Dictionary-First, No LLM)  ║")
    print("╚══════════════════════════════════════════════════════════╝")
    print(f"  Time: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print(f"  Mode: {'DRY RUN' if args.dry_run else 'FULL'}")

    # ── Step 1: Fetch from Notion ──
    if args.input:
        export_csv = Path(args.input)
        print(f"\n  Using explicit input: {export_csv}")
    elif args.skip_fetch:
        export_csv = latest_file("notion_export_*.csv")
        if not export_csv:
            # Fall back to latest enriched
            export_csv = latest_file("notion_enriched_*.csv")
        if not export_csv:
            print("ERROR: No export CSV found. Run without --skip-fetch.")
            sys.exit(1)
        print(f"\n  Using existing export: {export_csv}")
    else:
        rc = run_step("Step 1: Fetching from Notion", [
            sys.executable, "notion_fetch.py"
        ])
        if rc != 0:
            print("ERROR: Notion fetch failed.")
            sys.exit(1)
        export_csv = latest_file("notion_export_*.csv")
        if not export_csv:
            print("ERROR: No export CSV produced.")
            sys.exit(1)
        print(f"  → {export_csv}")

    # ── Step 2: Enrich with dictionary (no AI) ──
    rc = run_step("Step 2: Dictionary enrichment (POS, English, Latin)", [
        sys.executable, "enrich_csv.py", str(export_csv), "--no-ai"
    ])
    if rc != 0:
        print("ERROR: Enrichment failed.")
        sys.exit(1)

    enriched_csv = latest_file("notion_enriched_*.csv")
    if not enriched_csv:
        print("ERROR: No enriched CSV produced.")
        sys.exit(1)
    print(f"  → {enriched_csv}")

    # ── Step 3: Fetch audio ──
    if args.skip_audio:
        print("\n  [SKIPPING AUDIO]")
        final_csv = enriched_csv
    else:
        audio_args = [sys.executable, "fetch_audio.py", str(enriched_csv)]
        if args.dry_run:
            audio_args.append("--dry-run")

        rc = run_step("Step 3: Fetching pronunciation audio", audio_args)
        if rc != 0:
            print("WARNING: Audio fetch had errors (continuing with available data).")

        # fetch_audio.py saves its own enriched CSV with audio columns
        post_audio = latest_file("notion_enriched_*.csv")
        final_csv = post_audio if post_audio and post_audio != enriched_csv else enriched_csv

    # ── Summary ──
    print()
    print("=" * 60)
    print("  PIPELINE COMPLETE")
    print("=" * 60)
    print(f"  Final CSV: {final_csv}")

    # Quick stats
    with open(final_csv, newline="", encoding="utf-8") as f:
        rows = list(csv.DictReader(f))

    total = len(rows)
    has_pos = sum(1 for r in rows if (r.get("Position in a sentence") or "").strip())
    has_eng = sum(1 for r in rows if (r.get("English") or "").strip())
    has_cat = sum(1 for r in rows if (r.get("Category") or "").strip())
    has_lvl = sum(1 for r in rows if (r.get("Level") or "").strip())
    has_audio = sum(1 for r in rows if (r.get("Audio URL") or r.get("Audio File") or "").strip())

    print(f"\n  Coverage ({total} rows):")
    print(f"    Position (POS):  {has_pos:>4} ({100*has_pos//total}%)")
    print(f"    English:         {has_eng:>4} ({100*has_eng//total}%)")
    print(f"    Category:        {has_cat:>4} ({100*has_cat//total}%)")
    print(f"    Level:           {has_lvl:>4} ({100*has_lvl//total}%)")
    print(f"    Audio:           {has_audio:>4} ({100*has_audio//total}%)")

    missing_cat = total - has_cat
    missing_lvl = total - has_lvl
    if missing_cat > 0 or missing_lvl > 0:
        print(f"\n  ⚠ {missing_cat} rows still need Category, {missing_lvl} need Level.")
        print(f"    These require LLM. Run: python enrich_csv.py {final_csv}")
        print(f"    (Only those {max(missing_cat, missing_lvl)} rows will trigger AI calls)")

    print(f"\n  To push to Notion:")
    print(f"    python push_to_notion.py {final_csv}")
    print()


if __name__ == "__main__":
    main()
