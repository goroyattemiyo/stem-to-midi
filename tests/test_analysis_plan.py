from __future__ import annotations

import pytest

from stem_to_midi.analysis_plan import (
    build_output_stem,
    calculate_analysis_extent,
    get_transcription_preset,
    suggest_transcription_preset,
)


def test_full_track_extent_covers_source_from_zero() -> None:
    extent = calculate_analysis_extent(
        source_duration_sec=242.5,
        start_sec=0.0,
        requested_duration_sec=None,
    )

    assert extent.start_sec == 0.0
    assert extent.end_sec == 242.5
    assert extent.duration_sec == 242.5
    assert extent.coverage_fraction == 1.0
    assert extent.is_full_track
    assert build_output_stem("Lead Vocals.wav", extent) == "Lead Vocals.full"


def test_validation_clip_has_distinct_range_name() -> None:
    extent = calculate_analysis_extent(
        source_duration_sec=242.5,
        start_sec=29.682,
        requested_duration_sec=30.0,
    )

    assert extent.end_sec == pytest.approx(59.682)
    assert extent.coverage_fraction == pytest.approx(30.0 / 242.5)
    assert not extent.is_full_track
    assert (
        build_output_stem("Lead Vocals.wav", extent)
        == "Lead Vocals.30s-from-29.682"
    )


def test_clip_is_truncated_at_source_end() -> None:
    extent = calculate_analysis_extent(
        source_duration_sec=100.0,
        start_sec=90.0,
        requested_duration_sec=30.0,
    )

    assert extent.end_sec == 100.0
    assert extent.duration_sec == 10.0
    assert extent.coverage_fraction == 0.1


def test_lead_vocal_filename_selects_vocal_preset() -> None:
    preset = suggest_transcription_preset("0 Lead Vocals.wav")

    assert preset.key == "vocal"
    assert preset.onset_split is False
    assert preset.voicing_threshold < get_transcription_preset("bass").voicing_threshold
    assert preset.midi_program != get_transcription_preset("bass").midi_program


def test_unknown_preset_is_rejected() -> None:
    with pytest.raises(ValueError, match="Unknown transcription preset"):
        get_transcription_preset("piano")
