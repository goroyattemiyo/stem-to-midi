# Stem to MIDI 開発記録

最終更新: 2026-08-04

この文書は、実装内容だけでなく、実音源から得た気づき、採用した判断、後で再検討する項目を残すための記録である。

## 1. プロジェクト開始時の目的

Sunoなどで分離したWAVステムから、編集可能なMIDIと楽譜を作る。

当初から一括の完全自動変換ではなく、次の段階を分離する方針とした。

```text
Tempo Lab
→ Raw MIDI Lab
→ Clean MIDI Lab
→ Score Editor
→ MusicXML / PDF
```

理由は、テンポ位置の誤り、音高検出の誤り、楽譜表現の誤りを同時に扱うと、原因を切り分けられないためである。

## 2. 開発環境の立ち上げ

### リポジトリ

- Repository: `goroyattemiyo/stem-to-midi`
- Default branch: `main`
- 開発方式: 機能ごとのブランチ、Draft PR、GitHub ActionsでRuffとpytest

### Windowsローカル環境

最初の仮想環境作成時、`python`コマンドが削除済みのPython 3.12を参照していた。

```text
No Python at 'C:\Users\admin\AppData\Local\Programs\Python\Python312\python.exe'
```

`py -0p`でPython Launcherの状態を確認し、Python 3.11を追加して、リポジトリ直下に`.venv`を作成した。

開発時の実行例:

```powershell
cd C:\dev\stem-to-midi
py -3.11 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -e ".[dev]"
.\.venv\Scripts\python.exe -m streamlit run app.py
```

Python 3.11を使う判断には、現在のMVPだけでなく、将来の音声MIDI変換バックエンド候補との互換性を保ちやすくする意図がある。

## 3. PRごとの履歴

## PR #1: Add initial Tempo Lab

- PR: https://github.com/goroyattemiyo/stem-to-midi/pull/1
- 作成・マージ: 2026-08-04

### 目的

固定テンポのWAVからBPMと拍位置を検出し、人が耳で補正できる最小ツールを作る。

### 実装

- Streamlit UI
- WAVアップロード
- librosaによるBPM・拍位置検出
- BPMの手動修正
- 先頭拍位置の手動修正
- 波形上の自動検出拍と補正グリッド
- 元音源とクリック付きプレビュー
- tempo JSON出力
- Pythonプロジェクト設定
- pytest、Ruff、GitHub Actions

### 意図的に外したもの

- 可変テンポ
- Audio-to-MIDI
- 楽譜出力

### 検証

- ローカルpytest: 5件成功
- コンパイル確認成功
- GitHub Actions成功

### 学び

最初に拍グリッドを確定できるようにしたことで、後のMIDI検出結果を音源の絶対時刻と比較できる土台ができた。

## PR #2: Separate felt tempo from internal grid

- PR: https://github.com/goroyattemiyo/stem-to-midi/pull/2
- 作成・マージ: 2026-08-04

### 背景

最初の実曲検証で、自動検出は約144.23 BPMだったが、曲の体感は約72.12 BPMだった。

単純にBPMを半分にすると、将来の八分・16分音符量子化に使う細かいグリッドまで失われる。そのため、音楽的な体感テンポと処理用内部グリッドを分離した。

### 実装

- `felt_bpm`
- `grid_multiplier`
- `grid_bpm`
- 内部グリッドを保ちやすいBPM ÷2／×2
- 体感拍と内部グリッドの別表示
- クリック対象の切り替え
- 先頭拍と最寄り検出拍の差
- 拍検出終了から音源末尾までの余白
- JSON schema Version 2
- 旧フィールドの互換維持

### 実音源から得た値

最初のJSONでは、おおむね次の状態だった。

```text
検出テンポ       144.230769 BPM
体感テンポ        72.115385 BPM
内部グリッド     144.230770 BPM
先頭拍補正          2.320 秒
最寄り検出拍との差    -16 ms
検出終了後の余白      7.76 秒
```

### 判断

- 画面上の体感テンポとMIDI処理用テンポを分ける。
- MIDI量子化では内部グリッドを使う。
- 先頭拍は自動検出値をそのまま採用せず、ユーザー補正可能にする。

### 検証

- テンポ診断テスト成功
- GitHub Actions成功

## PR #3: Add tempo JSON import and resume workflow

- PR: https://github.com/goroyattemiyo/stem-to-midi/pull/3
- 作成・マージ: 2026-08-04

### 目的

保存したtempo.jsonを解析結果ではなく、作業再開用プロジェクトとして使えるようにする。

### 実装

- Version 1 JSON読込
- Version 2 JSON読込
- 体感テンポ、内部倍率、先頭拍の復元
- 保存済み拍配列を信用せず、設定から再生成
- SHA-256による元WAV照合
- SHAがない場合のファイル名・長さ照合
- 不一致時の明示確認
- 壊れたJSON、未対応Versionのエラー表示
- `first_beat_sec`を正規フィールドとして追加

### 判断

拍配列は派生データとし、保存済み配列よりBPMと先頭拍を正とする。これにより、設定値と拍配列が食い違う事故を避ける。

### 検証

- JSONパーサー・照合テスト: 7件追加
- GitHub Actions成功

## PR #4: Add bass Raw MIDI validation lab

- PR: https://github.com/goroyattemiyo/stem-to-midi/pull/4
- 作成・マージ: 2026-08-04

### 目的

ベースステムからRaw MIDIを生成し、モデル選定より先に実データで誤りの種類を測る。

### バックエンド選択

最初の対象を分離済みの単音ベースとしたため、`librosa.pyin`を基準方式として採用した。

理由:

- 既存依存のlibrosaで利用できる
- フレーム単位の音高・有声判定・確信度を観察できる
- パラメータ変更の影響を説明しやすい
- 後で別バックエンドと同じノートJSON形式で比較できる

### 実装

- Raw MIDI Labページ
- 30秒、60秒、全曲の解析
- tempo.json読込
- 別ステム間はSHAではなく長さを中心に位置確認
- 最低音・最高音
- 有声音確信度
- 最短音
- 同音内の短い無音補完
- 同音再アタックの分割
- pYINフレームと抽出ノートのピアノロール
- 音符数、有声音率、中央確信度、中央音長
- 細切れ、低確信度、音域端、低有声音率の警告
- 絶対時刻を保つRaw MIDI
- テンポ、4/4拍子、`FIRST_BEAT`マーカー
- `raw-notes.json`
- Mido依存追加

### 検証

- 合成したA2・D3フレーズの検出
- 短い同音ギャップ補完
- 再アタック分割
- MIDI絶対時刻とテンポメタデータ
- GitHub Actions成功

### CIで起きたこと

最初のCIでは、Ruffの`RUF046`により、`round()`の戻り値へ不要な`int()`を重ねた4箇所が失敗した。不要なキャストを除去し、再実行で成功した。

### 判断

- Raw段階では量子化しない。
- 誤りを観察できる情報を残す。
- 全曲処理より先に短区間で検証する。
- Basic Pitchなどの導入は、pYINで不足する問題を確認してから判断する。

## PR #5: Align preview, analysis, and click starts

- PR: https://github.com/goroyattemiyo/stem-to-midi/pull/5
- 作成・マージ: 2026-08-04

### 背景

Tempo Labの先頭拍、確認開始位置、Raw MIDI Labの解析開始位置が別々に設定されると、クリックと検出結果を比較しにくい。

JSON適用時に確認開始が0秒付近へ残る処理もあり、先頭拍から確認する意図と一致していなかった。

### 実装

- Tempo Labの確認開始を先頭拍へ追従
- JSON適用時に確認開始を`first_beat_sec`へ設定
- 最寄りの体感拍／小節頭へのスナップ
- 共通の拍・小節アラインメント関数
- 小節頭のアクセントクリック
- プレビュー開始サンプル0へのクリック配置
- Raw MIDI Labの開始方法
  - 先頭拍
  - 小節頭
  - 自由位置
- プレビュー、クリック、pYIN、ピアノロールで同じ`analysis_start`を使用
- 開始基準と体感拍からの位相差表示

### 検証

- アラインメント関数テスト
- 先頭サンプルのクリックテスト
- Ruff成功
- 全pytest成功

### 判断

`first_beat_sec`と`analysis_start`を後工程でも使う共通基準とする。Clean MIDI、Score Editor、再生カーソル同期も同じ時間モデルへ接続する。

## 4. 開発中に確立したデータ形式

## tempo.json

役割:

- 体感テンポ
- 内部グリッド
- 先頭拍
- 元WAV情報
- 自動検出値と補正値

原則:

- BPMと先頭拍を正とする。
- 拍配列は再生成可能な派生データとする。
- 旧Versionを読み込み、新Versionへ移行できるようにする。

## raw-notes.json

役割:

- Raw音符の絶対時刻
- MIDI音高
- ベロシティ
- 確信度
- 検出設定
- 解析区間
- tempo.json由来のテンポ情報

原則:

- 未量子化状態を保存する。
- 後のClean処理で再利用する。
- 検出バックエンドに依存しすぎない形式にする。

## 将来のscore.json

役割:

- 小節・拍単位の編集
- 五線譜・TAB表示
- ユーザー修正状態
- Undo／Redo
- MIDI・MusicXML生成元

詳細は`ROADMAP.md`へ記録する。

## 5. 現在の品質確認フロー

```text
1. Tempo LabでドラムまたはミックスWAVを開く
2. 体感テンポ、内部グリッド、先頭拍を調整する
3. クリック付き再生で後半までずれないか確認する
4. tempo.jsonを保存する
5. Raw MIDI LabでベースWAVとtempo.jsonを開く
6. 先頭拍または小節頭から30秒解析する
7. 原音＋クリックとピアノロールを比較する
8. raw.midとraw-notes.jsonを保存する
9. 誤りを分類する
```

## 6. 次の検証で記録する項目

実ベースステムごとに次を残す。

```text
曲・ステム名:
解析区間:
体感BPM:
内部グリッドBPM:
先頭拍:
検出音符数:
有声音率:
中央確信度:
中央音長:
短音の多さ:
オクターブ誤り:
発音漏れ:
拍ずれ:
設定変更:
人の評価:
```

評価は少なくとも次の4段階に分ける。

- そのまま使える
- 少量修正で使える
- 大幅修正が必要
- 検出方式の変更が必要

## 7. 現在の次工程

1. 実ベースWAVの30秒区間を複数検証
2. `raw-notes.json`の統計と原音確認
3. 誤りの上位要因を決定
4. Clean MIDI Labを実装
5. ベース1曲でClean MIDIを完成
6. Score JSONを定義
7. 五線譜＋TAB、原音波形、TAB入力グリッドの編集MVPへ進む

詳細計画は[ROADMAP.md](ROADMAP.md)を参照する。
