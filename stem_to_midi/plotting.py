from __future__ import annotations

import matplotlib.pyplot as plt
import numpy as np
from matplotlib.figure import Figure


def plot_waveform_with_beats(
    audio: np.ndarray,
    sample_rate: int,
    start_sec: float,
    duration_sec: float,
    detected_beats_sec: tuple[float, ...],
    felt_beats_sec: tuple[float, ...],
    grid_beats_sec: tuple[float, ...],
) -> Figure:
    """Plot a waveform window with detected, felt, and internal-grid markers."""

    signal = np.asarray(audio, dtype=np.float32).reshape(-1)
    start_sample = min(max(int(start_sec * sample_rate), 0), len(signal))
    end_sample = min(int((start_sec + duration_sec) * sample_rate), len(signal))
    segment = signal[start_sample:end_sample]

    max_points = 12_000
    stride = max(1, int(np.ceil(max(len(segment), 1) / max_points)))
    displayed = segment[::stride]
    times = start_sec + np.arange(len(displayed)) * stride / sample_rate

    figure, axis = plt.subplots(figsize=(12, 3.5))
    axis.plot(times, displayed, linewidth=0.7, label="Waveform")

    end_sec = start_sec + duration_sec
    detected_visible = [beat for beat in detected_beats_sec if start_sec <= beat <= end_sec]
    felt_visible = [beat for beat in felt_beats_sec if start_sec <= beat <= end_sec]
    grid_visible = [beat for beat in grid_beats_sec if start_sec <= beat <= end_sec]

    for index, beat in enumerate(detected_visible):
        axis.axvline(
            beat,
            linestyle=":",
            alpha=0.35,
            label="Detected beats" if index == 0 else None,
        )

    if not _beat_sequences_match(felt_beats_sec, grid_beats_sec):
        for index, beat in enumerate(grid_visible):
            axis.axvline(
                beat,
                linestyle="--",
                alpha=0.5,
                label="Internal grid" if index == 0 else None,
            )

    for index, beat in enumerate(felt_visible):
        axis.axvline(
            beat,
            linestyle="-",
            alpha=0.8,
            label="Felt pulse" if index == 0 else None,
        )

    axis.set_xlim(start_sec, min(end_sec, len(signal) / sample_rate))
    axis.set_xlabel("Time (seconds)")
    axis.set_ylabel("Amplitude")
    axis.set_title("Waveform and tempo grids")
    axis.legend(loc="upper right")
    figure.tight_layout()
    return figure


def _beat_sequences_match(
    first: tuple[float, ...],
    second: tuple[float, ...],
) -> bool:
    if len(first) != len(second):
        return False
    if not first:
        return True
    return bool(np.allclose(first, second, rtol=0.0, atol=1e-9))
