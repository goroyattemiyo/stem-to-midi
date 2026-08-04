from __future__ import annotations

from io import BytesIO

import numpy as np
import soundfile as sf

from stem_to_midi.preview import render_click_preview, render_wav_segment


def test_render_wav_segment_has_expected_length() -> None:
    sample_rate = 8_000
    audio = np.zeros(sample_rate * 2, dtype=np.float32)

    payload = render_wav_segment(audio, sample_rate, start_sec=0.5, duration_sec=0.75)
    decoded, decoded_rate = sf.read(BytesIO(payload), dtype="float32")

    assert decoded_rate == sample_rate
    assert len(decoded) == int(sample_rate * 0.75)


def test_render_click_preview_adds_audio() -> None:
    sample_rate = 8_000
    audio = np.zeros(sample_rate, dtype=np.float32)

    payload = render_click_preview(
        audio,
        sample_rate,
        beat_times_sec=(0.1, 0.6),
        start_sec=0.0,
        duration_sec=1.0,
    )
    decoded, _ = sf.read(BytesIO(payload), dtype="float32")

    assert float(np.max(np.abs(decoded))) > 0.0


def test_click_at_segment_start_lands_in_first_samples() -> None:
    sample_rate = 8_000
    audio = np.zeros(sample_rate * 2, dtype=np.float32)

    payload = render_click_preview(
        audio,
        sample_rate,
        beat_times_sec=(0.5, 1.0),
        accent_times_sec=(0.5,),
        start_sec=0.5,
        duration_sec=1.0,
    )
    decoded, _ = sf.read(BytesIO(payload), dtype="float32")

    assert float(np.max(np.abs(decoded[:80]))) > 0.0
    assert float(np.max(np.abs(decoded[1_600:3_200]))) == 0.0
