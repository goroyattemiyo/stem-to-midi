from __future__ import annotations

import math


def beat_interval_sec(bpm: float) -> float:
    """Return the duration of one beat for a positive BPM value."""

    if not math.isfinite(bpm) or bpm <= 0.0:
        raise ValueError("BPM must be positive and finite")
    return 60.0 / bpm


def bar_interval_sec(bpm: float, beats_per_bar: int = 4) -> float:
    """Return the duration of one bar."""

    if beats_per_bar <= 0:
        raise ValueError("beats_per_bar must be positive")
    return beat_interval_sec(bpm) * beats_per_bar


def start_for_bar(
    first_beat_sec: float,
    bpm: float,
    bar_number: int,
    beats_per_bar: int = 4,
) -> float:
    """Return the absolute start time for a one-based bar number."""

    if not math.isfinite(first_beat_sec) or first_beat_sec < 0.0:
        raise ValueError("first_beat_sec must be non-negative and finite")
    if bar_number < 1:
        raise ValueError("bar_number must be at least 1")
    return first_beat_sec + (bar_number - 1) * bar_interval_sec(bpm, beats_per_bar)


def generate_bar_times(
    first_beat_sec: float,
    bpm: float,
    duration_sec: float,
    beats_per_bar: int = 4,
) -> tuple[float, ...]:
    """Generate bar-start times from the configured first beat."""

    if not math.isfinite(duration_sec) or duration_sec < 0.0:
        raise ValueError("duration_sec must be non-negative and finite")
    interval = bar_interval_sec(bpm, beats_per_bar)
    if first_beat_sec < 0.0 or not math.isfinite(first_beat_sec):
        raise ValueError("first_beat_sec must be non-negative and finite")
    if first_beat_sec >= duration_sec:
        return ()
    count = math.floor((duration_sec - first_beat_sec) / interval) + 1
    return tuple(first_beat_sec + index * interval for index in range(count))


def snap_time_to_grid(
    time_sec: float,
    *,
    first_beat_sec: float,
    bpm: float,
    beats_per_step: int = 1,
    maximum_sec: float | None = None,
) -> float:
    """Snap an absolute time to the nearest beat or multi-beat grid point.

    Grid points begin at ``first_beat_sec``. Times before the configured first
    beat snap to the first beat rather than inventing beats in the intro.
    """

    if not math.isfinite(time_sec):
        raise ValueError("time_sec must be finite")
    if beats_per_step <= 0:
        raise ValueError("beats_per_step must be positive")
    if first_beat_sec < 0.0 or not math.isfinite(first_beat_sec):
        raise ValueError("first_beat_sec must be non-negative and finite")
    if maximum_sec is not None and (
        not math.isfinite(maximum_sec) or maximum_sec < 0.0
    ):
        raise ValueError("maximum_sec must be non-negative and finite")

    interval = beat_interval_sec(bpm) * beats_per_step
    grid_index = max(round((time_sec - first_beat_sec) / interval), 0)
    snapped = first_beat_sec + grid_index * interval
    if maximum_sec is not None:
        snapped = min(snapped, maximum_sec)
    return max(snapped, 0.0)


def maximum_bar_number(
    *,
    first_beat_sec: float,
    bpm: float,
    duration_sec: float,
    clip_duration_sec: float,
    beats_per_bar: int = 4,
) -> int:
    """Return the last bar whose preview can fit fully inside the source."""

    if clip_duration_sec <= 0.0 or not math.isfinite(clip_duration_sec):
        raise ValueError("clip_duration_sec must be positive and finite")
    latest_start = max(duration_sec - clip_duration_sec, first_beat_sec)
    if latest_start <= first_beat_sec:
        return 1
    interval = bar_interval_sec(bpm, beats_per_bar)
    return max(math.floor((latest_start - first_beat_sec) / interval) + 1, 1)
