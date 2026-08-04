from __future__ import annotations

from io import BytesIO

import numpy as np
import pytest
import soundfile as sf

from stem_to_midi.tempo import (
    calculate_grid_diagnostics,
    generate_fixed_beat_times,
    load_wav_bytes,
)


def test_generate_fixed_beat_times_at_120_bpm() -> None:
    beats = generate_fixed_beat_times(bpm=120.0, first_beat_sec=0.25, duration_sec=2.0)

    assert beats == pytest.approx((0.25, 0.75, 1.25, 1.75))


def test_generate_fixed_beat_times_rejects_invalid_bpm() -> None:
    with pytest.raises(ValueError, match="BPM"):
        generate_fixed_beat_times(bpm=0.0, first_beat_sec=0.0, duration_sec=1.0)


def test_calculate_grid_diagnostics_uses_nearest_detected_beat() -> None:
    diagnostics = calculate_grid_diagnostics(
        duration_sec=10.0,
        first_beat_sec=2.32,
        detected_beats_sec=(1.909333, 2.336, 2.762667),
    )

    assert diagnostics.nearest_detected_beat_sec == pytest.approx(2.336)
    assert diagnostics.first_beat_offset_sec == pytest.approx(-0.016)
    assert diagnostics.detection_tail_sec == pytest.approx(7.237333)


def test_calculate_grid_diagnostics_without_detected_beats() -> None:
    diagnostics = calculate_grid_diagnostics(
        duration_sec=4.5,
        first_beat_sec=0.25,
        detected_beats_sec=(),
    )

    assert diagnostics.nearest_detected_beat_sec is None
    assert diagnostics.first_beat_offset_sec is None
    assert diagnostics.detection_tail_sec == pytest.approx(4.5)


def test_load_wav_bytes_converts_stereo_to_mono() -> None:
    stereo = np.array([[0.25, -0.25], [0.5, 0.0]], dtype=np.float32)
    buffer = BytesIO()
    sf.write(buffer, stereo, 8_000, format="WAV", subtype="FLOAT")

    audio, sample_rate = load_wav_bytes(buffer.getvalue())

    assert sample_rate == 8_000
    assert audio == pytest.approx(np.array([0.0, 0.25], dtype=np.float32))
