from __future__ import annotations

from pathlib import Path

import streamlit as st
import streamlit.components.v1 as components

from stem_to_midi.score_phase1 import (
    MidiInspection,
    PerformanceNote,
    ScoreNote,
    build_musicxml,
    extract_track_notes,
    inspect_midi,
    maximum_polyphony,
    midi_note_name,
    quantize_monophonic_notes,
    render_musicxml_page,
    score_statistics,
)

st.set_page_config(page_title="Stem to Score — Score Lab", page_icon="🎼", layout="wide")

_SUBDIVISIONS = {
    "4分音符まで": 4,
    "8分音符まで": 8,
    "16分音符まで": 16,
}
_STRATEGIES = {
    "最高音をメロディとして抽出": "highest",
    "最低音をベースとして抽出": "lowest",
    "最も強い音を優先": "loudest",
    "最も長い音を優先": "longest",
}
_CLEFS = {
    "ト音記号": "treble",
    "ヘ音記号": "bass",
}


@st.cache_data(show_spinner=False)
def _inspect(midi_bytes: bytes) -> MidiInspection:
    return inspect_midi(midi_bytes)


@st.cache_data(show_spinner=False)
def _compile_score(
    midi_bytes: bytes,
    *,
    track_index: int,
    subdivision: int,
    strategy: str,
    title: str,
    tempo_bpm: float,
    clef: str,
) -> tuple[tuple[PerformanceNote, ...], tuple[ScoreNote, ...], str]:
    performance_notes = extract_track_notes(midi_bytes, track_index)
    score_notes = quantize_monophonic_notes(
        performance_notes,
        subdivision=subdivision,
        strategy=strategy,
    )
    musicxml = build_musicxml(
        score_notes,
        title=title,
        tempo_bpm=tempo_bpm,
        clef=clef,
    )
    return performance_notes, score_notes, musicxml


@st.cache_data(show_spinner=False)
def _render_page(musicxml: str, page_number: int, scale: int) -> tuple[str, int, int]:
    rendered = render_musicxml_page(
        musicxml,
        page_number=page_number,
        scale=scale,
    )
    return rendered.svg, rendered.page_number, rendered.page_count


def main() -> None:
    st.title("Stem to Score — Score Lab")
    st.caption(
        "Phase 1: 外部MIDIを単旋律として整理し、MusicXMLと五線譜プレビューを生成します。"
    )

    uploaded = st.file_uploader(
        "MIDIファイル",
        type=["mid", "midi"],
        help="Basic Pitch、OpenMusic、DAWなどで作成した標準MIDIファイルを選択します。",
    )
    if uploaded is None:
        st.info("まずMIDIファイルを選択してください。")
        _render_phase_scope()
        return

    midi_bytes = uploaded.getvalue()
    try:
        inspection = _inspect(midi_bytes)
    except ValueError as exc:
        st.error(f"MIDIを読み込めませんでした: {exc}")
        return

    note_tracks = [track for track in inspection.tracks if track.note_count > 0]
    if not note_tracks:
        st.error("ノートイベントを含むトラックがありません。")
        return

    summary = st.columns(4)
    summary[0].metric("MIDI形式", f"Type {inspection.midi_type}")
    summary[1].metric("基準テンポ", f"{inspection.tempo_bpm:.2f} BPM")
    summary[2].metric("時間分解能", f"{inspection.ticks_per_beat} PPQ")
    summary[3].metric("ノートトラック", len(note_tracks))

    _render_source_warnings(inspection)

    st.subheader("楽譜化の設定")
    selected_track_index = st.selectbox(
        "使用するトラック",
        options=[track.index for track in note_tracks],
        format_func=lambda index: _format_track(inspection, index),
    )
    selected_track = inspection.tracks[selected_track_index]

    first_row = st.columns(4)
    with first_row[0]:
        title = st.text_input("曲名", value=Path(uploaded.name).stem)
    with first_row[1]:
        tempo_bpm = st.number_input(
            "楽譜テンポ（BPM）",
            min_value=20.0,
            max_value=400.0,
            value=float(round(inspection.tempo_bpm, 3)),
            step=0.1,
            format="%.2f",
        )
    with first_row[2]:
        subdivision_label = st.selectbox(
            "最大細分",
            options=list(_SUBDIVISIONS),
            index=2,
            help="Phase 1では選択した細分グリッドへ開始・終了位置を丸めます。",
        )
    with first_row[3]:
        default_clef_index = 1 if (selected_track.max_pitch or 127) < 60 else 0
        clef_label = st.selectbox(
            "音部記号",
            options=list(_CLEFS),
            index=default_clef_index,
        )

    second_row = st.columns([3, 1])
    with second_row[0]:
        strategy_label = st.selectbox(
            "多声音がある場合の単旋律抽出",
            options=list(_STRATEGIES),
            help="同時刻へ量子化された候補から、楽譜に残す1音を選びます。",
        )
    with second_row[1]:
        render_scale = st.slider(
            "プレビュー倍率",
            min_value=25,
            max_value=80,
            value=40,
            step=5,
        )

    try:
        with st.spinner("MIDIを楽譜用に整理しています…"):
            performance_notes, score_notes, musicxml = _compile_score(
                midi_bytes,
                track_index=selected_track_index,
                subdivision=_SUBDIVISIONS[subdivision_label],
                strategy=_STRATEGIES[strategy_label],
                title=title.strip() or Path(uploaded.name).stem,
                tempo_bpm=float(tempo_bpm),
                clef=_CLEFS[clef_label],
            )
    except ValueError as exc:
        st.error(f"楽譜を生成できませんでした: {exc}")
        return

    if not performance_notes:
        st.error("選択したトラックから完結したノートを抽出できませんでした。")
        return
    if not score_notes:
        st.error("量子化後に残るノートがありませんでした。")
        return

    raw_polyphony = maximum_polyphony(performance_notes)
    stats = score_statistics(score_notes)
    result_metrics = st.columns(5)
    result_metrics[0].metric("入力ノート", len(performance_notes))
    result_metrics[1].metric("楽譜ノート", int(stats["note_count"]))
    result_metrics[2].metric("最大同時音", raw_polyphony)
    result_metrics[3].metric("推定小節数", int(stats["measure_count"]))
    result_metrics[4].metric(
        "音域",
        f"{midi_note_name(int(stats['min_pitch']))}–{midi_note_name(int(stats['max_pitch']))}",
    )

    if raw_polyphony > 1:
        st.warning(
            "このトラックには同時発音があります。Phase 1では選択した規則で単旋律へ圧縮しています。"
        )

    st.subheader("五線譜プレビュー")
    requested_page = int(
        st.number_input(
            "表示ページ",
            min_value=1,
            max_value=999,
            value=1,
            step=1,
        )
    )

    try:
        with st.spinner("Verovioで楽譜を描画しています…"):
            svg, resolved_page, page_count = _render_page(
                musicxml,
                requested_page,
                render_scale,
            )
    except (RuntimeError, ValueError) as exc:
        st.error(f"楽譜プレビューを生成できませんでした: {exc}")
        st.code(r'.\.venv\Scripts\python.exe -m pip install -e ".[dev,accuracy]"')
    else:
        if requested_page > page_count:
            st.info(f"全{page_count}ページのため、最終ページを表示しています。")
        st.caption(f"{resolved_page} / {page_count} ページ")
        components.html(
            _wrap_svg(svg),
            height=920,
            scrolling=True,
        )

    output_stem = Path(uploaded.name).stem
    st.download_button(
        "MusicXMLをダウンロード",
        data=musicxml.encode("utf-8"),
        file_name=f"{output_stem}.phase1.score.musicxml",
        mime="application/vnd.recordare.musicxml+xml",
        type="primary",
    )

    with st.expander("生成したMusicXMLを確認"):
        st.code(musicxml, language="xml")

    _render_phase_scope()


def _format_track(inspection: MidiInspection, track_index: int) -> str:
    track = inspection.tracks[track_index]
    pitch_range = "音域なし"
    if track.min_pitch is not None and track.max_pitch is not None:
        pitch_range = f"{midi_note_name(track.min_pitch)}–{midi_note_name(track.max_pitch)}"
    channels = ", ".join(str(channel + 1) for channel in track.channels) or "なし"
    return (
        f"{track.index}: {track.name} / {track.note_count} notes / "
        f"{pitch_range} / Ch {channels}"
    )


def _render_source_warnings(inspection: MidiInspection) -> None:
    if inspection.tempo_change_count == 0:
        st.info("テンポイベントがないため、MIDI標準値の120 BPMを使用します。")
    elif inspection.tempo_change_count > 1:
        st.warning(
            f"テンポイベントが{inspection.tempo_change_count}個あります。"
            "Phase 1では最初のテンポだけを使用します。"
        )

    if inspection.time_signature != (4, 4):
        numerator, denominator = inspection.time_signature
        st.warning(
            f"元MIDIの先頭拍子は{numerator}/{denominator}です。"
            "Phase 1の出力は4/4として生成します。"
        )
    elif inspection.time_signature_change_count > 1:
        st.warning(
            f"拍子イベントが{inspection.time_signature_change_count}個あります。"
            "Phase 1では4/4固定です。"
        )


def _wrap_svg(svg: str) -> str:
    return f"""
<!doctype html>
<html>
<head>
<meta charset="utf-8">
<style>
html, body {{
  margin: 0;
  padding: 0;
  background: #ffffff;
}}
.score {{
  box-sizing: border-box;
  width: 100%;
  min-width: 720px;
  padding: 12px;
}}
.score svg {{
  display: block;
  width: 100%;
  height: auto;
}}
</style>
</head>
<body>
<div class="score">{svg}</div>
</body>
</html>
"""


def _render_phase_scope() -> None:
    with st.expander("Phase 1の対応範囲"):
        st.markdown(
            """
- 外部MIDIの1トラックを選択
- 固定テンポ
- 4/4
- 単旋律へ圧縮
- 最大4分、8分、16分の基本クオンタイズ
- 休符と小節をまたぐタイ
- MusicXML出力
- Verovioによる五線譜プレビュー

Score JSON、原音同期、候補比較、手動編集は次のPhaseで追加します。
"""
        )


if __name__ == "__main__":
    main()
