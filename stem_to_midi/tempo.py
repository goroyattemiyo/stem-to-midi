from __future__ import annotations

from dataclasses import dataclass
from io import BytesIO

import librosa
import numpy as np
import soundfile as sf


@dataclass(frozen=True)
class TempoAnalysis:
    """Tempo analysis result for one mono audio signal."""

    duration_sec: float
    sample_rate: int
    detected_bpm: float
    detected_beat_times_sec: tuple[float, ...]


def load_wav_bytes(data: bytes) -> tuple[np.ndarray, int]:
    """Decode WAV bytes into a finite mono float32 signal."""

    if not data:
        raise ValueError("WAV data is empty")

    audio, sample_rate = sf.read(
        BytesIO(data),
        dtype="float32",
        always_2d=True,
    )
    if sample_rate <= 0:
        raise ValueError("Invalid sample rate")
    if audio.size == 0:
        raise ValueError("WAV contains no audio frames")

    mono = np.mean(audio, axis=1, dtype=np.float32)
    mono = np.nan_to_num(mono, nan=0.0, posinf=0.0, neginf=0.0)
    return np.asarray(mono, dtype=np.float32), int(sample_rate)


def analyze_tempo(audio: np.ndarray, sample_rate: int) -> TempoAnalysis:
    """Estimate global BPM and beat positions with librosa."""

    signal = np.asarray(audio, dtype=np.float32).reshape(-1)
    if signal.size == 0:
        raise ValueError("Audio signal is empty")
    if sample_rate <= 0:
        raise ValueError("Sample rate must be positive")

    onset_envelope = librosa.onset.onset_strength(
        y=signal,
        sr=sample_rate,
        aggregate=np.median,
    )
    tempo, beat_times = librosa.beat.beat_track(
        onset_envelope=onset_envelope,
        sr=sample_rate,
        trim=False,
        units="time",
    )

    tempo_values = np.asarray(tempo, dtype=float).reshape(-1)
    bpm = float(tempo_values[0]) if tempo_values.size else 0.0
    if not np.isfinite(bpm) or bpm < 0:
        bpm = 0.0

    beats = np.asarray(beat_times, dtype=float).reshape(-1)
    beats = beats[np.isfinite(beats)]
    beats = beats[(beats >= 0.0) & (beats <= signal.size / sample_rate)]

    return TempoAnalysis(
        duration_sec=float(signal.size / sample_rate),
        sample_rate=int(sample_rate),
        detected_bpm=bpm,
        detected_beat_times_sec=tuple(float(value) for value in beats),
    )


def generate_fixed_beat_times(
    bpm: float,
    first_beat_sec: float,
    duration_sec: float,
) -> tuple[float, ...]:
    """Generate a fixed-tempo beat grid from a BPM and first beat position."""

    if not np.isfinite(bpm) or bpm <= 0:
        raise ValueError("BPM must be positive")
    if not np.isfinite(first_beat_sec) or first_beat_sec < 0:
        raise ValueError("First beat position must be non-negative")
    if not np.isfinite(duration_sec) or duration_sec < 0:
        raise ValueError("Duration must be non-negative")
    if first_beat_sec > duration_sec:
        return ()

    interval_sec = 60.0 / float(bpm)
    count = int(np.floor((duration_sec - first_beat_sec) / interval_sec)) + 1
    values = first_beat_sec + np.arange(count, dtype=float) * interval_sec
    return tuple(float(value) for value in values if value <= duration_sec + 1e-9)
