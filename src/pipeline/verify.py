"""
Verify audio clips match expected words using cross-source spectral comparison.

Strategy (no AI, no tokens, fully local):
    1. CROSS-SOURCE AGREEMENT: Compare MFCC fingerprints of the same word
       from Lingua Libre vs Common Voice forced-aligned clip. If spectral
       similarity is high → both confirmed correct. Disagreement → flag.
    2. ALIGNMENT CONFIDENCE: Use the CTC alignment score already computed
       during extraction (from clip_audio.py). Low confidence → suspect.
    3. DURATION HEURISTIC: Expected word duration correlates with character
       count. Outliers are flagged.

Plugs into the enrichment pipeline:
    - After fetch_audio.py downloads Lingua Libre audio
    - After clip_audio.py extracts Common Voice clips
    - Produces a verification CSV consumed by enrich_csv.py / push_to_notion.py

Output:
    - output/audio_verification_{timestamp}.csv
    - Verdicts: CONFIRMED (multi-source agree), PASS (single source, passes
      heuristics), SUSPECT (heuristic flags), FAIL (cross-source mismatch
      or severe anomalies)

Usage:
    python verify_audio.py                    # verify all words with audio
    python verify_audio.py --word добро       # verify one word
    python verify_audio.py --threshold 0.75   # stricter similarity (default 0.70)

Requirements:
    pip install soundfile numpy scipy   (already installed)
"""

import csv
import sys
import argparse
import numpy as np
import soundfile as sf
from datetime import datetime
from pathlib import Path
from scipy.fft import dct

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------

CLIPS_DIR = Path(__file__).parent / "audio" / "clips"   # Common Voice extracts
WORDS_DIR = Path(__file__).parent / "audio" / "words"   # Lingua Libre downloads
OUTPUT_DIR = Path(__file__).parent / "output"
AUDIO_DIR = Path(__file__).parent / "audio"

# Thresholds
CROSS_SOURCE_THRESHOLD = 0.70  # cosine similarity to confirm cross-source match
CONFIDENCE_THRESHOLD = 0.40    # minimum forced alignment confidence
MIN_DURATION_PER_CHAR = 0.04   # seconds — expect at least 40ms per character
MAX_DURATION_PER_CHAR = 0.25   # seconds — flag if much longer than expected
TARGET_SR = 16000


# ---------------------------------------------------------------------------
# MFCC computation (pure numpy + scipy, no librosa or AI)
# ---------------------------------------------------------------------------

def compute_mfcc(audio: np.ndarray, sr: int = TARGET_SR,
                 n_mfcc: int = 13, n_fft: int = 512,
                 hop: int = 160, n_mels: int = 40) -> np.ndarray:
    """
    Compute MFCC features from raw audio. Pure numpy/scipy implementation.
    Returns shape (n_mfcc, n_frames).
    """
    # Pre-emphasis
    audio = np.append(audio[0], audio[1:] - 0.97 * audio[:-1])

    # Frame the signal
    frame_len = n_fft
    n_frames = 1 + (len(audio) - frame_len) // hop
    if n_frames < 1:
        return np.zeros((n_mfcc, 1))

    frames = np.stack([
        audio[i * hop: i * hop + frame_len] for i in range(n_frames)
    ])

    # Window
    window = np.hamming(frame_len)
    frames = frames * window

    # FFT → power spectrum
    mag = np.abs(np.fft.rfft(frames, n=n_fft))
    power = (mag ** 2) / n_fft

    # Mel filterbank
    mel_fb = _mel_filterbank(sr, n_fft, n_mels)
    mel_spec = power @ mel_fb.T
    mel_spec = np.maximum(mel_spec, 1e-10)
    log_mel = np.log(mel_spec)

    # DCT → MFCCs
    mfccs = dct(log_mel, type=2, axis=1, norm='ortho')[:, :n_mfcc]
    return mfccs.T  # (n_mfcc, n_frames)


def _mel_filterbank(sr: int, n_fft: int, n_mels: int) -> np.ndarray:
    """Create mel-scale triangular filterbank."""
    low_mel = 0.0
    high_mel = 2595.0 * np.log10(1.0 + (sr / 2) / 700.0)
    mel_points = np.linspace(low_mel, high_mel, n_mels + 2)
    hz_points = 700.0 * (10.0 ** (mel_points / 2595.0) - 1.0)
    bins = np.floor((n_fft + 1) * hz_points / sr).astype(int)

    fb = np.zeros((n_mels, n_fft // 2 + 1))
    for m in range(n_mels):
        left, center, right = bins[m], bins[m + 1], bins[m + 2]
        for k in range(left, center):
            if center != left:
                fb[m, k] = (k - left) / (center - left)
        for k in range(center, right):
            if right != center:
                fb[m, k] = (right - k) / (right - center)
    return fb


def mfcc_cosine_similarity(mfcc_a: np.ndarray, mfcc_b: np.ndarray) -> float:
    """
    Compare two MFCC matrices via mean-vector cosine similarity.
    Reduces each clip to its average MFCC vector, then computes cosine sim.
    """
    vec_a = mfcc_a.mean(axis=1)
    vec_b = mfcc_b.mean(axis=1)

    dot = np.dot(vec_a, vec_b)
    norm_a = np.linalg.norm(vec_a)
    norm_b = np.linalg.norm(vec_b)
    if norm_a < 1e-10 or norm_b < 1e-10:
        return 0.0
    return float(dot / (norm_a * norm_b))


# ---------------------------------------------------------------------------
# Audio loading and normalization
# ---------------------------------------------------------------------------

def load_audio(path: Path) -> tuple[np.ndarray, int] | None:
    """Load audio file, normalize to mono float32 16kHz."""
    if not path.exists():
        return None
    try:
        audio, sr = sf.read(str(path), dtype='float32')
        if audio.ndim > 1:
            audio = audio.mean(axis=1)
        # Resample to 16kHz if needed (simple linear interpolation for speed)
        if sr != TARGET_SR:
            duration = len(audio) / sr
            new_len = int(duration * TARGET_SR)
            indices = np.linspace(0, len(audio) - 1, new_len)
            audio = np.interp(indices, np.arange(len(audio)), audio)
        return audio, TARGET_SR
    except Exception:
        return None


# ---------------------------------------------------------------------------
# Verification checks
# ---------------------------------------------------------------------------

def check_duration(audio: np.ndarray, sr: int, word: str) -> tuple[str, str]:
    """
    Check if clip duration is reasonable for the word length.
    Returns (verdict, reason).
    """
    duration = len(audio) / sr
    n_chars = len(word)
    if n_chars == 0:
        return "FAIL", "empty word"

    dur_per_char = duration / n_chars

    if duration < 0.05:
        return "FAIL", f"too short ({duration:.3f}s)"
    if duration > 5.0:
        return "FAIL", f"too long ({duration:.3f}s)"
    # Short words (1-3 chars) get extra tolerance — speakers elongate them
    max_threshold = MAX_DURATION_PER_CHAR * (1.5 if n_chars <= 3 else 1.0)
    if dur_per_char < MIN_DURATION_PER_CHAR:
        return "SUSPECT", f"fast ({dur_per_char:.3f}s/char)"
    if dur_per_char > max_threshold:
        return "SUSPECT", f"slow ({dur_per_char:.3f}s/char)"
    return "PASS", f"{duration:.3f}s"


def check_silence(audio: np.ndarray) -> tuple[str, str]:
    """Check if clip is mostly silence."""
    rms = np.sqrt(np.mean(audio ** 2))
    if rms < 0.005:
        return "FAIL", f"silent (rms={rms:.5f})"
    if rms < 0.01:
        return "SUSPECT", f"very quiet (rms={rms:.4f})"
    return "PASS", f"rms={rms:.4f}"


def load_clip_confidence(word: str) -> float | None:
    """
    Try to read the alignment confidence for a word from clip results logs.
    Returns confidence float or None if not found.
    """
    results_files = sorted(AUDIO_DIR.glob("clip_results_*.csv"), reverse=True)
    for rf in results_files:
        try:
            with open(rf, newline='', encoding='utf-8') as f:
                for row in csv.DictReader(f):
                    if row.get('word', '').lower() == word.lower():
                        return float(row.get('confidence', 0))
        except Exception:
            continue
    return None


# ---------------------------------------------------------------------------
# Main verification logic
# ---------------------------------------------------------------------------

def verify_word(word: str, threshold: float = CROSS_SOURCE_THRESHOLD) -> dict:
    """
    Verify a single word's audio across all available sources.

    Checks:
        1. Cross-source similarity (Lingua Libre vs Common Voice clip)
        2. Alignment confidence (from clip_audio.py results)
        3. Duration heuristic
        4. Silence detection
    """
    clip_path = CLIPS_DIR / f"{word}.wav"
    # Also check for suffixed variants (e.g., вода_extracted.wav)
    if not clip_path.exists():
        for suffix in ("_extracted", "_cv", "_aligned"):
            alt = CLIPS_DIR / f"{word}{suffix}.wav"
            if alt.exists():
                clip_path = alt
                break
    ll_path = WORDS_DIR / f"{word}.wav"

    has_clip = clip_path.exists()
    has_ll = ll_path.exists()

    result = {
        "word": word,
        "has_cv_clip": has_clip,
        "has_lingua_libre": has_ll,
        "cross_source_sim": "",
        "alignment_conf": "",
        "duration_check": "",
        "silence_check": "",
        "verdict": "NO_AUDIO",
        "reason": "no audio files found",
    }

    if not has_clip and not has_ll:
        return result

    # Load audio from available sources
    clip_audio = load_audio(clip_path) if has_clip else None
    ll_audio = load_audio(ll_path) if has_ll else None

    issues = []
    passes = []

    # --- Check 1: Cross-source spectral comparison ---
    if clip_audio and ll_audio:
        mfcc_clip = compute_mfcc(clip_audio[0], clip_audio[1])
        mfcc_ll = compute_mfcc(ll_audio[0], ll_audio[1])
        sim = mfcc_cosine_similarity(mfcc_clip, mfcc_ll)
        result["cross_source_sim"] = f"{sim:.3f}"

        if sim >= threshold:
            passes.append(f"cross-source match ({sim:.2f})")
        elif sim >= threshold * 0.8:
            issues.append(f"weak cross-source ({sim:.2f})")
        else:
            issues.append(f"cross-source MISMATCH ({sim:.2f})")

    # --- Check 2: Alignment confidence ---
    conf = load_clip_confidence(word)
    if conf is not None:
        result["alignment_conf"] = f"{conf:.3f}"
        if conf >= CONFIDENCE_THRESHOLD:
            passes.append(f"alignment conf={conf:.2f}")
        else:
            issues.append(f"low alignment conf={conf:.2f}")

    # --- Check 3: Duration ---
    primary_audio = clip_audio or ll_audio
    if primary_audio:
        dur_verdict, dur_reason = check_duration(primary_audio[0], primary_audio[1], word)
        result["duration_check"] = dur_reason
        if dur_verdict == "PASS":
            passes.append("duration OK")
        elif dur_verdict == "SUSPECT":
            issues.append(f"duration: {dur_reason}")
        else:
            issues.append(f"duration FAIL: {dur_reason}")

    # --- Check 4: Silence ---
    if primary_audio:
        sil_verdict, sil_reason = check_silence(primary_audio[0])
        result["silence_check"] = sil_reason
        if sil_verdict != "PASS":
            issues.append(f"silence: {sil_reason}")
        else:
            passes.append("not silent")

    # --- Final verdict ---
    severe = [i for i in issues if "MISMATCH" in i or "FAIL" in i or "silent" in i]

    if severe:
        result["verdict"] = "FAIL"
        result["reason"] = "; ".join(severe)
    elif has_clip and has_ll and any("cross-source match" in p for p in passes):
        result["verdict"] = "CONFIRMED"
        result["reason"] = "multi-source agreement"
    elif issues:
        result["verdict"] = "SUSPECT"
        result["reason"] = "; ".join(issues)
    else:
        result["verdict"] = "PASS"
        result["reason"] = "; ".join(passes) or "single source, heuristics OK"

    return result


def verify_all(word_filter: str | None = None,
               threshold: float = CROSS_SOURCE_THRESHOLD) -> list[dict]:
    """Verify all words that have audio in either source directory."""
    # Collect all words with audio
    words = set()
    if CLIPS_DIR.exists():
        for f in CLIPS_DIR.glob("*.wav"):
            stem = f.stem
            # Strip extraction suffixes to get base word
            for suffix in ("_test", "_aligned", "_extracted", "_cv", "_ll"):
                if stem.endswith(suffix):
                    stem = stem[:-len(suffix)]
            words.add(stem)
    if WORDS_DIR.exists():
        words.update(f.stem for f in WORDS_DIR.glob("*.wav"))

    if word_filter:
        words = {w for w in words if w.lower() == word_filter.lower()}

    if not words:
        print("  No audio files found to verify.")
        return []

    words_sorted = sorted(words)
    print(f"\nVerifying {len(words_sorted)} words (cross-source threshold={threshold})...\n")
    print(f"  {'Word':<15} {'CV':>3} {'LL':>3} {'Similarity':>10} {'Conf':>5} {'Verdict':<10} Reason")
    print(f"  {'-'*15} {'-'*3} {'-'*3} {'-'*10} {'-'*5} {'-'*10} {'-'*25}")

    results = []
    counts = {"CONFIRMED": 0, "PASS": 0, "SUSPECT": 0, "FAIL": 0, "NO_AUDIO": 0}

    for word in words_sorted:
        r = verify_word(word, threshold)
        results.append(r)
        counts[r["verdict"]] += 1

        # Display
        cv = "✓" if r["has_cv_clip"] else "·"
        ll = "✓" if r["has_lingua_libre"] else "·"
        sim = r["cross_source_sim"] or "—"
        conf = r["alignment_conf"] or "—"
        marker = {"CONFIRMED": "✓✓", "PASS": "✓", "SUSPECT": "?", "FAIL": "✗", "NO_AUDIO": "—"}
        reason_short = r["reason"][:35]
        print(f"  {word:<15} {cv:>3} {ll:>3} {sim:>10} {conf:>5} "
              f"{marker[r['verdict']]:>2} {r['verdict']:<10} {reason_short}")

    # Summary
    total = len(results)
    print(f"\n  {'='*70}")
    print(f"  CONFIRMED (multi-source): {counts['CONFIRMED']:>4}")
    print(f"  PASS (single-source OK):  {counts['PASS']:>4}")
    print(f"  SUSPECT (needs review):   {counts['SUSPECT']:>4}")
    print(f"  FAIL (mismatch/bad):      {counts['FAIL']:>4}")
    confirmed_pass = counts['CONFIRMED'] + counts['PASS']
    print(f"  Trust rate: {confirmed_pass}/{total} ({100*confirmed_pass//max(total,1)}%)")

    return results


# ---------------------------------------------------------------------------
# Pipeline integration
# ---------------------------------------------------------------------------

def verify_from_csv(csv_path: str, threshold: float = CROSS_SOURCE_THRESHOLD) -> list[dict]:
    """
    Verify audio for all words in an enriched CSV file.
    Use this to plug into the enrichment pipeline.
    """
    with open(csv_path, newline='', encoding='utf-8') as f:
        reader = csv.DictReader(f)
        rows = list(reader)

    words = set()
    for row in rows:
        for key in ["Macedonian (Cyrillic) ", "Macedonian (Cyrillic)", "Macedonian"]:
            val = (row.get(key) or "").strip()
            if val:
                words.add(val)
                break

    if not words:
        print("  No Macedonian words found in CSV.")
        return []

    print(f"  Verifying audio for {len(words)} words from CSV...")
    results = []
    for word in sorted(words):
        r = verify_word(word, threshold)
        if r["verdict"] != "NO_AUDIO":
            results.append(r)

    return results


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(
        description="Verify audio clips via cross-source spectral comparison (no AI, no tokens)")
    parser.add_argument("--word", type=str, help="Verify only this word")
    parser.add_argument("--threshold", type=float, default=CROSS_SOURCE_THRESHOLD,
                        help=f"Cross-source cosine similarity threshold (default {CROSS_SOURCE_THRESHOLD})")
    parser.add_argument("--csv", type=str, default=None,
                        help="Verify words from a specific enriched CSV")
    args = parser.parse_args()

    print("=" * 70)
    print("AUDIO VERIFICATION (Cross-Source Spectral Comparison)")
    print("  Method: MFCC cosine similarity + alignment confidence + heuristics")
    print("  Cost: $0 (fully local, no AI)")
    print("=" * 70)

    if args.csv:
        results = verify_from_csv(args.csv, args.threshold)
    else:
        results = verify_all(args.word, args.threshold)

    if not results:
        print("\n  No audio to verify.")
        return

    # Save report
    OUTPUT_DIR.mkdir(exist_ok=True)
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    report_path = OUTPUT_DIR / f"audio_verification_{ts}.csv"
    with open(report_path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=results[0].keys())
        writer.writeheader()
        writer.writerows(results)
    print(f"\n  Report saved: {report_path}")

    # Exit with error if failures
    fails = sum(1 for r in results if r["verdict"] == "FAIL")
    suspects = sum(1 for r in results if r["verdict"] == "SUSPECT")
    if fails:
        print(f"\n  ⚠ {fails} FAILED, {suspects} SUSPECT — review these clips!")
        sys.exit(1)


if __name__ == "__main__":
    main()
