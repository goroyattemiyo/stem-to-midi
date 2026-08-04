from __future__ import annotations

from collections.abc import Iterable, Sequence
from dataclasses import dataclass, replace
from importlib.metadata import PackageNotFoundError, version
from importlib.util import find_spec
from itertools import pairwise
from pathlib import Path
from tempfile import NamedTemporaryFile

import librosa
import numpy as np
import soundfile as sf

from stem_to_midi.transcription import NoteEvent, TranscriptionResult


@dataclass(frozen=True)
class BasicPitchConfig:
    """Configuration for Spotify Basic Pitch note extraction."""

    min_midi: int = 48
    max_midi: int = 84
    onset_threshold: float = 0.5
    frame_threshold: float = 0.3
    min_note_ms: float = 127.7
    melodia_trick: bool = True
    monophonic_path: bool = True


@dataclass(frozen=True)
class BasicPitchRun:
    """Normalized Basic Pitch output and the unfiltered model note events."""

    result: TranscriptionResult
    raw_notes: tuple[NoteEvent, ...]
    backend_version: str


def basic_pitch_available() -> bool:
    """Return whether the optional Basic Pitch package can be imported."""

    return find_spec("basic_pitch") is not None


def installed_basic_pitch_version() -> str:
    try:
        return version("basic-pitch")
    except PackageNotFoundError:
        return "not-installed"


def transcribe_basic_pitch(
    audio: np.ndarray,
    sample_rate: int,
    config: BasicPitchConfig,
    *,
    start_sec: float = 0.0,
    duration_sec: float | None = None,
) -> BasicPitchRun:
    """Run Basic Pitch and normalize its note events to absolute source time."""

    _validate_config(config)
    signal = np.asarray(audio, dtype=np.float32).reshape(-1)
    if signal.size == 0:
        raise ValueError("Audio signal is empty")
    if sample_rate <= 0:
        raise ValueError("Sample rate must be positive")
    if not basic_pitch_available():
        raise RuntimeError(
            "Basic Pitch is not installed. Install the optional accuracy dependencies first."
        )

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

    start_sample = round(start * sample_rate)
    end_sample = round(end * sample_rate)
    segment = signal[start_sample:end_sample]
    temp_path = _write_temporary_wav(segment, sample_rate)
    try:
        from basic_pitch.inference import predict

        _, _, note_events = predict(
            temp_path,
            onset_threshold=config.onset_threshold,
            frame_threshold=config.frame_threshold,
            minimum_note_length=config.min_note_ms,
            minimum_frequency=float(librosa.midi_to_hz(config.min_midi)),
            maximum_frequency=float(librosa.midi_to_hz(config.max_midi)),
            multiple_pitch_bends=False,
            melodia_trick=config.melodia_trick,
            # We ignore Basic Pitch's MIDI object and render our own tempo-aware file.
            midi_tempo=120.0,
        )
    except (ImportError, OSError, RuntimeError, ValueError) as exc:
        raise RuntimeError(f"Basic Pitch inference failed: {exc}") from exc
    finally:
        temp_path.unlink(missing_ok=True)

    raw_notes = convert_basic_pitch_events(
        note_events,
        offset_sec=start,
        analysis_end_sec=end,
        min_midi=config.min_midi,
        max_midi=config.max_midi,
    )
    selected_notes = (
        select_monophonic_path(raw_notes) if config.monophonic_path else raw_notes
    )
    selected_notes = merge_adjacent_same_pitch(selected_notes, maximum_gap_sec=0.08)
    coverage = note_coverage_fraction(selected_notes, start_sec=start, end_sec=end)
    confidences = [note.confidence for note in selected_notes]
    median_confidence = float(np.median(confidences)) if confidences else 0.0

    result = TranscriptionResult(
        notes=selected_notes,
        frame_times_sec=np.array([], dtype=float),
        frame_midi=np.array([], dtype=float),
        voiced_probability=np.array([], dtype=float),
        voiced_fraction=coverage,
        median_confidence=median_confidence,
        analysis_start_sec=start,
        analysis_end_sec=end,
    )
    return BasicPitchRun(
        result=result,
        raw_notes=raw_notes,
        backend_version=installed_basic_pitch_version(),
    )


def convert_basic_pitch_events(
    events: Iterable[Sequence[object]],
    *,
    offset_sec: float,
    analysis_end_sec: float,
    min_midi: int = 0,
    max_midi: int = 127,
) -> tuple[NoteEvent, ...]:
    """Convert Basic Pitch tuples to validated absolute-time note events."""

    notes: list[NoteEvent] = []
    for event in events:
        if len(event) < 4:
            continue
        relative_start = float(event[0])
        relative_end = float(event[1])
        pitch = int(event[2])
        amplitude = float(event[3])
        if not all(np.isfinite(value) for value in (relative_start, relative_end, amplitude)):
            continue
        if relative_end <= relative_start or not min_midi <= pitch <= max_midi:
            continue

        start = max(offset_sec + relative_start, offset_sec)
        end = min(offset_sec + relative_end, analysis_end_sec)
        if end <= start:
            continue
        confidence = float(np.clip(amplitude, 0.0, 1.0))
        velocity = int(np.clip(round(127 * confidence), 1, 127))
        notes.append(
            NoteEvent(
                start_sec=start,
                end_sec=end,
                pitch=pitch,
                velocity=velocity,
                confidence=confidence,
                mean_pitch=float(pitch),
            )
        )

    notes.sort(key=lambda note: (note.start_sec, note.end_sec, note.pitch))
    return tuple(notes)


def select_monophonic_path(
    notes: Sequence[NoteEvent],
    *,
    overlap_tolerance_sec: float = 0.03,
) -> tuple[NoteEvent, ...]:
    """Select one continuous, non-overlapping melody path from polyphonic candidates."""

    if not notes:
        return ()
    ordered = sorted(notes, key=lambda note: (note.end_sec, note.start_sec, note.pitch))
    scores = [0.0] * len(ordered)
    previous: list[int | None] = [None] * len(ordered)

    for current_index, current in enumerate(ordered):
        reward = _note_reward(current)
        best_score = reward
        best_previous: int | None = None
        for candidate_index in range(current_index):
            candidate = ordered[candidate_index]
            if candidate.end_sec > current.start_sec + overlap_tolerance_sec:
                continue
            transition = _transition_penalty(candidate, current)
            score = scores[candidate_index] + reward - transition
            if score > best_score:
                best_score = score
                best_previous = candidate_index
        scores[current_index] = best_score
        previous[current_index] = best_previous

    cursor: int | None = max(range(len(scores)), key=scores.__getitem__)
    selected: list[NoteEvent] = []
    while cursor is not None:
        selected.append(ordered[cursor])
        cursor = previous[cursor]
    selected.reverse()

    trimmed: list[NoteEvent] = []
    for note in selected:
        if trimmed and trimmed[-1].end_sec > note.start_sec:
            prior = trimmed[-1]
            trimmed_end = max(prior.start_sec + 0.001, note.start_sec)
            if trimmed_end > prior.start_sec:
                trimmed[-1] = replace(prior, end_sec=trimmed_end)
        if note.end_sec > note.start_sec:
            trimmed.append(note)
    return tuple(trimmed)


def merge_adjacent_same_pitch(
    notes: Sequence[NoteEvent],
    *,
    maximum_gap_sec: float,
) -> tuple[NoteEvent, ...]:
    if maximum_gap_sec < 0:
        raise ValueError("Maximum gap must be non-negative")
    if not notes:
        return ()

    ordered = sorted(notes, key=lambda note: (note.start_sec, note.end_sec, note.pitch))
    merged: list[NoteEvent] = [ordered[0]]
    for note in ordered[1:]:
        previous = merged[-1]
        gap = note.start_sec - previous.end_sec
        if note.pitch == previous.pitch and gap <= maximum_gap_sec:
            total_duration = previous.duration_sec + note.duration_sec
            if total_duration > 0:
                confidence = (
                    previous.confidence * previous.duration_sec
                    + note.confidence * note.duration_sec
                ) / total_duration
            else:
                confidence = max(previous.confidence, note.confidence)
            merged[-1] = NoteEvent(
                start_sec=previous.start_sec,
                end_sec=max(previous.end_sec, note.end_sec),
                pitch=previous.pitch,
                velocity=max(previous.velocity, note.velocity),
                confidence=confidence,
                mean_pitch=float(previous.pitch),
            )
        else:
            merged.append(note)
    return tuple(merged)


def note_coverage_fraction(
    notes: Sequence[NoteEvent],
    *,
    start_sec: float,
    end_sec: float,
) -> float:
    if end_sec <= start_sec:
        raise ValueError("Coverage range must be positive")
    intervals = sorted(
        (
            max(note.start_sec, start_sec),
            min(note.end_sec, end_sec),
        )
        for note in notes
        if note.end_sec > start_sec and note.start_sec < end_sec
    )
    covered = 0.0
    current_start: float | None = None
    current_end: float | None = None
    for interval_start, interval_end in intervals:
        if interval_end <= interval_start:
            continue
        if current_start is None or current_end is None:
            current_start, current_end = interval_start, interval_end
            continue
        if interval_start <= current_end:
            current_end = max(current_end, interval_end)
        else:
            covered += current_end - current_start
            current_start, current_end = interval_start, interval_end
    if current_start is not None and current_end is not None:
        covered += current_end - current_start
    return float(np.clip(covered / (end_sec - start_sec), 0.0, 1.0))


def maximum_polyphony(notes: Sequence[NoteEvent]) -> int:
    events: list[tuple[float, int]] = []
    for note in notes:
        events.append((note.start_sec, 1))
        events.append((note.end_sec, -1))
    active = 0
    maximum = 0
    for _, delta in sorted(events, key=lambda item: (item[0], item[1])):
        active += delta
        maximum = max(maximum, active)
    return maximum


def count_large_pitch_jumps(
    notes: Sequence[NoteEvent],
    *,
    threshold_semitones: int = 12,
    maximum_gap_sec: float = 2.0,
) -> int:
    if threshold_semitones <= 0:
        raise ValueError("Jump threshold must be positive")
    ordered = sorted(notes, key=lambda note: (note.start_sec, note.end_sec))
    return sum(
        1
        for previous, current in pairwise(ordered)
        if current.start_sec - previous.end_sec <= maximum_gap_sec
        and abs(current.pitch - previous.pitch) >= threshold_semitones
    )


def longest_note_gap(
    notes: Sequence[NoteEvent],
    *,
    start_sec: float,
    end_sec: float,
) -> float:
    if end_sec <= start_sec:
        raise ValueError("Gap range must be positive")
    ordered = sorted(notes, key=lambda note: (note.start_sec, note.end_sec))
    cursor = start_sec
    longest = 0.0
    for note in ordered:
        if note.end_sec <= start_sec or note.start_sec >= end_sec:
            continue
        longest = max(longest, max(note.start_sec - cursor, 0.0))
        cursor = max(cursor, min(note.end_sec, end_sec))
    longest = max(longest, end_sec - cursor)
    return longest


def _write_temporary_wav(audio: np.ndarray, sample_rate: int) -> Path:
    with NamedTemporaryFile(suffix=".wav", delete=False) as handle:
        path = Path(handle.name)
    sf.write(path, audio, sample_rate, subtype="PCM_16")
    return path


def _note_reward(note: NoteEvent) -> float:
    duration_reward = 1.5 * min(max(note.duration_sec, 0.0), 2.0)
    confidence_reward = 0.75 * float(np.clip(note.confidence, 0.0, 1.0))
    return duration_reward + confidence_reward + 0.05


def _transition_penalty(previous: NoteEvent, current: NoteEvent) -> float:
    distance = abs(current.pitch - previous.pitch)
    pitch_penalty = 0.06 * min(distance, 24)
    if distance >= 12:
        pitch_penalty += 0.8
    gap = max(current.start_sec - previous.end_sec, 0.0)
    gap_penalty = 0.03 * min(gap, 4.0)
    return pitch_penalty + gap_penalty


def _validate_config(config: BasicPitchConfig) -> None:
    if not 0 <= config.min_midi <= 127 or not 0 <= config.max_midi <= 127:
        raise ValueError("MIDI range must be between 0 and 127")
    if config.min_midi >= config.max_midi:
        raise ValueError("Minimum MIDI note must be lower than maximum MIDI note")
    if not 0.0 <= config.onset_threshold <= 1.0:
        raise ValueError("Onset threshold must be between 0 and 1")
    if not 0.0 <= config.frame_threshold <= 1.0:
        raise ValueError("Frame threshold must be between 0 and 1")
    if config.min_note_ms <= 0:
        raise ValueError("Minimum note duration must be positive")
