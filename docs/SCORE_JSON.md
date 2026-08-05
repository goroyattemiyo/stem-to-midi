# Score JSON 仕様

最終更新: 2026-08-05

## 1. 目的

`score.json`は、楽譜表示、簡易編集、再生成のための正本データである。

ABC、MusicXML、MIDIの代替規格を作ることが目的ではない。これらの交換形式だけでは保持しにくい次の情報を保存する。

- 元音源上の開始秒と終了秒
- 元MIDIイベントとの対応
- 転写バックエンド
- 検出確信度
- 自動補正前後の値
- 補正理由
- 別の譜割り候補
- ユーザー確認状態
- Undo / Redoに使う変更履歴

```text
performance.json
  ↓ Score Compiler
score.json
  ├─ Clean MIDI
  ├─ MusicXML
  ├─ ABC
  └─ 楽譜プレビュー
```

## 2. ABC記譜法との関係

`score.json`はABCのような1本の文字列ではなく、構造化されたイベントデータとする。

ABCは人間が読み書きしやすく、デバッグや交換に便利なので、`score.json`から生成できるようにする。

```text
score.json = 編集用の正本
ABC        = 人間向けの簡潔なテキスト表現
MusicXML   = 楽譜ソフトとの交換形式
MIDI       = 再生・DAW編集形式
```

## 3. 二層モデル

## 3.1 Performance Notes

音源または外部MIDIから得た演奏情報。時間は秒単位で保持する。

```json
{
  "id": "perf-000001",
  "start_sec": 29.697,
  "end_sec": 30.511,
  "pitch": 67,
  "velocity": 91,
  "confidence": 0.82,
  "source": {
    "kind": "audio_transcription",
    "method": "basic_pitch",
    "source_file": "Lead Vocals.wav"
  }
}
```

Performance Notesは、前ノリ、後ノリ、音の実長、転写モデルの結果を保持する。楽譜用クオンタイズで上書きしない。

## 3.2 Score Events

楽譜として整理された情報。時間は四分音符単位の有理数で保持する。

```json
{
  "id": "score-000001",
  "type": "note",
  "part_id": "lead-vocal",
  "start_qn": "8/1",
  "duration_qn": "1/1",
  "pitch": {
    "midi": 67,
    "step": "G",
    "alter": 0,
    "octave": 4
  },
  "voice": 1,
  "status": "auto_cleaned",
  "source_refs": ["perf-000001"]
}
```

## 4. 音楽時間

四分音符を`1/1`として表す。

| 値 | 音価 |
|---|---|
| `4/1` | 全音符 |
| `2/1` | 二分音符 |
| `3/2` | 付点四分音符 |
| `1/1` | 四分音符 |
| `1/2` | 八分音符 |
| `1/4` | 16分音符 |
| `1/8` | 32分音符 |

JSONの浮動小数ではなく`"分子/分母"`文字列を使う。

理由:

- 小節境界を誤差なく判定できる
- タイや休符の長さを正確に分割できる
- 3連符などを将来`1/3`として扱える
- JSONの小数丸め誤差を避けられる

`start_qn`は曲の第1小節第1拍を`0/1`とする絶対音楽時刻である。

4/4では1小節が`4/1`となる。

```text
measure_index = floor(start_qn / 4)
position_in_measure = start_qn mod 4
```

表示用の小節番号は1始まりとする。

## 5. トップレベル構造

```json
{
  "schema_version": 1,
  "project": {
    "id": "project-uuid",
    "title": "Suno Song",
    "created_at": "2026-08-05T23:30:00+09:00",
    "updated_at": "2026-08-05T23:30:00+09:00"
  },
  "timing": {
    "felt_bpm": 71.4,
    "time_signature": [4, 4],
    "first_beat_sec": 29.682,
    "tempo_source": "tempo.json"
  },
  "sources": [],
  "parts": [],
  "events": [],
  "alternatives": [],
  "history": []
}
```

## 6. timing

```json
{
  "felt_bpm": 71.4,
  "grid_multiplier": 2,
  "grid_bpm": 142.8,
  "time_signature": [4, 4],
  "first_beat_sec": 29.682,
  "tempo_map": null
}
```

- `felt_bpm`: 楽譜の拍と小節を表すテンポ
- `grid_bpm`: 内部量子化候補を作る細かいグリッド
- `first_beat_sec`: 第1小節第1拍の音源上の位置
- `tempo_map`: 将来の可変テンポ用。固定テンポMVPでは`null`

秒と四分音符位置の基本変換:

```text
quarter_note_sec = 60 / felt_bpm
absolute_sec = first_beat_sec + start_qn * quarter_note_sec
start_qn = (absolute_sec - first_beat_sec) / quarter_note_sec
```

MVPでは固定テンポを前提とする。

## 7. sources

元ファイルと中間データを追跡する。

```json
{
  "id": "source-audio-1",
  "kind": "audio",
  "file_name": "Lead Vocals.wav",
  "sha256": "...",
  "duration_sec": 289.734188,
  "sample_rate": 48000
}
```

```json
{
  "id": "source-midi-1",
  "kind": "midi",
  "file_name": "Lead Vocals.melody.mid",
  "sha256": "...",
  "origin": "accuracy_lab"
}
```

想定する`kind`:

- `audio`
- `midi`
- `tempo_project`
- `performance_json`
- `score_json`

## 8. parts

```json
{
  "id": "lead-vocal",
  "name": "Lead Vocal",
  "role": "melody",
  "instrument": "voice",
  "midi_program": 53,
  "clef": "treble",
  "transposition": 0,
  "staff": {
    "type": "standard"
  }
}
```

想定する`role`:

- `melody`
- `bass`
- `harmony`
- `drums`
- `unknown`

初期MVPは`melody`または`bass`の単音1パートを対象とする。

## 9. noteイベント

```json
{
  "id": "score-000001",
  "type": "note",
  "part_id": "lead-vocal",
  "start_qn": "8/1",
  "duration_qn": "1/1",
  "pitch": {
    "midi": 67,
    "step": "G",
    "alter": 0,
    "octave": 4
  },
  "voice": 1,
  "tie": {
    "group_id": null,
    "start": false,
    "stop": false
  },
  "articulations": [],
  "status": "auto_cleaned",
  "confidence": 0.82,
  "source_refs": ["perf-000001"],
  "adjustments": []
}
```

`pitch.midi`を音高の正規値とする。`step`、`alter`、`octave`は記譜時の綴りを保持する。

`alter`:

- `-1`: フラット
- `0`: ナチュラル
- `1`: シャープ

将来、ダブルフラットやダブルシャープのために整数範囲を拡張できる。

## 10. restイベント

```json
{
  "id": "rest-000001",
  "type": "rest",
  "part_id": "lead-vocal",
  "start_qn": "9/1",
  "duration_qn": "1/2",
  "voice": 1,
  "status": "auto_generated",
  "reason": "gap_after_quantization"
}
```

休符は常に保存する必要はないが、楽譜候補の比較、ユーザー編集、MusicXML生成を単純化するため、Score Compilerが確定した休符はイベントとして保持する。

## 11. status

| 値 | 意味 |
|---|---|
| `detected` | 転写結果を未整理で配置した |
| `auto_cleaned` | Score Compilerが補正した |
| `auto_generated` | 休符やタイなどを自動生成した |
| `user_edited` | ユーザーが変更した |
| `confirmed` | ユーザーが確認済みにした |
| `rejected` | 候補から除外した |

ユーザー編集後に自動処理を再実行しても、`user_edited`と`confirmed`は原則として上書きしない。

## 12. adjustments

自動補正やユーザー操作をイベント単位で追跡する。

```json
{
  "id": "adjustment-000001",
  "type": "quantize_start",
  "actor": "score_compiler",
  "from": {
    "start_sec": 29.697
  },
  "to": {
    "start_qn": "0/1",
    "start_sec": 29.682
  },
  "reason": "nearest_phrase_anchor",
  "cost": {
    "timing_error_ms": 15.0,
    "complexity_delta": -2.0
  }
}
```

想定する`type`:

- `quantize_start`
- `quantize_end`
- `merge_same_pitch`
- `remove_short_note`
- `octave_shift`
- `collapse_vibrato`
- `create_rest`
- `create_tie`
- `change_pitch`
- `split_note`
- `user_override`

## 13. alternatives

Score Compilerが迷った小節やフレーズの別候補を保存する。

```json
{
  "id": "alternative-measure-24-b",
  "scope": {
    "part_id": "lead-vocal",
    "measure_start": 24,
    "measure_end": 24
  },
  "label": "16分音符まで",
  "score": {
    "total": 42.8,
    "timing_error_ms": 31.2,
    "complexity": 11.6
  },
  "event_ids": [
    "candidate-b-note-1",
    "candidate-b-note-2"
  ],
  "selected": true
}
```

候補イベントは`alternatives`内に埋め込むか、共通イベントプールを参照する。実装時に読み書きの単純さを比較して決める。

## 14. history

Undo / Redoと再現性のため、操作ログを保持する。

```json
{
  "id": "edit-000001",
  "timestamp": "2026-08-05T23:30:00+09:00",
  "actor": "user",
  "operation": "change_pitch",
  "target_ids": ["score-000001"],
  "before": {
    "pitch_midi": 68
  },
  "after": {
    "pitch_midi": 67
  }
}
```

大規模データでは完全スナップショットを毎回保存せず、差分ログと定期スナップショットを組み合わせる。

MVPではメモリ上のUndo / Redoを優先し、保存形式は後から最適化してよい。

## 15. 完全な最小例

```json
{
  "schema_version": 1,
  "project": {
    "id": "demo-song",
    "title": "Suno Song"
  },
  "timing": {
    "felt_bpm": 71.4,
    "grid_multiplier": 2,
    "grid_bpm": 142.8,
    "time_signature": [4, 4],
    "first_beat_sec": 29.682,
    "tempo_map": null
  },
  "sources": [
    {
      "id": "source-midi-1",
      "kind": "midi",
      "file_name": "Lead Vocals.melody.mid"
    }
  ],
  "parts": [
    {
      "id": "lead-vocal",
      "name": "Lead Vocal",
      "role": "melody",
      "instrument": "voice",
      "midi_program": 53,
      "clef": "treble",
      "transposition": 0
    }
  ],
  "events": [
    {
      "id": "score-000001",
      "type": "note",
      "part_id": "lead-vocal",
      "start_qn": "0/1",
      "duration_qn": "1/1",
      "pitch": {
        "midi": 67,
        "step": "G",
        "alter": 0,
        "octave": 4
      },
      "voice": 1,
      "tie": {
        "group_id": null,
        "start": false,
        "stop": false
      },
      "status": "auto_cleaned",
      "confidence": 0.82,
      "source_refs": ["perf-000001"],
      "adjustments": []
    },
    {
      "id": "rest-000001",
      "type": "rest",
      "part_id": "lead-vocal",
      "start_qn": "1/1",
      "duration_qn": "1/2",
      "voice": 1,
      "status": "auto_generated",
      "reason": "gap_after_quantization"
    }
  ],
  "alternatives": [],
  "history": []
}
```

この例をABCへ変換すると、概念的には次のようになる。

```abc
X:1
T:Suno Song
M:4/4
L:1/8
Q:1/4=71.4
K:C
G2 z |
```

## 16. バリデーション要件

- イベントIDが重複しない
- `duration_qn`が正数である
- 同一声部で意図しない音符重複がない
- MIDI音高が0〜127である
- `source_refs`が存在するPerformance Noteを指す
- タイの開始と終了が同じ`group_id`で対応する
- 4/4 MVPでは各小節内のイベントと休符が合計`4/1`になる
- `felt_bpm`が正数である
- `first_beat_sec`が非負である

## 17. スキーマ方針

- 破壊的変更では`schema_version`を上げる
- 読み込み時に旧Versionを移行する
- 未知フィールドは可能な限り保持する
- MusicXMLやABCの都合だけで内部構造を変更しない
- 表示ライブラリ固有のIDや座標を正本へ保存しない

`score.json`は、楽譜を表示するためだけでなく、**どの演奏情報を、なぜ、どの譜面表現へ変えたかを追跡する形式**とする。
