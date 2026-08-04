from __future__ import annotations

from io import BytesIO

import numpy as np
import pytest
import soundfile as sf

from stem_to_midi.tempo import generate_fixed_beat_times, load_wav_bytes


def test_generate_fixed_beat_times_at_120_bpm() -> None:
    beats = generate_fixed_beat_times(bpm=120.0, first_beat_sec=0.25, duration_sec=2.0)

    assert beats == pytest.approx((0.25, 0.75, 1.25, 1.75))


def test_generate_fixed_beat_times_rejects_invalid_bpm() -> None:
    with pytest.raises(ValueError, match="BPM"):
        generate_fixed_beat_times(bpm=0.0, first_beat_sec=0.0, duration_sec=1.0)


def test_load_wav_bytes_converts_stereo_to_mono() -> None:
    stereo = np.array([[0.25, -0.25], [0.5, 0.0]], dtype=np.float32)
    buffer = BytesIO()
    sf.write(buffer, stereo, 8_000, format="WAV", subtype="FLOAT")

    audio, sample_rate = load_wav_bytes(buffer.getvalue())

    assert sample_rate == 8_000
    assert audio == pytest.approx(np.array([0.0, 0.25], dtype=np.float32))
