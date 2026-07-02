# Contributing

Thanks for your interest in improving the Macedonian Vocabulary Pipeline. This guide covers the development workflow.

## Development setup

Install with the dev and audio dependency groups:

```bash
git clone https://github.com/viktor1223/Macedonian-Notion-Updates.git
cd Macedonian-Notion-Updates
pip install -e ".[audio,ai,dev]"
```

See [docs/setup.md](docs/setup.md) for credential configuration.

## Running tests

```bash
pytest tests/
```

Tests are network-free and do not require a Notion token or the heavy audio/AI models, so they run fast. Please add or update tests when you change behavior in `core` or `pipeline`.

## Code organization

Before adding code, read [docs/architecture.md](docs/architecture.md). The key rule: `src/core/` must not import from `src/pipeline/`, `src/builders/`, or `src/notion/`. Dependencies flow one direction only.

Common extension points:

- **New audio source:** add to `audio_sources.yaml` plus a resolver branch in `src/pipeline/audio_resolve.py`
- **New Notion property:** add a builder in `src/core/notion_client.py`, reference it in `src/notion/push.py`
- **New CLI command:** register it in `cli.py` and implement the logic in the appropriate `src/` package

## Style

- Target Python 3.11+; modern type hints (`str | None`) are fine
- Keep functions focused; put shared primitives in `src/core/`
- Prefer explicit, timestamped output files over hidden state
- Match the existing import pattern: `from src.core.X import Y`

## Commit messages

Write clear, imperative commit subjects (for example, `Add FLEURS audio resolver`). Group related changes into a single logical commit.

## Pull requests

1. Branch from `main` with a descriptive name (`feat/...`, `fix/...`, `docs/...`)
2. Make sure `pytest tests/` passes
3. Update the relevant docs if you change behavior
4. Open a PR describing what changed and why

## Reporting issues

When filing an issue, include the command you ran, the full error output, your Python version, and which dependency groups you installed.
