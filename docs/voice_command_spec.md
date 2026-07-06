# 音声コマンド仕様書

## 基本方針

AI APIは使用しない。

決まった音声コマンドで操作する。

Android / iPhone / Webクライアントは検索・判定ロジックを持たず、認識した文字列をサーバー共通APIへ送信する。

## 共通API

### GET /api/voice-command

パラメータ:

- `q`: SpeechRecognizerなどで認識した音声文字列

例:

```text
/api/voice-command?q=再生
/api/voice-command?q=最新
/api/voice-command?q=日曜天国を再生
/api/voice-command?q=TBSを探して
/api/voice-command?q=止めて
/api/voice-command?q=状態
```

再生レスポンス:

```json
{
  "ok": true,
  "action": "play",
  "message": "最新の録音を再生します",
  "file_id": "xxxxxxxx"
}
```

エラーレスポンス:

```json
{
  "ok": false,
  "message": "録音が見つかりません"
}
```

Day25時点では固定コマンドに加えて、番組名・キーワード検索コマンドに対応する。

| コマンド | action | 内容 |
| --- | --- | --- |
| 再生 | play | 最新録音1件のfile_idを返す |
| 最新 | play | 最新録音1件のfile_idを返す |
| ○○を再生 | play | ○○で録音を検索し、最新1件のfile_idを返す |
| ○○を探して | play | ○○で録音を検索し、最新1件のfile_idを返す |
| 止めて | pause | クライアント側の再生停止 |
| 状態 | status | クライアント側の状態確認 |

検索コマンドでは、サーバー側で末尾の操作語を除去して検索語を作る。

除去対象:

- `を再生`
- `再生`
- `を探して`
- `探して`
- `を聞きたい`
- `聞きたい`
- `を聴きたい`
- `聴きたい`

検索対象:

- `title`
- `station`
- `filename`
- `date`
- `path`

検索結果が1件以上ある場合、録音一覧の並び順に従って最新の1件を返す。

```json
{
  "ok": true,
  "action": "play",
  "message": "日曜天国を再生します",
  "file_id": "xxxxxxxx"
}
```

検索結果が0件の場合:

```json
{
  "ok": false,
  "message": "日曜天国の録音が見つかりません"
}
```

Android / iPhone / Webクライアントは、`action=play` と `file_id` を受け取ったらその録音を再生する。検索語抽出・録音検索・再生対象file_idの選択はサーバー側に集約する。

## 再生

- 「再生」
- 「続けて」
- 「止めて」
- 「一時停止」

## シーク

- 「30秒戻して」
- 「1分進めて」

## 検索

- 「日曜天国を再生」
- 「昨日の日曜天国を再生」
- 「TBSを探して」

## 候補選択

- 「1番」
- 「2番」
- 「最新」
- 「キャンセル」

## ヘルプ

- 「使い方」
- 「何ができる」

## 音声応答例

- 「再生します」
- 「一時停止しました」
- 「30秒戻します」
- 「3件見つかりました」
