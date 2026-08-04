from __future__ import annotations

import hashlib
import json
from pathlib import Path

import matplotlib.pyplot as plt
import streamlit as st

from stem_to_midi.alignment import generate_bar_times, snap_time_to_grid
from stem_to_midi.plotting import plot_waveform_with_beats
from stem_to_midi.preview import render_click_preview, render_wav_segment
from stem_to_midi.project import (
    SourceMatch,
    TempoProjectSettings,
    evaluate_source_match,
    parse_tempo_project,
)
from stem_to_midi.tempo import (
    TempoAnalysis,
    analyze_tempo,
    calculate_grid_diagnostics,
    generate_fixed_beat_times,
    load_wav_bytes,
)

st.set_page_config(page_title="Stem to MIDI — Tempo Lab", page_icon="🎵", layout="wide")

_GRID_MULTIPLIERS = (1, 2)


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
    _render_project_import(
        source_digest=source_digest,
        source_file=uploaded.name,
        duration_sec=analysis.duration_sec,
    )

    metrics = st.columns(4)
    metrics[0].metric("長さ", _format_duration(analysis.duration_sec))
    metrics[1].metric("サンプルレート", f"{sample_rate:,} Hz")
    metrics[2].metric("検出BPM", f"{analysis.detected_bpm:.2f}")
    metrics[3].metric("検出拍数", len(analysis.detected_beat_times_sec))

    st.subheader("テンポ補正")
    bpm_column, multiplier_column, bpm_buttons = st.columns([2, 2, 1])
    with bpm_column:
        st.number_input(
            "体感テンポ（BPM）",
            min_value=20.0,
            max_value=400.0,
            step=0.1,
            format="%.2f",
            key="felt_bpm",
        )
    with multiplier_column:
        st.selectbox(
            "内部グリッド倍率",
            options=_GRID_MULTIPLIERS,
            format_func=lambda value: f"×{value}",
            key="grid_multiplier",
            help="MIDI量子化用の細かさです。ハーフタイム曲では×2が便利です。",
        )
    with bpm_buttons:
        st.write("体感補正")
        left, right = st.columns(2)
        left.button(
            "÷2",
            use_container_width=True,
            on_click=_scale_felt_bpm,
            args=(0.5,),
            help="内部グリッドをなるべく維持したまま体感テンポを半分にします。",
        )
        right.button(
            "×2",
            use_container_width=True,
            on_click=_scale_felt_bpm,
            args=(2.0,),
            help="内部グリッドをなるべく維持したまま体感テンポを倍にします。",
        )

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

    felt_bpm = float(st.session_state.felt_bpm)
    grid_multiplier = int(st.session_state.grid_multiplier)
    grid_bpm = felt_bpm * grid_multiplier
    first_beat_sec = float(st.session_state.first_beat_sec)

    felt_beats = generate_fixed_beat_times(felt_bpm, first_beat_sec, analysis.duration_sec)
    grid_beats = generate_fixed_beat_times(grid_bpm, first_beat_sec, analysis.duration_sec)
    bar_starts = generate_bar_times(first_beat_sec, felt_bpm, analysis.duration_sec)
    diagnostics = calculate_grid_diagnostics(
        duration_sec=analysis.duration_sec,
        first_beat_sec=first_beat_sec,
        detected_beats_sec=analysis.detected_beat_times_sec,
    )

    tempo_metrics = st.columns(4)
    tempo_metrics[0].metric("体感テンポ", f"{felt_bpm:.2f} BPM")
    tempo_metrics[1].metric(
        "内部グリッド",
        f"{grid_bpm:.2f} BPM",
        delta=f"×{grid_multiplier}",
        delta_color="off",
    )
    tempo_metrics[2].metric(
        "先頭拍誤差",
        _format_offset_ms(diagnostics.first_beat_offset_sec),
    )
    tempo_metrics[3].metric(
        "検出終了後の余白",
        f"{diagnostics.detection_tail_sec:.2f} 秒",
    )
    st.caption(
        "先頭拍誤差は、補正した先頭拍と最寄りの自動検出拍との差です。"
        "内部グリッドは将来のMIDI量子化に使います。"
    )

    st.subheader("確認")
    click_mode = st.radio(
        "クリック音",
        options=("体感拍", "内部グリッド"),
        horizontal=True,
        help="体感拍で音楽的な脈を確認し、内部グリッドで量子化の細かさを確認します。",
    )
    preview_duration = st.select_slider(
        "確認区間の長さ",
        options=[5, 10, 15, 30],
        value=15,
        format_func=lambda value: f"{value}秒",
    )
    follow_first_beat = st.checkbox(
        "確認開始位置を先頭拍に合わせる",
        key="preview_follow_first_beat",
        help="先頭拍を動かすと、波形・元音源・クリック付き音源の開始位置も追従します。",
    )
    max_start = max(analysis.duration_sec - preview_duration, 0.0)
    if follow_first_beat:
        preview_start = min(first_beat_sec, analysis.duration_sec)
        st.session_state.preview_start = preview_start
        st.success(
            f"確認開始 {preview_start:.3f}秒 = 先頭拍。"
            "再生直後の高いクリックが1小節目の頭です。"
        )
    elif max_start <= 0.0:
        preview_start = 0.0
        st.session_state.preview_start = 0.0
        st.caption("音源が確認区間より短いため、先頭から再生します。")
    else:
        st.session_state.preview_start = min(
            float(st.session_state.get("preview_start", first_beat_sec)),
            float(max_start),
        )
        preview_start = st.slider(
            "確認開始位置",
            min_value=0.0,
            max_value=float(max_start),
            step=0.01,
            format="%.3f 秒",
            key="preview_start",
        )
        snap_columns = st.columns(2)
        snap_columns[0].button(
            "最寄りの体感拍へスナップ",
            use_container_width=True,
            on_click=_snap_preview_start,
            args=(first_beat_sec, felt_bpm, 1, max_start),
        )
        snap_columns[1].button(
            "最寄りの小節頭へスナップ",
            use_container_width=True,
            on_click=_snap_preview_start,
            args=(first_beat_sec, felt_bpm, 4, max_start),
        )

    figure = plot_waveform_with_beats(
        audio=audio,
        sample_rate=sample_rate,
        start_sec=preview_start,
        duration_sec=float(preview_duration),
        detected_beats_sec=analysis.detected_beat_times_sec,
        felt_beats_sec=felt_beats,
        grid_beats_sec=grid_beats,
    )
    st.pyplot(figure, use_container_width=True)
    plt.close(figure)

    original_preview = render_wav_segment(
        audio,
        sample_rate,
        preview_start,
        float(preview_duration),
    )
    preview_beats = felt_beats if click_mode == "体感拍" else grid_beats
    click_preview = render_click_preview(
        audio,
        sample_rate,
        preview_beats,
        preview_start,
        float(preview_duration),
        accent_times_sec=bar_starts,
    )

    original_column, click_column = st.columns(2)
    with original_column:
        st.markdown("**元音源**")
        st.audio(original_preview, format="audio/wav")
    with click_column:
        st.markdown(f"**クリック付き（{click_mode}／小節頭アクセント）**")
        st.audio(click_preview, format="audio/wav")

    payload = {
        "schema_version": 2,
        "source_file": uploaded.name,
        "source_sha256": source_digest,
        "duration_sec": round(analysis.duration_sec, 6),
        "sample_rate": sample_rate,
        "tempo_mode": "fixed",
        "detected_bpm": round(analysis.detected_bpm, 6),
        "felt_bpm": round(felt_bpm, 6),
        "grid_multiplier": grid_multiplier,
        "grid_bpm": round(grid_bpm, 6),
        "corrected_bpm": round(felt_bpm, 6),
        "detected_first_beat_sec": (
            round(analysis.detected_beat_times_sec[0], 6)
            if analysis.detected_beat_times_sec
            else None
        ),
        "nearest_detected_beat_sec": _round_optional(
            diagnostics.nearest_detected_beat_sec
        ),
        "first_beat_sec": round(first_beat_sec, 6),
        "corrected_first_beat_sec": round(first_beat_sec, 6),
        "first_beat_offset_ms": _round_optional(
            diagnostics.first_beat_offset_sec,
            multiplier=1_000.0,
        ),
        "detection_tail_sec": round(diagnostics.detection_tail_sec, 6),
        "detected_beat_times_sec": [
            round(value, 6) for value in analysis.detected_beat_times_sec
        ],
        "felt_beat_times_sec": [round(value, 6) for value in felt_beats],
        "grid_beat_times_sec": [round(value, 6) for value in grid_beats],
        "corrected_beat_times_sec": [round(value, 6) for value in felt_beats],
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
        "この版は固定テンポの調整に限定しています。"
        "Follow tempo changesのテンポマップ編集は次段階です。"
    )


def _render_project_import(
    *,
    source_digest: str,
    source_file: str,
    duration_sec: float,
) -> None:
    with st.expander("保存済みtempo.jsonから作業を再開", expanded=False):
        project_file = st.file_uploader(
            "tempo.json（任意）",
            type=["json"],
            key="tempo_project_file",
        )
        if project_file is None:
            st.caption("旧形式Version 1と現在のVersion 2に対応しています。")
            return

        try:
            settings = parse_tempo_project(project_file.getvalue())
        except (TypeError, ValueError) as exc:
            st.error(f"JSONを読み込めませんでした: {exc}")
            return

        source_match = evaluate_source_match(
            settings,
            source_sha256=source_digest,
            source_file=source_file,
            duration_sec=duration_sec,
        )
        _show_project_summary(settings, source_match)

        first_beat_valid = settings.first_beat_sec <= duration_sec
        if not first_beat_valid:
            st.error(
                "JSONの先頭拍位置が選択中のWAVの長さを超えています。"
                "この設定は適用できません。"
            )

        allow_mismatch = source_match.status != "mismatch"
        if source_match.status == "mismatch":
            allow_mismatch = st.checkbox(
                "WAVが一致しなくても、テンポ設定だけ適用する",
                key="allow_mismatched_project",
            )

        st.button(
            "JSONの設定を適用",
            type="primary",
            disabled=not first_beat_valid or not allow_mismatch,
            on_click=_apply_project_settings,
            args=(settings,),
        )

    applied_message = st.session_state.pop("project_applied_message", None)
    if applied_message:
        st.success(applied_message)


def _show_project_summary(
    settings: TempoProjectSettings,
    source_match: SourceMatch,
) -> None:
    if settings.schema_version == 1:
        st.info("Version 1のJSONをVersion 2の設定へ変換して読み込みました。")
    else:
        st.success("Version 2のJSONを読み込みました。")

    if source_match.status == "match":
        method = "SHA-256" if source_match.method == "sha256" else "ファイル名と長さ"
        st.success(f"選択中のWAVと一致しました（{method}）。")
    elif source_match.status == "mismatch":
        method = "SHA-256" if source_match.method == "sha256" else "ファイル名または長さ"
        st.warning(f"選択中のWAVと一致しません（{method}）。")
    else:
        st.warning("照合情報がないため、選択中のWAVとの一致を確認できません。")

    columns = st.columns(3)
    columns[0].metric("体感テンポ", f"{settings.felt_bpm:.2f} BPM")
    columns[1].metric(
        "内部グリッド",
        f"{settings.grid_bpm:.2f} BPM",
        delta=f"×{settings.grid_multiplier}",
        delta_color="off",
    )
    columns[2].metric("先頭拍", f"{settings.first_beat_sec:.3f} 秒")


def _apply_project_settings(settings: TempoProjectSettings) -> None:
    st.session_state.felt_bpm = float(settings.felt_bpm)
    st.session_state.grid_multiplier = int(settings.grid_multiplier)
    st.session_state.first_beat_sec = float(settings.first_beat_sec)
    st.session_state.preview_start = float(settings.first_beat_sec)
    st.session_state.preview_follow_first_beat = True
    st.session_state.project_applied_message = (
        f"JSONの設定を適用しました：{settings.felt_bpm:.2f} BPM、"
        f"内部グリッド×{settings.grid_multiplier}、先頭拍{settings.first_beat_sec:.3f}秒"
    )


def _initialize_state(source_digest: str, analysis: TempoAnalysis) -> None:
    fallback_bpm = analysis.detected_bpm if analysis.detected_bpm > 0 else 120.0
    first_detected = (
        analysis.detected_beat_times_sec[0] if analysis.detected_beat_times_sec else 0.0
    )

    if st.session_state.get("source_digest") == source_digest:
        if "felt_bpm" not in st.session_state:
            legacy_bpm = float(st.session_state.get("corrected_bpm", fallback_bpm))
            st.session_state.felt_bpm = legacy_bpm
            st.session_state.grid_multiplier = _infer_grid_multiplier(
                felt_bpm=legacy_bpm,
                detected_bpm=analysis.detected_bpm,
            )
        if "grid_multiplier" not in st.session_state:
            st.session_state.grid_multiplier = 1
        if "first_beat_sec" not in st.session_state:
            st.session_state.first_beat_sec = float(first_detected)
        if "preview_start" not in st.session_state:
            st.session_state.preview_start = float(first_detected)
        if "preview_follow_first_beat" not in st.session_state:
            st.session_state.preview_follow_first_beat = True
        return

    st.session_state.source_digest = source_digest
    st.session_state.felt_bpm = float(fallback_bpm)
    st.session_state.grid_multiplier = 1
    st.session_state.first_beat_sec = float(first_detected)
    st.session_state.preview_start = float(first_detected)
    st.session_state.preview_follow_first_beat = True


def _scale_felt_bpm(factor: float) -> None:
    current_felt = float(st.session_state.felt_bpm)
    current_multiplier = int(st.session_state.grid_multiplier)
    current_grid = current_felt * current_multiplier
    new_felt = min(max(current_felt * factor, 20.0), 400.0)

    st.session_state.felt_bpm = new_felt
    st.session_state.grid_multiplier = min(
        _GRID_MULTIPLIERS,
        key=lambda multiplier: abs(new_felt * multiplier - current_grid),
    )


def _shift_first_beat(delta_sec: float, duration_sec: float) -> None:
    current = float(st.session_state.first_beat_sec)
    st.session_state.first_beat_sec = min(max(current + delta_sec, 0.0), duration_sec)
    if bool(st.session_state.get("preview_follow_first_beat", True)):
        st.session_state.preview_start = st.session_state.first_beat_sec


def _snap_preview_start(
    first_beat_sec: float,
    bpm: float,
    beats_per_step: int,
    maximum_sec: float,
) -> None:
    current = float(st.session_state.get("preview_start", first_beat_sec))
    st.session_state.preview_start = snap_time_to_grid(
        current,
        first_beat_sec=first_beat_sec,
        bpm=bpm,
        beats_per_step=beats_per_step,
        maximum_sec=maximum_sec,
    )


def _infer_grid_multiplier(felt_bpm: float, detected_bpm: float) -> int:
    if felt_bpm <= 0 or detected_bpm <= 0:
        return 1
    return min(
        _GRID_MULTIPLIERS,
        key=lambda multiplier: abs(felt_bpm * multiplier - detected_bpm),
    )


def _format_offset_ms(offset_sec: float | None) -> str:
    if offset_sec is None:
        return "—"
    return f"{offset_sec * 1_000:+.0f} ms"


def _round_optional(
    value: float | None,
    multiplier: float = 1.0,
) -> float | None:
    if value is None:
        return None
    return round(value * multiplier, 6)


def _format_duration(seconds: float) -> str:
    total_seconds = max(round(seconds), 0)
    minutes, remaining = divmod(total_seconds, 60)
    return f"{minutes}:{remaining:02d}"


if __name__ == "__main__":
    main()
