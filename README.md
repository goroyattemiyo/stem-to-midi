# Stem to Score

> Repository: `stem-to-midi`  
> Working product name: **Stem to Score**

Sunoなどで生成した曲を、**人が読んで演奏し、MuseScoreやFlatで修正できる楽譜へ仕上げる**ためのローカルツールです。

Audio-to-MIDIの精度だけを競うのではなく、転写されたMIDIを正しいテンポと小節へ配置し、過剰な16分・32分音符、短い休符、不自然なタイを減らして、実用的な譜面へ変換することを目指します。

```text
音源 / ステム / 外部MIDI
  ↓
テンポ・拍・小節の確定
  ↓
演奏イベントへ正規化
  ↓
読みやすさを考慮したScore Compiler
  ↓
アプリ内の五線譜プレビュー
  ↓
Score JSON / Clean MIDI / MusicXML
```

## ドキュメント

- [製品設計](docs/PRODUCT_DESIGN.md): 目的、ユーザーフロー、Score Lab、Score Compiler
- [Score JSON仕様](docs/SCORE_JSON.md): Performance Notesと楽譜イベントのデータ設計
- [開発ロードマップ](docs/ROADMAP.md): 外部MIDI入力からMusicXMLプレビューまでの実装順
- [開発記録](docs/DEVELOPMENT_LOG.md): 既存機能、PR、実音源から得た判断

## 設計の中心

### 演奏情報と楽譜情報を分ける

元音源やMIDIの細かなタイミングは`performance.json`へ残し、楽譜上の位置、音価、休符、タイは`score.json`へ保存します。

譜面を8分音符へ整理しても、元の前ノリ、後ノリ、開始秒、終了秒、検出確信度を失いません。

### MIDIをそのまま楽譜にしない

Score Compilerは複数の譜割り候補を作り、次をまとめて評価します。

- 元演奏とのタイミング誤差
- 32分音符と32分休符の数
- 短い休符の数
- タイの数
- 小節内の音符密度
- 前後フレーズとのリズム不一致

UIでは「原音忠実 ↔ 読みやすい」のスライダーとして調整できる設計です。

### 転写方式に依存しない

入力候補は限定しません。

- pYINで生成した単音MIDI
- Basic Pitchで生成したMIDI
- OpenMusicなど外部サービスのMIDI
- DAWや人手で作ったMIDI
- 将来追加する別の転写バックエンド

どのMIDIも共通のPerformance Notesへ変換し、その後の楽譜処理を共通化します。

## 現在実装済み

### Tempo Lab

- WAV読み込み
- BPMと拍位置の自動検出
- 体感テンポと内部グリッドの分離
- 先頭拍位置の手動補正
- 波形、拍線、クリック付きプレビュー
- `tempo.json`保存と再読込
- WAV照合

### Raw MIDI Lab

- pYINによるベース、ボーカル、単音リードの追跡
- 30秒、60秒、全曲解析
- 音域、確信度、最短音、短い隙間の設定
- ピアノロールと品質警告
- Raw MIDIと検出ノートJSON出力

### Accuracy Lab

- Spotify Basic Pitchによる多音候補生成
- Raw多音MIDIと単音メロディ候補の出力
- 音域、オンセット、持続フレーム、最短音の設定
- 最大同時音、発音カバー率、長い未検出区間、オクターブ跳躍の表示
- 4/4の体感テンポを使ったMIDI書き出し

現在のTempo Lab、Raw MIDI Lab、Accuracy Labは、今後は主に時間軸と転写候補を確認する診断機能として使います。

## 次に実装するもの

1. 外部MIDIのインポート
2. MIDIを共通Performance Notesへ変換
3. Score JSON Version 1
4. 最大16分までの基本クオンタイズ
5. 休符とタイの生成
6. MusicXML出力
7. Verovioによるアプリ内五線譜プレビュー
8. 読みやすさスライダーと問題小節の候補比較

最初のMVPは、固定テンポ、4/4、単旋律1パートに限定します。

## セットアップ

Python 3.11を推奨します。

### Windows

```powershell
cd C:\dev\stem-to-midi
py -3.11 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -e ".[dev]"
```

Accuracy Labも使う場合:

```powershell
.\.venv\Scripts\python.exe -m pip install -e ".[dev,accuracy]"
```

### macOS / Linux

```bash
python3.11 -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"
```

## 起動

### Windows

```powershell
cd C:\dev\stem-to-midi
.\.venv\Scripts\python.exe -m streamlit run app.py
```

### macOS / Linux

```bash
streamlit run app.py
```

終了は起動したターミナルで`Ctrl+C`です。

## テスト

```bash
pytest
ruff check .
```

## データ管理

音源、ステム、生成MIDI、Score JSONなどの制作データはGitへコミットしません。

```text
workspace/
├─ input/
│  └─ song-name/
│     ├─ audio/
│     ├─ stems/
│     └─ midi/
├─ project/
│  └─ song-name/
│     ├─ tempo.json
│     ├─ performance.json
│     └─ score.json
└─ output/
   └─ song-name/
      ├─ clean.mid
      └─ score.musicxml
```

## 最終的に目指す操作

```text
Sunoで良い曲ができる
  ↓
音源、ステム、またはMIDIを追加する
  ↓
「楽譜を生成」を押す
  ↓
アプリ内で五線譜を確認する
  ↓
怪しい数小節だけ直す
  ↓
MusicXMLをMuseScoreまたはFlatへ渡す
```

目標は、**Suno曲を楽譜として残したい人が、専門的な採譜作業を最小限にできること**です。
