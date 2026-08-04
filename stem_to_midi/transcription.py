from __future__ import annotations

from dataclasses import dataclass

import librosa
import numpy as np

_ANALYSIS_SAMPLE_RATE = 22_050
_DEFAULT_FRAME_LENGTH = 4_096
_DEFAULT_HOP_LENGTH = 512


@dataclass(frozen=True)
class TranscriptionConfig:
    """Configuration for monophonic pYIN note extraction."""

    min_midi: int = 28
    max_midi: int = 60
    voicing_threshold: float = 0.6
    min_note_ms: float = 90.0
    max_gap_ms: float = 60.0
    onset_split: bool = True
    analysis_sample_rate: int = _ANALYSIS_SAMPLE_RATE
    frame_length: int = _DEFAULT_FRAME_LENGTH
    hop_length: int = _DEFAULT_HOP_LENGTH


@dataclass(frozen=True)
class NoteEvent:
    """One monophonic MIDI note candidate in absolute source time."""

    start_sec: float
    end_sec: float
    pitch: int
    velocity: int
    confidence: float
    mean_pitch: float

    @property
    def duration_sec(self) -> float:
        return self.end_sec - self.start_sec


@dataclass(frozen=True)
class TranscriptionResult:
    """Raw pitch track, extracted notes, and validation metrics."""

    notes: tuple[NoteEvent, ...]
    frame_times_sec: np.ndarray
    frame_midi: np.ndarray
    voiced_probability: np.ndarray
    voiced_fraction: float
    median_confidence: float
    analysis_start_sec: float
    analysis_end_sec: float


def transcribe_monophonic(
    audio: np.ndarray,
    sample_rate: int,
    config: TranscriptionConfig,
    *,
    start_sec: float = 0.0,
    duration_sec: float | None = None,
) -> TranscriptionResult:
    """Track one predominant pitch and convert it into unquantized note events."""

    signal = np.asarray(audio, dtype=np.float32).reshape(-1)
    if signal.size == 0:
        raise ValueError("Audio signal is empty")
    if sample_rate <= 0:
        raise ValueError("Sample rate must be positive")
    _validate_config(config)

    source_duration = signal.size / sample_rate
    start = min(max(float(start_sec), 0.0), source_duration)
    if duration_sec is None:
        end = source_duration
    else:
        if duration_sec <= 0:
            raise ValueError("Duration must be positive")
        end = min(start + float(duration_sec), source_duration)
    if end <= start:
        raise ValueError("Selected analysis range is empty")

    start_sample = int(round(start * sample_rate))
    end_sample = int(round(end * sample_rate))
    segment = signal[start_sample:end_sample]
    analysis_signal = _resample(segment, sample_rate, config.analysis_sample_rate)
    if analysis_signal.size < config.frame_length:
        analysis_signal = np.pad(
            analysis_signal,
            (0, config.frame_length - analysis_signal.size),
        )

    f0, voiced_flag, voiced_probability = librosa.pyin(
        analysis_signal,
        fmin=float(librosa.midi_to_hz(config.min_midi)),
        fmax=float(librosa.midi_to_hz(config.max_midi)),
        sr=config.analysis_sample_rate,
        frame_length=config.frame_length,
        hop_length=config.hop_length,
        fill_na=np.nan,
    )
    frame_midi = librosa.hz_to_midi(f0)
    frame_midi = _median_smooth(frame_midi, radius=2)
    frame_times = start + librosa.times_like(
        frame_midi,
        sr=config.analysis_sample_rate,
        hop_length=config.hop_length,
    )

    rms = librosa.feature.rms(
        y=analysis_signal,
        frame_length=config.frame_length,
        hop_length=config.hop_length,
        center=True,
    )[0]
    length = min(len(frame_midi), len(voiced_flag), len(voiced_probability), len(rms))
    frame_midi = np.asarray(frame_midi[:length], dtype=float)
    frame_times = np.asarray(frame_times[:length], dtype=float)
    voiced_flag = np.asarray(voiced_flag[:length], dtype=bool)
    voiced_probability = np.asarray(voiced_probability[:length], dtype=float)
    rms = np.asarray(rms[:length], dtype=float)

    within_range = frame_times < end
    frame_midi = frame_midi[within_range]
    frame_times = frame_times[within_range]
    voiced_flag = voiced_flag[within_range]
    voiced_probability = voiced_probability[within_range]
    rms = rms[within_range]
    length = len(frame_times)

    onset_frames: tuple[int, ...] = ()
    if config.onset_split:
        detected = librosa.onset.onset_detect(
            y=analysis_signal,
            sr=config.analysis_sample_rate,
            hop_length=config.hop_length,
            backtrack=True,
            units="frames",
        )
        onset_frames = tuple(int(value) for value in detected if 0 <= value < length)

    notes = extract_note_events(
        frame_times_sec=frame_times,
        frame_midi=frame_midi,
        voiced_probability=voiced_probability,
        voiced_flag=voiced_flag,
        rms=rms,
        config=config,
        onset_frames=onset_frames,
    )

    accepted = (
        voiced_flag
        & np.isfinite(frame_midi)
        & (voiced_probability >= config.voicing_threshold)
        & (frame_midi >= config.min_midi - 0.5)
        & (frame_midi <= config.max_midi + 0.5)
    )
    voiced_fraction = float(np.mean(accepted)) if accepted.size else 0.0
    median_confidence = (
        float(np.median(voiced_probability[accepted])) if np.any(accepted) else 0.0
    )

    return TranscriptionResult(
        notes=notes,
        frame_times_sec=frame_times,
        frame_midi=frame_midi,
        voiced_probability=voiced_probability,
        voiced_fraction=voiced_fraction,
        median_confidence=median_confidence,
        analysis_start_sec=start,
        analysis_end_sec=end,
    )


def extract_note_events(
    *,
    frame_times_sec: np.ndarray,
    frame_midi: np.ndarray,
    voiced_probability: np.ndarray,
    voiced_flag: np.ndarray,
    rms: np.ndarray,
    config: TranscriptionConfig,
    onset_frames: tuple[int, ...] = (),
) -> tuple[NoteEvent, ...]:
    """Convert frame-level pitch observations into monophonic note events."""

    _validate_config(config)
    arrays = [
        np.asarray(frame_times_sec, dtype=float),
        np.asarray(frame_midi, dtype=float),
        np.asarray(voiced_probability, dtype=float),
        np.asarray(voiced_flag, dtype=bool),
        np.asarray(rms, dtype=float),
    ]
    lengths = {len(array) for array in arrays}
    if len(lengths) != 1:
        raise ValueError("Frame arrays must have the same length")
    if not arrays[0].size:
        return ()

    times, midi_values, probabilities, flags, frame_rms = arrays
    if len(times) > 1:
        frame_step = float(np.median(np.diff(times)))
    else:
        frame_step = config.hop_length / config.analysis_sample_rate
    if not np.isfinite(frame_step) or frame_step <= 0:
        raise ValueError("Frame times must be strictly increasing")

    rounded_pitch = np.full(len(times), -1, dtype=int)
    valid = (
        flags
        & np.isfinite(midi_values)
        & np.isfinite(probabilities)
        & (probabilities >= config.voicing_threshold)
        & (midi_values >= config.min_midi - 0.5)
        & (midi_values <= config.max_midi + 0.5)
    )
    rounded_pitch[valid] = np.rint(midi_values[valid]).astype(int)

    max_gap_frames = max(int(round((config.max_gap_ms / 1_000.0) / frame_step)), 0)
    _fill_short_same_pitch_gaps(rounded_pitch, max_gap_frames)

    minimum_frames = max(int(np.ceil((config.min_note_ms / 1_000.0) / frame_step)), 1)
    onset_set = {frame for frame in onset_frames if 0 < frame < len(times)}
    segments: list[tuple[int, int, int]] = []
    start_index: int | None = None
    current_pitch = -1

    for index, pitch in enumerate(rounded_pitch):
        split_at_onset = (
            start_index is not None
            and index in onset_set
            and index - start_index >= minimum_frames
        )
        if pitch < 0:
            if start_index is not None:
                segments.append((start_index, index, current_pitch))
                start_index = None
                current_pitch = -1
            continue
        if start_index is None:
            start_index = index
            current_pitch = int(pitch)
            continue
        if pitch != current_pitch or split_at_onset:
            segments.append((start_index, index, current_pitch))
            start_index = index
            current_pitch = int(pitch)

    if start_index is not None:
        segments.append((start_index, len(times), current_pitch))

    valid_rms = frame_rms[np.isfinite(frame_rms) & (frame_rms > 0)]
    rms_reference = float(np.percentile(valid_rms, 95)) if valid_rms.size else 1.0
    rms_reference = max(rms_reference, np.finfo(float).eps)

    notes: list[NoteEvent] = []
    for segment_start, segment_end, pitch in segments:
        if segment_end - segment_start < minimum_frames:
            continue
        start_sec = float(times[segment_start])
        end_sec = float(times[segment_end - 1] + frame_step)
        values = midi_values[segment_start:segment_end]
        finite_values = values[np.isfinite(values)]
        mean_pitch = float(np.median(finite_values)) if finite_values.size else float(pitch)
        confidence_values = probabilities[segment_start:segment_end]
        finite_confidence = confidence_values[np.isfinite(confidence_values)]
        confidence = (
            float(np.median(finite_confidence)) if finite_confidence.size else 0.0
        )
        segment_rms = frame_rms[segment_start:segment_end]
        finite_rms = segment_rms[np.isfinite(segment_rms) & (segment_rms >= 0)]
        median_rms = float(np.median(finite_rms)) if finite_rms.size else 0.0
        velocity = _rms_to_velocity(median_rms, rms_reference)
        notes.append(
            NoteEvent(
                start_sec=start_sec,
                end_sec=end_sec,
                pitch=int(pitch),
                velocity=velocity,
                confidence=confidence,
                mean_pitch=mean_pitch,
            )
        )

    return tuple(notes)


def _fill_short_same_pitch_gaps(pitches: np.ndarray, max_gap_frames: int) -> None:
    if max_gap_frames <= 0 or len(pitches) < 3:
        return
    index = 0
    while index < len(pitches):
        if pitches[index] >= 0:
            index += 1
            continue
        gap_start = index
        while index < len(pitches) and pitches[index] < 0:
            index += 1
        gap_end = index
        gap_length = gap_end - gap_start
        left = pitches[gap_start - 1] if gap_start > 0 else -1
        right = pitches[gap_end] if gap_end < len(pitches) else -1
        if gap_length <= max_gap_frames and left >= 0 and left == right:
            pitches[gap_start:gap_end] = left


def _median_smooth(values: np.ndarray, radius: int) -> np.ndarray:
    source = np.asarray(values, dtype=float)
    output = source.copy()
    for index in range(len(source)):
        window = source[max(0, index - radius) : min(len(source), index + radius + 1)]
        finite = window[np.isfinite(window)]
        if finite.size:
            output[index] = float(np.median(finite))
    return output


def _rms_to_velocity(rms: float, reference: float) -> int:
    ratio = min(max(rms / reference, 0.0), 1.0)
    return int(np.clip(round(30 + 97 * np.sqrt(ratio)), 1, 127))


def _resample(audio: np.ndarray, original_rate: int, target_rate: int) -> np.ndarray:
    if original_rate == target_rate:
        return np.asarray(audio, dtype=np.float32)
    return np.asarray(
        librosa.resample(
            np.asarray(audio, dtype=np.float32),
            orig_sr=original_rate,
            target_sr=target_rate,
        ),
        dtype=np.float32,
    )


def _validate_config(config: TranscriptionConfig) -> None:
    if not 0 <= config.min_midi <= 127 or not 0 <= config.max_midi <= 127:
        raise ValueError("MIDI range must be between 0 and 127")
    if config.min_midi >= config.max_midi:
        raise ValueError("Minimum MIDI note must be lower than maximum MIDI note")
    if not 0.0 <= config.voicing_threshold <= 1.0:
        raise ValueError("Voicing threshold must be between 0 and 1")
    if config.min_note_ms <= 0:
        raise ValueError("Minimum note duration must be positive")
    if config.max_gap_ms < 0:
        raise ValueError("Maximum gap must be non-negative")
    if config.analysis_sample_rate <= 0:
        raise ValueError("Analysis sample rate must be positive")
    if config.frame_length <= 0 or config.hop_length <= 0:
        raise ValueError("Frame and hop lengths must be positive")
