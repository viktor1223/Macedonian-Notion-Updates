#!/usr/bin/env python3
"""
Macedonian Vocabulary Pipeline — CLI Entry Point

Usage:
    python cli.py fetch              # Pull data from Notion
    python cli.py enrich [FILE]      # Dictionary enrichment (no AI)
    python cli.py enrich --ai [FILE] # Enrichment with LLM for Category/Level
    python cli.py audio [FILE]       # Fetch audio from Lingua Libre
    python cli.py clip-all           # Extract all words from Common Voice sentences
    python cli.py push [FILE]        # Push updates to Notion
    python cli.py create [FILE]      # Create new pages in Notion
    python cli.py build-dict         # Build dictionary from kaikki.org
    python cli.py build-freq         # Build frequency bands from corpora
    python cli.py download           # Download corpora (Wikipedia/Wiktionary)
    python cli.py full               # Full pipeline: fetch → enrich → audio → push
"""

import sys
from pathlib import Path

# Add project root to path so src/ imports work
sys.path.insert(0, str(Path(__file__).parent))


def cmd_fetch():
    from src.notion.fetch import main
    main()


def cmd_enrich():
    from src.pipeline.enrich import main
    main()


def cmd_audio():
    from src.pipeline.audio_resolve import run_batch
    from src.core.files import latest_enriched
    csv_path = sys.argv[2] if len(sys.argv) > 2 else str(latest_enriched())
    run_batch(csv_path)


def cmd_clip_all():
    from src.pipeline.clip_extract import main
    sys.argv = [sys.argv[0], "--clip-all", "--local-dir", "corpora/common_voice/audio/mk_train_0"]
    main()


def cmd_push():
    from src.notion.push import main
    main()


def cmd_create():
    from src.notion.create import main
    main()


def cmd_build_dict():
    from src.builders.dictionary import main
    main()


def cmd_build_freq():
    from src.builders.frequency import main
    main()


def cmd_download():
    from src.builders.corpora import main
    main()


def cmd_full():
    """Full pipeline: fetch → enrich → audio → push"""
    import subprocess
    steps = [
        ([sys.executable, "cli.py", "fetch"], "Fetching from Notion"),
        ([sys.executable, "cli.py", "enrich"], "Enriching with dictionary"),
        ([sys.executable, "cli.py", "push"], "Pushing to Notion"),
    ]
    for cmd, desc in steps:
        print(f"\n{'='*60}")
        print(f"  {desc}")
        print(f"{'='*60}")
        result = subprocess.run(cmd, cwd=Path(__file__).parent)
        if result.returncode != 0:
            print(f"ERROR: {desc} failed (exit {result.returncode})")
            sys.exit(1)
    print(f"\n{'='*60}")
    print("  Pipeline complete!")
    print(f"{'='*60}")


COMMANDS = {
    "fetch": cmd_fetch,
    "enrich": cmd_enrich,
    "audio": cmd_audio,
    "clip-all": cmd_clip_all,
    "push": cmd_push,
    "create": cmd_create,
    "build-dict": cmd_build_dict,
    "build-freq": cmd_build_freq,
    "download": cmd_download,
    "full": cmd_full,
}


def main():
    if len(sys.argv) < 2 or sys.argv[1] in ("-h", "--help"):
        print(__doc__)
        print("Commands:")
        for name in COMMANDS:
            print(f"  {name}")
        sys.exit(0)

    command = sys.argv[1]
    if command not in COMMANDS:
        print(f"Unknown command: {command}")
        print(f"Available: {', '.join(COMMANDS.keys())}")
        sys.exit(1)

    # Shift argv so subcommands see their own args
    sys.argv = [f"cli.py {command}"] + sys.argv[2:]
    COMMANDS[command]()


if __name__ == "__main__":
    main()
