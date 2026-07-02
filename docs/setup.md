# Setup guide

This guide walks you through installing the pipeline, configuring credentials, and verifying your environment.

## Prerequisites

- **Python 3.11 or newer** — the code uses modern type-hint syntax (`str | None`)
- **A Notion account** with an integration token and a vocabulary database
- **~2 GB free disk** if you plan to download speech corpora for audio extraction
- **git** and a terminal

## Install

Clone the repository and install in editable mode:

```bash
git clone https://github.com/viktor1223/Macedonian-Notion-Updates.git
cd Macedonian-Notion-Updates
pip install -e .
```

### Optional dependency groups

The core install is lightweight. Heavier features are opt-in:

```bash
pip install -e ".[audio]"   # torch + torchaudio + datasets (forced alignment)
pip install -e ".[ai]"      # openai (LLM enrichment fallback)
pip install -e ".[dev]"     # pytest (running the test suite)
pip install -e ".[audio,ai,dev]"   # everything
```

| Group | Adds | Needed for |
| --- | --- | --- |
| `audio` | `torch`, `torchaudio`, `datasets` | `clip-all`, audio forced alignment |
| `ai` | `openai` | `enrich --ai` (LLM fallback for Category/Level) |
| `dev` | `pytest`, `pytest-cov` | running tests |

## Configure credentials

Copy the example environment file and fill in your values:

```bash
cp .env.example .env
```

Edit `.env`:

```bash
# Required — your Notion integration token
NOTION_TOKEN=secret_xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx

# Optional — only needed for `enrich --ai`
# Uses GitHub Models by default (free tier); leave blank for dictionary-only mode
GITHUB_TOKEN=ghp_xxxxxxxxxxxxxxxxxxxx

# Optional — use Azure OpenAI instead of GitHub Models
# AZURE_OPENAI_ENDPOINT=https://your-resource.openai.azure.com
# AZURE_OPENAI_DEPLOYMENT=gpt-4o-mini
```

### Getting a Notion token

1. Go to [notion.so/my-integrations](https://www.notion.so/my-integrations)
2. Create a new internal integration
3. Copy the **Internal Integration Secret** into `NOTION_TOKEN`
4. Share your vocabulary database with the integration (in Notion: **Share** to **Add connections** to your integration)

The database ID is currently hardcoded in `src/core/notion_client.py`. If you fork this for your own database, update `DATABASE_ID` there.

## Verify

Run the test suite to confirm everything is wired up:

```bash
pytest tests/
```

You should see 16 tests pass. If `pytest` is not found, install the dev group:

```bash
pip install -e ".[dev]"
```

Confirm the CLI is reachable:

```bash
python cli.py --help
```

## Next steps

- Read the [usage guide](usage.md) to learn every command
- Read the [pipeline overview](pipeline.md) to understand the data flow
