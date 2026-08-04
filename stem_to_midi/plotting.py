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
    adjusted_beats_sec: tuple[float, ...],
) -> Figure:
    """Plot a waveform window with detected and adjusted beat markers."""

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
    adjusted_visible = [beat for beat in adjusted_beats_sec if start_sec <= beat <= end_sec]

    for index, beat in enumerate(detected_visible):
        axis.axvline(
            beat,
            linestyle=":",
            alpha=0.45,
            label="Detected beats" if index == 0 else None,
        )
    for index, beat in enumerate(adjusted_visible):
        axis.axvline(
            beat,
            linestyle="--",
            alpha=0.8,
            label="Adjusted grid" if index == 0 else None,
        )

    axis.set_xlim(start_sec, min(end_sec, len(signal) / sample_rate))
    axis.set_xlabel("Time (seconds)")
    axis.set_ylabel("Amplitude")
    axis.set_title("Waveform and beat grid")
    axis.legend(loc="upper right")
    figure.tight_layout()
    return figure
