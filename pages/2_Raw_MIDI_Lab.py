from __future__ import annotations

import hashlib
import json
from pathlib import Path

import matplotlib.pyplot as plt
import numpy as np
import streamlit as st

from stem_to_midi.midi_export import render_raw_midi
from stem_to_midi.preview import render_wav_segment
from stem_to_midi.project import TempoProjectSettings, parse_tempo_project
from stem_to_midi.tempo import load_wav_bytes
from stem_to_midi.transcription import (
    TranscriptionConfig,
    TranscriptionResult,
    transcribe_monophonic,
)
from stem_to_midi.transcription_plot import plot_transcription

st.set_page_config(page_title="Stem to MIDI — Raw MIDI Lab", page_icon="🎸", layout="wide")


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
    st.title("Raw MIDI Lab — Bass spike")
    st.caption(
        "ベースなど単音中心のステムをpYINで追跡し、無量子化のRaw MIDIとして出力します。"
    )
    st.info(
        "最初は30秒区間で精度を確認してください。良ければ全曲へ広げます。"
        "この段階では音符を拍グリッドへ丸めません。"
    )

    wav_file = st.file_uploader("音高ステムWAV（まずはBass推奨）", type=["wav"])
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

    duration_sec = len(audio) / sample_rate
    _show_source_summary(wav_file.name, duration_sec, sample_rate, settings)

    st.subheader("検出設定")
    range_column, confidence_column, cleanup_column = st.columns(3)
    with range_column:
        min_options = list(range(20, 61))
        max_options = list(range(36, 85))
        min_midi = st.selectbox(
            "最低音",
            options=min_options,
            index=min_options.index(28),
            format_func=_midi_note_name,
        )
        max_midi = st.selectbox(
            "最高音",
            options=max_options,
            index=max_options.index(60),
            format_func=_midi_note_name,
        )
    with confidence_column:
        voicing_threshold = st.slider(
            "有声音の確信度",
            min_value=0.30,
            max_value=0.95,
            value=0.60,
            step=0.05,
            help="高くすると誤検出は減りますが、弱い音を落としやすくなります。",
        )
        onset_split = st.checkbox(
            "同じ音程の再アタックを分割",
            value=True,
            help="同じ音を弾き直した箇所を、オンセット検出で別音符にします。",
        )
    with cleanup_column:
        min_note_ms = st.slider(
            "最短音符",
            min_value=40,
            max_value=300,
            value=90,
            step=10,
            format="%d ms",
        )
        max_gap_ms = st.slider(
            "同音内で埋める無音",
            min_value=0,
            max_value=200,
            value=60,
            step=10,
            format="%d ms",
        )

    if min_midi >= max_midi:
        st.error("最低音は最高音より低くしてください。")
        st.stop()

    st.subheader("解析範囲")
    range_mode = st.radio(
        "処理量",
        options=("30秒で検証", "60秒で検証", "全曲"),
        horizontal=True,
    )
    if range_mode == "全曲":
        analysis_start = 0.0
        analysis_duration: float | None = None
        st.caption(
            f"全曲 {_format_duration(duration_sec)} を解析します。数分かかる場合があります。"
        )
    else:
        selected_duration = 30.0 if range_mode == "30秒で検証" else 60.0
        selected_duration = min(selected_duration, duration_sec)
        max_start = max(duration_sec - selected_duration, 0.0)
        current_start = min(
            float(st.session_state.get("raw_midi_start", 0.0)),
            float(max_start),
        )
        st.session_state.raw_midi_start = current_start
        analysis_start = st.slider(
            "開始位置",
            min_value=0.0,
            max_value=float(max_start),
            step=0.1,
            key="raw_midi_start",
        )
        analysis_duration = selected_duration
        preview = render_wav_segment(audio, sample_rate, analysis_start, selected_duration)
        st.audio(preview, format="audio/wav")

    request_key = _request_key(
        wav_bytes=wav_bytes,
        tempo_bytes=tempo_file.getvalue(),
        min_midi=min_midi,
        max_midi=max_midi,
        voicing_threshold=voicing_threshold,
        min_note_ms=float(min_note_ms),
        max_gap_ms=float(max_gap_ms),
        onset_split=onset_split,
        start_sec=analysis_start,
        duration_sec=analysis_duration,
    )

    if st.button("Raw MIDIを生成", type="primary", use_container_width=True):
        with st.spinner("pYINで音高を追跡しています…"):
            try:
                result = run_transcription(
                    wav_bytes,
                    min_midi=min_midi,
                    max_midi=max_midi,
                    voicing_threshold=voicing_threshold,
                    min_note_ms=float(min_note_ms),
                    max_gap_ms=float(max_gap_ms),
                    onset_split=onset_split,
                    start_sec=analysis_start,
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
        st.warning("設定が変更されています。現在の結果は変更前のものです。再生成してください。")

    config = TranscriptionConfig(
        min_midi=min_midi,
        max_midi=max_midi,
        voicing_threshold=voicing_threshold,
        min_note_ms=float(min_note_ms),
        max_gap_ms=float(max_gap_ms),
        onset_split=onset_split,
    )
    _show_result(result, settings, config, wav_file.name, wav_bytes, sample_rate)


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
    result: TranscriptionResult,
    settings: TempoProjectSettings,
    config: TranscriptionConfig,
    source_name: str,
    wav_bytes: bytes,
    sample_rate: int,
) -> None:
    st.subheader("検証結果")
    durations = [note.duration_sec for note in result.notes]
    pitches = [note.pitch for note in result.notes]
    metrics = st.columns(4)
    metrics[0].metric("検出音符", len(result.notes))
    metrics[1].metric("有声音率", f"{result.voiced_fraction * 100:.1f}%")
    metrics[2].metric("中央確信度", f"{result.median_confidence:.2f}")
    metrics[3].metric(
        "中央音長",
        f"{np.median(durations) * 1_000:.0f} ms" if durations else "—",
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

    midi_bytes = render_raw_midi(
        result.notes,
        bpm=settings.grid_bpm,
        first_beat_sec=settings.first_beat_sec,
        track_name=f"{Path(source_name).stem} Raw",
    )
    notes_payload = _build_notes_payload(
        result=result,
        settings=settings,
        config=config,
        source_name=source_name,
        wav_bytes=wav_bytes,
        sample_rate=sample_rate,
    )
    stem = Path(source_name).stem
    left, right = st.columns(2)
    left.download_button(
        "Raw MIDIをダウンロード",
        data=midi_bytes,
        file_name=f"{stem}.raw.mid",
        mime="audio/midi",
        type="primary",
        use_container_width=True,
    )
    right.download_button(
        "検出ノートJSONをダウンロード",
        data=json.dumps(notes_payload, ensure_ascii=False, indent=2),
        file_name=f"{stem}.raw-notes.json",
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
        st.warning("設定した音域の端に音符があります。実音が切れていないか音域を広げて確認してください。")
    if result.voiced_fraction < 0.05:
        st.warning("有声音率が非常に低いです。解析区間にベース演奏があるか確認してください。")


def _build_notes_payload(
    *,
    result: TranscriptionResult,
    settings: TempoProjectSettings,
    config: TranscriptionConfig,
    source_name: str,
    wav_bytes: bytes,
    sample_rate: int,
) -> dict[str, object]:
    return {
        "schema_version": 1,
        "transcription_method": "librosa.pyin-monophonic",
        "source_file": source_name,
        "source_sha256": hashlib.sha256(wav_bytes).hexdigest(),
        "sample_rate": sample_rate,
        "analysis_start_sec": round(result.analysis_start_sec, 6),
        "analysis_end_sec": round(result.analysis_end_sec, 6),
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


if __name__ == "__main__":
    main()
