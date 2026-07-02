"""
File discovery utilities — find latest timestamped output files.
"""

from pathlib import Path

OUTPUT_DIR = Path(__file__).parent.parent / "output"
AUDIO_DIR = Path(__file__).parent.parent / "audio"


def latest_file(pattern: str, directory: Path = OUTPUT_DIR) -> Path | None:
    """Find the most recent file matching a glob pattern.

    >>> latest_file("notion_enriched_*.csv")
    Path('.../output/notion_enriched_20260701_211555.csv')
    """
    files = sorted(directory.glob(pattern), reverse=True)
    return files[0] if files else None


def latest_export() -> Path:
    """Find latest Notion export CSV."""
    result = latest_file("notion_export_*.csv")
    if not result:
        raise FileNotFoundError(f"No notion_export_*.csv in {OUTPUT_DIR}")
    return result


def latest_enriched() -> Path:
    """Find latest enriched CSV."""
    result = latest_file("notion_enriched_*.csv")
    if not result:
        result = latest_file("notion_export_*.csv")
    if not result:
        raise FileNotFoundError(f"No enriched or export CSV in {OUTPUT_DIR}")
    return result
