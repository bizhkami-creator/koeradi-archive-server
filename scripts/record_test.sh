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

# station_id から station_name を取得
STATION_NAME=$(python3 -c "
import yaml
with open('$PROJECT_ROOT/config/stations.yaml', 'r', encoding='utf-8') as f:
    data = yaml.safe_load(f) or {}
mapping = {s['station_id']: s['station_name'] for s in data.get('stations', []) if isinstance(s, dict)}
print(mapping.get('$STATION_ID', '$STATION_ID'))
" 2>/dev/null || echo "$STATION_ID")

# 保存先ディレクトリとファイル名の構築
OUTPUT_DIR="$PROJECT_ROOT/data/audio/$STATION_NAME/$YEAR/$MONTH"
FILE_NAME="${DATE_STR}_${PROGRAM_NAME}.m4a"
OUTPUT_FILE="$OUTPUT_DIR/$FILE_NAME"
FAILED_DIR="$PROJECT_ROOT/data/failed_recordings/$STATION_NAME/$YEAR/$MONTH"
PART_FILE="$FAILED_DIR/${FILE_NAME%.m4a}.part.m4a"

mkdir -p "$OUTPUT_DIR"
mkdir -p "$FAILED_DIR"

log "=== 録音テスト開始 ==="
log "放送局: $STATION_NAME ($STATION_ID)"
log "開始日時: $START_DATETIME ($DATE_STR)"
log "録音時間: ${DURATION_MINUTES}分"
log "番組名: $PROGRAM_NAME"
log "保存先: $OUTPUT_FILE"

read -r TIMEOUT_SECONDS TERMINATE_GRACE_SECONDS HTTP_IO_TIMEOUT_SECONDS < <(
    python3 - "$PROJECT_ROOT" "$DURATION_MINUTES" <<'PY'
import sys
sys.path.insert(0, sys.argv[1] + "/scripts")
from recording_runtime import calculate_timeout_seconds, load_recording_settings
settings = load_recording_settings()
print(calculate_timeout_seconds(sys.argv[2], settings), settings["terminate_grace_seconds"], settings["http_io_timeout_seconds"])
PY
)

VENDOR_SCRIPT="${KOERADI_VENDOR_SCRIPT:-$SCRIPT_DIR/vendor/rec_radiko_ts.sh}"

if [ ! -f "$VENDOR_SCRIPT" ]; then
    log_error "録音スクリプトが見つかりません: $VENDOR_SCRIPT"
    exit 1
fi

# rec_radiko_ts.sh の実行。正式名は成功時のみ原子的に確定する。
START_EPOCH=$(date +%s)
RUN_OUTPUT_LOG=$(mktemp)
trap 'rm -f "$RUN_OUTPUT_LOG"' EXIT
TMP_BEFORE=$(find /tmp -maxdepth 1 -type d -name 'recradikots_*' -printf '%p\n' 2>/dev/null | sort || true)
log "[INFO] 録音開始: station=$STATION_NAME station_id=$STATION_ID program=$PROGRAM_NAME broadcast=$START_DATETIME duration_minutes=$DURATION_MINUTES timeout_seconds=$TIMEOUT_SECONDS output=$OUTPUT_FILE process=timeout"
set +e
KOERADI_FFMPEG_RW_TIMEOUT_US=$((HTTP_IO_TIMEOUT_SECONDS * 1000000)) \
timeout --verbose --signal=TERM --kill-after="${TERMINATE_GRACE_SECONDS}s" "${TIMEOUT_SECONDS}s" \
    "$VENDOR_SCRIPT" -s "$STATION_ID" -f "$START_DATETIME" -d "$DURATION_MINUTES" -o "$PART_FILE" 2>&1 | tee "$RUN_OUTPUT_LOG" -a "$LOG_FILE"
EXIT_CODE="${PIPESTATUS[0]}"
set -e
ELAPSED_SECONDS=$(( $(date +%s) - START_EPOCH ))
PART_SIZE=$(stat -c '%s' "$PART_FILE" 2>/dev/null || echo 0)
TMP_AFTER=$(find /tmp -maxdepth 1 -type d -name 'recradikots_*' -printf '%p\n' 2>/dev/null | sort || true)
NEW_TMP=$(comm -13 <(printf '%s\n' "$TMP_BEFORE") <(printf '%s\n' "$TMP_AFTER") | paste -sd, -)

if [ "$EXIT_CODE" -eq 0 ]; then
    mv -f "$PART_FILE" "$OUTPUT_FILE"
    OUTPUT_SIZE=$(stat -c '%s' "$OUTPUT_FILE" 2>/dev/null || echo 0)
    log "[INFO] 録音終了: elapsed_seconds=$ELAPSED_SECONDS exit_code=0 size_bytes=$OUTPUT_SIZE output=$OUTPUT_FILE"
    log "=== 録音テスト成功 ==="
    log "ファイルが正常に保存されました: $OUTPUT_FILE"
elif [ "$EXIT_CODE" -eq 124 ] || [ "$EXIT_CODE" -eq 137 ]; then
    SIGKILL_SENT=$(grep -q "signal KILL" "$RUN_OUTPUT_LOG" && echo true || echo false)
    log_error "classification=RECORDING_TIMEOUT station=$STATION_NAME program=$PROGRAM_NAME broadcast=$START_DATETIME elapsed_seconds=$ELAPSED_SECONDS timeout_seconds=$TIMEOUT_SECONDS sigterm_sent=true sigkill_sent=$SIGKILL_SENT partial_file=$PART_FILE partial_size_bytes=$PART_SIZE temp_dirs=${NEW_TMP:-none}"
    exit 124
else
    CLASSIFICATION="RECORDING_FAILED"
    FINAL_EXIT_CODE="$EXIT_CODE"
    if grep -qi 'auth failed' "$RUN_OUTPUT_LOG"; then
        CLASSIFICATION="AUTH_FAILURE"
        FINAL_EXIT_CODE=65
    elif grep -qi 'Document is empty' "$RUN_OUTPUT_LOG"; then
        CLASSIFICATION="EMPTY_RESPONSE"
        FINAL_EXIT_CODE=66
    fi
    STDERR_TAIL=$(tail -n 5 "$RUN_OUTPUT_LOG" | tr '\n' ' ' | sed -E 's/(AuthToken: )[[:graph:]]+/\1[REDACTED]/gi')
    log_error "classification=$CLASSIFICATION station=$STATION_NAME program=$PROGRAM_NAME broadcast=$START_DATETIME elapsed_seconds=$ELAPSED_SECONDS exit_code=$FINAL_EXIT_CODE partial_file=$PART_FILE partial_size_bytes=$PART_SIZE temp_dirs=${NEW_TMP:-none} retry=false stderr_tail=$STDERR_TAIL"
    log_error "=== 録音テスト失敗 (Exit Code: $EXIT_CODE) ==="
    log_error "radikoの仕様変更、配信時間外、またはエリア外制限の可能性があります。"
    exit "$FINAL_EXIT_CODE"
fi
