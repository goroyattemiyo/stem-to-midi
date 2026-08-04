from __future__ import annotations

import hashlib
import json
from pathlib import Path

import matplotlib.pyplot as plt
import streamlit as st

from stem_to_midi.plotting import plot_waveform_with_beats
from stem_to_midi.preview import render_click_preview, render_wav_segment
from stem_to_midi.tempo import (
    analyze_tempo,
    generate_fixed_beat_times,
    load_wav_bytes,
    TempoAnalysis,
)


st.set_page_config(page_title="Stem to MIDI — Tempo Lab", page_icon="🎵", layout="wide")


@st.cache_data(show_spinner=False)
def decode_and_analyze(wav_bytes: bytes) -> tuple[object, int, TempoAnalysis]:
    audio, sample_rate = load_wav_bytes(wav_bytes)
    analysis = analyze_tempo(audio, sample_rate)
    return audio, sample_rate, analysis


def main() -> None:
    st.title("Stem to MIDI — Tempo Lab")
    st.caption("WAVを解析し、聴きながら固定テンポの拍グリッドを調整します。")

    uploaded = st.file_uploader("WAVファイル", type=["wav"])
    if uploaded is None:
        st.info("SunoからダウンロードしたドラムまたはミックスのWAVを選択してください。")
        return

    wav_bytes = uploaded.getvalue()
    source_digest = hashlib.sha256(wav_bytes).hexdigest()

    try:
        with st.spinner("テンポと拍位置を解析しています…"):
            audio, sample_rate, analysis = decode_and_analyze(wav_bytes)
    except (OSError, RuntimeError, ValueError) as exc:
        st.error(f"WAVを解析できませんでした: {exc}")
        return

    _initialize_state(source_digest, analysis)

    metrics = st.columns(4)
    metrics[0].metric("長さ", _format_duration(analysis.duration_sec))
    metrics[1].metric("サンプルレート", f"{sample_rate:,} Hz")
    metrics[2].metric("検出BPM", f"{analysis.detected_bpm:.2f}")
    metrics[3].metric("検出拍数", len(analysis.detected_beat_times_sec))

    st.subheader("テンポ補正")
    bpm_column, bpm_buttons = st.columns([2, 1])
    with bpm_column:
        st.number_input(
            "BPM",
            min_value=20.0,
            max_value=400.0,
            step=0.1,
            format="%.2f",
            key="corrected_bpm",
        )
    with bpm_buttons:
        st.write("候補補正")
        left, right = st.columns(2)
        left.button("÷2", use_container_width=True, on_click=_scale_bpm, args=(0.5,))
        right.button("×2", use_container_width=True, on_click=_scale_bpm, args=(2.0,))

    offset_column, offset_buttons = st.columns([2, 2])
    with offset_column:
        st.number_input(
            "先頭の拍位置（秒）",
            min_value=0.0,
            max_value=max(float(analysis.duration_sec), 0.01),
            step=0.01,
            format="%.3f",
            key="first_beat_sec",
        )
    with offset_buttons:
        st.write("位置補正")
        buttons = st.columns(4)
        for column, label, delta in zip(
            buttons,
            ("−50ms", "−10ms", "+10ms", "+50ms"),
            (-0.05, -0.01, 0.01, 0.05),
            strict=True,
        ):
            column.button(
                label,
                use_container_width=True,
                on_click=_shift_first_beat,
                args=(delta, analysis.duration_sec),
            )

    adjusted_beats = generate_fixed_beat_times(
        float(st.session_state.corrected_bpm),
        float(st.session_state.first_beat_sec),
        analysis.duration_sec,
    )

    st.subheader("確認")
    preview_duration = st.select_slider(
        "確認区間の長さ",
        options=[5, 10, 15, 30],
        value=15,
        format_func=lambda value: f"{value}秒",
    )
    max_start = max(analysis.duration_sec - preview_duration, 0.0)
    if max_start <= 0.0:
        preview_start = 0.0
        st.session_state.preview_start = 0.0
        st.caption("音源が確認区間より短いため、先頭から再生します。")
    else:
        st.session_state.preview_start = min(
            float(st.session_state.get("preview_start", 0.0)),
            float(max_start),
        )
        preview_start = st.slider(
            "確認開始位置",
            min_value=0.0,
            max_value=float(max_start),
            step=0.1,
            key="preview_start",
        )

    figure = plot_waveform_with_beats(
        audio=audio,
        sample_rate=sample_rate,
        start_sec=preview_start,
        duration_sec=float(preview_duration),
        detected_beats_sec=analysis.detected_beat_times_sec,
        adjusted_beats_sec=adjusted_beats,
    )
    st.pyplot(figure, use_container_width=True)
    plt.close(figure)

    original_preview = render_wav_segment(
        audio,
        sample_rate,
        preview_start,
        float(preview_duration),
    )
    click_preview = render_click_preview(
        audio,
        sample_rate,
        adjusted_beats,
        preview_start,
        float(preview_duration),
    )

    original_column, click_column = st.columns(2)
    with original_column:
        st.markdown("**元音源**")
        st.audio(original_preview, format="audio/wav")
    with click_column:
        st.markdown("**クリック付き**")
        st.audio(click_preview, format="audio/wav")

    payload = {
        "source_file": uploaded.name,
        "source_sha256": source_digest,
        "duration_sec": round(analysis.duration_sec, 6),
        "sample_rate": sample_rate,
        "tempo_mode": "fixed",
        "detected_bpm": round(analysis.detected_bpm, 6),
        "corrected_bpm": round(float(st.session_state.corrected_bpm), 6),
        "detected_first_beat_sec": (
            round(analysis.detected_beat_times_sec[0], 6)
            if analysis.detected_beat_times_sec
            else None
        ),
        "corrected_first_beat_sec": round(float(st.session_state.first_beat_sec), 6),
        "detected_beat_times_sec": [
            round(value, 6) for value in analysis.detected_beat_times_sec
        ],
        "corrected_beat_times_sec": [round(value, 6) for value in adjusted_beats],
    }
    output_name = f"{Path(uploaded.name).stem}.tempo.json"
    st.download_button(
        "解析結果JSONをダウンロード",
        data=json.dumps(payload, ensure_ascii=False, indent=2),
        file_name=output_name,
        mime="application/json",
        type="primary",
    )

    st.caption(
        "この初期版は固定テンポの調整に限定しています。Follow tempo changesのテンポマップ編集は次段階です。"
    )


def _initialize_state(source_digest: str, analysis: TempoAnalysis) -> None:
    if st.session_state.get("source_digest") == source_digest:
        return

    fallback_bpm = analysis.detected_bpm if analysis.detected_bpm > 0 else 120.0
    first_beat = analysis.detected_beat_times_sec[0] if analysis.detected_beat_times_sec else 0.0
    st.session_state.source_digest = source_digest
    st.session_state.corrected_bpm = float(fallback_bpm)
    st.session_state.first_beat_sec = float(first_beat)
    st.session_state.preview_start = 0.0


def _scale_bpm(factor: float) -> None:
    current = float(st.session_state.corrected_bpm)
    st.session_state.corrected_bpm = min(max(current * factor, 20.0), 400.0)


def _shift_first_beat(delta_sec: float, duration_sec: float) -> None:
    current = float(st.session_state.first_beat_sec)
    st.session_state.first_beat_sec = min(max(current + delta_sec, 0.0), duration_sec)


def _format_duration(seconds: float) -> str:
    total_seconds = max(round(seconds), 0)
    minutes, remaining = divmod(total_seconds, 60)
    return f"{minutes}:{remaining:02d}"


if __name__ == "__main__":
    main()
