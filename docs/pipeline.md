# Pipeline overview

This document explains how a Macedonian word travels from a raw source to a fully enriched, audio-enabled Notion page.

## End-to-end flow

```mermaid
flowchart TD
    Notion[(Notion database)] -->|fetch| CSV1[vocabulary CSV]
    CSV1 -->|enrich| CSV2[enriched CSV<br/>POS, gender, English, Latin]
    CSV2 -->|audio| Clips[word audio clips]
    Clips -->|validate| Verified[verified clips]
    Verified -->|host| Pages[GitHub Pages URLs]
    CSV2 -->|push| Notion
    Pages -->|Audio File URL| Notion
```

## Stage 1 — Enrichment

**Input:** a word list (from Notion or a frequency import)
**Output:** POS, gender, English gloss, Latin transliteration, and optionally Category and Level

The enricher (`src/pipeline/enrich.py`) resolves each word against a local dictionary built from the [kaikki.org](https://kaikki.org/dictionary/Macedonian/) Macedonian Wiktionary extract.

1. **Exact match** — look the word up directly.
2. **De-inflection** — if no match, strip common Macedonian suffixes (definite articles `ата`, `ото`, `ите`; verb endings `ам`, `аш`, `а`) and retry.
3. **Phrase lookup** — for multi-word entries, strip particles and prepositions, then look up the head word.
4. **LLM fallback (optional)** — with `--ai`, words still unresolved go to `gpt-4o-mini`, which returns Category and CEFR Level as JSON.

The dictionary provides POS, gender, English gloss(es), romanization, inflected forms, and verb aspect (perfective/imperfective).

## Stage 2 — Audio resolution

**Input:** enriched words
**Output:** a pronunciation clip per word

Sources are checked in the priority order defined in [audio_sources.yaml](../audio_sources.yaml):

| Priority | Source | Method | License |
| --- | --- | --- | --- |
| 1 | Lingua Libre | Direct API lookup (word-level recordings) | CC-BY-SA 4.0 |
| 2 | Common Voice | Forced alignment from sentences | CC-0 |
| 3 | FLEURS | Forced alignment from sentences | CC-BY 4.0 |
| 4 | VoxPopuli | Forced alignment (disabled by default) | CC-0 |

Lingua Libre is preferred because its recordings are already isolated single words. The other sources are full sentences, so the pipeline must extract the target word.

### Forced alignment

For sentence-based sources, the pipeline uses **Meta MMS** (Massively Multilingual Speech) via `torchaudio.pipelines.MMS_FA`:

1. Romanize the Cyrillic sentence transcript (CTC tokenizer works on Latin).
2. Run CTC forced alignment to get a start and end time for each word.
3. Extract the target word's slice with a small padding margin.
4. Record a confidence score; clips below the `min_confidence` threshold (default 0.4) are rejected.

## Stage 3 — Validation

**Input:** extracted clips
**Output:** clips confirmed to contain the right word

Because forced alignment can drift, extracted clips are re-checked. When a word has audio from two or more sources, the pipeline runs an MFCC cross-source comparison to confirm the clips are consistent. This catches misaligned extractions before they reach Notion.

## Stage 4 — Hosting and sync

**Input:** verified clips + enriched data
**Output:** playable Notion pages

Notion cannot play audio from local file paths, so clips are hosted on GitHub Pages at [viktor1223.github.io/macedonian-audio](https://viktor1223.github.io/macedonian-audio/). Each clip becomes a stable public URL that the `push` step writes into the page's **Audio File** property, making it playable inline.

The `push` step updates existing pages; `create` makes new ones from a frequency import.

## Why this order

Enrichment comes first because audio resolution and validation both benefit from knowing the word's romanization and lemma. Hosting is last because only verified clips should be published. Each stage writes a timestamped artifact to `output/`, so any stage can be re-run independently without repeating earlier work.
