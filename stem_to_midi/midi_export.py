from __future__ import annotations

from io import BytesIO

import mido

from stem_to_midi.transcription import NoteEvent


def render_raw_midi(
    notes: tuple[NoteEvent, ...],
    *,
    bpm: float,
    first_beat_sec: float,
    track_name: str = "Bass Raw",
    program: int = 33,
    ticks_per_beat: int = 480,
    beats_per_bar: int = 4,
    beat_unit: int = 4,
) -> bytes:
    """Render absolute-time note candidates as a Standard MIDI File."""

    if bpm <= 0:
        raise ValueError("BPM must be positive")
    if first_beat_sec < 0:
        raise ValueError("First beat position must be non-negative")
    if not 0 <= program <= 127:
        raise ValueError("Program must be between 0 and 127")
    if ticks_per_beat <= 0:
        raise ValueError("Ticks per beat must be positive")
    if beats_per_bar <= 0 or beat_unit <= 0:
        raise ValueError("Time signature values must be positive")

    tempo = mido.bpm2tempo(bpm)
    midi_file = mido.MidiFile(type=1, ticks_per_beat=ticks_per_beat)

    tempo_track = mido.MidiTrack()
    midi_file.tracks.append(tempo_track)
    tempo_track.append(mido.MetaMessage("track_name", name="Tempo", time=0))
    tempo_track.append(mido.MetaMessage("set_tempo", tempo=tempo, time=0))
    tempo_track.append(
        mido.MetaMessage(
            "time_signature",
            numerator=beats_per_bar,
            denominator=beat_unit,
            time=0,
        )
    )
    first_beat_tick = _seconds_to_ticks(first_beat_sec, ticks_per_beat, tempo)
    tempo_track.append(
        mido.MetaMessage(
            "marker",
            text="FIRST_BEAT",
            time=first_beat_tick,
        )
    )
    tempo_track.append(mido.MetaMessage("end_of_track", time=0))

    note_track = mido.MidiTrack()
    midi_file.tracks.append(note_track)
    note_track.append(mido.MetaMessage("track_name", name=track_name, time=0))
    note_track.append(mido.Message("program_change", program=program, time=0))

    absolute_events: list[tuple[int, int, mido.Message]] = []
    for note in notes:
        if not 0 <= note.pitch <= 127:
            raise ValueError("Note pitch must be between 0 and 127")
        if note.end_sec <= note.start_sec:
            raise ValueError("Note end must be after note start")
        start_tick = _seconds_to_ticks(note.start_sec, ticks_per_beat, tempo)
        end_tick = max(
            _seconds_to_ticks(note.end_sec, ticks_per_beat, tempo),
            start_tick + 1,
        )
        absolute_events.append(
            (
                start_tick,
                1,
                mido.Message(
                    "note_on",
                    note=note.pitch,
                    velocity=note.velocity,
                    time=0,
                ),
            )
        )
        absolute_events.append(
            (
                end_tick,
                0,
                mido.Message("note_off", note=note.pitch, velocity=0, time=0),
            )
        )

    previous_tick = 0
    ordered_events = sorted(absolute_events, key=lambda value: (value[0], value[1]))
    for absolute_tick, _, message in ordered_events:
        message.time = max(absolute_tick - previous_tick, 0)
        note_track.append(message)
        previous_tick = absolute_tick
    note_track.append(mido.MetaMessage("end_of_track", time=0))

    buffer = BytesIO()
    midi_file.save(file=buffer)
    return buffer.getvalue()


def _seconds_to_ticks(seconds: float, ticks_per_beat: int, tempo: int) -> int:
    return max(int(round(mido.second2tick(seconds, ticks_per_beat, tempo))), 0)
