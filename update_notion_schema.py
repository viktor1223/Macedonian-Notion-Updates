"""
Patch the Notion database schema to match the expanded category/position/level design:

  - Updates 'Position in a sentence' multi-select options
  - Replaces 'Category' multi-select options with the full expanded set
  - Adds a new 'Level' select property (A1 / A2 / B1 / B2 / C1)

Run once before pushing enriched data back to Notion.
"""

import os
import requests
from dotenv import load_dotenv

load_dotenv()

DATABASE_ID = "31e2ef16fdf7821295f081b94e558d7e"
NOTION_API_VERSION = "2022-06-28"
NOTION_BASE_URL = "https://api.notion.com/v1"

# ---------------------------------------------------------------------------
# Schema — keep in sync with enrich_csv.py
# ---------------------------------------------------------------------------

POSITION_OPTIONS = [
    {"name": "Noun",           "color": "blue"},
    {"name": "Pronoun",        "color": "purple"},
    {"name": "Verb",           "color": "red"},
    {"name": "Adjective",      "color": "orange"},
    {"name": "Adverb",         "color": "yellow"},
    {"name": "Expression",     "color": "green"},
    {"name": "Question words", "color": "pink"},
    {"name": "Number",         "color": "gray"},
    {"name": "Particle",       "color": "brown"},
    {"name": "Conjunction",    "color": "default"},
    {"name": "Preposition",    "color": "blue"},
    {"name": "Interjection",   "color": "green"},
]

# Lesson options — thematic groupings (property name: 'Lesson ')
LESSON_OPTIONS = [
    # Core
    {"name": "Greetings & Farewells",     "color": "green"},
    {"name": "Introductions",             "color": "blue"},
    {"name": "Questions",                 "color": "purple"},
    {"name": "Common Phrases",            "color": "yellow"},
    {"name": "Numbers & Quantities",      "color": "gray"},
    # Describing the world
    {"name": "Colors",                    "color": "pink"},
    {"name": "Size, Shape & Amount",      "color": "orange"},
    {"name": "Time & Dates",              "color": "brown"},
    {"name": "Nature & Weather",          "color": "green"},
    # People
    {"name": "Family & Relationships",    "color": "red"},
    {"name": "Body & Health",             "color": "orange"},
    {"name": "Feelings & States",         "color": "purple"},
    # Daily life
    {"name": "Food & Drink",              "color": "yellow"},
    {"name": "Home & Housing",            "color": "brown"},
    {"name": "Clothing & Appearance",     "color": "pink"},
    {"name": "Shopping & Money",          "color": "green"},
    {"name": "Work & School",             "color": "blue"},
    # Getting around
    {"name": "Transport & Travel",        "color": "gray"},
    {"name": "Directions & Places",       "color": "red"},
    {"name": "Countries & Nationalities", "color": "purple"},
    # Language building blocks
    {"name": "Core Verbs",                "color": "red"},
    {"name": "Conjunctions & Connectors", "color": "default"},
    {"name": "Pronouns & Determiners",    "color": "blue"},
]

LEVEL_OPTIONS = [
    {"name": "A1", "color": "green"},
    {"name": "A2", "color": "blue"},
    {"name": "B1", "color": "yellow"},
    {"name": "B2", "color": "orange"},
    {"name": "C1", "color": "red"},
]

LEXICAL_FREQUENCY_BAND_OPTIONS = [
    {"name": "Top 100", "color": "green"},
    {"name": "Top 500", "color": "blue"},
    {"name": "Top 1000", "color": "yellow"},
    {"name": "Top 2000", "color": "orange"},
    {"name": "Top 5000", "color": "brown"},
    {"name": "Outside Core", "color": "gray"},
    {"name": "Unknown", "color": "default"},
]

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def headers(token: str) -> dict:
    return {
        "Authorization": f"Bearer {token}",
        "Notion-Version": NOTION_API_VERSION,
        "Content-Type": "application/json",
    }


def patch_database(token: str, payload: dict) -> dict:
    url = f"{NOTION_BASE_URL}/databases/{DATABASE_ID}"
    resp = requests.patch(url, headers=headers(token), json=payload)
    if not resp.ok:
        print(f"  Error {resp.status_code}: {resp.text}")
    resp.raise_for_status()
    return resp.json()


def retrieve_database(token: str) -> dict:
    url = f"{NOTION_BASE_URL}/databases/{DATABASE_ID}"
    resp = requests.get(url, headers=headers(token))
    resp.raise_for_status()
    return resp.json()


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    token = os.getenv("NOTION_TOKEN")
    if not token:
        raise EnvironmentError("NOTION_TOKEN not set in .env")

    db = retrieve_database(token)
    existing_props = set(db.get("properties", {}).keys())
    print(f"Existing properties: {sorted(existing_props)}")

    payload = {
        "properties": {}
    }

    # Skip Position/Lesson/Category updates — they're already configured in Notion.
    # Only patch them if they haven't been set up yet.
    if "Position in a sentence" not in existing_props:
        payload["properties"]["Position in a sentence"] = {
            "multi_select": {"options": [{"name": o["name"]} for o in POSITION_OPTIONS]}
        }

    if "Lesson " in existing_props:
        payload["properties"]["Lesson "] = {
            "name": "Lesson",
            "multi_select": {"options": [{"name": o["name"]} for o in LESSON_OPTIONS]}
        }

    if "Catagories" in existing_props:
        payload["properties"]["Catagories"] = {
            "name": "Category",
            "multi_select": {"options": [{"name": o["name"]} for o in LESSON_OPTIONS]}
        }

    # Add Level if it doesn't exist yet
    if "Level" not in existing_props:
        payload["properties"]["Level"] = {
            "select": {"options": LEVEL_OPTIONS}
        }
        print("Adding new 'Level' select property …")
    else:
        payload["properties"]["Level"] = {
            "select": {"options": [{"name": o["name"]} for o in LEVEL_OPTIONS]}
        }
        print("Updating existing 'Level' property …")

    # Add or update lexical frequency band
    if "Lexical Frequency Band" not in existing_props:
        payload["properties"]["Lexical Frequency Band"] = {
            "select": {"options": LEXICAL_FREQUENCY_BAND_OPTIONS}
        }
        print("Adding new 'Lexical Frequency Band' select property …")
    else:
        payload["properties"]["Lexical Frequency Band"] = {
            "select": {"options": [{"name": o["name"]} for o in LEXICAL_FREQUENCY_BAND_OPTIONS]}
        }
        print("Updating existing 'Lexical Frequency Band' property …")

    # Add Lemma Family (rich_text) — groups conjugations/inflections under root form
    if "Lemma Family" not in existing_props:
        payload["properties"]["Lemma Family"] = {"rich_text": {}}
        print("Adding new 'Lemma Family' rich_text property …")

    # Add Audio File (url) — link to pronunciation audio
    if "Audio File" not in existing_props:
        payload["properties"]["Audio File"] = {"url": {}}
        print("Adding new 'Audio File' url property …")

    # Add Audio Source (rich_text) — attribution tracking
    if "Audio Source" not in existing_props:
        payload["properties"]["Audio Source"] = {"rich_text": {}}
        print("Adding new 'Audio Source' rich_text property …")

    print("Patching database schema …")
    result = patch_database(token, payload)
    updated_props = sorted(result.get("properties", {}).keys())
    print(f"Done. Properties now: {updated_props}")


if __name__ == "__main__":
    main()
