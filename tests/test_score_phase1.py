from __future__ import annotations

import io
from xml.etree import ElementTree as ET

import mido
import pytest

from stem_to_midi.score_phase1 import (
    PerformanceNote,
    ScoreNote,
    build_musicxml,
    extract_track_notes,
    inspect_midi,
    maximum_polyphony,
    quantize_monophonic_notes,
    render_musicxml_page,
)


def _midi_bytes() -> bytes:
    midi = mido.MidiFile(type=1, ticks_per_beat=480)

    conductor = mido.MidiTrack()
    conductor.append(mido.MetaMessage("track_name", name="Conductor", time=0))
    conductor.append(
        mido.MetaMessage(
            "set_tempo",
            tempo=mido.bpm2tempo(90),
            time=0,
        )
    )
    conductor.append(
        mido.MetaMessage(
            "time_signature",
            numerator=4,
            denominator=4,
            time=0,
        )
    )
    midi.tracks.append(conductor)

    melody = mido.MidiTrack()
    melody.append(mido.MetaMessage("track_name", name="Melody", time=0))
    melody.append(mido.Message("note_on", note=60, velocity=80, channel=0, time=0))
    melody.append(mido.Message("note_off", note=60, velocity=0, channel=0, time=480))
    melody.append(mido.Message("note_on", note=64, velocity=90, channel=0, time=0))
    melody.append(mido.Message("note_off", note=64, velocity=0, channel=0, time=960))
    midi.tracks.append(melody)

    buffer = io.BytesIO()
    midi.save(file=buffer)
    return buffer.getvalue()


def test_inspect_and_extract_midi_track() -> None:
    midi_bytes = _midi_bytes()

    inspection = inspect_midi(midi_bytes)
    notes = extract_track_notes(midi_bytes, 1)

    assert inspection.midi_type == 1
    assert inspection.ticks_per_beat == 480
    assert inspection.tempo_bpm == pytest.approx(90.0, abs=0.001)
    assert inspection.time_signature == (4, 4)
    assert inspection.tracks[1].name == "Melody"
    assert inspection.tracks[1].note_count == 2
    assert [(note.start_qn, note.end_qn, note.pitch) for note in notes] == [
        (0.0, 1.0, 60),
        (1.0, 3.0, 64),
    ]


def test_quantize_highest_voice_and_remove_overlap() -> None:
    notes = (
        PerformanceNote(0.02, 1.02, 60, 80, 0),
        PerformanceNote(0.03, 0.55, 72, 70, 0),
        PerformanceNote(0.52, 1.48, 74, 90, 0),
    )

    score_notes = quantize_monophonic_notes(
        notes,
        subdivision=16,
        strategy="highest",
    )

    assert [(note.start_division, note.duration_divisions, note.pitch) for note in score_notes] == [
        (0, 2, 72),
        (2, 4, 74),
    ]
    assert maximum_polyphony(notes) == 3


def test_musicxml_contains_rests_and_cross_measure_ties() -> None:
    musicxml = build_musicxml(
        (
            ScoreNote(start_division=2, duration_divisions=2, pitch=60, velocity=80),
            ScoreNote(start_division=14, duration_divisions=6, pitch=62, velocity=90),
        ),
        title="Test Song",
        tempo_bpm=90.0,
        clef="treble",
    )
    root = ET.fromstring(musicxml)

    measures = root.findall("./part/measure")
    assert len(measures) == 2
    assert root.findtext("./work/work-title") == "Test Song"
    assert measures[0].findtext("./attributes/divisions") == "4"
    assert measures[0].findtext("./attributes/time/beats") == "4"
    assert measures[0].findtext("./direction/direction-type/metronome/per-minute") == "90"

    tied_notes = [
        note
        for measure in measures
        for note in measure.findall("note")
        if note.findall("tie")
    ]
    assert any(
        any(tie.attrib["type"] == "start" for tie in note.findall("tie"))
        for note in tied_notes
    )
    assert any(
        any(tie.attrib["type"] == "stop" for tie in note.findall("tie"))
        for note in tied_notes
    )
    assert any(
        note.find("rest") is not None
        for measure in measures
        for note in measure.findall("note")
    )


def test_verovio_renders_generated_musicxml() -> None:
    musicxml = build_musicxml(
        (ScoreNote(start_division=0, duration_divisions=4, pitch=60, velocity=80),),
        title="Render Test",
        tempo_bpm=120.0,
    )

    rendered = render_musicxml_page(musicxml)

    assert rendered.page_count >= 1
    assert rendered.page_number == 1
    assert "<svg" in rendered.svg
