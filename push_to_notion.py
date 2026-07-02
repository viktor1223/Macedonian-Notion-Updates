"""
Push enriched CSV data back to Notion, updating four properties per page:
    - Category               (multi_select) — now renamed from 'Catagories'
    - Position in a sentence (multi_select)
    - Level                  (select)
    - Lexical Frequency Band (select)

Deliberately leaves 'Lesson ' untouched — it is managed separately
and links to practice-problem pages.

Usage:
    python push_to_notion.py                           # uses latest enriched CSV
    python push_to_notion.py output/my_enriched.csv   # explicit file
"""

import csv
import os
import sys
import time
from pathlib import Path

import requests
from dotenv import load_dotenv

load_dotenv()

NOTION_API_VERSION = "2022-06-28"
NOTION_BASE_URL = "https://api.notion.com/v1"
OUTPUT_DIR = Path(__file__).parent / "output"

# Properties we write back — Lesson  is intentionally excluded
PUSH_PROPERTIES = {"Category", "Position in a sentence", "Level", "Lexical Frequency Band", "Lemma Family"}


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def get_token() -> str:
    token = os.getenv("NOTION_TOKEN")
    if not token:
        raise EnvironmentError("NOTION_TOKEN not set in .env")
    return token


def headers(token: str) -> dict:
    return {
        "Authorization": f"Bearer {token}",
        "Notion-Version": NOTION_API_VERSION,
        "Content-Type": "application/json",
    }


def csv_value_to_multi_select(value: str) -> list[dict]:
    """'Greetings & Farewells, Questions' → [{'name': ...}, ...]"""
    if not value or value.strip().lower() in ("none", ""):
        return []
    return [{"name": v.strip()} for v in value.split(",") if v.strip()]


def build_page_payload(row: dict) -> dict:
    """Build the Notion page PATCH payload from a CSV row."""
    props = {}

    pos = row.get("Position in a sentence", "").strip()
    if pos and pos.lower() != "none":
        props["Position in a sentence"] = {
            "multi_select": csv_value_to_multi_select(pos)
        }

    cat = row.get("Category", "").strip()
    if cat and cat.lower() != "none":
        props["Category"] = {
            "multi_select": csv_value_to_multi_select(cat)
        }

    level = row.get("Level", "").strip()
    if level:
        props["Level"] = {"select": {"name": level}}

    lexical_band = row.get("Lexical Frequency Band", "").strip()
    if lexical_band:
        props["Lexical Frequency Band"] = {"select": {"name": lexical_band}}

    # Lemma Family (rich_text) — groups inflected forms under their root
    lemma_family = row.get("Lemma Family", "").strip()
    if lemma_family:
        props["Lemma Family"] = {"rich_text": [{"text": {"content": lemma_family}}]}

    # Audio File (files property — external URL to playable audio)
    audio_url = row.get("Audio URL", "").strip()
    audio_file_local = row.get("Audio File", "").strip()
    if audio_url:
        # Use the public URL directly (Lingua Libre, etc.)
        word_display = row.get("Macedonian (Cyrillic) ", "audio").strip() or "audio"
        props["Audio File"] = {
            "files": [{
                "type": "external",
                "name": f"{word_display}.wav",
                "external": {"url": audio_url}
            }]
        }
    elif audio_file_local and audio_file_local.startswith("http"):
        # URL stored in Audio File column
        word_display = row.get("Macedonian (Cyrillic) ", "audio").strip() or "audio"
        props["Audio File"] = {
            "files": [{
                "type": "external",
                "name": f"{word_display}.wav",
                "external": {"url": audio_file_local}
            }]
        }

    # Audio Source (rich_text — attribution)
    audio_source = row.get("Audio Source", "").strip()
    if audio_source:
        props["Audio Source"] = {"rich_text": [{"text": {"content": audio_source}}]}

    # Fill English translation (rich_text)
    english = row.get("English", "").strip()
    if english:
        props["English"] = {"rich_text": [{"text": {"content": english}}]}

    # Fill Macedonian Latin transliteration (rich_text)
    latin = row.get("Macedonian (Latin)", "").strip()
    if latin:
        props["Macedonian (Latin)"] = {"rich_text": [{"text": {"content": latin}}]}

    # Fill Macedonian Cyrillic (title field) — only if it has content
    cyrillic = row.get("Macedonian (Cyrillic) ", "").strip()
    if cyrillic:
        props["Macedonian (Cyrillic) "] = {"title": [{"text": {"content": cyrillic}}]}

    return {"properties": props}


def update_page(token: str, page_id: str, payload: dict) -> dict:
    url = f"{NOTION_BASE_URL}/pages/{page_id}"
    for attempt in range(5):
        try:
            resp = requests.patch(url, headers=headers(token), json=payload, timeout=30)
            resp.raise_for_status()
            return resp.json()
        except (requests.ConnectionError, requests.exceptions.ChunkedEncodingError) as e:
            if attempt < 4:
                time.sleep(2 * (attempt + 1))
                continue
            raise


def latest_enriched() -> Path:
    files = sorted(OUTPUT_DIR.glob("notion_enriched_*.csv"))
    if not files:
        raise FileNotFoundError(f"No notion_enriched_*.csv found in {OUTPUT_DIR}")
    return files[-1]


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    input_path = Path(sys.argv[1]) if len(sys.argv) > 1 else latest_enriched()
    print(f"Input:  {input_path}\n")

    token = get_token()

    with open(input_path, newline="", encoding="utf-8") as f:
        rows = list(csv.DictReader(f))

    print(f"Pushing {len(rows)} pages to Notion …\n")

    ok = 0
    errors = 0
    for i, row in enumerate(rows, 1):
        page_id = row.get("id", "").strip()
        english = (row.get("English") or "").strip()

        if not page_id:
            print(f"  [{i:>3}] SKIP — no page ID")
            continue

        payload = build_page_payload(row)
        if not payload["properties"]:
            print(f"  [{i:>3}] SKIP — nothing to update  ({english})")
            continue

        try:
            update_page(token, page_id, payload)
            level = row.get("Level", "")
            cat   = row.get("Category", "")
            pos   = row.get("Position in a sentence", "")
            band  = row.get("Lexical Frequency Band", "")
            print(f"  [{i:>3}] OK  {english[:45]:<45} | {level} | {band} | {cat[:30]} | {pos}")
            ok += 1
        except requests.HTTPError as e:
            print(f"  [{i:>3}] ERR {english[:45]} — {e}")
            errors += 1

        # Notion rate-limit: ~3 req/s — small pause between writes
        time.sleep(0.35)

    print(f"\nDone. {ok} updated, {errors} errors.")


if __name__ == "__main__":
    main()
