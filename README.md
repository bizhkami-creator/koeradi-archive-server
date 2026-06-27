# KoeRadi Archive Server (Day1)

Raspberry Pi上で動作する「KoeRadi Archive Server」の初期リポジトリ構造および基盤スクリプトです。

## 目的
radikoタイムフリーから取得した音声を将来的に保存・管理し、Google Driveへ同期することで、Androidアプリ「こえラジ」から検索・再生できるようにするためのサーバー基盤を構築します。

## ディレクトリ構成
```
koeradi-archive/
├── README.md             # プロジェクトの概要と説明書
├── requirements.txt      # 必要なPythonパッケージ一覧
├── config/
│   └── programs.yaml     # 録音対象番組の設定ファイル
├── data/
│   ├── audio/            # 音声ファイルの保存先
│   │   └── sample/       # サンプル音声配置フォルダ
│   └── metadata/         # 生成されたメタデータ(metadata.json)の保存先
├── scripts/
│   ├── generate_metadata.py # 音声ファイルからmetadata.jsonを生成するスクリプト
│   └── sync_drive.sh        # rcloneを使用してGoogle Driveへ同期するスクリプト
└── logs/                 # ログファイル保存用フォルダ
```

## Day1でできること
- プロジェクト基本構造の定義と初期化
- 音声ファイル（`.m4a`, `.mp3`, `.aac`）の走査および `data/metadata/metadata.json` の生成
- rcloneを使用したGoogle Drive同期用シェルスクリプトの雛形準備

## 今後の予定
- radikoからの自動録音・タイムフリー取得処理の実装
- cron / systemd による定期自動実行（録音処理・メタデータ更新・クラウド同期）
- 過去アーカイブの自動クリーンアップ機能

## クラウド同期について
本システムでは、Google Driveとの同期に [rclone](https://rclone.org/) を使用する想定です。
リモート名 `koeradi-drive` としてGoogle Drive上の `KoeRadiArchive` フォルダへ同期を行います。
