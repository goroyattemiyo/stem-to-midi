# Stem to Score 開発ロードマップ

最終更新: 2026-08-05

## 1. 目標

Sunoなどで生成した曲を、人が読んで演奏し、MuseScoreやFlatで修正できる楽譜へ仕上げる。

```text
音源 / ステム / 外部MIDI
  ↓
テンポ・拍・小節の確定
  ↓
Performance Notesへ正規化
  ↓
Score Compilerで読みやすい譜面へ整理
  ↓
Score Labで楽譜プレビューと部分修正
  ↓
Score JSON / Clean MIDI / MusicXML
```

Audio-to-MIDIの精度競争だけを目的にしない。転写結果がどの方式で作られたかに関係なく、読める楽譜へ変換できることを重視する。

製品全体の設計は[PRODUCT_DESIGN.md](PRODUCT_DESIGN.md)、編集データ形式は[SCORE_JSON.md](SCORE_JSON.md)を参照する。

## 2. 開発原則

### 演奏情報と楽譜情報を分離する

- 元音源やMIDIの時刻はPerformance Notesへ保持する
- 楽譜上の位置と音価はScore Eventsへ保持する
- クオンタイズ後も元の秒位置を失わない
- Score JSONからMIDI、MusicXML、ABCを生成する

### 読みやすさを評価対象にする

音響的な誤差だけでなく、次も計測する。

- 32分音符と32分休符の数
- 短い休符の数
- タイの数
- 小節内の音符密度
- 前後フレーズとのリズム不一致
- 楽譜ソフトへ渡した後の手修正量

### 通常操作と診断操作を分ける

通常ユーザーの中心画面はScore Labとする。

Tempo Lab、Raw MIDI Lab、Accuracy Labは、時間軸や転写候補を確認する高度・診断用画面へ位置付け直す。

### 小さく完成させる

最初の楽譜MVPは次へ限定する。

- 固定テンポ
- 4/4
- 単旋律1パート
- 四分、八分、16分音符
- 付点音符
- 休符
- 小節をまたぐタイ
- MusicXML出力

## 3. 現在地

### 実装済み

#### 時間軸

- WAV読み込み
- BPMと拍位置の自動検出
- 体感テンポと内部グリッドの分離
- 先頭拍位置の手動補正
- クリック付きプレビュー
- `tempo.json`保存と再読み込み
- 音源照合

#### 転写

- pYINによる単音ステム追跡
- Basic Pitchによる多音候補生成
- 30秒、60秒、全曲解析
- Basic Pitch Raw候補からの単音メロディ経路選択
- 発音カバー率、最大同時音、長い空白、オクターブ跳躍の診断
- Raw MIDI、メロディMIDI、検証JSON出力

#### MIDI出力

- 絶対時刻の保持
- 先頭拍マーカー
- 4/4の体感テンポでの書き出し
- DAW互換のASCIIトラック名

### 未実装

- 外部MIDIの共通インポート
- Performance Notesの正式スキーマ
- Score JSON
- 読みやすさを考慮したクオンタイズ
- 休符とタイの生成
- Score Lab
- MusicXML生成
- アプリ内五線譜プレビュー
- 問題小節の候補比較

## 4. 新しいアーキテクチャ

```text
Project Import
  ├─ audio.wav / audio.mp3
  ├─ stems/*.wav
  ├─ external.mid
  ├─ tempo.json
  ├─ performance.json
  └─ score.json

Beat Setup
  └─ tempo.json

Transcription Diagnostics
  ├─ pYIN
  ├─ Basic Pitch
  ├─ external MIDI
  └─ performance.json

Score Compiler
  ├─ voice selection
  ├─ note cleanup
  ├─ phrase analysis
  ├─ quantization candidates
  ├─ readability scoring
  └─ score.json

Score Lab
  ├─ score preview
  ├─ audio / MIDI comparison
  ├─ alternative selection
  └─ simple editing

Export
  ├─ clean.mid
  ├─ score.musicxml
  ├─ score.abc
  └─ score.json
```

## 5. マイルストーン

## M0: 設計の再定義

### 内容

- 製品目的を「Audio-to-MIDI」から「Suno曲を読める楽譜へ」に変更
- Performance NotesとScore Eventsを分離
- Score JSONを編集データの正本として定義
- Score Labを中心画面として定義
- 転写画面を診断機能として再配置

### 完了条件

- README、製品設計、Score JSON仕様、ロードマップが一致している
- 次の実装PRが設計文書から切り出せる

## M1: 外部MIDIインポートとPerformance Notes

### 内容

- Standard MIDI Fileを読み込む
- テンポ、拍子、トラック、チャンネル、プログラムを解析する
- note_on / note_offを絶対秒へ変換する
- 外部MIDIとAccuracy Lab MIDIを共通イベントへ正規化する
- 多音MIDIから対象トラックまたは対象音域を選択する
- `performance.json`を保存する

### UI

- MIDIアップロード
- トラック一覧
- 音域、音符数、同時発音数、長さの表示
- 採用するトラックの選択
- tempo.jsonを使うか、MIDI内テンポを使うか選択

### 完了条件

- OpenMusic製MIDIを読み込める
- Accuracy LabのメロディMIDIを同じ形式へ変換できる
- 元MIDIとPerformance Notesの開始・終了時刻が1ms以内で一致する

## M2: Score Compiler基盤

### 内容

- 秒から四分音符位置への変換
- 有理数による音楽時間
- 最大細分を8分、16分、32分から選択
- 開始位置と終了位置の基本クオンタイズ
- 小節分割
- 休符生成
- 小節をまたぐ音符のタイ分割
- Score JSON Version 1の読み書きと検証

### 完了条件

- 4/4単旋律をScore JSONへ変換できる
- 各小節の音符と休符の合計が4拍になる
- Score JSONからClean MIDIを再生成できる
- 保存と再読込でイベントIDと編集状態を失わない

## M3: MusicXMLと楽譜プレビュー

### 内容

- Score JSONからMusicXMLを生成
- 音部記号、テンポ、拍子、小節番号を出力
- 音符、休符、付点、タイを出力
- VerovioでMusicXMLをSVGへ変換
- Streamlit上に五線譜を表示
- ページ切り替えとズーム

### 完了条件

- アプリ内で1パートの五線譜を確認できる
- MusicXMLをMuseScoreまたはFlatで開ける
- プレビューとMusicXMLの小節・音価が一致する

## M4: Readability Quantizer

### 内容

- 短い同音間ギャップの吸収
- 短音除去
- ビブラートと隣接半音の統合候補
- 複数の譜割り候補生成
- タイミング誤差と譜面複雑度の採点
- 「原音忠実 ↔ 読みやすい」スライダー
- 最大細分と短い隙間処理の設定

### 初期コスト

- 32分音符
- 32分休符
- 短い休符
- タイ
- 1拍内の過剰な音符数
- 前後小節と異なるリズム型

### 完了条件

- Raw MIDI直接インポートより32分音符と短い休符が明確に減る
- 同じ入力と設定から同じScore JSONを再生成できる
- 原音忠実モードと読みやすいモードの違いを楽譜と試聴で比較できる

## M5: Score Lab MVP

### 画面

```text
┌──────────────────────────────────────┐
│ 曲名 / パート / BPM / 拍子            │
├──────────────────────────────────────┤
│ 読みやすさ / 最大細分 / 隙間処理      │
├──────────────────────────────────────┤
│ 五線譜プレビュー                      │
├──────────────────────────────────────┤
│ 波形 / ピアノロール / 再生カーソル    │
├──────────────────────────────────────┤
│ 問題小節 / 候補A / 候補B / Raw        │
├──────────────────────────────────────┤
│ MusicXML / MIDI / Score JSON           │
└──────────────────────────────────────┘
```

### 編集

- 小節を選択
- 候補を切り替える
- 音程を半音上下する
- 音符を削除する
- 隣接音符を結合する
- 音符を分割する
- Rawへ戻す
- 確認済みにする

### 完了条件

- 曲全体ではなく問題小節だけを修正できる
- 編集後の楽譜を再表示できる
- 編集後のMusicXMLとMIDIを出力できる

## M6: 反復フレーズと自動補正

### 内容

- 同じリフ、Aメロ、サビの反復候補を検出
- 音高列とリズム列を別々に比較
- 同じフレーズの譜割りを多数決で統一
- 反復間の違いを演奏揺れか本当の差か分類

### 完了条件

- 反復部分の不規則な32分音符が減る
- 自動統一した箇所をユーザーが確認・解除できる

## M7: 楽器別展開

### ボーカル・主旋律

- ビブラート吸収
- しゃくり、フォール、経過音の分類
- 歌メロ向けフレーズ分割

### ベース

- 単音優先
- 低音域の倍音補正
- TABの弦・フレット候補

### ギター・ピアノ

- 多声音の声部分離
- 和音の同時開始整理
- 右手・左手またはメロディ・伴奏の分離

### ドラム

- General MIDI Drum Map
- 打点の量子化
- 打楽器譜への変換

## M8: 高度な出力と統合

- ABC出力
- TAB付きMusicXML
- PDF生成
- MuseScore CLI連携
- Flat API連携
- 可変テンポ
- 変拍子
- 歌詞
- プロジェクト一括処理

## 6. 次に着手するPR

優先順は次のとおり。

1. `midi_import.py`とPerformance Noteモデル
2. 外部MIDIを読み込むProject Import画面
3. Score JSON Version 1のPythonモデルとバリデーション
4. 最大16分までの基本Score Compiler
5. MusicXML生成とVerovioプレビュー

最初の実データ検証には、OpenMusicで生成した多音MIDIとAccuracy LabのメロディMIDIを使う。

## 7. 当面やらないこと

- 独自の大規模音高認識モデルを学習する
- OpenMusicの画面をブラウザ自動操作する
- 最初から全ステムの総譜を作る
- 最初からMuseScore相当の五線譜エディターを作る
- 楽譜プレビューより先にPDF完成度を追う

まず、**既存MIDIを読める単旋律楽譜へ変換し、アプリ内で確認できる状態**を完成させる。
