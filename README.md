# Stem to MIDI

Sunoなどで分離したWAVステムを、編集可能なMIDIへ変換するためのローカルツールです。

現在は、拍グリッドを確定する **Tempo Lab**、軽量な単音検出を行う **Raw MIDI Lab**、Spotify Basic Pitchで高精度候補を作る **Accuracy Lab** を実装しています。

## ドキュメント

- [開発ロードマップ](docs/ROADMAP.md): Clean MIDI、Score JSON、五線譜＋TAB編集UI、MusicXML／PDFまでの計画
- [開発記録](docs/DEVELOPMENT_LOG.md): 環境構築、PRごとの判断、実音源から得た検証履歴

## 現在できること

- WAVファイルの読み込み
- BPMと拍位置の自動検出
- 体感テンポとMIDI量子化用の内部グリッドを分けて調整
- 波形上への検出拍・体感拍・内部グリッド表示
- BPMの手入力、半分・倍テンポ補正
- 先頭拍位置の10ms／50ms単位調整
- 体感拍または内部グリッドを選んだクリック付きプレビュー
- 確認開始位置の先頭拍追従、拍・小節頭スナップ
- 保存済みtempo.jsonからの作業再開
- SHA-256、またはファイル名と長さによるWAV照合
- pYINによるベース・ボーカルなどの単音ステム追跡
- Spotify Basic Pitchによる多音対応の高精度候補生成
- 30秒／60秒区間での先行比較と全曲解析
- Basic PitchのRaw候補から連続性を重視した単音メロディ経路を抽出
- 最大同時音、発音カバー率、長い未検出区間、オクターブ級の跳躍を表示
- Raw MIDI、メロディMIDI、検証用JSONの出力

現時点では固定テンポ向けです。可変テンポマップ編集、Clean MIDI、楽器・声部分離、楽譜出力は次段階です。

## JSONから作業を再開

WAVを選択した後、「保存済みtempo.jsonから作業を再開」を開いてJSONを選択します。

読み込んだJSONから、次の編集状態を復元します。

- 体感テンポ
- 内部グリッド倍率
- 先頭拍位置

拍時刻の配列はJSONから直接復元せず、設定と現在のWAVの長さから再生成します。元WAVのSHA-256が一致しない場合は警告し、確認チェックを入れるまで適用しません。

## 体感テンポと内部グリッド

ハーフタイムに感じる曲では、体感テンポを72 BPM、内部グリッドを144 BPMのように分けられます。

- **体感テンポ**: 4/4の拍と小節を表す音楽的なテンポ
- **内部グリッド**: 八分音符や16分音符を量子化するための細かい処理グリッド

Accuracy LabのMIDIは4/4の体感テンポで書き出し、内部グリッドはJSONへ保持します。

## Raw MIDI Lab

サイドバーから「Raw MIDI Lab」を開き、音高ステムWAVとtempo.jsonを選びます。

pYINで1本の主要音程を追跡します。軽量で確信度を確認しやすい一方、多声音、倍音の強い歌声、分離ノイズでは音符が抜ける場合があります。

最初は30秒または60秒だけ解析し、問題が少なければ全曲へ切り替えます。出力は無量子化のRaw MIDIと検出ノートJSONです。

## Accuracy Lab

サイドバーから「Accuracy Lab」を開き、Raw MIDI Labと同じWAVとtempo.jsonを選びます。

Spotify Basic Pitchを使い、次の2種類を出力します。

- **Basic Pitch Raw MIDI**: モデルが検出した多声音候補を保持
- **メロディMIDI**: 音の長さ、強さ、前後の音程連続性から単音経路を選択

まず同じ30秒区間をpYIN版と比較してください。メロディMIDIで倍音誤検出が増える場合は、音域、オンセットしきい値、持続フレームしきい値、最短音符を調整します。

Basic Pitchは任意依存です。通常セットアップ後、次を追加実行します。

```powershell
.\.venv\Scripts\python.exe -m pip install -e ".[accuracy]"
```

インストール後はStreamlitを停止し、再起動してください。

## セットアップ

Python 3.11を推奨します。

```bash
python -m venv .venv
source .venv/bin/activate  # Windows: .venv\\Scripts\\activate
pip install -e ".[dev]"
```

WindowsでAccuracy Labも使う場合:

```powershell
.\.venv\Scripts\python.exe -m pip install -e ".[dev,accuracy]"
```

## 起動

```bash
streamlit run app.py
```

Windowsでは次でも起動できます。

```powershell
.\.venv\Scripts\python.exe -m streamlit run app.py
```

## テスト

```bash
pytest
ruff check .
```

## 直近の予定

1. 同一ステム・同一区間でpYINとBasic Pitchを比較
2. 音程漏れ、余分な倍音、オクターブ誤り、細切れを集計
3. 良い候補を統合するClean MIDI処理
4. 体感テンポへ量子化し、編集可能なScore JSONへ変換
5. TAB／楽譜編集MVP
6. MusicXML・PDF出力

以降の計画と完了条件は[開発ロードマップ](docs/ROADMAP.md)を参照してください。

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
