"""
Extract individual word clips from Common Voice sentences using
Meta's MMS CTC forced alignment model.

Pipeline:
    1. Load the Common Voice word-to-sentence index (audio/common_voice_word_index.csv)
    2. Download sentence audio from Common Voice
    3. Run forced alignment (Cyrillic → romanized → MMS CTC alignment)
    4. Clip target word from the sentence
    5. Save clip + confidence score for human review

Requirements:
    pip install torch torchaudio soundfile datasets numpy

Usage:
    python clip_audio.py                    # process all indexed words
    python clip_audio.py --word добро       # process one word
    python clip_audio.py --dry-run          # show plan without processing
    python clip_audio.py --limit 20         # process first 20 words only
"""

import csv
import io
import os
import sys
import time
import torch
import torchaudio
import soundfile as sf
import numpy as np
from datetime import datetime
from pathlib import Path

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------

AUDIO_DIR = Path(__file__).parent / "audio"
CLIPS_DIR = AUDIO_DIR / "clips"
CV_INDEX = AUDIO_DIR / "common_voice_word_index.csv"
OUTPUT_DIR = Path(__file__).parent / "output"

MIN_CONFIDENCE = 0.4  # minimum alignment confidence to accept a clip
PAD_SECONDS = 0.04  # padding around extracted word (40ms each side)

from core.romanize import romanize  # noqa: E402 — shared transliteration


# ---------------------------------------------------------------------------
# Alignment engine
# ---------------------------------------------------------------------------

class Aligner:
    """MMS CTC forced alignment wrapper."""

    def __init__(self):
        from torchaudio.pipelines import MMS_FA as bundle
        print("Loading MMS forced alignment model...")
        self.model = bundle.get_model()
        self.tokenizer = bundle.get_tokenizer()
        self.aligner = bundle.get_aligner()
        self.sample_rate = 16000
        print("  Model ready.")

    def align(self, waveform: torch.Tensor, words: list[str]) -> list[dict]:
        """
        Align words to audio waveform.

        Args:
            waveform: mono audio tensor, shape (1, samples), 16kHz
            words: list of Cyrillic words in the sentence

        Returns:
            list of {word, start, end, confidence} dicts
        """
        words_roman = [romanize(w) for w in words]
        # Filter empty romanizations (numbers, punctuation)
        valid = [(w, r) for w, r in zip(words, words_roman) if r]
        if not valid:
            return []

        words_clean = [w for w, r in valid]
        roman_clean = [r for w, r in valid]

        with torch.inference_mode():
            emission, _ = self.model(waveform)
            tokens = self.tokenizer(roman_clean)
            word_spans = self.aligner(emission[0], tokens)

        ratio = waveform.shape[1] / emission.shape[1]
        results = []

        for wi, (word, spans) in enumerate(zip(words_clean, word_spans)):
            if not spans:
                continue
            t_start = spans[0].start * ratio / self.sample_rate
            t_end = spans[-1].end * ratio / self.sample_rate
            confidence = sum(s.score for s in spans) / len(spans)
            results.append({
                'word': word,
                'start': t_start,
                'end': t_end,
                'confidence': confidence,
            })

        return results

    def extract_clip(self, waveform: torch.Tensor, start: float, end: float,
                     pad: float = PAD_SECONDS) -> np.ndarray:
        """Extract a clip from waveform given start/end times."""
        sr = self.sample_rate
        s_idx = max(0, int((start - pad) * sr))
        e_idx = min(waveform.shape[1], int((end + pad) * sr))
        return waveform[0, s_idx:e_idx].numpy()


# ---------------------------------------------------------------------------
# Audio loading
# ---------------------------------------------------------------------------

def load_cv_audio(audio_path: str) -> tuple[np.ndarray, int] | None:
    """
    Load Common Voice audio file from the pre-loaded dataset cache.
    Falls back to streaming if cache not available.
    Returns (audio_array, sample_rate) or None on failure.
    """
    # Use the global cache if available (populated by batch_load_cv_audio)
    global _cv_audio_cache
    if _cv_audio_cache and audio_path in _cv_audio_cache:
        return _cv_audio_cache[audio_path]
    return None


# Global cache for batch-loaded Common Voice audio
_cv_audio_cache: dict[str, tuple[np.ndarray, int]] = {}


def batch_load_cv_audio(needed_paths: set[str]) -> int:
    """
    Batch-load all needed audio from Common Voice dataset in a single streaming pass.
    Populates the global _cv_audio_cache.
    Returns number of files loaded.
    """
    global _cv_audio_cache
    from datasets import load_dataset, Audio

    if not needed_paths:
        return 0

    print(f"  Loading {len(needed_paths)} audio files from Common Voice (streaming)...")
    loaded = 0

    try:
        ds = load_dataset(
            "fsicoli/common_voice_17_0", "mk",
            split="train", streaming=True,
            trust_remote_code=True
        )

        for sample in ds:
            path = sample.get('path', '')
            # Match against needed paths
            matched_key = None
            for needed in needed_paths:
                if path.endswith(needed) or needed in path:
                    matched_key = needed
                    break

            if matched_key and matched_key not in _cv_audio_cache:
                audio_array = sample['audio']['array']
                sr = sample['audio']['sampling_rate']
                if hasattr(audio_array, 'numpy'):
                    audio_array = audio_array
                audio_array = np.array(audio_array, dtype=np.float32)
                if audio_array.ndim > 1:
                    audio_array = audio_array.mean(axis=1)
                _cv_audio_cache[matched_key] = (audio_array, sr)
                loaded += 1

                if loaded % 20 == 0:
                    print(f"    Loaded {loaded}/{len(needed_paths)} audio files...", end='\r')

                if loaded >= len(needed_paths):
                    break  # Got everything we need

    except Exception as e:
        print(f"    Error during batch load: {e}")

    print(f"    Loaded {loaded}/{len(needed_paths)} audio files from Common Voice")
    return loaded


def load_audio_file(path: str) -> tuple[np.ndarray, int] | None:
    """Load a local audio file."""
    try:
        audio, sr = sf.read(path)
        if audio.ndim > 1:
            audio = audio.mean(axis=1)
        return audio, sr
    except Exception:
        return None


# ---------------------------------------------------------------------------
# Main pipeline
# ---------------------------------------------------------------------------

def process_word(aligner_instance: Aligner, word: str, sentence: str,
                 audio_array: np.ndarray, sr: int) -> dict | None:
    """
    Process one word: align and extract clip.
    Returns clip info dict or None if extraction failed.
    """
    # Resample to 16kHz
    waveform = torch.tensor(audio_array, dtype=torch.float32).unsqueeze(0)
    if sr != 16000:
        waveform = torchaudio.transforms.Resample(sr, 16000)(waveform)

    # Split sentence into words (strip punctuation for matching)
    sentence_words = [w.strip('.,!?;:()""„"–—') for w in sentence.split()
                      if any(c.isalpha() for c in w)]

    # Run alignment
    results = aligner_instance.align(waveform, sentence_words)

    # Find our target word in the alignment results
    for r in results:
        if r['word'].lower() == word.lower():
            if r['confidence'] >= MIN_CONFIDENCE:
                clip = aligner_instance.extract_clip(waveform, r['start'], r['end'])
                return {
                    'word': word,
                    'start': r['start'],
                    'end': r['end'],
                    'confidence': r['confidence'],
                    'clip': clip,
                    'duration': len(clip) / 16000,
                }
    return None


def process_sentence_all_words(aligner_instance: Aligner, sentence: str,
                                audio_array: np.ndarray, sr: int) -> list[dict]:
    """
    Align a full sentence and extract ALL words.
    Returns list of {word, start, end, confidence, clip, duration} dicts.
    """
    waveform = torch.tensor(audio_array, dtype=torch.float32).unsqueeze(0)
    if sr != 16000:
        waveform = torchaudio.transforms.Resample(sr, 16000)(waveform)

    sentence_words = [w.strip('.,!?;:()""„"–—«»') for w in sentence.split()
                      if any(c.isalpha() for c in w)]

    results = aligner_instance.align(waveform, sentence_words)
    clips = []

    for r in results:
        if r['confidence'] >= MIN_CONFIDENCE:
            clip = aligner_instance.extract_clip(waveform, r['start'], r['end'])
            clips.append({
                'word': r['word'].lower(),
                'start': r['start'],
                'end': r['end'],
                'confidence': r['confidence'],
                'clip': clip,
                'duration': len(clip) / 16000,
            })

    return clips


def run_clip_all(args):
    """
    Process ALL Common Voice sentences and extract every word.
    Builds a complete audio dictionary: word → best clip.
    Keeps the highest-confidence clip per word.
    """
    local_dir = args.local_dir
    if not local_dir:
        local_dir = "corpora/common_voice/audio/mk_train_0"
    local_dir = Path(local_dir)

    if not local_dir.exists():
        print(f"Error: Audio directory not found: {local_dir}")
        print("  Download with: curl -sL 'https://huggingface.co/datasets/fsicoli/common_voice_17_0/resolve/main/audio/mk/train/mk_train_0.tar' | tar x -C corpora/common_voice/audio")
        sys.exit(1)

    # Load sentence metadata from train.tsv
    tsv_path = Path("corpora/common_voice/train.tsv")
    if not tsv_path.exists():
        print(f"Error: {tsv_path} not found.")
        sys.exit(1)

    with open(tsv_path, newline='', encoding='utf-8') as f:
        reader = csv.DictReader(f, delimiter='\t')
        sentences = list(reader)

    if args.limit:
        sentences = sentences[:args.limit]

    print("=" * 60)
    print("CLIP ALL — Building Complete Audio Dictionary")
    print("=" * 60)
    print(f"  Sentences to process: {len(sentences)}")
    print(f"  Audio directory: {local_dir}")
    print(f"  Output: {CLIPS_DIR}/")
    print(f"  Min confidence: {MIN_CONFIDENCE}")

    if args.dry_run:
        # Estimate
        total_words = sum(len(s.get('sentence', '').split()) for s in sentences)
        print(f"\n  Estimated words to extract: ~{total_words}")
        print(f"  [DRY RUN] No processing done.")
        return

    # Initialize aligner
    aligner_instance = Aligner()
    CLIPS_DIR.mkdir(parents=True, exist_ok=True)

    # Track best clip per word (highest confidence wins)
    best_clips: dict[str, dict] = {}  # word → {confidence, clip, sentence, ...}
    total_extracted = 0
    sentences_processed = 0
    sentences_failed = 0

    for i, row in enumerate(sentences, 1):
        sentence = row.get('sentence', '').strip()
        audio_filename = row.get('path', '').strip()
        if not sentence or not audio_filename:
            continue

        audio_path = local_dir / audio_filename
        if not audio_path.exists():
            sentences_failed += 1
            continue

        # Load audio
        try:
            audio_array, sr = sf.read(str(audio_path))
            if audio_array.ndim > 1:
                audio_array = audio_array.mean(axis=1)
        except Exception:
            sentences_failed += 1
            continue

        # Extract all words from this sentence
        clips = process_sentence_all_words(aligner_instance, sentence, audio_array, sr)
        total_extracted += len(clips)
        sentences_processed += 1

        for c in clips:
            word = c['word']
            # Keep best confidence per word
            if word not in best_clips or c['confidence'] > best_clips[word]['confidence']:
                best_clips[word] = {
                    'confidence': c['confidence'],
                    'clip': c['clip'],
                    'duration': c['duration'],
                    'sentence': sentence,
                    'audio_file': audio_filename,
                }

        if i % 50 == 0:
            print(f"  [{i:>4}/{len(sentences)}] {sentences_processed} OK, "
                  f"{len(best_clips)} unique words, {total_extracted} clips total")

    # Save all best clips to disk
    print(f"\n  Saving {len(best_clips)} word clips...")
    saved = 0
    for word, info in best_clips.items():
        # Skip very short words (single letters, unless they're real words like 'а', 'и')
        if len(word) < 2 and word not in ('а', 'и', 'е', 'о'):
            continue
        clip_path = CLIPS_DIR / f"{word}.wav"
        # Only overwrite if new clip has higher confidence
        if clip_path.exists():
            # Check existing confidence from results log if available
            pass  # Always overwrite in clip-all mode (best confidence selected above)
        sf.write(str(clip_path), info['clip'], 16000)
        saved += 1

    # Save results index
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    index_path = AUDIO_DIR / f"clip_dictionary_{ts}.csv"
    with open(index_path, 'w', newline='', encoding='utf-8') as f:
        w = csv.DictWriter(f, fieldnames=['word', 'confidence', 'duration', 'sentence', 'audio_file', 'source', 'license'])
        w.writeheader()
        for word, info in sorted(best_clips.items()):
            if len(word) < 2 and word not in ('а', 'и', 'е', 'о'):
                continue
            w.writerow({
                'word': word,
                'confidence': f"{info['confidence']:.4f}",
                'duration': f"{info['duration']:.3f}",
                'sentence': info['sentence'],
                'audio_file': info['audio_file'],
                'source': 'Common Voice 17.0 MK',
                'license': 'CC-0',
            })

    print(f"\n{'=' * 60}")
    print(f"  COMPLETE")
    print(f"{'=' * 60}")
    print(f"  Sentences processed: {sentences_processed}/{len(sentences)}")
    print(f"  Sentences failed: {sentences_failed}")
    print(f"  Total clips extracted: {total_extracted}")
    print(f"  Unique words saved: {saved}")
    print(f"  Dictionary index: {index_path}")
    print(f"  Clips directory: {CLIPS_DIR}/")


def main():
    import argparse
    parser = argparse.ArgumentParser(description="Extract word clips from Common Voice via forced alignment")
    parser.add_argument("--word", type=str, help="Process only this word")
    parser.add_argument("--clip-all", action="store_true",
                        help="Process ALL sentences and extract ALL words (builds full audio dictionary)")
    parser.add_argument("--dry-run", action="store_true", help="Show plan without processing")
    parser.add_argument("--limit", type=int, default=0, help="Max words/sentences to process")
    parser.add_argument("--local-dir", type=str, help="Local directory with pre-downloaded CV audio files")
    args = parser.parse_args()

    # ─── CLIP-ALL MODE: Process every sentence, extract every word ───
    if args.clip_all:
        run_clip_all(args)
        return

    # Load word index
    if not CV_INDEX.exists():
        print(f"Error: {CV_INDEX} not found. Run fetch_audio.py first.")
        sys.exit(1)

    with open(CV_INDEX, newline='', encoding='utf-8') as f:
        index_rows = list(csv.DictReader(f))

    # Deduplicate: keep best sentence per word (shortest for cleaner alignment)
    word_best = {}  # word → row (pick shortest sentence)
    for row in index_rows:
        w = row['word']
        if w not in word_best or len(row['sentence']) < len(word_best[w]['sentence']):
            word_best[w] = row

    if args.word:
        if args.word.lower() not in word_best:
            print(f"Word '{args.word}' not found in index")
            sys.exit(1)
        word_best = {args.word.lower(): word_best[args.word.lower()]}

    words_to_process = list(word_best.keys())
    if args.limit:
        words_to_process = words_to_process[:args.limit]

    print(f"{'=' * 60}")
    print(f"AUDIO CLIP EXTRACTION (Common Voice + Forced Alignment)")
    print(f"{'=' * 60}")
    print(f"  Words to process: {len(words_to_process)}")
    print(f"  Min confidence: {MIN_CONFIDENCE}")
    print(f"  Output: {CLIPS_DIR}/")
    if args.dry_run:
        print(f"  Mode: DRY RUN")
        print(f"\n  Words queued:")
        for w in words_to_process[:30]:
            sent = word_best[w]['sentence'][:50]
            print(f"    {w:15s} ← \"{sent}...\"")
        if len(words_to_process) > 30:
            print(f"    ... +{len(words_to_process) - 30} more")
        return

    # Initialize aligner
    aligner_instance = Aligner()
    CLIPS_DIR.mkdir(parents=True, exist_ok=True)

    # Batch-load all needed audio from Common Voice in one pass
    needed_audio_paths = set()
    for word in words_to_process:
        clip_path = CLIPS_DIR / f"{word}.wav"
        if not clip_path.exists() and not args.local_dir:
            needed_audio_paths.add(word_best[word]['audio_path'])

    if needed_audio_paths:
        batch_load_cv_audio(needed_audio_paths)

    # Process each word
    results_log = []
    extracted = 0
    failed = 0
    low_confidence = 0

    for i, word in enumerate(words_to_process, 1):
        row = word_best[word]
        sentence = row['sentence']

        # Skip if clip already exists
        clip_path = CLIPS_DIR / f"{word}.wav"
        if clip_path.exists():
            extracted += 1
            continue

        # Load audio
        audio_data = None
        if args.local_dir:
            local_path = os.path.join(args.local_dir, row['audio_path'])
            audio_data = load_audio_file(local_path)

        if audio_data is None:
            audio_data = load_cv_audio(row['audio_path'])

        if audio_data is None:
            print(f"  [{i:>3}] SKIP  {word:15s} — could not load audio")
            failed += 1
            continue

        audio_array, sr = audio_data

        # Process
        result = process_word(aligner_instance, word, sentence, audio_array, sr)

        if result:
            sf.write(str(clip_path), result['clip'], 16000)
            extracted += 1
            results_log.append({
                'word': word,
                'confidence': f"{result['confidence']:.3f}",
                'duration': f"{result['duration']:.3f}",
                'sentence': sentence,
                'source': 'Common Voice 17.0 MK',
                'license': 'CC-0',
                'status': 'extracted',
            })
            print(f"  [{i:>3}] OK    {word:15s} conf={result['confidence']:.3f} dur={result['duration']:.3f}s")
        else:
            failed += 1
            print(f"  [{i:>3}] FAIL  {word:15s} — alignment failed or low confidence")

    # Save results
    print(f"\n{'=' * 60}")
    print(f"  Extracted: {extracted}")
    print(f"  Failed: {failed}")
    print(f"  Low confidence skipped: {low_confidence}")

    if results_log:
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        log_path = AUDIO_DIR / f"clip_results_{ts}.csv"
        with open(log_path, 'w', newline='', encoding='utf-8') as f:
            w = csv.DictWriter(f, fieldnames=['word', 'confidence', 'duration', 'sentence', 'source', 'license', 'status'])
            w.writeheader()
            w.writerows(results_log)
        print(f"  Results log: {log_path}")


if __name__ == "__main__":
    main()
