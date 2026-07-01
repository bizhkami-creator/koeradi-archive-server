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
│   ├── programs.yaml         # 録音対象番組の設定ファイル
│   ├── stations.yaml         # 一括録音対象放送局の設定ファイル (Day13追加)
│   ├── recording_rules.yaml  # キーワード録音ルール設定ファイル (Day14追加)
│   └── settings.yaml         # 運用設定ファイル (Day18追加)
├── data/
│   ├── audio/                # 音声ファイルの保存先 (data/audio/{放送局名}/{YYYY}/{MM}/{YYYY-MM-DD}_{番組名}.m4a)
│   │   └── sample/           # サンプル音声配置フォルダ
│   ├── metadata/             # 生成されたメタデータ(metadata.json)の保存先
│   ├── program_guides/       # 取得したradiko番組表JSONの保存先
│   └── filtered_programs/    # キーワード抽出結果JSONの保存先 (Day14追加)
├── docs/
│   └── rclone_setup.md       # Google Drive (rclone) 設定ガイド
├── scripts/
│   ├── run_yesterday_all.sh  # 昨日の全対象局一括録音運用スクリプト (Day14更新)
│   ├── run_date_all.sh       # 指定日の全対象局一括録音運用スクリプト (Day19追加)
│   ├── run_daily.sh          # 全局一括実行スクリプト (自動録音 ➔ メタデータ更新 ➔ クラウド同期)
│   ├── record_guide_day.sh   # 番組表JSONに基づく局別全番組録音バッチスクリプト (Day14更新)
│   ├── record_from_guide.py  # 番組表JSONに基づく全番組自動録音スクリプト (Day14更新)
│   ├── filter_programs.py   # キーワード条件に合致する番組抽出スクリプト (Day14追加)
│   ├── record_station_day.sh # 局別・日付別設定ファイルバッチ録音スクリプト
│   ├── record_station_day.py # 局別・日付別判定録音スクリプト
│   ├── fetch_program_guide.py# radiko番組表JSON取得スクリプト
│   ├── generate_metadata.py  # 音声ファイルからmetadata.jsonを生成するスクリプト
│   ├── record_test.sh        # radikoタイムフリー録音の個別テストスクリプト
│   ├── record_from_config.py # 設定ファイルに基づく自動判定・録音スクリプト
│   ├── sync_drive.sh         # rcloneを使用してGoogle Driveへ同期するスクリプト
│   ├── run_settings_job.py   # Settings画面ジョブ実行ラッパー (Day18追加)
│   ├── scheduled_recording.py# systemd timer用の定期録音エントリーポイント (Day19追加)
│   ├── install_scheduler_service.sh # systemd scheduler timer インストールスクリプト (Day19追加)
│   └── vendor/               # 外部オープンソーススクリプト配置先
│       └── rec_radiko_ts.sh     # radikoタイムフリー取得スクリプト
├── systemd/
│   ├── koeradi-scheduler.service # 定期録音用 systemd service (Day19追加)
│   └── koeradi-scheduler.timer   # 定期録音用 systemd timer (Day19追加)
├── web_admin/                # Web管理画面アプリケーション (Day15/Day18更新)
│   ├── app.py                # Flaskアプリケーション本体 (録音一覧・配信エンドポイント追加)
│   ├── templates/            # HTMLテンプレート (dashboard.html, rules.html, stations.html, recordings.html, settings.html)
│   └── static/               # CSSスタイルシート (style.css)
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
- **Day10**: 番組表JSONに基づく全番組自動録音機能 (`record_from_guide.py` / `record_guide_day.sh`) および昨日の全対象局一括録音スクリプト (`run_yesterday_all.sh`) の追加。番組表全件自動録音、重複スキップ、ファイル名安全化、`--limit` オプション対応。
- **Day11**: 専用ストレージとして外付けHDD (`/dev/sda1`) を初期化・フォーマット(ext4)・`/mnt/koeradi` への自動マウント設定。
- **Day12**: データ保存先を Raspberry Pi SDカードから外付けHDDへ完全移行。`data -> /mnt/koeradi` のシンボリックリンク構造によりコード修正なしで移行完了。
- **Day13**: 複数放送局設定ファイル (`config/stations.yaml`) の導入と `run_yesterday_all.sh` のマルチステーション対応。
- **Day14**: キーワード検索・あいまい検索フィルタリング機能 (`config/recording_rules.yaml` / `filter_programs.py`) の導入と録音の絞り込み機能 (`run_yesterday_all.sh --filtered`) の追加。
- **Day15**: ブラウザからキーワード録音ルールの確認・追加・有効化/無効化・削除および filtered dry-run の実行ができる Web管理画面 (`web_admin/app.py`) を実装。
- **Day16**: サーバーの運用状況（HDD使用率、Google Drive同期状態、録音済み件数、キーワード数、本日の録音予定番組、最新録音履歴）がひと目で確認できる運用ダッシュボードを構築。録音フォルダおよび Google Drive の保存構造を `局名/YYYY/MM/YYYY-MM-DD_番組名.m4a` へ最適化。
- **Day17**: Web管理画面に録音一覧ページ (`/recordings`) および手動録音実行ページ (`/manual-recording`) を追加。ブラウザ上での HTML5 オーディオ直接再生、リアルタイム検索・フィルタリング、バックグラウンドでの非同期録音ジョブ実行（Preview機能・ログ表示機能含む）、および Path Traversal 対策セキュリティ音声配信エンドポイント (`/audio/...`) を構築。
- **Day18**: Web管理画面に Settings 画面 (`/settings`) を追加。Google Drive同期ON/OFF、Scheduler設定ファイル管理、昨日分Dry Run、昨日分録音、今すぐ同期、バックグラウンド実行ジョブのステータス表示を実装。Day18では cron / systemd timer の実設定はまだ行わず、`config/settings.yaml` の管理のみ対応。
- **Day19**: `config/settings.yaml` の Scheduler 設定に基づいて録音ジョブを実行する `scheduled_recording.py` と systemd service/timer を追加。Settings画面から timer/service 状態、Next run time、`logs/scheduler.log` の末尾を確認し、Scheduler dry-run / Run scheduler now をバックグラウンド起動できるようにした。
- **Day19追加対応**: Recordings画面に録音ファイル削除機能を追加。選択した録音ファイルは完全削除せず `data/trash/YYYY-MM-DD_HHMMSS/` へ移動し、`generate_metadata.py` で `metadata.json` を再生成します。チェック時のみ Google Drive 側も `rclone delete` で削除し、操作内容は `logs/delete_recordings.log` に記録します。

## ストレージ構成 (Day11/Day12)
データ保存領域（`data` ディレクトリ）は外付けHDD（`/mnt/koeradi`）へ接続されており、シンボリックリンクを通じて透過的にアクセスされます。

```bash
# マウント状態およびシンボリックリンクの確認
ls -l data
df -h /mnt/koeradi
```

## 設定ファイル構成

### 放送局設定 (`config/stations.yaml`)
`run_yesterday_all.sh` で一括録音対象とする放送局を定義します。放送局を追加・削除する際は本ファイルを編集します。

```yaml
stations:
  - LFR
  - TBS
```

### キーワード録音ルール設定 (`config/recording_rules.yaml`) (Day14)
番組表の全番組録音によるディスク容量の圧迫を防ぐため、特定のキーワードに合致した番組のみを抽出・録音するための設定ファイルです。
`title`（番組名）、`personality`（出演者）、`description`（番組内容）のいずれかにキーワードが含まれるか、類似度判定(threshold 0.75以上)にヒットした番組が抽出されます。

```yaml
rules:
  - name: オードリー
    keyword: オードリー
    enabled: true

  - name: 伊集院光
    keyword: 伊集院光
    enabled: true

  - name: テスト用 ラジオショー
    keyword: ラジオショー
    enabled: false
```

### 運用設定 (`config/settings.yaml`) (Day18/Day19)
Google Drive同期とSchedulerの運用設定を定義します。ファイルが存在しない場合はWeb管理画面または `scheduled_recording.py` 実行時に自動生成されます。

```yaml
drive:
  enabled: true

scheduler:
  enabled: false
  mode: filtered
  interval: daily
  hour: 3
  minute: 0
  lookback_days: 7
```

`scheduler.enabled: true` の場合のみ定期録音ジョブを実行します。`mode: filtered` は `bash scripts/run_date_all.sh <YYYY-MM-DD> --filtered`、`mode: full` は `bash scripts/run_date_all.sh <YYYY-MM-DD>` を実行します。`lookback_days` は `1` / `3` / `7` をサポートし、当日を含めたうえで、`1` は今日＋昨日、`3` は今日＋過去3日、`7` は今日＋過去7日を対象にします。不正値は `7` に補正されます。`interval` は `hourly` / `every_6_hours` / `daily` / `weekly` をサポートします。

## 昨日の全対象局一括録音運用スクリプトの使い方 (`run_yesterday_all.sh`)
`config/stations.yaml` に設定された全局の昨日の番組を自動録音し、メタデータ更新およびGoogle Drive同期まで一括実行します。

```bash
# キーワード抽出録音 (filtered モード) - dry-run
bash scripts/run_yesterday_all.sh --filtered --dry-run

# キーワード抽出録音 (filtered モード) - 本番実行
bash scripts/run_yesterday_all.sh --filtered

# 全番組録音モード (従来動作)
bash scripts/run_yesterday_all.sh --dry-run
bash scripts/run_yesterday_all.sh
```

## 指定日の全対象局一括録音運用スクリプトの使い方 (`run_date_all.sh`) (Day19)
任意の日付を指定して、`config/stations.yaml` の有効局を一括処理します。Schedulerの複数日録音はこのスクリプトを日付ごとに呼び出します。

```bash
bash scripts/run_date_all.sh 2026-06-27 --filtered --dry-run
bash scripts/run_date_all.sh 2026-06-27 --filtered
bash scripts/run_date_all.sh 2026-06-27 --dry-run
bash scripts/run_date_all.sh 2026-06-27
```

## 番組表キーワード抽出の使い方 (`filter_programs.py`) (Day14)
指定した放送局と日付の番組表JSONから、`config/recording_rules.yaml` にヒットする番組を抽出し `data/filtered_programs/{station}/{date}.json` に保存します。

```bash
# dry-run モード (確認のみ)
python3 scripts/filter_programs.py --station LFR --date 2026-06-27 --dry-run

# 本番抽出実行
python3 scripts/filter_programs.py --station LFR --date 2026-06-27
```

## radiko番組表JSONに基づく自動録音の使い方 (Day10/Day14)
番組表JSONまたは抽出結果JSONを利用して、指定した放送局と日付の番組を自動録音・メタデータ更新・Google Drive同期します。

```bash
# キーワード抽出番組のみ録音対象にする場合 (--filtered-only)
python3 scripts/record_from_guide.py --station LFR --date 2026-06-27 --filtered-only --dry-run

# バッチスクリプト実行 (--filtered-only 対応)
bash scripts/record_guide_day.sh LFR 2026-06-27 --filtered-only --dry-run
```

## radiko番組表取得の使い方 (`fetch_program_guide.py`)
指定した放送局(例: `LFR`, `TBS`)と日付の番組表を取得し、JSONファイルとして保存します。

```bash
python3 scripts/fetch_program_guide.py --station LFR --date 2026-06-27
python3 scripts/fetch_program_guide.py --station TBS --date 2026-06-27
```

## 全局一括運用スクリプトの使い方 (`run_daily.sh`)
```bash
# 昨日の録音・同期を一括実行 (デフォルト動作)
bash scripts/run_daily.sh --yesterday
bash scripts/run_daily.sh --date 2026-06-27
```

## Scheduler / systemd timer の使い方 (Day19)
`scripts/scheduled_recording.py` は systemd timer から呼ばれる定期録音エントリーポイントです。`config/settings.yaml` を読み、`scheduler.enabled` が `false` の場合は録音せず正常終了します。外付けHDD `/mnt/koeradi` がマウントされていない場合は録音を中止します。`scheduler.lookback_days` に応じて、当日と過去1/3/7日分を順番に処理します。

### 手動実行
```bash
# 設定に基づくdry-run (lookback_days対象)
python3 scripts/scheduled_recording.py --dry-run

# 設定に基づく本番実行 (lookback_days対象)
python3 scripts/scheduled_recording.py
```

`scheduler.mode` による実行コマンドは以下です。

```bash
# filtered
bash scripts/run_date_all.sh <YYYY-MM-DD> --filtered
bash scripts/run_date_all.sh <YYYY-MM-DD> --filtered --dry-run

# full
bash scripts/run_date_all.sh <YYYY-MM-DD>
bash scripts/run_date_all.sh <YYYY-MM-DD> --dry-run
```

実行結果は `logs/scheduler.log` に記録されます。

### systemd timer インストール
```bash
chmod +x scripts/install_scheduler_service.sh
bash scripts/install_scheduler_service.sh
```

インストールスクリプトは `systemd/koeradi-scheduler.service` と `systemd/koeradi-scheduler.timer` を `/etc/systemd/system/` にコピーし、`daemon-reload`、timerの有効化、起動、状態表示を行います。Day19の timer はまず定期起動の確認を優先し、`OnCalendar=hourly` で起動します。実際に録音するかどうかは `scheduled_recording.py` が `settings.yaml` を見て判断します。

### 状態確認
```bash
systemctl status koeradi-scheduler.timer --no-pager
systemctl list-timers --all | grep koeradi
journalctl -u koeradi-scheduler.service -n 50 --no-pager
tail -100 logs/scheduler.log
```

## Web管理画面・運用ダッシュボードの使い方 (`web_admin/app.py`) (Day15/Day19)
ブラウザからサーバーの運用状態の確認、録音条件の設定変更、および dry-run 実行が行えるWebアプリケーションです。

### 起動方法
```bash
python3 web_admin/app.py
```

### アクセスURL
```text
http://<RaspberryPiのIPアドレス>:8080
```
(ローカル確認の場合は `http://localhost:8080`)

### 機能と使い方
- **運用ダッシュボード (トップページ `/`)** (Day16追加):
  - **システム状態**: 外付けHDDの使用率・空き容量、Google Driveの最終同期日時・結果、録音済み番組総数、登録キーワード数を一目で確認できます。
  - **今日録音対象になる番組**: 本日の番組表から設定ルールにヒットする録音予定番組（放送局、開始時刻、番組名、ヒットしたルール）をリアルタイム表示します。
  - **最新録音履歴**: `metadata.json` に記録された最新20件の録音履歴を表示します。
  - **ナビゲーション・操作ボタン**: `Recording Rules`（ルール設定画面へ移動）、`Dry Run`（シミュレーション実行）、`Refresh`（ダッシュボードの最新情報更新）を備えています。
- **キーワードルールの管理 (`/rules`)**:
  - 録音キーワードの確認、新規追加、有効化/無効化切り替え、削除が可能です。
- **dry-run 実行**:
  - ボタンをクリックすると、昨日の番組表に対するキーワード抽出シミュレーションがブラウザ上で実行され、コンソールに結果が表示されます。
- **Settings画面 (`/settings`)** (Day18/Day19追加):
  - **Google Drive同期ON/OFF**: `drive.enabled` を切り替えます。OFFの場合、自動同期およびWeb画面からの今すぐ同期は実行されず、「Google Drive同期は無効です。」と表示されます。
  - **Scheduler設定**: `enabled`, `mode`, `interval`, `hour`, `minute`, `lookback_days` を保存できます。Day19では systemd timer から `scheduled_recording.py` を起動し、設定値に基づいて録音ジョブを実行またはスキップします。
  - **録音対象期間**: `lookback_days` により、今日＋昨日 / 今日＋過去3日 / 今日＋過去7日を選択できます。Settingsの対象期間Dry Run / 対象期間録音もこの設定に従います。
  - **Scheduler状態表示**: Scheduler service status、Timer status、Next run time、`logs/scheduler.log` の末尾を確認できます。
  - **Testボタン**: 昨日分Dry Run、昨日分録音、今すぐ同期、Scheduler dry-run、Run scheduler now をブラウザからバックグラウンド起動できます。
  - **ステータス表示**: 実行中、成功、失敗、Google Drive同期無効、実行開始時刻、実行コマンド、終了コード、最新ログの一部を表示します。
  - **ジョブログ**: `logs/settings_jobs.log` に実行日時、ジョブ名、コマンド、`drive.enabled`、起動結果、終了コードを記録します。
- **録音削除 (`/recordings`)** (Day19追加対応):
  - 録音カードごとにチェックボックスを表示し、画面上部の「全選択」で一括選択できます。
  - 画面下部の「削除」ボタンで、選択した録音ファイルを `data/trash/YYYY-MM-DD_HHMMSS/` に移動します。完全削除は行いません。
  - 削除前に「本当に削除しますか？」と対象件数を確認します。
  - 削除後は `scripts/generate_metadata.py` を再実行し、`metadata.json` を現在の `data/audio/` の状態から再生成します。
  - 「Google Driveも削除する」にチェックした場合のみ、対象ファイルに対して `rclone delete koeradi-drive:KoeRadiArchive/<relative_path>` を実行します。チェックなしの場合はローカルの trash 移動だけです。
  - 削除操作は `logs/delete_recordings.log` に、日時、件数、対象ファイル、Google Drive削除有無、成功/失敗をJSON Lines形式で記録します。
  - Dashboard にはゴミ箱件数とゴミ箱容量を表示します。

> [!CAUTION]
> **外部公開に関する注意事項**
> 本Web管理画面は家庭内LAN環境での利用を前提としており、ログイン認証機能を備えていません。
> **ポートフォワーディング等によるインターネットへの外部公開は絶対に行わないでください。**

## 今後の予定
- cron / systemd による定期自動実行（全自動化）
- 過去アーカイブの自動クリーンアップ機能
