# Stem to MIDI

Sunoなどで分離したWAVステムを、編集可能なMIDIへ変換するためのローカルツールです。

最初のバージョンは **Tempo Lab** に限定しています。WAVからテンポと拍位置を解析し、音源を聴きながら固定テンポのBPMと先頭拍位置を調整して、後工程で再利用できるJSONを保存します。

## 現在できること

- WAVファイルの読み込み
- BPMと拍位置の自動検出
- 波形上への検出拍・補正後グリッド表示
- BPMの手入力、半分・倍テンポ補正
- 先頭拍位置の10ms／50ms単位調整
- 元音源とクリック付きプレビューの比較再生
- 解析結果と補正後拍グリッドのJSON出力

現時点では固定テンポ向けです。Sunoの「Follow tempo changes」に対応する可変テンポマップ編集とAudio-to-MIDI変換は次段階です。

## セットアップ

Python 3.11以上を使用します。

```bash
python -m venv .venv
source .venv/bin/activate  # Windows: .venv\\Scripts\\activate
pip install -e ".[dev]"
```

## 起動

```bash
streamlit run app.py
```

ブラウザでWAVを選択し、クリック付きプレビューを聴きながらBPMと先頭拍位置を調整します。

## テスト

```bash
pytest
ruff check .
```

## 予定

1. Fixed版とFollow版の解析比較
2. 可変テンポの拍マップ表示
3. Basic PitchによるRaw MIDI生成
4. 楽器別クリーニングと量子化
5. Clean MIDI出力

## データ管理

音源や生成物はGitへコミットしません。ローカルでは次のような構成を推奨します。

```text
workspace/
├─ input/
│  └─ song-name/
│     ├─ fixed/
│     └─ follow/
└─ output/
```
