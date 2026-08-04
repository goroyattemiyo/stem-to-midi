from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class TranscriptionPreset:
    key: str
    label: str
    description: str
    min_midi: int
    max_midi: int
    voicing_threshold: float
    min_note_ms: float
    max_gap_ms: float
    onset_split: bool
    midi_program: int


@dataclass(frozen=True)
class AnalysisExtent:
    start_sec: float
    end_sec: float
    duration_sec: float
    source_duration_sec: float
    coverage_fraction: float
    is_full_track: bool


_PRESETS = {
    "bass": TranscriptionPreset(
        key="bass",
        label="ベース",
        description="低音の単音ステム向け。再アタックを残し、弱い倍音をやや厳しく除外します。",
        min_midi=28,
        max_midi=60,
        voicing_threshold=0.60,
        min_note_ms=90.0,
        max_gap_ms=60.0,
        onset_split=True,
        midi_program=33,
    ),
    "vocal": TranscriptionPreset(
        key="vocal",
        label="ボーカル／主旋律",
        description="歌声や単音リード向け。弱い音を拾いやすくし、同音の過剰分割を抑えます。",
        min_midi=48,
        max_midi=84,
        voicing_threshold=0.45,
        min_note_ms=70.0,
        max_gap_ms=100.0,
        onset_split=False,
        midi_program=53,
    ),
}


def transcription_presets() -> tuple[TranscriptionPreset, ...]:
    return tuple(_PRESETS.values())


def get_transcription_preset(key: str) -> TranscriptionPreset:
    try:
        return _PRESETS[key]
    except KeyError as exc:
        raise ValueError(f"Unknown transcription preset: {key}") from exc


def suggest_transcription_preset(source_name: str) -> TranscriptionPreset:
    normalized = Path(source_name).stem.casefold()
    vocal_markers = ("vocal", "vox", "voice", "melody", "lead")
    key = "vocal" if any(marker in normalized for marker in vocal_markers) else "bass"
    return get_transcription_preset(key)


def calculate_analysis_extent(
    *,
    source_duration_sec: float,
    start_sec: float,
    requested_duration_sec: float | None,
) -> AnalysisExtent:
    if source_duration_sec <= 0:
        raise ValueError("Source duration must be positive")
    if start_sec < 0:
        raise ValueError("Analysis start must be non-negative")

    start = min(float(start_sec), float(source_duration_sec))
    if requested_duration_sec is None:
        end = float(source_duration_sec)
    else:
        if requested_duration_sec <= 0:
            raise ValueError("Requested duration must be positive")
        end = min(start + float(requested_duration_sec), float(source_duration_sec))

    duration = max(end - start, 0.0)
    coverage = duration / float(source_duration_sec)
    tolerance = 0.05
    is_full = start <= tolerance and end >= source_duration_sec - tolerance
    return AnalysisExtent(
        start_sec=start,
        end_sec=end,
        duration_sec=duration,
        source_duration_sec=float(source_duration_sec),
        coverage_fraction=coverage,
        is_full_track=is_full,
    )


def build_output_stem(source_name: str, extent: AnalysisExtent) -> str:
    stem = Path(source_name).stem
    if extent.is_full_track:
        return f"{stem}.full"
    duration_label = _format_filename_seconds(extent.duration_sec, prefer_integer=True)
    start_label = _format_filename_seconds(extent.start_sec, prefer_integer=False)
    return f"{stem}.{duration_label}s-from-{start_label}"


def _format_filename_seconds(value: float, *, prefer_integer: bool) -> str:
    rounded_integer = round(value)
    if prefer_integer and abs(value - rounded_integer) < 0.005:
        return str(rounded_integer)
    return f"{value:.3f}".rstrip("0").rstrip(".")
