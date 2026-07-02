"""
Audio I/O utilities for loading, resampling, and saving audio clips.

Consolidates audio loading logic used across clip_audio.py,
validate_audio.py, and verify_audio.py.
"""

from pathlib import Path

import numpy as np
import soundfile as sf


def load_audio(path: str | Path) -> tuple[np.ndarray, int] | None:
    """Load an audio file and return (mono_array, sample_rate).

    Handles multi-channel audio by averaging to mono.
    Returns None if the file cannot be read.
    """
    try:
        audio, sr = sf.read(str(path))
        if audio.ndim > 1:
            audio = audio.mean(axis=1)
        return audio.astype(np.float32), sr
    except Exception:
        return None


def save_clip(path: str | Path, audio: np.ndarray, sample_rate: int = 16000) -> None:
    """Save an audio clip as a WAV file."""
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    sf.write(str(path), audio, sample_rate)


def get_duration(path: str | Path) -> float:
    """Get audio duration in seconds without loading the full file."""
    try:
        info = sf.info(str(path))
        return info.duration
    except Exception:
        return 0.0


def resample_waveform(waveform, from_sr: int, to_sr: int = 16000):
    """Resample a torch tensor waveform. Returns the resampled tensor.

    Requires torch and torchaudio (imported lazily to avoid import overhead
    when not doing alignment).
    """
    if from_sr == to_sr:
        return waveform
    import torchaudio
    return torchaudio.transforms.Resample(from_sr, to_sr)(waveform)
