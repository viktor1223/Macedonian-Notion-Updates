"""
Fetch all entries from a Notion database and export to JSON / CSV.

Requirements:
    pip install requests python-dotenv

Setup:
    1. Go to https://www.notion.so/my-integrations and create a new integration.
    2. Copy the Internal Integration Secret (starts with "ntn_..." or "secret_...").
    3. Open the target Notion database, click "..." → "Connections" → add your integration.
    4. Create a .env file in this directory:
           NOTION_TOKEN=ntn_xxxxxxxxxxxx
"""

import json
import csv
import os
import requests
from pathlib import Path
from datetime import datetime

from dotenv import load_dotenv

load_dotenv()

from src.core.notion_client import get_token, query_database, DATABASE_ID  # shared Notion client

OUTPUT_DIR = Path(__file__).parent.parent.parent / "output"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def get_plain_text(rich_text_list: list) -> str:
    """Collapse a Notion rich_text array into a plain string."""
    return "".join(rt.get("plain_text", "") for rt in rich_text_list)


def extract_property_value(prop: dict):
    """
    Convert a single Notion property object to a Python-native value.
    Handles the most common property types.
    """
    ptype = prop.get("type")

    if ptype == "title":
        return get_plain_text(prop.get("title", []))
    if ptype == "rich_text":
        return get_plain_text(prop.get("rich_text", []))
    if ptype == "number":
        return prop.get("number")
    if ptype == "select":
        sel = prop.get("select")
        return sel["name"] if sel else None
    if ptype == "multi_select":
        return [s["name"] for s in prop.get("multi_select", [])]
    if ptype == "date":
        date_obj = prop.get("date")
        if not date_obj:
            return None
        start = date_obj.get("start")
        end = date_obj.get("end")
        return f"{start} → {end}" if end else start
    if ptype == "checkbox":
        return prop.get("checkbox")
    if ptype == "url":
        return prop.get("url")
    if ptype == "email":
        return prop.get("email")
    if ptype == "phone_number":
        return prop.get("phone_number")
    if ptype == "status":
        status = prop.get("status")
        return status["name"] if status else None
    if ptype == "people":
        return [p.get("name") or p.get("id") for p in prop.get("people", [])]
    if ptype == "files":
        files = []
        for f in prop.get("files", []):
            if f.get("type") == "external":
                files.append(f["external"]["url"])
            elif f.get("type") == "file":
                files.append(f["file"]["url"])
        return files
    if ptype == "relation":
        return [r["id"] for r in prop.get("relation", [])]
    if ptype == "formula":
        formula = prop.get("formula", {})
        ftype = formula.get("type")
        return formula.get(ftype)
    if ptype == "rollup":
        rollup = prop.get("rollup", {})
        rtype = rollup.get("type")
        if rtype == "array":
            return [extract_property_value(item) for item in rollup.get("array", [])]
        return rollup.get(rtype)
    if ptype == "created_time":
        return prop.get("created_time")
    if ptype == "last_edited_time":
        return prop.get("last_edited_time")
    if ptype == "created_by":
        user = prop.get("created_by", {})
        return user.get("name") or user.get("id")
    if ptype == "last_edited_by":
        user = prop.get("last_edited_by", {})
        return user.get("name") or user.get("id")

    # Fallback: return raw value
    return prop.get(ptype)


def page_to_dict(page: dict) -> dict:
    """Flatten a Notion page object into a plain dict."""
    row = {
        "id": page["id"],
        "created_time": page.get("created_time"),
        "last_edited_time": page.get("last_edited_time"),
        "url": page.get("url"),
    }
    for name, prop in page.get("properties", {}).items():
        row[name] = extract_property_value(prop)
    return row


# ---------------------------------------------------------------------------
# Fetch
# ---------------------------------------------------------------------------

def fetch_all_pages(token: str, database_id: str) -> list[dict]:
    """
    Query the database via the Notion REST API, handling pagination automatically.
    Returns a list of raw page objects.
    """
    return query_database(token=token, database_id=database_id)


# ---------------------------------------------------------------------------
# Export helpers
# ---------------------------------------------------------------------------

def save_json(rows: list[dict], path: Path) -> None:
    with open(path, "w", encoding="utf-8") as f:
        json.dump(rows, f, ensure_ascii=False, indent=2, default=str)
    print(f"  JSON saved → {path}")


def save_csv(rows: list[dict], path: Path) -> None:
    if not rows:
        print("  No rows to write.")
        return
    # Collect all keys preserving insertion order
    keys = list(dict.fromkeys(k for row in rows for k in row))
    with open(path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=keys, extrasaction="ignore")
        writer.writeheader()
        for row in rows:
            # Stringify list values so CSV stays readable
            flat = {k: (", ".join(str(i) for i in v) if isinstance(v, list) else v)
                    for k, v in row.items()}
            writer.writerow(flat)
    print(f"  CSV  saved → {path}")


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    token = os.getenv("NOTION_TOKEN")
    if not token:
        raise EnvironmentError(
            "NOTION_TOKEN not set. Add it to a .env file:\n"
            "  NOTION_TOKEN=ntn_xxxxxxxxxxxx"
        )

    print(f"Fetching database {DATABASE_ID} …")
    raw_pages = fetch_all_pages(token, DATABASE_ID)
    print(f"  Retrieved {len(raw_pages)} pages.")

    rows = [page_to_dict(p) for p in raw_pages]

    OUTPUT_DIR.mkdir(exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    save_json(rows, OUTPUT_DIR / f"notion_export_{stamp}.json")
    save_csv(rows, OUTPUT_DIR / f"notion_export_{stamp}.csv")

    print("Done.")


if __name__ == "__main__":
    main()
