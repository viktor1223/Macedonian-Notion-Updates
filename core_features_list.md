1. Vocabulary Database
- Store Macedonian word/phrase (Cyrillic + Latin transliteration)
- English meaning
- Lemma/root form
- Part of speech / Position in a sentence (multi-select: Noun, Pronoun, Verb, Adjective, Adverb, Expression, Question words, Number, Particle, Conjunction, Preposition, Interjection)
- Category — thematic grouping (multi-select, 20 options across 5 groups — see schema below)
- Level — CEFR difficulty (select: A1 / A2 / B1 / B2 / C1)
- Lesson — links to practice-problem pages (managed separately, not overwritten by pipeline)
- Source
- Irregular verbs flag
- Flashcard flag
- [BUILT] Notion database: "Words & Phrases" (61 entries, live)

Category schema (20 options):
  Core:               Greetings & Farewells, Introductions, Questions, Common Phrases, Numbers & Quantities
  Describing world:   Colors, Size Shape & Amount, Time & Dates, Nature & Weather
  People:             Family & Relationships, Body & Health, Feelings & States
  Daily life:         Food & Drink, Home & Housing, Clothing & Appearance, Shopping & Money, Work & School
  Getting around:     Transport & Travel, Directions & Places, Countries & Nationalities
  Building blocks:    Core Verbs, Conjunctions & Connectors, Pronouns & Determiners

2. Frequency-Aware Ranking
- Build our own Macedonian frequency list from corpora
- Rank words by usefulness
- Track coverage of top 100 / 500 / 1000 / 2000 words

3. Duplicate Detection
- Detect exact duplicates
- Detect Cyrillic vs Latin transliteration duplicates
- Detect inflected-form duplicates
- Suggest merge/remove/convert-to-example

4. Grammar Enrichment
- Add noun/verb/adjective/etc.
- For nouns: gender, plural
- For verbs: aspect, tense patterns, conjugation notes
- Confidence score + human review flag

5. AI Enrichment Pipeline
- [BUILT] notion_fetch.py    — pulls all pages from Notion with full pagination
- [BUILT] enrich_csv.py      — classifies Position, Category, and Level via GPT-4o-mini (GitHub Models API, no extra API key needed)
- [BUILT] push_to_notion.py  — writes enriched fields back to Notion, respects rate limits, leaves Lesson untouched
- [BUILT] update_notion_schema.py — patches Notion database schema (options, new properties)
- Pipeline runs: fetch → enrich → push (each step is a standalone script, composable into run.py)
- Auth: Notion integration token in .env; GitHub token auto-fetched via gh CLI

6. Human Audio System
- Attach real human pronunciation clips
- Sources: tutor recordings, Wikimedia/Wiktionary, Common Voice, Forvo manual reference
- Track license, source, speaker, audio quality, approval status

7. Anki Sync
- Generate flashcards from approved entries
- Store Anki ID to prevent duplicates
- Update existing cards instead of recreating them
- Support word cards, phrase cards, listening cards, reverse cards

8. Import Pipeline
- Import from tutor notes, songs, books, podcasts, CSV, Notion, text files
- Extract new words/phrases
- Normalize and queue for review
- [BUILT] Notion pull via REST API (notion_fetch.py) — exports to timestamped JSON + CSV in output/