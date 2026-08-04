from __future__ import annotations

import math

import matplotlib.pyplot as plt
import numpy as np
from matplotlib.figure import Figure
from matplotlib.patches import Rectangle

from stem_to_midi.transcription import TranscriptionResult


def plot_transcription(
    result: TranscriptionResult,
    *,
    grid_bpm: float,
    first_beat_sec: float,
    beats_per_bar: int = 4,
) -> Figure:
    """Plot raw pYIN observations and extracted notes against the tempo grid."""

    if grid_bpm <= 0:
        raise ValueError("Grid BPM must be positive")
    if beats_per_bar <= 0:
        raise ValueError("Beats per bar must be positive")

    figure, axis = plt.subplots(figsize=(12, 4.5))
    finite_track = np.isfinite(result.frame_midi)
    if np.any(finite_track):
        axis.scatter(
            result.frame_times_sec[finite_track],
            result.frame_midi[finite_track],
            s=6,
            alpha=0.25,
            label="pYIN pitch frames",
        )

    for index, note in enumerate(result.notes):
        axis.add_patch(
            Rectangle(
                (note.start_sec, note.pitch - 0.4),
                note.duration_sec,
                0.8,
                alpha=0.65,
                label="Extracted notes" if index == 0 else None,
            )
        )

    interval_sec = 60.0 / grid_bpm
    first_index = math.floor((result.analysis_start_sec - first_beat_sec) / interval_sec)
    last_index = math.ceil((result.analysis_end_sec - first_beat_sec) / interval_sec)
    for beat_index in range(first_index, last_index + 1):
        beat_time = first_beat_sec + beat_index * interval_sec
        if not result.analysis_start_sec <= beat_time <= result.analysis_end_sec:
            continue
        is_bar = beat_index % beats_per_bar == 0
        axis.axvline(
            beat_time,
            linestyle="-" if is_bar else ":",
            linewidth=1.1 if is_bar else 0.6,
            alpha=0.45 if is_bar else 0.2,
        )

    pitches = [note.pitch for note in result.notes]
    finite_midi = result.frame_midi[finite_track]
    if pitches:
        lower = min(pitches) - 2
        upper = max(pitches) + 2
    elif finite_midi.size:
        lower = int(np.floor(np.min(finite_midi))) - 2
        upper = int(np.ceil(np.max(finite_midi))) + 2
    else:
        lower, upper = 24, 60

    tick_start = max(lower, 0)
    tick_end = min(upper, 127)
    ticks = list(range(tick_start, tick_end + 1))
    axis.set_yticks(ticks)
    axis.set_yticklabels([_midi_note_name(value) for value in ticks])
    axis.set_ylim(lower, upper)
    axis.set_xlim(result.analysis_start_sec, result.analysis_end_sec)
    axis.set_xlabel("Source time (seconds)")
    axis.set_ylabel("Pitch")
    axis.set_title("Raw pitch track and extracted MIDI notes")
    handles, labels = axis.get_legend_handles_labels()
    if handles:
        axis.legend(handles, labels, loc="upper right")
    figure.tight_layout()
    return figure


def _midi_note_name(note: int) -> str:
    names = ("C", "C♯", "D", "D♯", "E", "F", "F♯", "G", "G♯", "A", "A♯", "B")
    return f"{names[note % 12]}{note // 12 - 1}"
