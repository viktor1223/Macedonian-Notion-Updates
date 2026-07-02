"""Tests for core/audio_io.py"""

import sys
import tempfile
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).parent.parent))

from core.audio_io import load_audio, save_clip, get_duration


def test_save_and_load_clip(tmp_path):
    """Round-trip: save a clip then load it back."""
    path = tmp_path / "test_clip.wav"

    # Use values in [-1, 1] range to avoid WAV clipping
    audio = (np.random.randn(16000) * 0.5).astype(np.float32)
    save_clip(path, audio, 16000)

    loaded = load_audio(path)
    assert loaded is not None
    arr, sr = loaded
    assert sr == 16000
    assert len(arr) == 16000
    assert arr.dtype == np.float32
    # Verify correlation (WAV encoding may lose some precision with default subtype)
    correlation = np.corrcoef(arr, audio)[0, 1]
    assert correlation > 0.99, f"Low correlation: {correlation}"

    Path(path).unlink()


def test_load_audio_nonexistent():
    assert load_audio("/nonexistent/path.wav") is None


def test_get_duration():
    with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as f:
        path = f.name

    audio = np.zeros(32000, dtype=np.float32)  # 2 seconds at 16kHz
    save_clip(path, audio, 16000)

    dur = get_duration(path)
    assert abs(dur - 2.0) < 0.01

    Path(path).unlink()


def test_get_duration_nonexistent():
    assert get_duration("/nonexistent.wav") == 0.0


if __name__ == "__main__":
    import pytest
    pytest.main([__file__, "-v"])
