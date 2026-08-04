from __future__ import annotations

import json
import math
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

_GRID_MULTIPLIERS = (1, 2)
_SHA256_RE = re.compile(r"^[0-9a-fA-F]{64}$")


@dataclass(frozen=True)
class TempoProjectSettings:
    """Editable tempo settings restored from a saved Tempo Lab JSON file."""

    schema_version: int
    felt_bpm: float
    grid_multiplier: int
    first_beat_sec: float
    source_sha256: str | None = None
    source_file: str | None = None
    duration_sec: float | None = None
    sample_rate: int | None = None

    @property
    def grid_bpm(self) -> float:
        return self.felt_bpm * self.grid_multiplier


@dataclass(frozen=True)
class SourceMatch:
    """Compatibility result between a saved project and the selected WAV."""

    status: Literal["match", "mismatch", "unknown"]
    method: Literal["sha256", "metadata", "none"]


def parse_tempo_project(data: bytes | str) -> TempoProjectSettings:
    """Parse schema v1 or v2 Tempo Lab JSON into normalized settings."""

    text = _decode_json_text(data)
    try:
        payload = json.loads(text)
    except json.JSONDecodeError as exc:
        raise ValueError(f"Invalid JSON: line {exc.lineno}, column {exc.colno}") from exc

    if not isinstance(payload, dict):
        raise TypeError("Tempo JSON must contain a JSON object")

    schema_version = _read_schema_version(payload)
    if schema_version == 1:
        felt_bpm = _required_number(payload, "corrected_bpm")
        first_beat_sec = _required_number(payload, "corrected_first_beat_sec")
        detected_bpm = _optional_number(payload, "detected_bpm")
        grid_multiplier = _infer_grid_multiplier(felt_bpm, detected_bpm)
    elif schema_version == 2:
        felt_bpm = _required_number_with_fallback(payload, "felt_bpm", "corrected_bpm")
        first_beat_sec = _required_number_with_fallback(
            payload,
            "first_beat_sec",
            "corrected_first_beat_sec",
        )
        grid_multiplier = _read_grid_multiplier(payload, felt_bpm)
    else:
        raise ValueError(f"Unsupported schema_version: {schema_version}")

    if not 20.0 <= felt_bpm <= 400.0:
        raise ValueError("felt BPM must be between 20 and 400")
    if first_beat_sec < 0.0:
        raise ValueError("first beat position must be non-negative")

    source_sha256 = _optional_string(payload, "source_sha256")
    if source_sha256 is not None:
        if not _SHA256_RE.fullmatch(source_sha256):
            raise ValueError("source_sha256 must be a 64-character hexadecimal digest")
        source_sha256 = source_sha256.lower()

    source_file = _optional_string(payload, "source_file")
    duration_sec = _optional_number(payload, "duration_sec")
    if duration_sec is not None and duration_sec < 0.0:
        raise ValueError("duration_sec must be non-negative")

    sample_rate = _optional_integer(payload, "sample_rate")
    if sample_rate is not None and sample_rate <= 0:
        raise ValueError("sample_rate must be positive")

    return TempoProjectSettings(
        schema_version=schema_version,
        felt_bpm=felt_bpm,
        grid_multiplier=grid_multiplier,
        first_beat_sec=first_beat_sec,
        source_sha256=source_sha256,
        source_file=source_file,
        duration_sec=duration_sec,
        sample_rate=sample_rate,
    )


def evaluate_source_match(
    settings: TempoProjectSettings,
    *,
    source_sha256: str,
    source_file: str,
    duration_sec: float,
    duration_tolerance_sec: float = 0.05,
) -> SourceMatch:
    """Compare a saved project with the selected WAV, preferring SHA-256."""

    if settings.source_sha256 is not None:
        status = "match" if settings.source_sha256 == source_sha256.lower() else "mismatch"
        return SourceMatch(status=status, method="sha256")

    comparisons: list[bool] = []
    if settings.source_file is not None:
        comparisons.append(
            Path(settings.source_file).name.casefold() == Path(source_file).name.casefold()
        )
    if settings.duration_sec is not None:
        comparisons.append(abs(settings.duration_sec - duration_sec) <= duration_tolerance_sec)

    if not comparisons:
        return SourceMatch(status="unknown", method="none")
    status = "match" if all(comparisons) else "mismatch"
    return SourceMatch(status=status, method="metadata")


def _decode_json_text(data: bytes | str) -> str:
    if isinstance(data, str):
        return data
    if not isinstance(data, bytes):
        raise TypeError("Tempo JSON must be bytes or text")
    try:
        return data.decode("utf-8-sig")
    except UnicodeDecodeError as exc:
        raise ValueError("Tempo JSON must be UTF-8 encoded") from exc


def _read_schema_version(payload: dict[str, object]) -> int:
    raw = payload.get("schema_version", 1)
    if isinstance(raw, bool) or not isinstance(raw, int):
        raise TypeError("schema_version must be an integer")
    return raw


def _read_grid_multiplier(payload: dict[str, object], felt_bpm: float) -> int:
    raw_multiplier = payload.get("grid_multiplier")
    if raw_multiplier is not None:
        if isinstance(raw_multiplier, bool) or not isinstance(raw_multiplier, int):
            raise ValueError("grid_multiplier must be an integer")
        if raw_multiplier not in _GRID_MULTIPLIERS:
            raise ValueError("grid_multiplier must be 1 or 2")
        return raw_multiplier

    grid_bpm = _optional_number(payload, "grid_bpm")
    return _infer_grid_multiplier(felt_bpm, grid_bpm)


def _infer_grid_multiplier(felt_bpm: float, target_bpm: float | None) -> int:
    if target_bpm is None or felt_bpm <= 0.0 or target_bpm <= 0.0:
        return 1
    return min(
        _GRID_MULTIPLIERS,
        key=lambda multiplier: abs(felt_bpm * multiplier - target_bpm),
    )


def _required_number(payload: dict[str, object], key: str) -> float:
    value = _optional_number(payload, key)
    if value is None:
        raise ValueError(f"Missing numeric field: {key}")
    return value


def _required_number_with_fallback(
    payload: dict[str, object],
    key: str,
    fallback_key: str,
) -> float:
    value = _optional_number(payload, key)
    if value is not None:
        return value
    return _required_number(payload, fallback_key)


def _optional_number(payload: dict[str, object], key: str) -> float | None:
    raw = payload.get(key)
    if raw is None:
        return None
    if isinstance(raw, bool) or not isinstance(raw, (int, float)):
        raise TypeError(f"{key} must be numeric")
    value = float(raw)
    if not math.isfinite(value):
        raise ValueError(f"{key} must be finite")
    return value


def _optional_integer(payload: dict[str, object], key: str) -> int | None:
    raw = payload.get(key)
    if raw is None:
        return None
    if isinstance(raw, bool) or not isinstance(raw, int):
        raise TypeError(f"{key} must be an integer")
    return raw


def _optional_string(payload: dict[str, object], key: str) -> str | None:
    raw = payload.get(key)
    if raw is None:
        return None
    if not isinstance(raw, str) or not raw.strip():
        raise ValueError(f"{key} must be a non-empty string")
    return raw.strip()
