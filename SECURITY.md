# Security

This project touches paid and rate-limited services (Notion, GitHub Models, optionally Azure OpenAI). This page documents how credentials are handled and how to keep them safe.

## Credential handling

The project never stores secrets in source code or in the repository.

| Credential | How it is provided | Where it lives |
| --- | --- | --- |
| Notion token | `NOTION_TOKEN` environment variable | Local `.env` (git-ignored) |
| GitHub Models token | `GITHUB_TOKEN` env var, or `gh auth token` at runtime | Local shell / gh CLI |
| Azure OpenAI key | Fetched at runtime via the `az` CLI | Never written to disk |

Key points:

- **No hardcoded secrets.** Tokens are read from environment variables only (`os.getenv`). There are no credential literals anywhere in the source.
- **Azure key is never stored.** When Azure OpenAI is configured, the API key is fetched on demand with `az cognitiveservices account keys list` and held only in memory for the duration of the run. It is not saved to `.env` or any file.
- **Secrets are never logged.** No code prints token or key values. Status messages report only the account name and which provider is in use.
- **`.env` is git-ignored** along with `.env.*`, `*.pem`, `*.key`, `*.p12`, `credentials.json`, `secrets.json`, and cloud credential caches (`.azure/`, `.aws/`). Only `.env.example`, which contains placeholders, is committed.

## What is safe to commit

- `.env.example` with placeholder values (`ntn_xxxxxxxxxxxx`) and non-secret resource identifiers (Azure resource group and account name are not secrets on their own)
- Audio index CSVs and dictionaries (public open data)

## Protecting your accounts from unexpected charges

- **Keep `.env` out of git.** It already is. Do not force-add it and do not paste its contents into issues, screenshots, or chat.
- **Rotate a token immediately if it is ever exposed.** Regenerate the Notion integration secret at [notion.so/my-integrations](https://www.notion.so/my-integrations); regenerate GitHub tokens in GitHub settings; rotate Azure keys with `az cognitiveservices account keys regenerate`.
- **Prefer dictionary-only enrichment.** Running `python cli.py enrich` without `--ai` makes zero paid API calls.
- **Cap Azure spend.** If you use Azure OpenAI, set a budget alert on the resource group and use a low-cost deployment (`gpt-4o-mini`).
- **Scope the Azure key.** Use a dedicated resource group for this project so a leaked key cannot touch unrelated resources.
- **Use least privilege for the Notion integration.** Share only the vocabulary database with the integration, not your whole workspace.

## Reporting a vulnerability

If you find a security issue, open a private report via GitHub Security Advisories on this repository, or contact the maintainer directly rather than filing a public issue.

## Review status

A repository secret scan was performed covering the working tree and full git history. No credentials were found in tracked files, and no secret value appears in any commit. Credential handling follows the environment-variable and runtime-fetch pattern described above.
