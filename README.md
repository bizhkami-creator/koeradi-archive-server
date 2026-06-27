# KoeRadi Archive Server

Raspberry Pi上で動作する「KoeRadi Archive Server」のタイムフリー録音およびメタデータ管理・クラウド同期サーバーです。

## 目的
radikoタイムフリーから取得した音声を保存・管理し、Google Driveへ同期することで、Androidアプリ「こえラジ」から検索・再生できるようにするためのサーバー基盤を構築します。

## ディレクトリ構成
```
koeradi-archive/
├── README.md                 # プロジェクトの概要と説明書
├── requirements.txt          # 必要なPythonパッケージ一覧
├── config/
│   └── programs.yaml         # 録音対象番組の設定ファイル
├── data/
│   ├── audio/                # 音声ファイルの保存先 (KoeRadi 命名規則で保存)
│   │   └── sample/           # サンプル音声配置フォルダ
│   └── metadata/             # 生成されたメタデータ(metadata.json)の保存先
├── scripts/
│   ├── generate_metadata.py  # 音声ファイルからmetadata.jsonを生成するスクリプト
│   ├── record_test.sh        # radikoタイムフリー録音の個別テストスクリプト
│   ├── record_from_config.py # 設定ファイルに基づく自動判定・録音スクリプト
│   ├── sync_drive.sh         # rcloneを使用してGoogle Driveへ同期するスクリプト
│   └── vendor/               # 外部オープンソーススクリプト配置先
│       └── rec_radiko_ts.sh     # radikoタイムフリー取得スクリプト
└── logs/                     # ログファイル保存用フォルダ
```

## 外部スクリプトの出典
本プロジェクトでは、radikoタイムフリーからの音声取得に以下の外部オープンソーススクリプトを利用しています。
- **rec_radiko_ts.sh**: [uru2/rec_radiko_ts](https://github.com/uru2/rec_radiko_ts) (MIT License)
  - `scripts/vendor/rec_radiko_ts.sh` に配置しています。

## 開発ステータス
- **Day1**: 基本プロジェクト構造の構築、`metadata.json` 生成機能、`sync_drive.sh` 雛形の作成。
- **Day2**: radikoタイムフリー手動取得機能 (`record_test.sh`) の実装および動作検証、録音音声のGit追跡除外設定。
- **Day3**: `config/programs.yaml` に基づく複数番組判定・自動録音機能 (`record_from_config.py`) の実装、dry-run機能および録音後の metadata.json 自動更新連携。
- **Day4**: スケジュール安全実行化 (`--today`, `--yesterday`, `--date`)、重複録音防止(SKIP)処理、番組名のファイル名安全化(sanitize)、dry-run時パス・ステータス表示、ログ強化。

## 録音スクリプトの使い方

### 設定ファイルに基づく録音 (`record_from_config.py`)
`config/programs.yaml` に定義された番組の中から、対象日付の曜日かつ `enabled: true` の番組を抽出して録音します。
すでにファイルが存在する場合は二重録音を自動スキップします。

```bash
# 本日の録音対象を確認 (dry-run)
python3 scripts/record_from_config.py --today --dry-run

# 昨日の録音対象を確認 (dry-run)
python3 scripts/record_from_config.py --yesterday --dry-run

# 指定日の録音対象を確認 (dry-run)
python3 scripts/record_from_config.py --date 2026-06-27 --dry-run

# 録音実行 (デフォルトは --today と同じ扱い)
python3 scripts/record_from_config.py
```

### 単一番組の手動録音テスト (`record_test.sh`)
```bash
bash scripts/record_test.sh TBS 202606271000 1 test_program
```

## 今後の予定
- cron / systemd による定期自動実行（全自動化）
- 過去アーカイブの自動クリーンアップ機能
