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

### Score Lab — Phase 1

- 外部Standard MIDI Fileの読み込み
- MIDI Type、PPQ、テンポ、拍子、トラック、チャンネル、音域の表示
- 楽譜化するトラックの選択
- 最高音、最低音、強さ、長さによる単旋律抽出
- 四分、八分、16分グリッドへの基本クオンタイズ
- 4/4小節への配置
- 休符、付点音符、小節をまたぐタイの生成
- MusicXML出力
- Verovioによるアプリ内五線譜プレビュー
- ページ切り替えと表示倍率調整

Phase 1は固定テンポ、4/4、単旋律1パートに限定しています。Score JSON、原音同期、候補比較、手動編集は次のPhaseで追加します。

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

## Score Labの使い方

1. 左メニューから **Score Lab** を開く
2. Basic Pitch、OpenMusic、DAWなどで作った`.mid`または`.midi`を選ぶ
3. 楽譜化するトラックを選ぶ
4. 最大細分、単旋律抽出方法、テンポ、音部記号を調整する
5. 五線譜を確認し、MusicXMLをダウンロードする
6. 必要に応じてMuseScoreまたはFlatで仕上げる

MIDIに複数テンポや変拍子が含まれる場合、Phase 1では最初のテンポと4/4を使用し、画面に警告を表示します。

## 次に実装するもの

1. MIDIを正式なPerformance Notesへ保存
2. Score JSON Version 1
3. Score JSONから同じMusicXMLとClean MIDIを再生成
4. 短い隙間、細切れ音、過剰なタイを整理するReadability Quantizer
5. 「原音忠実 ↔ 読みやすい」スライダー
6. 問題小節の候補比較
7. 原音との同期再生と簡易修正

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

既存環境を更新した後も、Verovioなどの追加依存を反映するために同じインストールコマンドを再実行してください。

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
