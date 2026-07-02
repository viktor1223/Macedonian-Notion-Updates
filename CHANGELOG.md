# Changelog

All notable changes to this project are documented here. The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [1.0.0]

### Added

- Production package structure under `src/` with `core`, `pipeline`, `builders`, and `notion` layers
- Single `cli.py` entry point exposing ten subcommands (`fetch`, `enrich`, `audio`, `clip-all`, `push`, `create`, `build-dict`, `build-freq`, `download`, `full`)
- Dictionary enrichment from the kaikki.org Macedonian Wiktionary extract with de-inflection and phrase lookup
- Optional `gpt-4o-mini` enrichment fallback via GitHub Models or Azure OpenAI (`--ai` flag)
- Word-level audio extraction from Common Voice, FLEURS, and Lingua Libre using Meta MMS forced alignment
- Audio validation and cross-source MFCC verification
- GitHub Pages audio hosting so clips play directly in Notion
- Unit tests for romanization, audio I/O, and dictionary lookup
- Documentation suite: setup, usage, pipeline, architecture, and data-source attribution
- GitHub Actions CI running the test suite on Python 3.11 and 3.12

[1.0.0]: https://github.com/viktor1223/Macedonian-Notion-Updates/releases/tag/v1.0.0
