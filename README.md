# KoeRadi Archive Server

Raspberry Pi上で動作する「KoeRadi Archive Server」のタイムフリー録音およびメタデータ管理・クラウド同期サーバーです。

## 目的
radikoタイムフリーから取得した音声を保存・管理し、Google Driveへ同期することで、Androidアプリ「こえラジ」から検索・再生できるようにするためのサーバー基盤を構築します。

## ディレクトリ構成
```
koeradi-archive/
├── README.md             # プロジェクトの概要と説明書
├── requirements.txt      # 必要なPythonパッケージ一覧
├── config/
│   └── programs.yaml     # 録音対象番組の設定ファイル
├── data/
│   ├── audio/            # 音声ファイルの保存先 (KoeRadi 命名規則で保存)
│   │   └── sample/       # サンプル音声配置フォルダ
│   └── metadata/         # 生成されたメタデータ(metadata.json)の保存先
├── scripts/
│   ├── generate_metadata.py # 音声ファイルからmetadata.jsonを生成するスクリプト
│   ├── record_test.sh       # radikoタイムフリー録音のテストスクリプト
│   ├── sync_drive.sh        # rcloneを使用してGoogle Driveへ同期するスクリプト
│   └── vendor/              # 外部オープンソーススクリプト配置先
│       └── rec_radiko_ts.sh # radikoタイムフリー取得スクリプト
└── logs/                 # ログファイル保存用フォルダ
```

## 外部スクリプトの出典
本プロジェクトでは、radikoタイムフリーからの音声取得に以下の外部オープンソーススクリプトを利用しています。
- **rec_radiko_ts.sh**: [uru2/rec_radiko_ts](https://github.com/uru2/rec_radiko_ts) (MIT License)
  - `scripts/vendor/rec_radiko_ts.sh` に配置しています。

## 開発ステータス
- **Day1**: 基本プロジェクト構造の構築、`metadata.json` 生成機能、`sync_drive.sh` 雛形の作成。
- **Day2**: radikoタイムフリー手動取得機能 (`record_test.sh`) の実装および動作検証、録音音声のGit追跡除外設定。

## 録音テストスクリプトの使い方
手動で1番組を取得し、`data/audio/<STATION>/YYYY-MM-DD_STATION_PROGRAM.m4a` 形式で保存します。

```bash
bash scripts/record_test.sh <station_id> <start_datetime> <duration_minutes> <program_name>
```
**例（2026年6月27日 10:00からの1分間を録音）:**
```bash
bash scripts/record_test.sh TBS 202606271000 1 test_program
```

## 今後の予定
- 複数番組対応・自動スケジュール録音の実装
- cron / systemd による定期自動実行
- 過去アーカイブの自動クリーンアップ機能
