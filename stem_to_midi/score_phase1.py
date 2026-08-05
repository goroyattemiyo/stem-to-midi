from __future__ import annotations

import io
import math
from collections import defaultdict, deque
from dataclasses import dataclass
from xml.etree import ElementTree as ET

import mido

DIVISIONS_PER_QUARTER = 4
_DEFAULT_TEMPO = 500_000
_DEFAULT_TIME_SIGNATURE = (4, 4)


@dataclass(frozen=True)
class MidiTrackSummary:
    index: int
    name: str
    note_count: int
    channels: tuple[int, ...]
    min_pitch: int | None
    max_pitch: int | None


@dataclass(frozen=True)
class MidiInspection:
    midi_type: int
    ticks_per_beat: int
    tempo_bpm: float
    tempo_change_count: int
    time_signature: tuple[int, int]
    time_signature_change_count: int
    duration_qn: float
    tracks: tuple[MidiTrackSummary, ...]


@dataclass(frozen=True)
class PerformanceNote:
    start_qn: float
    end_qn: float
    pitch: int
    velocity: int
    channel: int


@dataclass(frozen=True)
class ScoreNote:
    start_division: int
    duration_divisions: int
    pitch: int
    velocity: int

    @property
    def end_division(self) -> int:
        return self.start_division + self.duration_divisions


@dataclass(frozen=True)
class RenderedScorePage:
    svg: str
    page_number: int
    page_count: int


def inspect_midi(midi_bytes: bytes) -> MidiInspection:
    midi = _load_midi(midi_bytes)
    tempo_events: list[tuple[int, int]] = []
    signature_events: list[tuple[int, int, int]] = []
    duration_ticks = 0
    tracks: list[MidiTrackSummary] = []

    for index, track in enumerate(midi.tracks):
        absolute_tick = 0
        note_count = 0
        channels: set[int] = set()
        pitches: list[int] = []
        name = f"Track {index + 1}"

        for message in track:
            absolute_tick += int(message.time)
            if message.type == "track_name" and message.name:
                name = str(message.name)
            elif message.type == "set_tempo":
                tempo_events.append((absolute_tick, int(message.tempo)))
            elif message.type == "time_signature":
                signature_events.append(
                    (absolute_tick, int(message.numerator), int(message.denominator))
                )
            elif message.type == "note_on" and int(message.velocity) > 0:
                note_count += 1
                channels.add(int(message.channel))
                pitches.append(int(message.note))

        duration_ticks = max(duration_ticks, absolute_tick)
        tracks.append(
            MidiTrackSummary(
                index=index,
                name=name,
                note_count=note_count,
                channels=tuple(sorted(channels)),
                min_pitch=min(pitches) if pitches else None,
                max_pitch=max(pitches) if pitches else None,
            )
        )

    tempo_events.sort(key=lambda item: item[0])
    signature_events.sort(key=lambda item: item[0])
    primary_tempo = tempo_events[0][1] if tempo_events else _DEFAULT_TEMPO
    primary_signature = (
        (signature_events[0][1], signature_events[0][2])
        if signature_events
        else _DEFAULT_TIME_SIGNATURE
    )

    return MidiInspection(
        midi_type=int(midi.type),
        ticks_per_beat=int(midi.ticks_per_beat),
        tempo_bpm=float(mido.tempo2bpm(primary_tempo)),
        tempo_change_count=len(tempo_events),
        time_signature=primary_signature,
        time_signature_change_count=len(signature_events),
        duration_qn=duration_ticks / float(midi.ticks_per_beat),
        tracks=tuple(tracks),
    )


def extract_track_notes(midi_bytes: bytes, track_index: int) -> tuple[PerformanceNote, ...]:
    midi = _load_midi(midi_bytes)
    if not 0 <= track_index < len(midi.tracks):
        raise ValueError(f"track_index out of range: {track_index}")

    track = midi.tracks[track_index]
    absolute_tick = 0
    active: dict[tuple[int, int], deque[tuple[int, int]]] = defaultdict(deque)
    notes: list[PerformanceNote] = []

    for message in track:
        absolute_tick += int(message.time)
        if not hasattr(message, "channel") or not hasattr(message, "note"):
            continue

        key = (int(message.channel), int(message.note))
        is_note_on = message.type == "note_on" and int(message.velocity) > 0
        is_note_off = message.type == "note_off" or (
            message.type == "note_on" and int(message.velocity) == 0
        )

        if is_note_on:
            active[key].append((absolute_tick, int(message.velocity)))
        elif is_note_off and active[key]:
            start_tick, velocity = active[key].popleft()
            if absolute_tick > start_tick:
                notes.append(
                    PerformanceNote(
                        start_qn=start_tick / float(midi.ticks_per_beat),
                        end_qn=absolute_tick / float(midi.ticks_per_beat),
                        pitch=key[1],
                        velocity=velocity,
                        channel=key[0],
                    )
                )

    for (channel, pitch), pending in active.items():
        while pending:
            start_tick, velocity = pending.popleft()
            if absolute_tick > start_tick:
                notes.append(
                    PerformanceNote(
                        start_qn=start_tick / float(midi.ticks_per_beat),
                        end_qn=absolute_tick / float(midi.ticks_per_beat),
                        pitch=pitch,
                        velocity=velocity,
                        channel=channel,
                    )
                )

    notes.sort(key=lambda note: (note.start_qn, note.pitch, note.end_qn))
    return tuple(notes)


def quantize_monophonic_notes(
    notes: tuple[PerformanceNote, ...] | list[PerformanceNote],
    *,
    subdivision: int = 16,
    strategy: str = "highest",
) -> tuple[ScoreNote, ...]:
    if subdivision not in {4, 8, 16}:
        raise ValueError("subdivision must be one of 4, 8, or 16")
    if strategy not in {"highest", "lowest", "loudest", "longest"}:
        raise ValueError("unsupported monophonic strategy")

    step_divisions = (4 * DIVISIONS_PER_QUARTER) // subdivision
    grouped: dict[int, list[ScoreNote]] = defaultdict(list)

    for note in notes:
        start_division = _round_to_step(note.start_qn * DIVISIONS_PER_QUARTER, step_divisions)
        end_division = _round_to_step(note.end_qn * DIVISIONS_PER_QUARTER, step_divisions)
        start_division = max(start_division, 0)
        end_division = max(end_division, start_division + step_divisions)
        grouped[start_division].append(
            ScoreNote(
                start_division=start_division,
                duration_divisions=end_division - start_division,
                pitch=int(note.pitch),
                velocity=int(note.velocity),
            )
        )

    selected = [
        _choose_candidate(candidates, strategy)
        for _, candidates in sorted(grouped.items(), key=lambda item: item[0])
    ]
    if not selected:
        return ()

    normalized: list[ScoreNote] = []
    for index, note in enumerate(selected):
        next_start = selected[index + 1].start_division if index + 1 < len(selected) else None
        end_division = note.end_division
        if next_start is not None:
            end_division = min(end_division, next_start)
        end_division = max(end_division, note.start_division + step_divisions)
        if next_start is not None and end_division > next_start:
            end_division = next_start
        if end_division <= note.start_division:
            continue

        normalized_note = ScoreNote(
            start_division=note.start_division,
            duration_divisions=end_division - note.start_division,
            pitch=note.pitch,
            velocity=note.velocity,
        )
        if (
            normalized
            and normalized[-1].pitch == normalized_note.pitch
            and normalized[-1].end_division == normalized_note.start_division
        ):
            previous = normalized[-1]
            normalized[-1] = ScoreNote(
                start_division=previous.start_division,
                duration_divisions=normalized_note.end_division - previous.start_division,
                pitch=previous.pitch,
                velocity=max(previous.velocity, normalized_note.velocity),
            )
        else:
            normalized.append(normalized_note)

    return tuple(normalized)


def score_statistics(notes: tuple[ScoreNote, ...] | list[ScoreNote]) -> dict[str, int | float]:
    if not notes:
        return {
            "note_count": 0,
            "measure_count": 1,
            "min_pitch": 0,
            "max_pitch": 0,
            "duration_qn": 0.0,
        }
    last_end = max(note.end_division for note in notes)
    return {
        "note_count": len(notes),
        "measure_count": max(1, math.ceil(last_end / 16)),
        "min_pitch": min(note.pitch for note in notes),
        "max_pitch": max(note.pitch for note in notes),
        "duration_qn": last_end / DIVISIONS_PER_QUARTER,
    }


def build_musicxml(
    notes: tuple[ScoreNote, ...] | list[ScoreNote],
    *,
    title: str,
    tempo_bpm: float,
    clef: str = "treble",
    part_name: str = "Melody",
) -> str:
    if tempo_bpm <= 0:
        raise ValueError("tempo_bpm must be positive")
    if clef not in {"treble", "bass"}:
        raise ValueError("clef must be treble or bass")

    score = ET.Element("score-partwise", version="4.0")
    work = ET.SubElement(score, "work")
    ET.SubElement(work, "work-title").text = title
    identification = ET.SubElement(score, "identification")
    encoding = ET.SubElement(identification, "encoding")
    ET.SubElement(encoding, "software").text = "Stem to Score"

    part_list = ET.SubElement(score, "part-list")
    score_part = ET.SubElement(part_list, "score-part", id="P1")
    ET.SubElement(score_part, "part-name").text = part_name
    part = ET.SubElement(score, "part", id="P1")

    ordered_notes = sorted(notes, key=lambda note: (note.start_division, note.pitch))
    measure_length = 4 * DIVISIONS_PER_QUARTER
    last_end = max((note.end_division for note in ordered_notes), default=0)
    measure_count = max(1, math.ceil(last_end / measure_length))

    for measure_index in range(measure_count):
        measure_start = measure_index * measure_length
        measure_end = measure_start + measure_length
        measure = ET.SubElement(part, "measure", number=str(measure_index + 1))

        if measure_index == 0:
            _append_attributes(measure, clef)
            _append_tempo(measure, tempo_bpm)

        cursor = measure_start
        intersecting = [
            note
            for note in ordered_notes
            if note.start_division < measure_end and note.end_division > measure_start
        ]

        for note in intersecting:
            segment_start = max(note.start_division, measure_start)
            segment_end = min(note.end_division, measure_end)
            if segment_start > cursor:
                _append_rest_duration(measure, segment_start - cursor)
            if segment_end <= cursor:
                continue
            segment_start = max(segment_start, cursor)
            _append_note_duration(
                measure,
                pitch=note.pitch,
                duration=segment_end - segment_start,
                tie_stop=note.start_division < segment_start,
                tie_start=note.end_division > segment_end,
            )
            cursor = segment_end

        if cursor < measure_end:
            _append_rest_duration(measure, measure_end - cursor)

        if measure_index == measure_count - 1:
            barline = ET.SubElement(measure, "barline", location="right")
            ET.SubElement(barline, "bar-style").text = "light-heavy"

    ET.indent(score, space="  ")
    xml_body = ET.tostring(score, encoding="unicode")
    return '<?xml version="1.0" encoding="UTF-8" standalone="no"?>\n' + xml_body


def render_musicxml_page(
    musicxml: str,
    *,
    page_number: int = 1,
    page_width: int = 2100,
    page_height: int = 2970,
    scale: int = 40,
) -> RenderedScorePage:
    try:
        import verovio
    except ImportError as exc:
        raise RuntimeError(
            'Verovio is not installed. Run pip install -e ".[dev]" again.'
        ) from exc

    toolkit = verovio.toolkit()
    toolkit.setOptions(
        {
            "inputFrom": "xml",
            "pageWidth": page_width,
            "pageHeight": page_height,
            "scale": scale,
            "adjustPageHeight": True,
            "breaks": "auto",
            "header": "none",
            "footer": "none",
            "svgViewBox": True,
        }
    )
    if not toolkit.loadData(musicxml):
        raise ValueError("Verovio could not load the generated MusicXML")
    page_count = max(int(toolkit.getPageCount()), 1)
    resolved_page = min(max(int(page_number), 1), page_count)
    return RenderedScorePage(
        svg=toolkit.renderToSVG(resolved_page),
        page_number=resolved_page,
        page_count=page_count,
    )


def maximum_polyphony(notes: tuple[PerformanceNote, ...] | list[PerformanceNote]) -> int:
    events: list[tuple[float, int]] = []
    for note in notes:
        events.append((note.start_qn, 1))
        events.append((note.end_qn, -1))
    active = 0
    maximum = 0
    for _, delta in sorted(events, key=lambda item: (item[0], item[1])):
        active += delta
        maximum = max(maximum, active)
    return maximum


def midi_note_name(pitch: int) -> str:
    if not 0 <= pitch <= 127:
        raise ValueError(f"MIDI pitch out of range: {pitch}")
    names = ("C", "C♯", "D", "D♯", "E", "F", "F♯", "G", "G♯", "A", "A♯", "B")
    return f"{names[pitch % 12]}{(pitch // 12) - 1}"


def _load_midi(midi_bytes: bytes) -> mido.MidiFile:
    if not midi_bytes:
        raise ValueError("MIDI data is empty")
    try:
        return mido.MidiFile(file=io.BytesIO(midi_bytes))
    except (EOFError, OSError, TypeError, ValueError) as exc:
        raise ValueError(f"Invalid MIDI file: {exc}") from exc


def _round_to_step(value: float, step: int) -> int:
    return int(math.floor((value / step) + 0.5)) * step


def _choose_candidate(candidates: list[ScoreNote], strategy: str) -> ScoreNote:
    if strategy == "highest":
        return max(
            candidates,
            key=lambda note: (note.pitch, note.velocity, note.duration_divisions),
        )
    if strategy == "lowest":
        return min(
            candidates,
            key=lambda note: (note.pitch, -note.velocity, -note.duration_divisions),
        )
    if strategy == "loudest":
        return max(
            candidates,
            key=lambda note: (note.velocity, note.duration_divisions, note.pitch),
        )
    return max(candidates, key=lambda note: (note.duration_divisions, note.velocity, note.pitch))


def _append_attributes(measure: ET.Element, clef: str) -> None:
    attributes = ET.SubElement(measure, "attributes")
    ET.SubElement(attributes, "divisions").text = str(DIVISIONS_PER_QUARTER)
    key = ET.SubElement(attributes, "key")
    ET.SubElement(key, "fifths").text = "0"
    time = ET.SubElement(attributes, "time")
    ET.SubElement(time, "beats").text = "4"
    ET.SubElement(time, "beat-type").text = "4"
    clef_element = ET.SubElement(attributes, "clef")
    if clef == "treble":
        ET.SubElement(clef_element, "sign").text = "G"
        ET.SubElement(clef_element, "line").text = "2"
    else:
        ET.SubElement(clef_element, "sign").text = "F"
        ET.SubElement(clef_element, "line").text = "4"


def _append_tempo(measure: ET.Element, tempo_bpm: float) -> None:
    direction = ET.SubElement(measure, "direction", placement="above")
    direction_type = ET.SubElement(direction, "direction-type")
    metronome = ET.SubElement(direction_type, "metronome")
    ET.SubElement(metronome, "beat-unit").text = "quarter"
    ET.SubElement(metronome, "per-minute").text = f"{tempo_bpm:.3f}".rstrip("0").rstrip(".")
    ET.SubElement(direction, "sound", tempo=f"{tempo_bpm:.6f}".rstrip("0").rstrip("."))


def _append_rest_duration(measure: ET.Element, duration: int) -> None:
    for piece_duration, note_type, dotted in _decompose_duration(duration):
        note = ET.SubElement(measure, "note")
        ET.SubElement(note, "rest")
        ET.SubElement(note, "duration").text = str(piece_duration)
        ET.SubElement(note, "voice").text = "1"
        ET.SubElement(note, "type").text = note_type
        if dotted:
            ET.SubElement(note, "dot")


def _append_note_duration(
    measure: ET.Element,
    *,
    pitch: int,
    duration: int,
    tie_stop: bool,
    tie_start: bool,
) -> None:
    pieces = _decompose_duration(duration)
    for index, (piece_duration, note_type, dotted) in enumerate(pieces):
        piece_tie_stop = tie_stop or index > 0
        piece_tie_start = tie_start or index < len(pieces) - 1
        note = ET.SubElement(measure, "note")
        pitch_element = ET.SubElement(note, "pitch")
        step, alter, octave = _midi_pitch_components(pitch)
        ET.SubElement(pitch_element, "step").text = step
        if alter:
            ET.SubElement(pitch_element, "alter").text = str(alter)
        ET.SubElement(pitch_element, "octave").text = str(octave)
        ET.SubElement(note, "duration").text = str(piece_duration)
        if piece_tie_stop:
            ET.SubElement(note, "tie", type="stop")
        if piece_tie_start:
            ET.SubElement(note, "tie", type="start")
        ET.SubElement(note, "voice").text = "1"
        ET.SubElement(note, "type").text = note_type
        if dotted:
            ET.SubElement(note, "dot")
        if piece_tie_stop or piece_tie_start:
            notations = ET.SubElement(note, "notations")
            if piece_tie_stop:
                ET.SubElement(notations, "tied", type="stop")
            if piece_tie_start:
                ET.SubElement(notations, "tied", type="start")


def _decompose_duration(duration: int) -> list[tuple[int, str, bool]]:
    if duration <= 0:
        raise ValueError("duration must be positive")
    values = (
        (16, "whole", False),
        (12, "half", True),
        (8, "half", False),
        (6, "quarter", True),
        (4, "quarter", False),
        (3, "eighth", True),
        (2, "eighth", False),
        (1, "16th", False),
    )
    result: list[tuple[int, str, bool]] = []
    remaining = duration
    for value, note_type, dotted in values:
        while remaining >= value:
            result.append((value, note_type, dotted))
            remaining -= value
    if remaining:
        raise AssertionError("duration decomposition failed")
    return result


def _midi_pitch_components(pitch: int) -> tuple[str, int, int]:
    if not 0 <= pitch <= 127:
        raise ValueError(f"MIDI pitch out of range: {pitch}")
    names = (
        ("C", 0),
        ("C", 1),
        ("D", 0),
        ("D", 1),
        ("E", 0),
        ("F", 0),
        ("F", 1),
        ("G", 0),
        ("G", 1),
        ("A", 0),
        ("A", 1),
        ("B", 0),
    )
    step, alter = names[pitch % 12]
    octave = (pitch // 12) - 1
    return step, alter, octave
