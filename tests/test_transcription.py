from __future__ import annotations

import numpy as np
import pytest

from stem_to_midi.transcription import (
    TranscriptionConfig,
    extract_note_events,
    transcribe_monophonic,
)


def test_extract_note_events_fills_short_gap_and_splits_on_onset() -> None:
    times = np.arange(10, dtype=float) * 0.05
    midi = np.array([45, 45, np.nan, 45, 45, 45, 45, 45, 45, 45], dtype=float)
    probability = np.array([0.9, 0.9, 0.1, 0.9, 0.9, 0.9, 0.9, 0.9, 0.9, 0.9])
    flags = probability > 0.5
    rms = np.full(10, 0.2)
    config = TranscriptionConfig(
        min_midi=40,
        max_midi=50,
        voicing_threshold=0.6,
        min_note_ms=90,
        max_gap_ms=60,
        onset_split=True,
    )

    notes = extract_note_events(
        frame_times_sec=times,
        frame_midi=midi,
        voiced_probability=probability,
        voiced_flag=flags,
        rms=rms,
        config=config,
        onset_frames=(6,),
    )

    assert [note.pitch for note in notes] == [45, 45]
    assert notes[0].start_sec == pytest.approx(0.0)
    assert notes[0].end_sec == pytest.approx(0.3)
    assert notes[1].start_sec == pytest.approx(0.3)
    assert notes[1].end_sec == pytest.approx(0.5)


def test_extract_note_events_removes_short_fragment() -> None:
    times = np.arange(5, dtype=float) * 0.05
    config = TranscriptionConfig(
        min_midi=40,
        max_midi=50,
        min_note_ms=120,
        max_gap_ms=0,
    )

    notes = extract_note_events(
        frame_times_sec=times,
        frame_midi=np.array([45, 45, np.nan, np.nan, np.nan]),
        voiced_probability=np.array([0.9, 0.9, 0.0, 0.0, 0.0]),
        voiced_flag=np.array([True, True, False, False, False]),
        rms=np.full(5, 0.1),
        config=config,
    )

    assert notes == ()


def test_transcribe_monophonic_tracks_synthetic_bass_phrase() -> None:
    sample_rate = 22_050
    first = _tone(110.0, 0.7, sample_rate)
    silence = np.zeros(int(0.15 * sample_rate), dtype=np.float32)
    second = _tone(146.832, 0.7, sample_rate)
    audio = np.concatenate([silence, first, silence, second, silence])
    config = TranscriptionConfig(
        min_midi=40,
        max_midi=55,
        voicing_threshold=0.55,
        min_note_ms=120,
        max_gap_ms=50,
        onset_split=True,
    )

    result = transcribe_monophonic(audio, sample_rate, config)

    pitches = [note.pitch for note in result.notes]
    assert 45 in pitches
    assert 50 in pitches
    assert result.voiced_fraction > 0.4
    assert result.median_confidence > 0.5


def _tone(frequency: float, duration_sec: float, sample_rate: int) -> np.ndarray:
    times = np.arange(int(duration_sec * sample_rate), dtype=float) / sample_rate
    envelope = np.minimum(np.minimum(times / 0.02, (duration_sec - times) / 0.02), 1.0)
    envelope = np.clip(envelope, 0.0, 1.0)
    signal = 0.5 * np.sin(2 * np.pi * frequency * times) * envelope
    return signal.astype(np.float32)
