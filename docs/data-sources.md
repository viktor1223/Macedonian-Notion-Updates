# Data sources and attribution

This project stands on the shoulders of open linguistic and speech datasets. This page credits every source and documents its license so redistribution stays compliant.

## Summary

| Source | Use | License | Redistribution |
| --- | --- | --- | --- |
| Mozilla Common Voice | Word audio (from sentences) | CC-0 | Full — public domain |
| Lingua Libre | Word audio (direct) | CC-BY-SA 4.0 | With attribution + share-alike |
| Google FLEURS | Word audio (from sentences) | CC-BY 4.0 | With attribution |
| kaikki.org (Wiktionary) | Dictionary enrichment | CC-BY-SA 3.0 | With attribution + share-alike |
| OpenSubtitles (OPUS) | Frequency lists | Per-source terms | Check individual terms |

## Audio sources

### Mozilla Common Voice

- **What:** Crowdsourced Macedonian sentence recordings (`fsicoli/common_voice_17_0`, config `mk`)
- **How used:** Individual words are extracted from sentences via forced alignment
- **License:** [CC-0](https://creativecommons.org/publicdomain/zero/1.0/) — public domain, no attribution legally required
- **Credit:** Thank you to the [Mozilla Common Voice](https://commonvoice.mozilla.org/) community and every volunteer who donated their voice

### Lingua Libre

- **What:** Word-level pronunciation recordings hosted on Wikimedia Commons
- **How used:** Direct API lookup — these are already isolated single words (highest priority source)
- **License:** [CC-BY-SA 4.0](https://creativecommons.org/licenses/by-sa/4.0/) — attribution and share-alike required
- **Speakers credited:** Bjankuloski06, Jovan.kostov
- **Project:** [Lingua Libre](https://lingualibre.org/) by Wikimedia France

### Google FLEURS

- **What:** Read-speech recordings (`google/fleurs`, config `mk_mk`)
- **How used:** Word extraction via forced alignment (priority 3)
- **License:** [CC-BY 4.0](https://creativecommons.org/licenses/by/4.0/) — attribution required
- **Credit:** Google Research, FLEURS dataset

## Dictionary and text sources

### kaikki.org (Wiktionary extract)

- **What:** Structured Macedonian Wiktionary data — POS, gender, glosses, inflections, aspect
- **How used:** Primary enrichment source; built into `sources/dictionaries/mk_kaikki_dictionary.json`
- **License:** [CC-BY-SA 3.0](https://creativecommons.org/licenses/by-sa/3.0/), inherited from Wiktionary
- **Credit:** [kaikki.org](https://kaikki.org/dictionary/Macedonian/) by Tatu Ylonen; underlying data from Wiktionary contributors

### OpenSubtitles frequency lists

- **What:** Word-frequency rankings derived from the OpenSubtitles corpus
- **How used:** Assigning frequency bands (Top 100 through Top 5000)
- **License:** Distributed via the [OPUS](https://opus.nlpl.eu/) project; check per-source terms before redistributing raw subtitle text
- **Credit:** OpenSubtitles.org and the OPUS corpus maintainers

## Forced-alignment model

### Meta MMS (Massively Multilingual Speech)

- **What:** CTC-based forced-alignment model used to locate words within sentence audio
- **How used:** Via `torchaudio.pipelines.MMS_FA`
- **Credit:** Meta AI, [MMS project](https://ai.meta.com/blog/multilingual-model-speech-recognition/)

## Hosted audio

Extracted and verified clips are redistributed via GitHub Pages at [viktor1223.github.io/macedonian-audio](https://viktor1223.github.io/macedonian-audio/). Only clips from sources that permit redistribution are hosted, and CC-BY-SA / CC-BY attribution is preserved through the `Audio Source` property on each Notion page and this attribution page.

## Compliance notes

- **CC-0 (Common Voice):** No restrictions on hosting or redistribution.
- **CC-BY-SA (Lingua Libre, Wiktionary):** Attribution is provided here and in-page; any redistribution must remain under a compatible share-alike license.
- **CC-BY (FLEURS):** Attribution provided; no share-alike requirement.
- If you fork or reuse this project, keep this attribution page intact and update it with your own hosting details.
