from __future__ import annotations

from io import BytesIO

import librosa
import numpy as np
import soundfile as sf


def render_wav_segment(
    audio: np.ndarray,
    sample_rate: int,
    start_sec: float,
    duration_sec: float,
) -> bytes:
    """Render a mono WAV segment to bytes."""

    segment = _slice_audio(audio, sample_rate, start_sec, duration_sec)
    return _encode_wav(segment, sample_rate)


def render_click_preview(
    audio: np.ndarray,
    sample_rate: int,
    beat_times_sec: tuple[float, ...] | list[float],
    start_sec: float,
    duration_sec: float,
    click_gain: float = 0.45,
) -> bytes:
    """Mix clicks over a selected audio segment and return WAV bytes."""

    if click_gain < 0:
        raise ValueError("Click gain must be non-negative")

    segment = _slice_audio(audio, sample_rate, start_sec, duration_sec)
    end_sec = start_sec + len(segment) / sample_rate
    relative_beats = np.asarray(
        [
            float(beat) - start_sec
            for beat in beat_times_sec
            if start_sec <= float(beat) < end_sec
        ],
        dtype=float,
    )

    clicks = librosa.clicks(
        times=relative_beats,
        sr=sample_rate,
        click_freq=1200.0,
        click_duration=0.04,
        length=len(segment),
    ).astype(np.float32)

    mixed = segment + clicks * float(click_gain)
    peak = float(np.max(np.abs(mixed))) if mixed.size else 0.0
    if peak > 0.98:
        mixed = mixed * (0.98 / peak)
    return _encode_wav(mixed, sample_rate)


def _slice_audio(
    audio: np.ndarray,
    sample_rate: int,
    start_sec: float,
    duration_sec: float,
) -> np.ndarray:
    signal = np.asarray(audio, dtype=np.float32).reshape(-1)
    if sample_rate <= 0:
        raise ValueError("Sample rate must be positive")
    if start_sec < 0:
        raise ValueError("Start position must be non-negative")
    if duration_sec <= 0:
        raise ValueError("Preview duration must be positive")

    start_sample = min(round(start_sec * sample_rate), len(signal))
    end_sample = min(round((start_sec + duration_sec) * sample_rate), len(signal))
    return np.asarray(signal[start_sample:end_sample], dtype=np.float32)


def _encode_wav(audio: np.ndarray, sample_rate: int) -> bytes:
    buffer = BytesIO()
    sf.write(buffer, audio, sample_rate, format="WAV", subtype="PCM_16")
    return buffer.getvalue()
