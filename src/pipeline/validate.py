"""
Validate that audio files actually contain the expected Macedonian word.

Uses Meta's MMS CTC forced alignment model to verify:
    1. The word is detectable in the audio (alignment succeeds)
    2. The confidence score exceeds a threshold
    3. The word occupies a reasonable portion of the audio duration

Outputs a validation report with pass/warn/fail grades.

Usage:
    python validate_audio.py                       # validate all audio/words/*.wav
    python validate_audio.py --word вода           # validate single word
    python validate_audio.py --dir audio/clips     # validate clips directory
    python validate_audio.py --threshold 0.7       # custom pass threshold
"""

import argparse
import csv
import os
import sys
from datetime import datetime
from pathlib import Path

import numpy as np
import soundfile as sf
import torch
import torchaudio

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------

AUDIO_DIR = Path(__file__).parent / "audio"
WORDS_DIR = AUDIO_DIR / "words"
CLIPS_DIR = AUDIO_DIR / "clips"
OUTPUT_DIR = Path(__file__).parent / "output"

DEFAULT_THRESHOLD_PASS = 0.75
DEFAULT_THRESHOLD_WARN = 0.50

from src.core.romanize import romanize  # noqa: E402 — shared transliteration


# ---------------------------------------------------------------------------
# Validator
# ---------------------------------------------------------------------------

class AudioValidator:
    """Validates audio content using MMS forced alignment."""

    def __init__(self, threshold_pass: float = DEFAULT_THRESHOLD_PASS,
                 threshold_warn: float = DEFAULT_THRESHOLD_WARN):
        from torchaudio.pipelines import MMS_FA as bundle
        print("Loading MMS forced alignment model...")
        self.model = bundle.get_model()
        self.tokenizer = bundle.get_tokenizer()
        self.aligner = bundle.get_aligner()
        self.sample_rate = 16000
        self.threshold_pass = threshold_pass
        self.threshold_warn = threshold_warn
        print(f"  Model ready. Pass≥{threshold_pass}, Warn≥{threshold_warn}")

    def validate(self, audio_path: str, expected_word: str) -> dict:
        """
        Validate that an audio file contains the expected word.

        Returns:
            {
                'word': str,
                'file': str,
                'grade': 'PASS' | 'WARN' | 'FAIL',
                'confidence': float,       # 0.0-1.0, -1 if alignment failed
                'word_duration': float,    # detected word duration in seconds
                'audio_duration': float,   # total audio duration
                'word_ratio': float,       # word_duration / audio_duration
                'reason': str,            # explanation of grade
            }
        """
        result = {
            'word': expected_word,
            'file': os.path.basename(audio_path),
            'grade': 'FAIL',
            'confidence': -1.0,
            'word_duration': 0.0,
            'audio_duration': 0.0,
            'word_ratio': 0.0,
            'reason': '',
        }

        # Load audio
        try:
            audio, sr = sf.read(audio_path)
        except Exception as e:
            result['reason'] = f"Cannot read file: {e}"
            return result

        if audio.ndim > 1:
            audio = audio.mean(axis=1)

        audio_duration = len(audio) / sr
        result['audio_duration'] = round(audio_duration, 3)

        # Reject very short or very long files
        if audio_duration < 0.1:
            result['reason'] = "Audio too short (<100ms)"
            return result
        if audio_duration > 30.0:
            result['reason'] = "Audio too long (>30s), likely not a single word"
            return result

        # Resample to 16kHz
        waveform = torch.tensor(audio, dtype=torch.float32).unsqueeze(0)
        if sr != 16000:
            waveform = torchaudio.transforms.Resample(sr, 16000)(waveform)

        # Romanize the expected word
        word_roman = romanize(expected_word)
        if not word_roman:
            result['reason'] = f"Cannot romanize '{expected_word}'"
            return result

        # Run forced alignment
        try:
            with torch.inference_mode():
                emission, _ = self.model(waveform)
                tokens = self.tokenizer([word_roman])
                word_spans = self.aligner(emission[0], tokens)
        except Exception as e:
            result['reason'] = f"Alignment error: {e}"
            return result

        if not word_spans or not word_spans[0]:
            result['reason'] = "Alignment returned no spans (word not detected)"
            return result

        # Calculate confidence and timing
        spans = word_spans[0]
        confidence = sum(s.score for s in spans) / len(spans)
        ratio = waveform.shape[1] / emission.shape[1]
        t_start = spans[0].start * ratio / self.sample_rate
        t_end = spans[-1].end * ratio / self.sample_rate
        word_duration = t_end - t_start

        result['confidence'] = round(confidence, 4)
        result['word_duration'] = round(word_duration, 3)
        result['word_ratio'] = round(word_duration / audio_duration, 3) if audio_duration > 0 else 0

        # Grade the result
        if confidence >= self.threshold_pass:
            result['grade'] = 'PASS'
            result['reason'] = f"High confidence alignment ({confidence:.3f})"
        elif confidence >= self.threshold_warn:
            result['grade'] = 'WARN'
            result['reason'] = f"Moderate confidence ({confidence:.3f}), review recommended"
        else:
            result['grade'] = 'FAIL'
            result['reason'] = f"Low confidence ({confidence:.3f}), likely wrong audio"

        # Additional checks
        if result['grade'] == 'PASS' and result['word_ratio'] < 0.1:
            result['grade'] = 'WARN'
            result['reason'] += "; word is <10% of audio (may contain extra content)"

        return result


# ---------------------------------------------------------------------------
# File discovery
# ---------------------------------------------------------------------------

def find_audio_files(directory: Path) -> list[tuple[str, Path]]:
    """
    Find audio files and extract expected word from filename.
    Filename patterns:
        - вода.wav → "вода"
        - добро_cv.wav → "добро"
        - LL-Q9296 (mkd)-Bjankuloski06-вода.wav → "вода"
    """
    files = []
    for f in sorted(directory.iterdir()):
        if not f.suffix.lower() in ('.wav', '.mp3', '.ogg', '.flac'):
            continue
        name = f.stem
        # Handle Lingua Libre naming: LL-Q9296 (mkd)-Speaker-word
        if name.startswith("LL-Q9296"):
            parts = name.split("-")
            if len(parts) >= 4:
                word = parts[-1]  # last segment is the word
            else:
                continue
        else:
            # Strip suffixes like _cv, _extracted, _test, _fleurs_test
            for suffix in ('_cv', '_extracted', '_test', '_fleurs_test', '_aligned'):
                if name.endswith(suffix):
                    name = name[:-len(suffix)]
                    break
            word = name

        if word:
            files.append((word, f))

    return files


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(description="Validate audio files match expected words")
    parser.add_argument("--word", type=str, help="Validate only this word")
    parser.add_argument("--dir", type=str, default=str(WORDS_DIR),
                        help="Directory containing audio files to validate")
    parser.add_argument("--threshold", type=float, default=DEFAULT_THRESHOLD_PASS,
                        help=f"Pass confidence threshold (default: {DEFAULT_THRESHOLD_PASS})")
    parser.add_argument("--warn-threshold", type=float, default=DEFAULT_THRESHOLD_WARN,
                        help=f"Warn confidence threshold (default: {DEFAULT_THRESHOLD_WARN})")
    parser.add_argument("--output", type=str, help="Output CSV path (auto-generated if omitted)")
    args = parser.parse_args()

    target_dir = Path(args.dir)
    if not target_dir.exists():
        print(f"Error: Directory '{target_dir}' not found")
        sys.exit(1)

    # Find files to validate
    audio_files = find_audio_files(target_dir)
    if args.word:
        audio_files = [(w, p) for w, p in audio_files if w == args.word]
        if not audio_files:
            print(f"No audio file found for word '{args.word}' in {target_dir}")
            sys.exit(1)

    if not audio_files:
        print(f"No audio files found in {target_dir}")
        sys.exit(1)

    print(f"{'=' * 60}")
    print(f"AUDIO VALIDATION REPORT")
    print(f"{'=' * 60}")
    print(f"  Directory: {target_dir}")
    print(f"  Files to validate: {len(audio_files)}")
    print(f"  Pass threshold: ≥{args.threshold}")
    print(f"  Warn threshold: ≥{args.warn_threshold}")
    print()

    # Initialize validator
    validator = AudioValidator(
        threshold_pass=args.threshold,
        threshold_warn=args.warn_threshold
    )

    # Validate each file
    results = []
    pass_count = 0
    warn_count = 0
    fail_count = 0

    for i, (word, filepath) in enumerate(audio_files, 1):
        result = validator.validate(str(filepath), word)
        results.append(result)

        grade_icon = {'PASS': '✓', 'WARN': '⚠', 'FAIL': '✗'}[result['grade']]
        grade_color = {'PASS': '', 'WARN': '', 'FAIL': ''}[result['grade']]

        print(f"  [{i:3d}/{len(audio_files)}] {grade_icon} {word:20s} "
              f"conf={result['confidence']:5.3f}  "
              f"dur={result['word_duration']:.2f}s/{result['audio_duration']:.2f}s  "
              f"[{result['grade']}]")

        if result['grade'] == 'PASS':
            pass_count += 1
        elif result['grade'] == 'WARN':
            warn_count += 1
        else:
            fail_count += 1

    # Summary
    total = len(results)
    print(f"\n{'=' * 60}")
    print(f"VALIDATION SUMMARY")
    print(f"{'=' * 60}")
    print(f"  ✓ PASS: {pass_count:4d} ({100 * pass_count // total}%)")
    print(f"  ⚠ WARN: {warn_count:4d} ({100 * warn_count // total}%)")
    print(f"  ✗ FAIL: {fail_count:4d} ({100 * fail_count // total}%)")
    print(f"  Total:  {total:4d}")

    if fail_count > 0:
        print(f"\n  FAILED FILES (need manual review):")
        for r in results:
            if r['grade'] == 'FAIL':
                print(f"    ✗ {r['word']:20s} — {r['reason']}")

    if warn_count > 0:
        print(f"\n  WARNINGS (spot-check recommended):")
        for r in results:
            if r['grade'] == 'WARN':
                print(f"    ⚠ {r['word']:20s} — {r['reason']}")

    # Save report
    if args.output:
        report_path = args.output
    else:
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        report_path = str(OUTPUT_DIR / f"audio_validation_{ts}.csv")

    os.makedirs(os.path.dirname(report_path), exist_ok=True)
    with open(report_path, 'w', newline='', encoding='utf-8') as f:
        writer = csv.DictWriter(f, fieldnames=[
            'word', 'file', 'grade', 'confidence',
            'word_duration', 'audio_duration', 'word_ratio', 'reason'
        ])
        writer.writeheader()
        writer.writerows(results)

    print(f"\n  Report saved: {report_path}")


if __name__ == "__main__":
    main()
