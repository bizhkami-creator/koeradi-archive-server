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
├── docs/
│   └── rclone_setup.md       # Google Drive (rclone) 設定ガイド
├── scripts/
│   ├── run_daily.sh          # 一括実行運用スクリプト (自動録音 ➔ メタデータ更新 ➔ クラウド同期)
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
- **Day5**: Google Drive同期連携 (`sync_drive.sh`) の強化、`--dry-run` オプション対応、同期前の自動メタデータ更新、エラー判定、rclone設定ガイド ([docs/rclone_setup.md](file:///home/yocchan/koeradi-archive/docs/rclone_setup.md)) の追加。
- **Day6**: 一括実行運用スクリプト (`run_daily.sh`) の追加。自動録音・メタデータ更新・クラウド同期を単一コマンドで統合。※cron化はまだ行わず手動実行で運用。

## 運用スクリプトの使い方 (`run_daily.sh`)
番組録音からメタデータ更新、Google Drive同期までを一括して実行します。
※将来的に cron で深夜自動実行する想定のため、オプションを省略した場合はデフォルトで前日 (`--yesterday`) を対象にします。

```bash
# 昨日の録音・同期を一括実行 (デフォルト動作)
bash scripts/run_daily.sh --yesterday

# 本日の録音・同期を一括実行
bash scripts/run_daily.sh --today

# 指定日の録音・同期を一括実行
bash scripts/run_daily.sh --date 2026-06-27

# dry-run モード (録音・同期共に転送を行わず確認のみ)
bash scripts/run_daily.sh --yesterday --dry-run
```

## 各種個別スクリプトの使い方

### クラウド同期 (`sync_drive.sh`)
```bash
bash scripts/sync_drive.sh --dry-run
bash scripts/sync_drive.sh
```

### 設定ファイルに基づく録音 (`record_from_config.py`)
```bash
python3 scripts/record_from_config.py --today --dry-run
python3 scripts/record_from_config.py
```

### 単一番組の手動録音テスト (`record_test.sh`)
```bash
bash scripts/record_test.sh TBS 202606271000 1 test_program
```

## 今後の予定
- cron / systemd による定期自動実行（全自動化）
- 過去アーカイブの自動クリーンアップ機能
