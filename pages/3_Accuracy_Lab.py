from __future__ import annotations

import hashlib
import json
from pathlib import Path

import matplotlib.pyplot as plt
import numpy as np
import streamlit as st

from stem_to_midi.analysis_plan import (
    AnalysisExtent,
    build_output_stem,
    calculate_analysis_extent,
    get_transcription_preset,
    suggest_transcription_preset,
    transcription_presets,
)
from stem_to_midi.basic_pitch_backend import (
    BasicPitchConfig,
    BasicPitchRun,
    basic_pitch_available,
    count_large_pitch_jumps,
    longest_note_gap,
    maximum_polyphony,
    transcribe_basic_pitch,
)
from stem_to_midi.midi_export import render_raw_midi
from stem_to_midi.project import TempoProjectSettings, parse_tempo_project
from stem_to_midi.tempo import load_wav_bytes
from stem_to_midi.transcription import NoteEvent
from stem_to_midi.transcription_plot import plot_transcription

st.set_page_config(page_title="Stem to MIDI — Accuracy Lab", page_icon="🎯", layout="wide")

_RANGE_MODES = ("30秒で比較", "60秒で比較", "全曲")


@st.cache_data(show_spinner=False)
def decode_wav(wav_bytes: bytes) -> tuple[np.ndarray, int]:
    return load_wav_bytes(wav_bytes)


@st.cache_data(show_spinner=False)
def run_basic_pitch(
    wav_bytes: bytes,
    *,
    min_midi: int,
    max_midi: int,
    onset_threshold: float,
    frame_threshold: float,
    min_note_ms: float,
    melodia_trick: bool,
    monophonic_path: bool,
    start_sec: float,
    duration_sec: float | None,
) -> BasicPitchRun:
    audio, sample_rate = load_wav_bytes(wav_bytes)
    config = BasicPitchConfig(
        min_midi=min_midi,
        max_midi=max_midi,
        onset_threshold=onset_threshold,
        frame_threshold=frame_threshold,
        min_note_ms=min_note_ms,
        melodia_trick=melodia_trick,
        monophonic_path=monophonic_path,
    )
    return transcribe_basic_pitch(
        audio,
        sample_rate,
        config,
        start_sec=start_sec,
        duration_sec=duration_sec,
    )


def main() -> None:
    st.title("Accuracy Lab — Basic Pitch")
    st.caption(
        "pYINより多くの音を拾えるSpotify Basic Pitchを使い、Raw候補と単音メロディ候補を作ります。"
    )
    st.info(
        "まず同じ30秒区間をRaw MIDI Labと比較し、改善を確認してから全曲へ進めてください。"
        "Basic Pitchは分離済みの単一楽器ステムで最も効果を期待できます。"
    )

    if not basic_pitch_available():
        st.warning("Basic Pitchの追加依存がまだインストールされていません。")
        st.code(
            '.\\.venv\\Scripts\\python.exe -m pip install -e ".[accuracy]"',
            language="powershell",
        )
        st.caption("インストール後、StreamlitをCtrl+Cで停止して再起動してください。")

    wav_file = st.file_uploader("音高ステムWAV", type=["wav"], key="accuracy_wav")
    tempo_file = st.file_uploader(
        "Tempo Labのtempo.json",
        type=["json"],
        key="accuracy_tempo",
    )
    if wav_file is None or tempo_file is None:
        st.stop()

    wav_bytes = wav_file.getvalue()
    try:
        settings = parse_tempo_project(tempo_file.getvalue())
        audio, sample_rate = decode_wav(wav_bytes)
    except (OSError, RuntimeError, TypeError, ValueError) as exc:
        st.error(f"入力ファイルを読み込めませんでした: {exc}")
        st.stop()

    source_duration_sec = len(audio) / sample_rate
    _show_source_summary(wav_file.name, source_duration_sec, sample_rate, settings)
    _initialize_state(wav_file.name, wav_bytes)

    st.subheader("Basic Pitch検出設定")
    preset_keys = tuple(preset.key for preset in transcription_presets())
    preset_key = st.selectbox(
        "楽器プリセット",
        options=preset_keys,
        format_func=lambda key: get_transcription_preset(key).label,
        key="accuracy_preset_key",
        on_change=_apply_preset,
    )

    range_column, threshold_column, cleanup_column = st.columns(3)
    with range_column:
        min_options = list(range(20, 73))
        max_options = list(range(36, 97))
        min_midi = st.selectbox(
            "最低音",
            options=min_options,
            format_func=_midi_note_name,
            key="accuracy_min_midi",
        )
        max_midi = st.selectbox(
            "最高音",
            options=max_options,
            format_func=_midi_note_name,
            key="accuracy_max_midi",
        )
    with threshold_column:
        onset_threshold = st.slider(
            "オンセットしきい値",
            min_value=0.20,
            max_value=0.90,
            step=0.05,
            key="accuracy_onset_threshold",
            help="下げると弱い発音を拾いやすくなりますが、余分な音も増えます。",
        )
        frame_threshold = st.slider(
            "持続フレームしきい値",
            min_value=0.10,
            max_value=0.80,
            step=0.05,
            key="accuracy_frame_threshold",
            help="下げると音を長く保持しやすくなります。",
        )
    with cleanup_column:
        min_note_ms = st.slider(
            "最短音符",
            min_value=40,
            max_value=300,
            step=10,
            format="%d ms",
            key="accuracy_min_note_ms",
        )
        monophonic_path = st.checkbox(
            "単音メロディ経路を抽出",
            key="accuracy_monophonic_path",
            help=(
                "同時に出た倍音候補から、音長・強さ・前後の音程連続性を使って1本を選びます。"
            ),
        )
        melodia_trick = st.checkbox(
            "弱い持続音も探索",
            key="accuracy_melodia_trick",
            help="Basic Pitch公式のmelodia後処理です。通常はONで比較します。",
        )

    if min_midi >= max_midi:
        st.error("最低音は最高音より低くしてください。")
        st.stop()

    st.subheader("解析範囲")
    range_mode = st.radio(
        "処理量",
        options=_RANGE_MODES,
        horizontal=True,
        key="accuracy_range_mode",
    )
    extent = _select_extent(range_mode, source_duration_sec, settings)
    output_stem = _accuracy_output_stem(wav_file.name, extent)
    _show_extent(extent, output_stem)

    if not basic_pitch_available():
        st.stop()

    duration_sec = None if extent.is_full_track else extent.duration_sec
    request_key = _request_key(
        wav_bytes=wav_bytes,
        tempo_bytes=tempo_file.getvalue(),
        preset_key=preset_key,
        min_midi=min_midi,
        max_midi=max_midi,
        onset_threshold=onset_threshold,
        frame_threshold=frame_threshold,
        min_note_ms=float(min_note_ms),
        melodia_trick=melodia_trick,
        monophonic_path=monophonic_path,
        start_sec=extent.start_sec,
        duration_sec=duration_sec,
    )

    label = "全曲をBasic Pitchで解析" if extent.is_full_track else "比較区間をBasic Pitchで解析"
    if st.button(label, type="primary", use_container_width=True):
        spinner = (
            f"全曲 {_format_duration(source_duration_sec)} をBasic Pitchで解析しています…"
            if extent.is_full_track
            else "選択区間をBasic Pitchで解析しています…"
        )
        with st.spinner(spinner):
            try:
                run = run_basic_pitch(
                    wav_bytes,
                    min_midi=min_midi,
                    max_midi=max_midi,
                    onset_threshold=onset_threshold,
                    frame_threshold=frame_threshold,
                    min_note_ms=float(min_note_ms),
                    melodia_trick=melodia_trick,
                    monophonic_path=monophonic_path,
                    start_sec=extent.start_sec,
                    duration_sec=duration_sec,
                )
            except (RuntimeError, ValueError) as exc:
                st.error(f"Basic Pitchで解析できませんでした: {exc}")
            else:
                st.session_state.accuracy_run = run
                st.session_state.accuracy_request_key = request_key

    run = st.session_state.get("accuracy_run")
    if not isinstance(run, BasicPitchRun):
        st.stop()
    if st.session_state.get("accuracy_request_key") != request_key:
        st.warning("設定が変更されています。再解析するまで下の結果は旧設定です。")

    config = BasicPitchConfig(
        min_midi=min_midi,
        max_midi=max_midi,
        onset_threshold=onset_threshold,
        frame_threshold=frame_threshold,
        min_note_ms=float(min_note_ms),
        melodia_trick=melodia_trick,
        monophonic_path=monophonic_path,
    )
    _show_result(
        run=run,
        settings=settings,
        config=config,
        preset_key=preset_key,
        source_name=wav_file.name,
        wav_bytes=wav_bytes,
        sample_rate=sample_rate,
        source_duration_sec=source_duration_sec,
    )


def _select_extent(
    range_mode: str,
    source_duration_sec: float,
    settings: TempoProjectSettings,
) -> AnalysisExtent:
    if range_mode == "全曲":
        return calculate_analysis_extent(
            source_duration_sec=source_duration_sec,
            start_sec=0.0,
            requested_duration_sec=None,
        )

    requested = 30.0 if range_mode == "30秒で比較" else 60.0
    requested = min(requested, source_duration_sec)
    maximum_start = max(source_duration_sec - requested, 0.0)
    default_start = min(settings.first_beat_sec, maximum_start)
    current = min(
        max(float(st.session_state.get("accuracy_start_sec", default_start)), 0.0),
        maximum_start,
    )
    st.session_state.accuracy_start_sec = current
    start = st.slider(
        "比較開始位置",
        min_value=0.0,
        max_value=float(maximum_start),
        step=0.01,
        format="%.3f 秒",
        key="accuracy_start_sec",
    )
    if st.button("先頭拍へ戻す", use_container_width=True):
        st.session_state.accuracy_start_sec = default_start
        st.rerun()
    return calculate_analysis_extent(
        source_duration_sec=source_duration_sec,
        start_sec=start,
        requested_duration_sec=requested,
    )


def _show_extent(extent: AnalysisExtent, output_stem: str) -> None:
    columns = st.columns(4)
    columns[0].metric("解析開始", f"{extent.start_sec:.3f} 秒")
    columns[1].metric("解析終了", f"{extent.end_sec:.3f} 秒")
    columns[2].metric("解析時間", _format_duration(extent.duration_sec))
    columns[3].metric("音源に対する割合", f"{extent.coverage_fraction * 100:.1f}%")
    st.code(f"出力予定: {output_stem}.melody.mid", language=None)
    if extent.is_full_track:
        st.success("0秒から音源末尾まで100%解析します。")
    else:
        st.warning("比較用の部分解析です。全曲MIDIではありません。")


def _show_source_summary(
    source_name: str,
    duration_sec: float,
    sample_rate: int,
    settings: TempoProjectSettings,
) -> None:
    columns = st.columns(5)
    columns[0].metric("ステム長", _format_duration(duration_sec))
    columns[1].metric("サンプルレート", f"{sample_rate:,} Hz")
    columns[2].metric("体感テンポ", f"{settings.felt_bpm:.2f} BPM")
    columns[3].metric("内部グリッド", f"{settings.grid_bpm:.2f} BPM")
    columns[4].metric("先頭拍", f"{settings.first_beat_sec:.3f} 秒")
    if settings.duration_sec is not None:
        difference = duration_sec - settings.duration_sec
        if abs(difference) <= 0.05:
            st.success("tempo.jsonとステムの長さが一致しています。")
        else:
            st.warning(
                f"tempo.jsonの元音源と{source_name}の長さが{difference:+.3f}秒異なります。"
            )


def _show_result(
    *,
    run: BasicPitchRun,
    settings: TempoProjectSettings,
    config: BasicPitchConfig,
    preset_key: str,
    source_name: str,
    wav_bytes: bytes,
    sample_rate: int,
    source_duration_sec: float,
) -> None:
    st.subheader("精度検証結果")
    result = run.result
    raw_polyphony = maximum_polyphony(run.raw_notes)
    selected_polyphony = maximum_polyphony(result.notes)
    jumps = count_large_pitch_jumps(result.notes)
    longest_gap = longest_note_gap(
        result.notes,
        start_sec=result.analysis_start_sec,
        end_sec=result.analysis_end_sec,
    )
    columns = st.columns(6)
    columns[0].metric("Basic Pitch", run.backend_version)
    columns[1].metric("Raw候補", len(run.raw_notes))
    columns[2].metric("採用音符", len(result.notes))
    columns[3].metric("Raw最大同時音", raw_polyphony)
    columns[4].metric("発音カバー率", f"{result.voiced_fraction * 100:.1f}%")
    columns[5].metric("12半音以上の跳躍", jumps)

    if config.monophonic_path:
        st.success(
            f"単音経路を適用し、最大同時音を{raw_polyphony}音から{selected_polyphony}音へ整理しました。"
        )
    if jumps:
        st.warning("大きな音程跳躍があります。倍音またはオクターブ誤検出の候補です。")
    if longest_gap >= 10.0:
        st.warning(
            f"最長未検出区間は約{longest_gap:.1f}秒です。歌唱区間なら検出漏れです。"
        )
    if not result.notes:
        st.error("音符を検出できませんでした。しきい値を下げるか、音域を広げてください。")
        return

    figure = plot_transcription(
        result,
        grid_bpm=settings.felt_bpm,
        first_beat_sec=settings.first_beat_sec,
    )
    st.pyplot(figure, use_container_width=True)
    plt.close(figure)

    rows = [_note_row(note) for note in result.notes]
    st.dataframe(rows, use_container_width=True, hide_index=True)

    preset = get_transcription_preset(preset_key)
    extent = calculate_analysis_extent(
        source_duration_sec=source_duration_sec,
        start_sec=result.analysis_start_sec,
        requested_duration_sec=result.analysis_end_sec - result.analysis_start_sec,
    )
    output_stem = _accuracy_output_stem(source_name, extent)
    selected_midi = render_raw_midi(
        result.notes,
        bpm=settings.felt_bpm,
        first_beat_sec=settings.first_beat_sec,
        track_name=f"{Path(source_name).stem} Basic Pitch Melody",
        program=preset.midi_program,
    )
    raw_midi = render_raw_midi(
        run.raw_notes,
        bpm=settings.felt_bpm,
        first_beat_sec=settings.first_beat_sec,
        track_name=f"{Path(source_name).stem} Basic Pitch Raw",
        program=preset.midi_program,
    )
    payload = _build_payload(
        run=run,
        settings=settings,
        config=config,
        preset_key=preset_key,
        source_name=source_name,
        wav_bytes=wav_bytes,
        sample_rate=sample_rate,
        source_duration_sec=source_duration_sec,
        extent=extent,
    )

    first, second, third = st.columns(3)
    first.download_button(
        "メロディMIDI",
        data=selected_midi,
        file_name=f"{output_stem}.melody.mid",
        mime="audio/midi",
        type="primary",
        use_container_width=True,
    )
    second.download_button(
        "Basic Pitch Raw MIDI",
        data=raw_midi,
        file_name=f"{output_stem}.raw.mid",
        mime="audio/midi",
        use_container_width=True,
    )
    third.download_button(
        "比較用JSON",
        data=json.dumps(payload, ensure_ascii=False, indent=2),
        file_name=f"{output_stem}.accuracy.json",
        mime="application/json",
        use_container_width=True,
    )
    st.caption(
        "MIDIの4/4テンポには体感BPMを使い、細かい内部グリッドBPMはJSONへ残します。"
    )


def _build_payload(
    *,
    run: BasicPitchRun,
    settings: TempoProjectSettings,
    config: BasicPitchConfig,
    preset_key: str,
    source_name: str,
    wav_bytes: bytes,
    sample_rate: int,
    source_duration_sec: float,
    extent: AnalysisExtent,
) -> dict[str, object]:
    preset = get_transcription_preset(preset_key)
    return {
        "schema_version": 3,
        "transcription_method": "spotify-basic-pitch",
        "transcription_backend_version": run.backend_version,
        "transcription_preset": preset.key,
        "transcription_preset_label": preset.label,
        "selection_mode": (
            "continuous-monophonic-path" if config.monophonic_path else "raw-polyphonic"
        ),
        "midi_program": preset.midi_program,
        "source_file": source_name,
        "source_sha256": hashlib.sha256(wav_bytes).hexdigest(),
        "sample_rate": sample_rate,
        "source_duration_sec": round(source_duration_sec, 6),
        "analysis_start_sec": round(extent.start_sec, 6),
        "analysis_end_sec": round(extent.end_sec, 6),
        "analyzed_fraction": round(extent.coverage_fraction, 6),
        "is_full_track": extent.is_full_track,
        "tempo": {
            "felt_bpm": settings.felt_bpm,
            "grid_multiplier": settings.grid_multiplier,
            "grid_bpm": settings.grid_bpm,
            "midi_bpm": settings.felt_bpm,
            "first_beat_sec": settings.first_beat_sec,
            "time_signature": "4/4",
        },
        "config": {
            "min_midi": config.min_midi,
            "max_midi": config.max_midi,
            "onset_threshold": config.onset_threshold,
            "frame_threshold": config.frame_threshold,
            "min_note_ms": config.min_note_ms,
            "melodia_trick": config.melodia_trick,
            "monophonic_path": config.monophonic_path,
        },
        "metrics": {
            "raw_note_count": len(run.raw_notes),
            "selected_note_count": len(run.result.notes),
            "raw_maximum_polyphony": maximum_polyphony(run.raw_notes),
            "selected_maximum_polyphony": maximum_polyphony(run.result.notes),
            "note_coverage_fraction": round(run.result.voiced_fraction, 6),
            "median_amplitude": round(run.result.median_confidence, 6),
            "large_pitch_jump_count": count_large_pitch_jumps(run.result.notes),
            "longest_note_gap_sec": round(
                longest_note_gap(
                    run.result.notes,
                    start_sec=extent.start_sec,
                    end_sec=extent.end_sec,
                ),
                6,
            ),
        },
        "notes": [_note_payload(note) for note in run.result.notes],
        "raw_notes": [_note_payload(note) for note in run.raw_notes],
    }


def _initialize_state(source_name: str, wav_bytes: bytes) -> None:
    source_key = f"{source_name}:{hashlib.sha256(wav_bytes).hexdigest()}"
    if st.session_state.get("accuracy_source_key") == source_key:
        return
    preset = suggest_transcription_preset(source_name)
    st.session_state.accuracy_source_key = source_key
    st.session_state.accuracy_preset_key = preset.key
    _set_preset_values(preset.key)


def _apply_preset() -> None:
    _set_preset_values(str(st.session_state.accuracy_preset_key))


def _set_preset_values(key: str) -> None:
    preset = get_transcription_preset(key)
    st.session_state.accuracy_min_midi = preset.min_midi
    st.session_state.accuracy_max_midi = preset.max_midi
    if key == "vocal":
        st.session_state.accuracy_onset_threshold = 0.45
        st.session_state.accuracy_frame_threshold = 0.25
        st.session_state.accuracy_min_note_ms = 80
    else:
        st.session_state.accuracy_onset_threshold = 0.50
        st.session_state.accuracy_frame_threshold = 0.30
        st.session_state.accuracy_min_note_ms = 100
    st.session_state.accuracy_monophonic_path = True
    st.session_state.accuracy_melodia_trick = True


def _accuracy_output_stem(source_name: str, extent: AnalysisExtent) -> str:
    source_stem = Path(source_name).stem
    extent_stem = build_output_stem(source_name, extent)
    suffix = extent_stem[len(source_stem) :]
    return f"{source_stem}.basic-pitch{suffix}"


def _note_row(note: NoteEvent) -> dict[str, object]:
    return {
        "note": _midi_note_name(note.pitch),
        "midi": note.pitch,
        "start_sec": round(note.start_sec, 3),
        "duration_sec": round(note.duration_sec, 3),
        "velocity": note.velocity,
        "amplitude": round(note.confidence, 3),
    }


def _note_payload(note: NoteEvent) -> dict[str, object]:
    return {
        "start_sec": round(note.start_sec, 6),
        "end_sec": round(note.end_sec, 6),
        "pitch": note.pitch,
        "velocity": note.velocity,
        "amplitude": round(note.confidence, 6),
    }


def _request_key(**values: object) -> str:
    digest = hashlib.sha256()
    for key in sorted(values):
        digest.update(key.encode("utf-8"))
        value = values[key]
        digest.update(value if isinstance(value, bytes) else repr(value).encode("utf-8"))
    return digest.hexdigest()


def _midi_note_name(note: int) -> str:
    names = ("C", "C♯", "D", "D♯", "E", "F", "F♯", "G", "G♯", "A", "A♯", "B")
    return f"{names[note % 12]}{note // 12 - 1} ({note})"


def _format_duration(seconds: float) -> str:
    total_seconds = max(round(seconds), 0)
    minutes, remaining = divmod(total_seconds, 60)
    return f"{minutes}:{remaining:02d}"


if __name__ == "__main__":
    main()
