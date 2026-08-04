from __future__ import annotations

from io import BytesIO

import mido
import pytest

from stem_to_midi.midi_export import render_raw_midi
from stem_to_midi.transcription import NoteEvent


def test_render_raw_midi_preserves_absolute_note_timing() -> None:
    notes = (
        NoteEvent(1.0, 1.5, 45, 90, 0.9, 45.0),
        NoteEvent(2.0, 2.25, 47, 80, 0.8, 47.0),
    )

    data = render_raw_midi(notes, bpm=120.0, first_beat_sec=0.25)
    midi_file = mido.MidiFile(file=BytesIO(data))

    assert midi_file.type == 1
    assert midi_file.ticks_per_beat == 480
    tempo_messages = [message for message in midi_file.tracks[0] if message.type == "set_tempo"]
    assert mido.tempo2bpm(tempo_messages[0].tempo) == pytest.approx(120.0)
    marker_messages = [message for message in midi_file.tracks[0] if message.type == "marker"]
    assert marker_messages[0].text == "FIRST_BEAT"
    assert marker_messages[0].time == 240

    absolute_tick = 0
    note_on_ticks: list[int] = []
    for message in midi_file.tracks[1]:
        absolute_tick += message.time
        if message.type == "note_on" and message.velocity > 0:
            note_on_ticks.append(absolute_tick)

    assert note_on_ticks == [960, 1920]


def test_render_raw_midi_accepts_non_ascii_track_name() -> None:
    notes = (NoteEvent(0.5, 1.0, 60, 90, 0.9, 60.0),)

    data = render_raw_midi(
        notes,
        bpm=120.0,
        first_beat_sec=0.0,
        track_name="日本語ファイル ボーカル／主旋律 Raw",
        program=53,
    )
    midi_file = mido.MidiFile(file=BytesIO(data))
    track_names = [message.name for message in midi_file.tracks[1] if message.type == "track_name"]

    assert track_names == ["Raw"]
