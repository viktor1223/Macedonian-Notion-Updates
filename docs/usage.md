# Usage guide

Every command runs through the single entry point `cli.py`. Run `python cli.py <command> --help` for command-specific flags.

## Command reference

### fetch

Pull the vocabulary database from Notion into a timestamped CSV under `output/`.

```bash
python cli.py fetch
```

This is usually the first step — it snapshots the current state of your Notion database so later commands work on a local copy.

### enrich

Add part of speech, gender, English gloss, and Latin transliteration from the local dictionary. Operates on the latest fetched CSV if no file is given.

```bash
python cli.py enrich                    # dictionary-only, zero API calls
python cli.py enrich --ai               # LLM fallback for words not in the dictionary
python cli.py enrich output/my_file.csv # enrich a specific file
```

Dictionary lookup is the primary path and covers most common words. The `--ai` flag enables a `gpt-4o-mini` fallback that fills in **Category** and **Level** (CEFR) for words the dictionary misses. Without `--ai`, those fields are left for manual entry — no API cost.

### audio

Resolve pronunciation audio for enriched words, checking sources in priority order (Lingua Libre to Common Voice to FLEURS).

```bash
python cli.py audio                     # uses latest enriched CSV
python cli.py audio output/my_file.csv
```

### clip-all

Extract every indexed word from Common Voice sentence recordings using Meta MMS forced alignment. This is the heavy audio-generation step and requires the `audio` dependency group.

```bash
python cli.py clip-all
```

### push

Write enrichment updates back to existing Notion pages. Updates Category, Level, Lexical Frequency Band, Lemma Family, and Audio File.

```bash
python cli.py push                      # uses latest enriched CSV
python cli.py push output/my_file.csv
```

### create

Create brand-new Notion pages from a frequency-list import CSV (for example `output/mk_frequency_production_notion_import.csv`).

```bash
python cli.py create output/mk_frequency_production_notion_import.csv
```

### build-dict

Build the local dictionary (`sources/dictionaries/mk_kaikki_dictionary.json`) from a raw kaikki.org Wiktionary download.

```bash
python cli.py build-dict
```

### build-freq

Compute frequency bands from downloaded corpora and produce a Notion import CSV.

```bash
python cli.py build-freq
```

### download

Download Macedonian corpora used by the frequency builder.

```bash
python cli.py download
```

### full

Run the common end-to-end path: fetch to enrich to push.

```bash
python cli.py full
```

## Common workflows

### Refresh enrichment for existing words

```bash
python cli.py fetch
python cli.py enrich
python cli.py push
```

### Add audio to words that lack it

```bash
python cli.py fetch
python cli.py audio
python cli.py push
```

### Import a new batch of vocabulary from a frequency list

```bash
python cli.py build-freq
python cli.py create output/mk_frequency_production_notion_import.csv
```

## Output files

All generated files land in `output/` with timestamps so runs never overwrite each other. The pipeline commands automatically pick up the most recent relevant file, so you rarely need to pass a path explicitly.
