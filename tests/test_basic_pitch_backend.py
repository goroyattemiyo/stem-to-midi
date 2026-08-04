from __future__ import annotations

import pytest

from stem_to_midi.basic_pitch_backend import (
    convert_basic_pitch_events,
    count_large_pitch_jumps,
    maximum_polyphony,
    merge_adjacent_same_pitch,
    note_coverage_fraction,
    select_monophonic_path,
)
from stem_to_midi.transcription import NoteEvent


def _note(
    start: float,
    end: float,
    pitch: int,
    confidence: float = 0.8,
) -> NoteEvent:
    return NoteEvent(
        start_sec=start,
        end_sec=end,
        pitch=pitch,
        velocity=round(127 * confidence),
        confidence=confidence,
        mean_pitch=float(pitch),
    )


def test_convert_basic_pitch_events_preserves_absolute_time() -> None:
    events = [
        (0.25, 0.75, 60, 0.8, None),
        (0.80, 1.20, 64, 0.5, None),
        (1.30, 2.50, 90, 0.9, None),
    ]

    notes = convert_basic_pitch_events(
        events,
        offset_sec=10.0,
        analysis_end_sec=12.0,
        min_midi=48,
        max_midi=84,
    )

    assert len(notes) == 2
    assert notes[0].start_sec == pytest.approx(10.25)
    assert notes[0].end_sec == pytest.approx(10.75)
    assert notes[0].pitch == 60
    assert notes[0].velocity == 102
    assert notes[1].start_sec == pytest.approx(10.80)


def test_monophonic_path_prefers_continuity_over_octave_duplicate() -> None:
    notes = (
        _note(0.0, 1.0, 60, 0.80),
        _note(0.0, 1.0, 72, 0.95),
        _note(1.01, 2.0, 62, 0.80),
    )

    selected = select_monophonic_path(notes)

    assert [note.pitch for note in selected] == [60, 62]
    assert maximum_polyphony(selected) == 1


def test_merge_adjacent_same_pitch_closes_short_gap() -> None:
    notes = (
        _note(1.0, 1.4, 65, 0.7),
        _note(1.45, 2.0, 65, 0.9),
        _note(2.2, 2.5, 67, 0.8),
    )

    merged = merge_adjacent_same_pitch(notes, maximum_gap_sec=0.08)

    assert len(merged) == 2
    assert merged[0].start_sec == 1.0
    assert merged[0].end_sec == 2.0
    assert merged[0].pitch == 65


def test_coverage_and_polyphony_metrics_use_interval_unions() -> None:
    notes = (
        _note(0.0, 1.0, 60),
        _note(0.5, 1.5, 64),
        _note(2.0, 2.5, 67),
    )

    coverage = note_coverage_fraction(notes, start_sec=0.0, end_sec=4.0)

    assert coverage == pytest.approx(0.5)
    assert maximum_polyphony(notes) == 2


def test_large_pitch_jump_counter_ignores_long_silent_sections() -> None:
    notes = (
        _note(0.0, 0.5, 60),
        _note(0.6, 1.0, 73),
        _note(10.0, 10.5, 48),
    )

    assert count_large_pitch_jumps(notes) == 1
