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
│   ├── metadata/             # 生成されたメタデータ(metadata.json)の保存先
│   └── program_guides/       # 取得したradiko番組表JSONの保存先
├── docs/
│   └── rclone_setup.md       # Google Drive (rclone) 設定ガイド
├── scripts/
│   ├── run_daily.sh          # 全局一括実行スクリプト (自動録音 ➔ メタデータ更新 ➔ クラウド同期)
│   ├── record_station_day.sh # 局別・日付別バッチ録音スクリプト (録音 ➔ メタデータ更新 ➔ クラウド同期)
│   ├── record_station_day.py # 局別・日付別判定録音スクリプト
│   ├── fetch_program_guide.py# radiko番組表JSON取得スクリプト
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
- **Day6**: 一括実行運用スクリプト (`run_daily.sh`) の追加。全自動録音・メタデータ更新・クラウド同期を単一コマンドで統合。
- **Day7**: rclone `koeradi-drive:` 実設定と Google Drive 実同期確認完了。
- **Day8**: 局別・日付別バッチ録音機能 (`record_station_day.sh` / `record_station_day.py`) の追加。特定放送局の対象番組をまとめて録音・同期。
- **Day9**: radiko番組表取得機能 (`fetch_program_guide.py`) の追加。放送局IDと日付を指定し番組表XMLを取得・パースしてJSON保存。

## radiko番組表取得の使い方 (`fetch_program_guide.py`)
指定した放送局(例: `LFR`, `TBS`)と日付の番組表を取得し、JSONファイルとして保存します。

```bash
python3 scripts/fetch_program_guide.py --station LFR --date 2026-06-27
python3 scripts/fetch_program_guide.py --station TBS --date 2026-06-27
```

## 局別・日付別バッチ録音の使い方 (`record_station_day.sh`)
特定放送局(例: `LFR`, `TBS`)と日付を指定し、該当する対象番組をまとめて録音・メタデータ更新・Google Drive同期します。

```bash
# dry-run モード (確認のみ)
bash scripts/record_station_day.sh LFR 2026-06-27 --dry-run

# 本番録音・同期実行
bash scripts/record_station_day.sh LFR 2026-06-27
```

## 全局一括運用スクリプトの使い方 (`run_daily.sh`)
```bash
# 昨日の録音・同期を一括実行 (デフォルト動作)
bash scripts/run_daily.sh --yesterday
bash scripts/run_daily.sh --date 2026-06-27
```

## 今後の予定
- 番組表JSONに基づく全番組自動録音・ファイル名安全化連携 (Day10以降)
- cron / systemd による定期自動実行（全自動化）
- 過去アーカイブの自動クリーンアップ機能
