from __future__ import annotations

import hashlib
import json
from pathlib import Path

import matplotlib.pyplot as plt
import numpy as np
import streamlit as st

from stem_to_midi.alignment import (
    generate_bar_times,
    maximum_bar_number,
    snap_time_to_grid,
    start_for_bar,
)
from stem_to_midi.analysis_plan import (
    AnalysisExtent,
    build_output_stem,
    calculate_analysis_extent,
    get_transcription_preset,
    suggest_transcription_preset,
    transcription_presets,
)
from stem_to_midi.midi_export import render_raw_midi
from stem_to_midi.preview import render_click_preview, render_wav_segment
from stem_to_midi.project import TempoProjectSettings, parse_tempo_project
from stem_to_midi.tempo import generate_fixed_beat_times, load_wav_bytes
from stem_to_midi.transcription import (
    TranscriptionConfig,
    TranscriptionResult,
    transcribe_monophonic,
)
from stem_to_midi.transcription_plot import plot_transcription

st.set_page_config(page_title="Stem to MIDI — Raw MIDI Lab", page_icon="🎙️", layout="wide")

_START_MODES = ("先頭拍", "小節頭", "自由位置")
_RANGE_MODES = ("30秒で検証", "60秒で検証", "全曲")


@st.cache_data(show_spinner=False)
def decode_wav(wav_bytes: bytes) -> tuple[np.ndarray, int]:
    return load_wav_bytes(wav_bytes)


@st.cache_data(show_spinner=False)
def run_transcription(
    wav_bytes: bytes,
    *,
    min_midi: int,
    max_midi: int,
    voicing_threshold: float,
    min_note_ms: float,
    max_gap_ms: float,
    onset_split: bool,
    start_sec: float,
    duration_sec: float | None,
) -> TranscriptionResult:
    audio, sample_rate = load_wav_bytes(wav_bytes)
    config = TranscriptionConfig(
        min_midi=min_midi,
        max_midi=max_midi,
        voicing_threshold=voicing_threshold,
        min_note_ms=min_note_ms,
        max_gap_ms=max_gap_ms,
        onset_split=onset_split,
    )
    return transcribe_monophonic(
        audio,
        sample_rate,
        config,
        start_sec=start_sec,
        duration_sec=duration_sec,
    )


def main() -> None:
    st.title("Raw MIDI Lab — 単音ステム採譜")
    st.caption(
        "ベース、ボーカル、単音リードをpYINで追跡し、無量子化のRaw MIDIとして出力します。"
    )
    st.info(
        "30秒／60秒は設定検証用です。曲全体のMIDIが必要なときは、必ず「全曲」を選んでください。"
    )

    wav_file = st.file_uploader("音高ステムWAV", type=["wav"])
    tempo_file = st.file_uploader("Tempo Labのtempo.json", type=["json"])
    if wav_file is None or tempo_file is None:
        st.stop()

    wav_bytes = wav_file.getvalue()
    try:
        settings = parse_tempo_project(tempo_file.getvalue())
    except (TypeError, ValueError) as exc:
        st.error(f"tempo.jsonを読み込めませんでした: {exc}")
        st.stop()

    try:
        audio, sample_rate = decode_wav(wav_bytes)
    except (OSError, RuntimeError, ValueError) as exc:
        st.error(f"WAVを読み込めませんでした: {exc}")
        st.stop()

    source_duration_sec = len(audio) / sample_rate
    _show_source_summary(wav_file.name, source_duration_sec, sample_rate, settings)
    _initialize_preset_state(wav_file.name, wav_bytes)

    st.subheader("検出設定")
    preset_options = tuple(preset.key for preset in transcription_presets())
    selected_preset_key = st.selectbox(
        "楽器プリセット",
        options=preset_options,
        format_func=lambda key: get_transcription_preset(key).label,
        key="raw_midi_preset_key",
        on_change=_apply_selected_preset,
        help="ファイル名にLead、Vocal、Voiceなどが含まれる場合はボーカル設定を初期選択します。",
    )
    preset = get_transcription_preset(selected_preset_key)
    st.caption(preset.description + " プリセット適用後も各値を手動調整できます。")

    range_column, confidence_column, cleanup_column = st.columns(3)
    with range_column:
        min_options = list(range(20, 73))
        max_options = list(range(36, 97))
        min_midi = st.selectbox(
            "最低音",
            options=min_options,
            format_func=_midi_note_name,
            key="raw_midi_min_midi",
        )
        max_midi = st.selectbox(
            "最高音",
            options=max_options,
            format_func=_midi_note_name,
            key="raw_midi_max_midi",
        )
    with confidence_column:
        voicing_threshold = st.slider(
            "有声音の確信度",
            min_value=0.30,
            max_value=0.95,
            step=0.05,
            key="raw_midi_voicing_threshold",
            help="低くすると弱い音を拾いやすくなりますが、分離ノイズも増えます。",
        )
        onset_split = st.checkbox(
            "同じ音程の再アタックを分割",
            key="raw_midi_onset_split",
            help="ベースでは有効、ビブラートを含むボーカルではOFFを初期値にしています。",
        )
    with cleanup_column:
        min_note_ms = st.slider(
            "最短音符",
            min_value=40,
            max_value=300,
            step=10,
            format="%d ms",
            key="raw_midi_min_note_ms",
        )
        max_gap_ms = st.slider(
            "同音内で埋める無音",
            min_value=0,
            max_value=200,
            step=10,
            format="%d ms",
            key="raw_midi_max_gap_ms",
        )

    if min_midi >= max_midi:
        st.error("最低音は最高音より低くしてください。")
        st.stop()

    st.subheader("解析範囲と同期確認")
    range_mode = st.radio(
        "処理量",
        options=_RANGE_MODES,
        horizontal=True,
        key="raw_midi_range_mode",
    )
    analysis_start, requested_duration, start_description = _select_analysis_range(
        range_mode=range_mode,
        source_duration_sec=source_duration_sec,
        settings=settings,
    )
    extent = calculate_analysis_extent(
        source_duration_sec=source_duration_sec,
        start_sec=analysis_start,
        requested_duration_sec=requested_duration,
    )
    if extent.duration_sec <= 0.0:
        st.error("選択した開始位置より後に解析できる音声がありません。")
        st.stop()

    output_stem = build_output_stem(wav_file.name, extent)
    _show_extent_summary(extent, start_description, output_stem)

    analysis_duration = None if extent.is_full_track else extent.duration_sec
    if not extent.is_full_track:
        _show_sync_preview(
            audio=audio,
            sample_rate=sample_rate,
            extent=extent,
            source_duration_sec=source_duration_sec,
            settings=settings,
        )

    request_key = _request_key(
        wav_bytes=wav_bytes,
        tempo_bytes=tempo_file.getvalue(),
        preset_key=selected_preset_key,
        midi_program=preset.midi_program,
        min_midi=min_midi,
        max_midi=max_midi,
        voicing_threshold=voicing_threshold,
        min_note_ms=float(min_note_ms),
        max_gap_ms=float(max_gap_ms),
        onset_split=onset_split,
        start_sec=extent.start_sec,
        duration_sec=analysis_duration,
    )

    button_label = "全曲のRaw MIDIを生成" if extent.is_full_track else "検証区間のRaw MIDIを生成"
    if st.button(button_label, type="primary", use_container_width=True):
        spinner_text = (
            f"全曲 {_format_duration(source_duration_sec)} をpYINで解析しています…"
            if extent.is_full_track
            else "選択区間をpYINで解析しています…"
        )
        with st.spinner(spinner_text):
            try:
                result = run_transcription(
                    wav_bytes,
                    min_midi=min_midi,
                    max_midi=max_midi,
                    voicing_threshold=voicing_threshold,
                    min_note_ms=float(min_note_ms),
                    max_gap_ms=float(max_gap_ms),
                    onset_split=onset_split,
                    start_sec=extent.start_sec,
                    duration_sec=analysis_duration,
                )
            except (RuntimeError, ValueError) as exc:
                st.error(f"音高を解析できませんでした: {exc}")
            else:
                st.session_state.raw_midi_result = result
                st.session_state.raw_midi_request_key = request_key

    result = st.session_state.get("raw_midi_result")
    if not isinstance(result, TranscriptionResult):
        st.stop()
    if st.session_state.get("raw_midi_request_key") != request_key:
        st.warning("設定または解析範囲が変更されています。再生成するまで下の結果は旧設定です。")

    config = TranscriptionConfig(
        min_midi=min_midi,
        max_midi=max_midi,
        voicing_threshold=voicing_threshold,
        min_note_ms=float(min_note_ms),
        max_gap_ms=float(max_gap_ms),
        onset_split=onset_split,
    )
    _show_result(
        result=result,
        settings=settings,
        config=config,
        source_name=wav_file.name,
        wav_bytes=wav_bytes,
        sample_rate=sample_rate,
        source_duration_sec=source_duration_sec,
        preset_key=selected_preset_key,
    )


def _select_analysis_range(
    *,
    range_mode: str,
    source_duration_sec: float,
    settings: TempoProjectSettings,
) -> tuple[float, float | None, str]:
    if range_mode == "全曲":
        st.success(
            f"全曲モード：0.000秒から{source_duration_sec:.3f}秒まで、音源の100%を解析します。"
        )
        st.caption("イントロの無音も含めて絶対時刻を保つため、解析開始は必ず0秒です。")
        return 0.0, None, "音源先頭（全曲）"

    selected_duration = 30.0 if range_mode == "30秒で検証" else 60.0
    selected_duration = min(selected_duration, source_duration_sec)
    start_mode = st.radio(
        "開始位置の合わせ方",
        options=_START_MODES,
        horizontal=True,
        key="raw_midi_start_mode",
        help="解析、音声プレビュー、クリック、ピアノロールが同じ絶対時刻から始まります。",
    )
    max_start = max(source_duration_sec - selected_duration, 0.0)

    if start_mode == "先頭拍":
        analysis_start = min(settings.first_beat_sec, max_start)
        st.session_state.raw_midi_start = analysis_start
        return analysis_start, selected_duration, "先頭拍（1小節目）"

    if start_mode == "小節頭":
        max_bar = maximum_bar_number(
            first_beat_sec=settings.first_beat_sec,
            bpm=settings.felt_bpm,
            duration_sec=source_duration_sec,
            clip_duration_sec=selected_duration,
        )
        current_bar = min(
            max(int(st.session_state.get("raw_midi_bar_number", 1)), 1),
            max_bar,
        )
        st.session_state.raw_midi_bar_number = current_bar
        bar_number = st.number_input(
            "開始小節",
            min_value=1,
            max_value=max_bar,
            step=1,
            key="raw_midi_bar_number",
        )
        analysis_start = min(
            start_for_bar(settings.first_beat_sec, settings.felt_bpm, int(bar_number)),
            max_start,
        )
        st.session_state.raw_midi_start = analysis_start
        return analysis_start, selected_duration, f"{int(bar_number)}小節目の頭"

    current_start = min(
        max(float(st.session_state.get("raw_midi_start", settings.first_beat_sec)), 0.0),
        float(max_start),
    )
    st.session_state.raw_midi_start = current_start
    analysis_start = st.slider(
        "自由な開始位置",
        min_value=0.0,
        max_value=float(max_start),
        step=0.01,
        format="%.3f 秒",
        key="raw_midi_start",
    )
    snap_columns = st.columns(2)
    snap_columns[0].button(
        "最寄りの体感拍へスナップ",
        use_container_width=True,
        on_click=_snap_raw_start,
        args=(settings.first_beat_sec, settings.felt_bpm, 1, max_start),
    )
    snap_columns[1].button(
        "最寄りの小節頭へスナップ",
        use_container_width=True,
        on_click=_snap_raw_start,
        args=(settings.first_beat_sec, settings.felt_bpm, 4, max_start),
    )
    return analysis_start, selected_duration, "自由位置"


def _show_extent_summary(
    extent: AnalysisExtent,
    start_description: str,
    output_stem: str,
) -> None:
    columns = st.columns(5)
    columns[0].metric("解析開始", f"{extent.start_sec:.3f} 秒")
    columns[1].metric("解析終了", f"{extent.end_sec:.3f} 秒")
    columns[2].metric("解析時間", _format_duration_precise(extent.duration_sec))
    columns[3].metric("音源に対する割合", f"{extent.coverage_fraction * 100:.1f}%")
    columns[4].metric("開始基準", start_description)
    st.code(f"出力予定: {output_stem}.raw.mid", language=None)
    if extent.is_full_track:
        st.success("全曲解析として保存されます。ファイル名に `.full` が付きます。")
    else:
        st.warning(
            "これは設定確認用の部分解析です。4分の曲から30秒を選んだ場合、約12.5%しか含みません。"
        )


def _show_sync_preview(
    *,
    audio: np.ndarray,
    sample_rate: int,
    extent: AnalysisExtent,
    source_duration_sec: float,
    settings: TempoProjectSettings,
) -> None:
    nearest_beat = snap_time_to_grid(
        extent.start_sec,
        first_beat_sec=settings.first_beat_sec,
        bpm=settings.felt_bpm,
    )
    phase_offset_ms = (extent.start_sec - nearest_beat) * 1_000.0
    st.metric("体感拍との位相差", f"{phase_offset_ms:+.0f} ms")

    grid_beats = generate_fixed_beat_times(
        settings.grid_bpm,
        settings.first_beat_sec,
        source_duration_sec,
    )
    bar_starts = generate_bar_times(
        settings.first_beat_sec,
        settings.felt_bpm,
        source_duration_sec,
    )
    original_preview = render_wav_segment(
        audio,
        sample_rate,
        extent.start_sec,
        extent.duration_sec,
    )
    click_preview = render_click_preview(
        audio,
        sample_rate,
        grid_beats,
        extent.start_sec,
        extent.duration_sec,
        accent_times_sec=bar_starts,
    )
    original_column, click_column = st.columns(2)
    with original_column:
        st.markdown("**解析対象の元音源**")
        st.audio(original_preview, format="audio/wav")
    with click_column:
        st.markdown("**同じ開始位置のクリック付き音源**")
        st.audio(click_preview, format="audio/wav")
    st.caption("高いクリックは小節頭、低いクリックは内部グリッドです。")


def _show_source_summary(
    source_name: str,
    duration_sec: float,
    sample_rate: int,
    settings: TempoProjectSettings,
) -> None:
    metrics = st.columns(4)
    metrics[0].metric("ステム長", _format_duration(duration_sec))
    metrics[1].metric("サンプルレート", f"{sample_rate:,} Hz")
    metrics[2].metric("内部グリッド", f"{settings.grid_bpm:.2f} BPM")
    metrics[3].metric("先頭拍", f"{settings.first_beat_sec:.3f} 秒")

    if settings.duration_sec is None:
        st.warning("tempo.jsonに元音源の長さがないため、ステム位置の一致を確認できません。")
        return
    difference = duration_sec - settings.duration_sec
    if abs(difference) <= 0.05:
        st.success("tempo.jsonとステムの長さが一致しています。別ステムなのでSHA-256は比較しません。")
    else:
        st.warning(
            f"tempo.jsonの元音源と{source_name}の長さが{difference:+.3f}秒異なります。"
            "書き出し開始位置や末尾の無音が同じか確認してください。"
        )


def _show_result(
    *,
    result: TranscriptionResult,
    settings: TempoProjectSettings,
    config: TranscriptionConfig,
    source_name: str,
    wav_bytes: bytes,
    sample_rate: int,
    source_duration_sec: float,
    preset_key: str,
) -> None:
    st.subheader("検出結果")
    preset = get_transcription_preset(preset_key)
    extent = calculate_analysis_extent(
        source_duration_sec=source_duration_sec,
        start_sec=result.analysis_start_sec,
        requested_duration_sec=result.analysis_end_sec - result.analysis_start_sec,
    )
    durations = [note.duration_sec for note in result.notes]
    pitches = [note.pitch for note in result.notes]
    metrics = st.columns(5)
    metrics[0].metric("解析済み", f"{extent.coverage_fraction * 100:.1f}%")
    metrics[1].metric("検出音符", len(result.notes))
    metrics[2].metric("有声音率", f"{result.voiced_fraction * 100:.1f}%")
    metrics[3].metric("中央確信度", f"{result.median_confidence:.2f}")
    metrics[4].metric(
        "中央音長",
        f"{np.median(durations) * 1_000:.0f} ms" if durations else "—",
    )
    if extent.is_full_track:
        st.success(
            f"全曲結果です：{extent.start_sec:.3f}〜{extent.end_sec:.3f}秒を解析しました。"
        )
    else:
        st.warning(
            f"部分結果です：{extent.start_sec:.3f}〜{extent.end_sec:.3f}秒のみ。"
            "曲全体のメロディではありません。"
        )

    _show_quality_hints(result, config)
    figure = plot_transcription(
        result,
        grid_bpm=settings.grid_bpm,
        first_beat_sec=settings.first_beat_sec,
    )
    st.pyplot(figure, use_container_width=True)
    plt.close(figure)

    if result.notes:
        rows = [
            {
                "note": _midi_note_name(note.pitch),
                "midi": note.pitch,
                "start_sec": round(note.start_sec, 3),
                "duration_sec": round(note.duration_sec, 3),
                "velocity": note.velocity,
                "confidence": round(note.confidence, 3),
                "mean_pitch": round(note.mean_pitch, 3),
            }
            for note in result.notes
        ]
        st.dataframe(rows, use_container_width=True, hide_index=True)

    output_stem = build_output_stem(source_name, extent)
    midi_bytes = render_raw_midi(
        result.notes,
        bpm=settings.grid_bpm,
        first_beat_sec=settings.first_beat_sec,
        track_name=f"{Path(source_name).stem} {preset.label} Raw",
        program=preset.midi_program,
    )
    notes_payload = _build_notes_payload(
        result=result,
        settings=settings,
        config=config,
        source_name=source_name,
        wav_bytes=wav_bytes,
        sample_rate=sample_rate,
        source_duration_sec=source_duration_sec,
        preset_key=preset_key,
        extent=extent,
    )
    left, right = st.columns(2)
    left.download_button(
        "Raw MIDIをダウンロード",
        data=midi_bytes,
        file_name=f"{output_stem}.raw.mid",
        mime="audio/midi",
        type="primary",
        use_container_width=True,
    )
    right.download_button(
        "検出ノートJSONをダウンロード",
        data=json.dumps(notes_payload, ensure_ascii=False, indent=2),
        file_name=f"{output_stem}.raw-notes.json",
        mime="application/json",
        use_container_width=True,
    )

    if pitches:
        st.caption(
            f"検出音域: {_midi_note_name(min(pitches))}〜{_midi_note_name(max(pitches))}。"
            "次段階で量子化、同音結合、オクターブ補正を行います。"
        )


def _show_quality_hints(result: TranscriptionResult, config: TranscriptionConfig) -> None:
    if not result.notes:
        st.error("音符が検出されませんでした。音域を広げるか、確信度を下げてください。")
        return

    durations = np.array([note.duration_sec for note in result.notes], dtype=float)
    pitches = [note.pitch for note in result.notes]
    analyzed_duration = result.analysis_end_sec - result.analysis_start_sec
    notes_per_minute = len(result.notes) / max(analyzed_duration / 60.0, 1e-9)

    if result.median_confidence < 0.60:
        st.warning("中央確信度が低めです。分離ノイズや倍音を音程として拾っている可能性があります。")
    if np.median(durations) < 0.12 or notes_per_minute > 300:
        st.warning("音符が細切れの可能性があります。最短音符または無音補完を増やしてください。")
    if config.min_midi in pitches or config.max_midi in pitches:
        st.warning("設定音域の端に音符があります。実音が切れていないか音域を広げてください。")
    if result.voiced_fraction < 0.05:
        st.warning("有声音率が非常に低いです。解析区間に対象の演奏や歌唱があるか確認してください。")


def _build_notes_payload(
    *,
    result: TranscriptionResult,
    settings: TempoProjectSettings,
    config: TranscriptionConfig,
    source_name: str,
    wav_bytes: bytes,
    sample_rate: int,
    source_duration_sec: float,
    preset_key: str,
    extent: AnalysisExtent,
) -> dict[str, object]:
    preset = get_transcription_preset(preset_key)
    return {
        "schema_version": 2,
        "transcription_method": "librosa.pyin-monophonic",
        "transcription_preset": preset.key,
        "transcription_preset_label": preset.label,
        "midi_program": preset.midi_program,
        "source_file": source_name,
        "source_sha256": hashlib.sha256(wav_bytes).hexdigest(),
        "sample_rate": sample_rate,
        "source_duration_sec": round(source_duration_sec, 6),
        "analysis_start_sec": round(result.analysis_start_sec, 6),
        "analysis_end_sec": round(result.analysis_end_sec, 6),
        "analyzed_duration_sec": round(extent.duration_sec, 6),
        "analyzed_fraction": round(extent.coverage_fraction, 6),
        "is_full_track": extent.is_full_track,
        "tempo": {
            "felt_bpm": settings.felt_bpm,
            "grid_multiplier": settings.grid_multiplier,
            "grid_bpm": settings.grid_bpm,
            "first_beat_sec": settings.first_beat_sec,
            "time_signature": "4/4",
        },
        "config": {
            "min_midi": config.min_midi,
            "max_midi": config.max_midi,
            "voicing_threshold": config.voicing_threshold,
            "min_note_ms": config.min_note_ms,
            "max_gap_ms": config.max_gap_ms,
            "onset_split": config.onset_split,
        },
        "metrics": {
            "note_count": len(result.notes),
            "voiced_fraction": round(result.voiced_fraction, 6),
            "median_confidence": round(result.median_confidence, 6),
        },
        "notes": [
            {
                "start_sec": round(note.start_sec, 6),
                "end_sec": round(note.end_sec, 6),
                "pitch": note.pitch,
                "velocity": note.velocity,
                "confidence": round(note.confidence, 6),
                "mean_pitch": round(note.mean_pitch, 6),
            }
            for note in result.notes
        ],
    }


def _initialize_preset_state(source_name: str, wav_bytes: bytes) -> None:
    source_key = f"{source_name}:{hashlib.sha256(wav_bytes).hexdigest()}"
    if st.session_state.get("raw_midi_preset_source") == source_key:
        return
    suggested = suggest_transcription_preset(source_name)
    st.session_state.raw_midi_preset_source = source_key
    st.session_state.raw_midi_preset_key = suggested.key
    _set_preset_values(suggested.key)


def _apply_selected_preset() -> None:
    key = str(st.session_state.raw_midi_preset_key)
    _set_preset_values(key)


def _set_preset_values(key: str) -> None:
    preset = get_transcription_preset(key)
    st.session_state.raw_midi_min_midi = preset.min_midi
    st.session_state.raw_midi_max_midi = preset.max_midi
    st.session_state.raw_midi_voicing_threshold = preset.voicing_threshold
    st.session_state.raw_midi_min_note_ms = round(preset.min_note_ms)
    st.session_state.raw_midi_max_gap_ms = round(preset.max_gap_ms)
    st.session_state.raw_midi_onset_split = preset.onset_split


def _snap_raw_start(
    first_beat_sec: float,
    bpm: float,
    beats_per_step: int,
    maximum_sec: float,
) -> None:
    current = float(st.session_state.get("raw_midi_start", first_beat_sec))
    st.session_state.raw_midi_start = snap_time_to_grid(
        current,
        first_beat_sec=first_beat_sec,
        bpm=bpm,
        beats_per_step=beats_per_step,
        maximum_sec=maximum_sec,
    )


def _request_key(**values: object) -> str:
    digest = hashlib.sha256()
    for key in sorted(values):
        digest.update(key.encode("utf-8"))
        value = values[key]
        if isinstance(value, bytes):
            digest.update(value)
        else:
            digest.update(repr(value).encode("utf-8"))
    return digest.hexdigest()


def _midi_note_name(note: int) -> str:
    names = ("C", "C♯", "D", "D♯", "E", "F", "F♯", "G", "G♯", "A", "A♯", "B")
    return f"{names[note % 12]}{note // 12 - 1} ({note})"


def _format_duration(seconds: float) -> str:
    total_seconds = max(round(seconds), 0)
    minutes, remaining = divmod(total_seconds, 60)
    return f"{minutes}:{remaining:02d}"


def _format_duration_precise(seconds: float) -> str:
    if seconds < 60:
        return f"{seconds:.1f} 秒"
    return _format_duration(seconds)


if __name__ == "__main__":
    main()
