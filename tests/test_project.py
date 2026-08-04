from __future__ import annotations

import json

import pytest

from stem_to_midi.project import evaluate_source_match, parse_tempo_project


def test_parse_v1_project_infers_double_grid() -> None:
    settings = parse_tempo_project(
        json.dumps(
            {
                "source_file": "2 Drums.wav",
                "source_sha256": "a" * 64,
                "duration_sec": 289.734188,
                "sample_rate": 48_000,
                "detected_bpm": 144.230769,
                "corrected_bpm": 72.115385,
                "corrected_first_beat_sec": 2.32,
            }
        )
    )

    assert settings.schema_version == 1
    assert settings.felt_bpm == pytest.approx(72.115385)
    assert settings.grid_multiplier == 2
    assert settings.grid_bpm == pytest.approx(144.23077)
    assert settings.first_beat_sec == pytest.approx(2.32)


def test_parse_v2_project_uses_explicit_settings() -> None:
    settings = parse_tempo_project(
        json.dumps(
            {
                "schema_version": 2,
                "felt_bpm": 72.0,
                "grid_multiplier": 2,
                "first_beat_sec": 1.25,
            }
        )
    )

    assert settings.schema_version == 2
    assert settings.felt_bpm == pytest.approx(72.0)
    assert settings.grid_multiplier == 2
    assert settings.first_beat_sec == pytest.approx(1.25)


def test_parse_v2_accepts_current_legacy_first_beat_field() -> None:
    settings = parse_tempo_project(
        json.dumps(
            {
                "schema_version": 2,
                "felt_bpm": 90.0,
                "grid_bpm": 180.0,
                "corrected_first_beat_sec": 0.5,
            }
        )
    )

    assert settings.grid_multiplier == 2
    assert settings.first_beat_sec == pytest.approx(0.5)


def test_parse_rejects_invalid_json() -> None:
    with pytest.raises(ValueError, match="Invalid JSON"):
        parse_tempo_project(b"{not json}")


def test_parse_rejects_invalid_grid_multiplier() -> None:
    with pytest.raises(ValueError, match="grid_multiplier"):
        parse_tempo_project(
            json.dumps(
                {
                    "schema_version": 2,
                    "felt_bpm": 120.0,
                    "grid_multiplier": 4,
                    "first_beat_sec": 0.0,
                }
            )
        )


def test_evaluate_source_match_prefers_sha256() -> None:
    settings = parse_tempo_project(
        json.dumps(
            {
                "schema_version": 2,
                "felt_bpm": 120.0,
                "grid_multiplier": 1,
                "first_beat_sec": 0.0,
                "source_sha256": "b" * 64,
                "source_file": "different.wav",
                "duration_sec": 10.0,
            }
        )
    )

    result = evaluate_source_match(
        settings,
        source_sha256="b" * 64,
        source_file="actual.wav",
        duration_sec=20.0,
    )

    assert result.status == "match"
    assert result.method == "sha256"


def test_evaluate_source_match_falls_back_to_metadata() -> None:
    settings = parse_tempo_project(
        json.dumps(
            {
                "schema_version": 2,
                "felt_bpm": 120.0,
                "grid_multiplier": 1,
                "first_beat_sec": 0.0,
                "source_file": "Drums.wav",
                "duration_sec": 10.02,
            }
        )
    )

    result = evaluate_source_match(
        settings,
        source_sha256="c" * 64,
        source_file="drums.wav",
        duration_sec=10.0,
    )

    assert result.status == "match"
    assert result.method == "metadata"
