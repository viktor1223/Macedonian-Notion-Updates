"""
Download open-licensed Macedonian text from Wikipedia and Wiktionary APIs.

Sources:
  - Macedonian Wikipedia (mk.wikipedia.org) — CC BY-SA 4.0
  - Macedonian Wiktionary (mk.wiktionary.org) — CC BY-SA 3.0

Usage:
    python download_corpora.py                    # default: 500 wiki articles
    python download_corpora.py --wiki-pages 1000  # more articles
    python download_corpora.py --skip-wiki        # wiktionary only
    python download_corpora.py --skip-wiktionary  # wikipedia only
"""

from __future__ import annotations

import json
import re
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

CORPORA_DIR = Path(__file__).parent / "corpora"
WIKI_DIR = CORPORA_DIR / "wikipedia"
WIKT_DIR = CORPORA_DIR / "wiktionary"
DICT_DIR = Path(__file__).parent / "sources" / "dictionaries"

MK_WIKI_API = "https://mk.wikipedia.org/w/api.php"
MK_WIKT_API = "https://mk.wiktionary.org/w/api.php"

USER_AGENT = "Macedonian-Core-Vocab-Builder/1.0 (language-learning project)"

MAX_RETRIES = 7
BASE_BACKOFF = 3.0

# Macedonian language detection at download time
_CYRILLIC_RE = re.compile(r"[\u0400-\u04FF]")
_LETTER_RE = re.compile(r"[a-zA-Z\u0400-\u04FF]")
_MK_FUNCTION_WORDS = {
    "и", "во", "на", "се", "да", "не", "што", "со", "за", "од",
    "како", "тоа", "е", "јас", "ти", "тој", "таа", "ние", "вие",
    "ова", "сум", "си", "сме", "сте",
}
_MK_DISTINCT_CHARS = set("ѓќѕџљњј")
_CYRILLIC_TOKEN_RE = re.compile(r"[\u0400-\u04FF]+")


def is_macedonian_text(text: str, min_cyr_ratio: float = 0.5) -> bool:
    """Check if text is predominantly Macedonian at download time.

    Uses three signals:
      1. Cyrillic character ratio (must be >= min_cyr_ratio of all letters)
      2. Macedonian function word presence
      3. Distinctly Macedonian characters (ѓ, ќ, ѕ, џ, љ, њ, ј)
    """
    if not text or len(text) < 50:
        return False

    letters = _LETTER_RE.findall(text)
    if len(letters) < 20:
        return False

    cyrillic = _CYRILLIC_RE.findall(text)
    cyr_ratio = len(cyrillic) / len(letters)
    if cyr_ratio < min_cyr_ratio:
        return False

    tokens = [t.lower() for t in _CYRILLIC_TOKEN_RE.findall(text)]
    if not tokens:
        return False

    # Check for Macedonian function words
    sample = tokens[:500]
    func_hits = sum(1 for t in sample if t in _MK_FUNCTION_WORDS)
    func_ratio = func_hits / len(sample)

    # Check for distinctly Macedonian characters
    distinct_hits = sum(1 for c in set(text.lower()) if c in _MK_DISTINCT_CHARS)

    # Accept if: decent function word presence OR distinct MK characters found
    return func_ratio >= 0.02 or distinct_hits >= 1


def api_get(base_url: str, params: dict) -> dict:
    params["format"] = "json"
    url = f"{base_url}?{urllib.parse.urlencode(params)}"
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    for attempt in range(MAX_RETRIES):
        try:
            with urllib.request.urlopen(req, timeout=30) as resp:
                return json.loads(resp.read().decode("utf-8"))
        except urllib.error.HTTPError as e:
            if e.code == 429 and attempt < MAX_RETRIES - 1:
                wait = BASE_BACKOFF * (2 ** attempt)
                print(f"    Rate limited, waiting {wait:.0f}s (attempt {attempt + 1}/{MAX_RETRIES})...")
                time.sleep(wait)
            else:
                raise


def fetch_all_page_titles(base_url: str, namespace: int = 0, limit: int = 500) -> list[str]:
    titles: list[str] = []
    apcontinue = None
    while len(titles) < limit:
        batch_size = min(500, limit - len(titles))
        params = {
            "action": "query",
            "list": "allpages",
            "apnamespace": namespace,
            "aplimit": batch_size,
        }
        if apcontinue:
            params["apcontinue"] = apcontinue

        data = api_get(base_url, params)
        pages = data.get("query", {}).get("allpages", [])
        titles.extend(p["title"] for p in pages)

        cont = data.get("continue", {})
        apcontinue = cont.get("apcontinue")
        if not apcontinue:
            break

        time.sleep(0.5)

    return titles[:limit]


def fetch_random_page_titles(base_url: str, limit: int = 500) -> list[str]:
    """Fetch random article titles — avoids the alphabetical stub problem."""
    titles: list[str] = []
    seen: set[str] = set()
    batch_size = 20  # API max for random

    while len(titles) < limit:
        params = {
            "action": "query",
            "list": "random",
            "rnnamespace": 0,
            "rnlimit": min(batch_size, limit - len(titles)),
        }
        data = api_get(base_url, params)
        for page in data.get("query", {}).get("random", []):
            title = page.get("title", "")
            if title and title not in seen:
                seen.add(title)
                titles.append(title)
        time.sleep(1.0)

    return titles[:limit]


def fetch_extracts(base_url: str, titles: list[str]) -> list[dict]:
    results: list[dict] = []
    rejected_non_mk = 0
    # MediaWiki API allows up to 20 titles per request for extracts
    batch_size = 20
    for i in range(0, len(titles), batch_size):
        batch = titles[i : i + batch_size]
        params = {
            "action": "query",
            "titles": "|".join(batch),
            "prop": "extracts",
            "explaintext": "1",
            "exlimit": str(len(batch)),
        }
        data = api_get(base_url, params)
        pages = data.get("query", {}).get("pages", {})
        for page_id, page in pages.items():
            if page_id == "-1":
                continue
            extract = page.get("extract", "").strip()
            if extract and len(extract) > 50:
                if not is_macedonian_text(extract):
                    rejected_non_mk += 1
                    continue
                results.append(
                    {
                        "title": page.get("title", ""),
                        "text": extract,
                    }
                )
        time.sleep(2.5)
        if (i // batch_size) % 5 == 0:
            print(f"  Fetched {min(i + batch_size, len(titles))}/{len(titles)} pages...")

    if rejected_non_mk:
        print(f"  Rejected {rejected_non_mk} pages (failed Macedonian language check)")
    return results


def save_corpus_text(articles: list[dict], output_path: Path) -> None:
    with open(output_path, "w", encoding="utf-8") as f:
        for article in articles:
            f.write(article["text"])
            f.write("\n\n")
    print(f"  Saved {len(articles)} articles → {output_path}")


def save_corpus_jsonl(articles: list[dict], output_path: Path) -> None:
    with open(output_path, "w", encoding="utf-8") as f:
        for article in articles:
            json.dump({"text": article["text"], "title": article["title"]}, f, ensure_ascii=False)
            f.write("\n")
    print(f"  Saved {len(articles)} articles → {output_path}")


def fetch_wiktionary_words(limit: int = 2000) -> list[str]:
    print(f"Fetching up to {limit} Wiktionary entry titles...")
    titles = fetch_all_page_titles(MK_WIKT_API, namespace=0, limit=limit)
    print(f"  Got {len(titles)} Wiktionary entry titles")
    return titles


def save_dictionary(words: list[str], output_path: Path) -> None:
    # Deduplicate and sort
    unique = sorted(set(w.strip().lower() for w in words if w.strip()))
    with open(output_path, "w", encoding="utf-8") as f:
        f.write("# Macedonian Wiktionary entries (auto-downloaded)\n")
        f.write(f"# Count: {len(unique)}\n")
        for word in unique:
            f.write(word + "\n")
    print(f"  Saved {len(unique)} dictionary words → {output_path}")


def main() -> None:
    import argparse

    parser = argparse.ArgumentParser(description="Download Macedonian corpora")
    parser.add_argument("--wiki-pages", type=int, default=500, help="Number of Wikipedia pages to fetch")
    parser.add_argument("--wikt-words", type=int, default=2000, help="Number of Wiktionary entries to fetch")
    parser.add_argument("--skip-wiki", action="store_true", help="Skip Wikipedia download")
    parser.add_argument("--skip-wiktionary", action="store_true", help="Skip Wiktionary download")
    args = parser.parse_args()

    WIKI_DIR.mkdir(parents=True, exist_ok=True)
    WIKT_DIR.mkdir(parents=True, exist_ok=True)
    DICT_DIR.mkdir(parents=True, exist_ok=True)

    if not args.skip_wiki:
        print(f"\n--- Macedonian Wikipedia ({args.wiki_pages} pages) ---")
        print("Fetching random page titles (avoids alphabetical stubs)...")
        titles = fetch_random_page_titles(MK_WIKI_API, limit=args.wiki_pages)
        print(f"  Got {len(titles)} titles")

        print("Fetching article extracts...")
        articles = fetch_extracts(MK_WIKI_API, titles)
        print(f"  Got {len(articles)} articles with content")

        save_corpus_text(articles, WIKI_DIR / "mk_wikipedia_articles.txt")
        save_corpus_jsonl(articles, WIKI_DIR / "mk_wikipedia_articles.jsonl")

    if not args.skip_wiktionary:
        print(f"\n--- Macedonian Wiktionary ({args.wikt_words} entries) ---")
        wikt_words = fetch_wiktionary_words(limit=args.wikt_words)

        # Save as corpus text (the entry titles themselves are Macedonian words)
        with open(WIKT_DIR / "mk_wiktionary_titles.txt", "w", encoding="utf-8") as f:
            for word in wikt_words:
                f.write(word + "\n")
        print(f"  Saved {len(wikt_words)} titles → {WIKT_DIR / 'mk_wiktionary_titles.txt'}")

        # Also save as dictionary for validation
        save_dictionary(wikt_words, DICT_DIR / "mk_wiktionary_lexicon.txt")

    print("\nDone. Corpora ready for frequency pipeline.")


if __name__ == "__main__":
    main()
