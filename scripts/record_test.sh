#!/bin/bash
# ==============================================================================
# record_test.sh
# ------------------------------------------------------------------------------
# radikoタイムフリーから1番組を手動取得し、KoeRadiの命名規則に従って
# data/audio/<STATION>/ に保存するテストスクリプトです。
#
# 使い方:
#   bash scripts/record_test.sh <station_id> <start_datetime> <duration_minutes> <program_name>
# 例:
#   bash scripts/record_test.sh TBS 202606281000 1 sample
# ==============================================================================

set -euo pipefail

# プロジェクトルートの取得
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(dirname "$SCRIPT_DIR")"

# ログファイルの設定
LOG_FILE="$PROJECT_ROOT/logs/record_test.log"
mkdir -p "$PROJECT_ROOT/logs"

# ログと標準出力の両方にメッセージを出力する関数
log() {
    echo "[$(date '+%Y-%m-%d %H:%M:%S')] $*" | tee -a "$LOG_FILE"
}

log_error() {
    echo "[$(date '+%Y-%m-%d %H:%M:%S')] [ERROR] $*" | tee -a "$LOG_FILE" >&2
}

# 引数のチェック
if [ "$#" -lt 4 ]; then
    log_error "引数が不足しています。"
    log_error "使い方: bash $0 <station_id> <start_datetime> <duration_minutes> <program_name>"
    log_error "例: bash $0 TBS 202606281000 1 sample"
    exit 1
fi

STATION_ID="$1"
START_DATETIME="$2"
DURATION_MINUTES="$3"
PROGRAM_NAME="$4"

# 日時文字列 (YYYYMMDDHHMM...) から YYYY-MM-DD を抽出
if [[ ${#START_DATETIME} -ge 8 ]]; then
    YEAR="${START_DATETIME:0:4}"
    MONTH="${START_DATETIME:4:2}"
    DAY="${START_DATETIME:6:2}"
    DATE_STR="${YEAR}-${MONTH}-${DAY}"
else
    log_error "start_datetime の形式が不正です。YYYYMMDDHHMM 形式で指定してください (入力: $START_DATETIME)"
    exit 1
fi

# 保存先ディレクトリとファイル名の構築
OUTPUT_DIR="$PROJECT_ROOT/data/audio/$STATION_ID"
FILE_NAME="${DATE_STR}_${STATION_ID}_${PROGRAM_NAME}.m4a"
OUTPUT_FILE="$OUTPUT_DIR/$FILE_NAME"

mkdir -p "$OUTPUT_DIR"

log "=== 録音テスト開始 ==="
log "放送局ID: $STATION_ID"
log "開始日時: $START_DATETIME ($DATE_STR)"
log "録音時間: ${DURATION_MINUTES}分"
log "番組名: $PROGRAM_NAME"
log "保存先: $OUTPUT_FILE"

VENDOR_SCRIPT="$SCRIPT_DIR/vendor/rec_radiko_ts.sh"

if [ ! -f "$VENDOR_SCRIPT" ]; then
    log_error "録音スクリプトが見つかりません: $VENDOR_SCRIPT"
    exit 1
fi

# rec_radiko_ts.sh の実行
set +e
"$VENDOR_SCRIPT" -s "$STATION_ID" -f "$START_DATETIME" -d "$DURATION_MINUTES" -o "$OUTPUT_FILE" 2>&1 | tee -a "$LOG_FILE"
EXIT_CODE="${PIPESTATUS[0]}"
set -e

if [ "$EXIT_CODE" -eq 0 ]; then
    log "=== 録音テスト成功 ==="
    log "ファイルが正常に保存されました: $OUTPUT_FILE"
else
    log_error "=== 録音テスト失敗 (Exit Code: $EXIT_CODE) ==="
    log_error "radikoの仕様変更、配信時間外、またはエリア外制限の可能性があります。"
    exit "$EXIT_CODE"
fi
