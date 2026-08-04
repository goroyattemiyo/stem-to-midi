from __future__ import annotations

import pytest

from stem_to_midi.alignment import (
    generate_bar_times,
    maximum_bar_number,
    snap_time_to_grid,
    start_for_bar,
)


def test_generate_bar_times_uses_first_beat_as_bar_one() -> None:
    assert generate_bar_times(2.0, 120.0, 7.0) == pytest.approx((2.0, 4.0, 6.0))


def test_snap_time_to_beat_never_invents_intro_beats() -> None:
    assert snap_time_to_grid(0.2, first_beat_sec=2.0, bpm=120.0) == pytest.approx(2.0)
    assert snap_time_to_grid(3.12, first_beat_sec=2.0, bpm=120.0) == pytest.approx(3.0)


def test_snap_time_to_bar() -> None:
    assert snap_time_to_grid(
        6.2,
        first_beat_sec=2.0,
        bpm=120.0,
        beats_per_step=4,
    ) == pytest.approx(6.0)


def test_start_for_bar_uses_one_based_bar_number() -> None:
    assert start_for_bar(2.32, 72.0, 3) == pytest.approx(8.9866666667)


def test_maximum_bar_number_keeps_clip_inside_source() -> None:
    assert maximum_bar_number(
        first_beat_sec=2.0,
        bpm=120.0,
        duration_sec=20.0,
        clip_duration_sec=5.0,
    ) == 7
