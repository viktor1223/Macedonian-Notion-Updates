"""
Notion API client — shared across fetch, push, and create operations.

Consolidates authentication, pagination, and property building logic.
"""

import os
import time
from pathlib import Path

import requests
from dotenv import load_dotenv

load_dotenv()

DATABASE_ID = "31e2ef16fdf7821295f081b94e558d7e"
NOTION_API_VERSION = "2022-06-28"
NOTION_BASE_URL = "https://api.notion.com/v1"


def get_token() -> str:
    """Get the Notion integration token from environment."""
    token = os.getenv("NOTION_TOKEN")
    if not token:
        raise EnvironmentError(
            "NOTION_TOKEN not set. Add it to .env or export it."
        )
    return token


def headers(token: str | None = None) -> dict:
    """Build standard Notion API headers."""
    if token is None:
        token = get_token()
    return {
        "Authorization": f"Bearer {token}",
        "Notion-Version": NOTION_API_VERSION,
        "Content-Type": "application/json",
    }


def query_database(token: str | None = None, database_id: str = DATABASE_ID,
                   filter_obj: dict | None = None) -> list[dict]:
    """Query a Notion database with automatic pagination.

    Returns all page objects (raw Notion API format).
    """
    if token is None:
        token = get_token()
    url = f"{NOTION_BASE_URL}/databases/{database_id}/query"
    pages = []
    cursor = None

    while True:
        payload = {"page_size": 100}
        if cursor:
            payload["start_cursor"] = cursor
        if filter_obj:
            payload["filter"] = filter_obj

        resp = requests.post(url, headers=headers(token), json=payload)
        resp.raise_for_status()
        data = resp.json()

        pages.extend(data.get("results", []))

        if data.get("has_more"):
            cursor = data.get("next_cursor")
        else:
            break

    return pages


def update_page(page_id: str, properties: dict, token: str | None = None,
                retry: bool = True) -> dict:
    """Update a Notion page's properties.

    Handles rate limiting with automatic retry.
    """
    if token is None:
        token = get_token()
    url = f"{NOTION_BASE_URL}/pages/{page_id}"
    payload = {"properties": properties}

    resp = requests.patch(url, headers=headers(token), json=payload)

    if resp.status_code == 429 and retry:
        wait = float(resp.headers.get("Retry-After", 1))
        time.sleep(wait)
        return update_page(page_id, properties, token, retry=False)

    resp.raise_for_status()
    return resp.json()


def create_page(properties: dict, token: str | None = None,
                database_id: str = DATABASE_ID, retry: bool = True) -> dict:
    """Create a new page in a Notion database.

    Handles rate limiting with automatic retry.
    """
    if token is None:
        token = get_token()
    url = f"{NOTION_BASE_URL}/pages"
    payload = {
        "parent": {"database_id": database_id},
        "properties": properties,
    }

    resp = requests.post(url, headers=headers(token), json=payload)

    if resp.status_code == 429 and retry:
        wait = float(resp.headers.get("Retry-After", 1))
        time.sleep(wait)
        return create_page(properties, token, database_id, retry=False)

    if not resp.ok:
        raise requests.HTTPError(
            f"{resp.status_code}: {resp.text[:200]}", response=resp
        )
    return resp.json()


# ---------------------------------------------------------------------------
# Property builders — convert CSV values to Notion API format
# ---------------------------------------------------------------------------

def multi_select(value: str) -> dict:
    """'Noun, Verb' → {"multi_select": [{"name": "Noun"}, {"name": "Verb"}]}"""
    if not value or value.strip().lower() in ("none", ""):
        return {"multi_select": []}
    return {"multi_select": [{"name": v.strip()} for v in value.split(",") if v.strip()]}


def select(value: str) -> dict | None:
    """'A1' → {"select": {"name": "A1"}}"""
    if not value or not value.strip():
        return None
    return {"select": {"name": value.strip()}}


def rich_text(value: str) -> dict:
    """'hello' → {"rich_text": [{"text": {"content": "hello"}}]}"""
    return {"rich_text": [{"text": {"content": value[:2000]}}]}


def title(value: str) -> dict:
    """'добро' → {"title": [{"text": {"content": "добро"}}]}"""
    return {"title": [{"text": {"content": value}}]}
