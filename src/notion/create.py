"""
Add new vocabulary words to Notion from the frequency pipeline output.

Creates a new page for each word that doesn't already exist in the database.
Sets Lexical Frequency Band and other fields on creation.

Usage:
    python add_vocab_to_notion.py                                    # uses latest production import
    python add_vocab_to_notion.py output/mk_frequency_production_notion_import.csv
"""

import csv
import os
import sys
import time
from pathlib import Path

import requests
from dotenv import load_dotenv

load_dotenv()

DATABASE_ID = "31e2ef16fdf7821295f081b94e558d7e"
NOTION_API_VERSION = "2022-06-28"
NOTION_BASE_URL = "https://api.notion.com/v1"
OUTPUT_DIR = Path(__file__).parent.parent.parent / "output"

from src.core.notion_client import get_token, headers  # shared Notion client


def fetch_existing_words(token: str) -> set[str]:
    """Fetch all existing Macedonian (Cyrillic) values from the database."""
    url = f"{NOTION_BASE_URL}/databases/{DATABASE_ID}/query"
    existing: set[str] = set()
    cursor = None

    while True:
        payload = {"page_size": 100}
        if cursor:
            payload["start_cursor"] = cursor

        resp = requests.post(url, headers=headers(token), json=payload)
        resp.raise_for_status()
        data = resp.json()

        for page in data.get("results", []):
            props = page.get("properties", {})

            # Check Macedonian (Cyrillic) field (title or rich_text)
            for field_name in ["Macedonian (Cyrillic) ", "Macedonian (Cyrillic)"]:
                field = props.get(field_name, {})
                field_type = field.get("type")
                if field_type == "title":
                    text = "".join(rt.get("plain_text", "") for rt in field.get("title", []))
                elif field_type == "rich_text":
                    text = "".join(rt.get("plain_text", "") for rt in field.get("rich_text", []))
                else:
                    text = ""
                if text.strip():
                    existing.add(text.strip().lower())

        if data.get("has_more"):
            cursor = data.get("next_cursor")
        else:
            break

    return existing


def create_page(token: str, word: str, row: dict) -> dict:
    """Create a new page in the Notion database for a vocabulary word."""
    properties = {
        # Title field — Macedonian (Cyrillic)
        "Macedonian (Cyrillic) ": {
            "title": [{"text": {"content": word}}]
        },
    }

    # Lexical Frequency Band
    band = row.get("Lexical Frequency Band", "").strip()
    if band:
        properties["Lexical Frequency Band"] = {"select": {"name": band}}

    # Source
    source = row.get("Source", "").strip()
    if source:
        properties["Source"] = {"rich_text": [{"text": {"content": source}}]}

    # Position in a sentence (multi_select)
    pos = row.get("Position in a sentence", "").strip()
    if pos:
        properties["Position in a sentence"] = {
            "multi_select": [{"name": v.strip()} for v in pos.split(",") if v.strip()]
        }

    # Category (multi_select)
    cat = row.get("Category", "").strip()
    if cat:
        properties["Category"] = {
            "multi_select": [{"name": v.strip()} for v in cat.split(",") if v.strip()]
        }

    # Level (select)
    level = row.get("Level", "").strip()
    if level:
        properties["Level"] = {"select": {"name": level}}

    # English (rich_text)
    english = row.get("English", "").strip()
    if english:
        properties["English"] = {"rich_text": [{"text": {"content": english[:2000]}}]}

    # Macedonian (Latin) (rich_text)
    latin = row.get("Macedonian (Latin)", "").strip()
    if latin:
        properties["Macedonian (Latin)"] = {"rich_text": [{"text": {"content": latin}}]}

    # Lemma Family (rich_text)
    lemma = row.get("Lemma Family", "").strip()
    if lemma:
        properties["Lemma Family"] = {"rich_text": [{"text": {"content": lemma}}]}

    # Audio Source (rich_text)
    audio_source = row.get("Audio Source", "").strip()
    if audio_source:
        properties["Audio Source"] = {"rich_text": [{"text": {"content": audio_source}}]}

    # Audio File (external URL — playable in Notion)
    audio_url = row.get("Audio URL", "").strip()
    if audio_url:
        properties["Audio File"] = {
            "files": [{
                "type": "external",
                "name": f"{word}.wav",
                "external": {"url": audio_url}
            }]
        }

    payload = {
        "parent": {"database_id": DATABASE_ID},
        "properties": properties,
    }

    url = f"{NOTION_BASE_URL}/pages"
    resp = requests.post(url, headers=headers(token), json=payload)
    if not resp.ok:
        print(f"    Error creating page for '{word}': {resp.status_code} {resp.text[:200]}")
    resp.raise_for_status()
    return resp.json()


def latest_import() -> Path:
    files = sorted(OUTPUT_DIR.glob("mk_frequency_*_notion_import.csv"))
    if not files:
        raise FileNotFoundError("No mk_frequency_*_notion_import.csv found in output/")
    return files[-1]


def main() -> None:
    input_path = Path(sys.argv[1]) if len(sys.argv) > 1 else latest_import()
    print(f"Input:  {input_path}\n")

    token = get_token()

    # Load vocab
    with open(input_path, newline="", encoding="utf-8") as f:
        rows = list(csv.DictReader(f))
    print(f"Total rows in file: {len(rows)}")

    # Fetch existing words from Notion to avoid duplicates
    print("Fetching existing Notion entries...")
    existing_words = fetch_existing_words(token)
    print(f"Existing entries in Notion: {len(existing_words)}")

    # Filter to new words only (rows without Notion ID)
    new_rows = []
    for row in rows:
        # Try multiple field names for the Macedonian word
        word = (row.get("Macedonian (Cyrillic) ") or row.get("Macedonian (Cyrillic)") or
                row.get("Macedonian") or "").strip()
        if not word:
            continue
        if word.lower() in existing_words:
            continue
        # Skip rows that already have a Notion ID (already pushed)
        if (row.get("id") or "").strip():
            continue
        new_rows.append((word, row))

    print(f"New words to add: {len(new_rows)}")
    if not new_rows:
        print("Nothing new to add. Done.")
        return

    print(f"\nAdding {len(new_rows)} new pages to Notion...\n")

    created = 0
    errors = 0
    for i, (word, row) in enumerate(new_rows, 1):
        pos = row.get("Position in a sentence", "")
        try:
            create_page(token, word, row)
            print(f"  [{i:>4}] CREATED  {word:<20} | {pos}")
            created += 1
        except requests.HTTPError:
            errors += 1

        # Rate limit: ~3 req/s
        time.sleep(0.35)

        if i % 100 == 0:
            print(f"         ... {created} created, {errors} errors so far")

    print(f"\nDone. {created} created, {errors} errors.")


if __name__ == "__main__":
    main()
