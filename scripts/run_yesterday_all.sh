#!/bin/bash
# ==============================================================================
# run_yesterday_all.sh
# ------------------------------------------------------------------------------
# 昨日の全対象局(config/stations.yamlに定義)の番組表JSONに基づく自動録音・
# メタデータ更新・Google Drive同期をワンコマンドで一括実行する運用スクリプトです。(Day13更新)
#
# 使い方:
#   bash scripts/run_yesterday_all.sh
#   bash scripts/run_yesterday_all.sh --dry-run
# ==============================================================================

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(dirname "$SCRIPT_DIR")"
LOG_FILE="$PROJECT_ROOT/logs/run_yesterday_all.log"
RECORD_GUIDE_DAY_SH="$SCRIPT_DIR/record_guide_day.sh"
STATIONS_YAML="$PROJECT_ROOT/config/stations.yaml"

mkdir -p "$PROJECT_ROOT/logs"

log() {
    echo "[$(date '+%Y-%m-%d %H:%M:%S')] $*" | tee -a "$LOG_FILE"
}

log_error() {
    echo "[$(date '+%Y-%m-%d %H:%M:%S')] [ERROR] $*" | tee -a "$LOG_FILE" >&2
}

log_warn() {
    echo "[$(date '+%Y-%m-%d %H:%M:%S')] [WARNING] $*" | tee -a "$LOG_FILE"
}

# 引数の解析
IS_DRY_RUN=false
while [[ $# -gt 0 ]]; do
    case "$1" in
        --dry-run)
            IS_DRY_RUN=true
            shift
            ;;
        *)
            log_error "不明な引数です: $1"
            log_error "使い方: bash $0 [--dry-run]"
            exit 1
            ;;
    esac
done

# 昨日の日付の自動計算
TARGET_DATE=$(date -d "yesterday" +%Y-%m-%d)

# 対象局一覧 (config/stations.yaml から取得)
if [ ! -f "$STATIONS_YAML" ]; then
    log_error "設定ファイルが見つかりません: $STATIONS_YAML"
    exit 1
fi

mapfile -t STATIONS < <(python3 -c "
import yaml, sys
try:
    with open('$STATIONS_YAML', 'r', encoding='utf-8') as f:
        data = yaml.safe_load(f)
        stations = data.get('stations', [])
        for s in stations:
            print(s)
except Exception as e:
    sys.stderr.write(str(e) + '\n')
    sys.exit(1)
")

if [ ${#STATIONS[@]} -eq 0 ]; then
    log_error "対象局が指定されていないか、設定ファイルの読み込みに失敗しました。"
    exit 1
fi

DRY_RUN_ARG=""
if [ "$IS_DRY_RUN" = true ]; then
    DRY_RUN_ARG="--dry-run"
fi

START_TIME_SEC=$(date +%s)
START_TIME_STR=$(date '+%Y-%m-%d %H:%M:%S')

log "=================================================="
log "=== run_yesterday_all.sh 一括運用処理開始 ==="
log "=================================================="
log "開始時刻: $START_TIME_STR"
log "対象日: $TARGET_DATE"
log "対象局一覧: ${STATIONS[*]}"
log "dry-run: $IS_DRY_RUN"

SUCCESS_COUNT=0
FAIL_COUNT=0

for station in "${STATIONS[@]}"; do
    log "--------------------------------------------------"
    log ">>> [放送局: $station] 処理開始 (日付: $TARGET_DATE)"
    log "--------------------------------------------------"
    
    STATION_START_SEC=$(date +%s)
    set +e
    bash "$RECORD_GUIDE_DAY_SH" "$station" "$TARGET_DATE" $DRY_RUN_ARG 2>&1 | tee -a "$LOG_FILE"
    STATION_EXIT="${PIPESTATUS[0]}"
    set -e
    STATION_END_SEC=$(date +%s)
    STATION_DURATION=$((STATION_END_SEC - STATION_START_SEC))

    if [ "$STATION_EXIT" -eq 0 ]; then
        log ">>> [放送局: $station] 処理終了: 成功 (実行時間: ${STATION_DURATION}秒)"
        SUCCESS_COUNT=$((SUCCESS_COUNT + 1))
    else
        log_error ">>> [放送局: $station] 処理終了: 失敗 (Exit Code: $STATION_EXIT, 実行時間: ${STATION_DURATION}秒)"
        FAIL_COUNT=$((FAIL_COUNT + 1))
    fi
done

END_TIME_SEC=$(date +%s)
END_TIME_STR=$(date '+%Y-%m-%d %H:%M:%S')
TOTAL_DURATION=$((END_TIME_SEC - START_TIME_SEC))

log "=================================================="
log "=== 最終運用サマリー ==="
log "=================================================="
log "開始時刻: $START_TIME_STR"
log "終了時刻: $END_TIME_STR"
log "対象日: $TARGET_DATE"
log "対象局一覧: ${STATIONS[*]}"
log "総対象局数: ${#STATIONS[@]}"
log "成功局数: $SUCCESS_COUNT"
log "失敗局数: $FAIL_COUNT"
log "総実行時間: ${TOTAL_DURATION}秒"
log "=================================================="

if [ "$FAIL_COUNT" -gt 0 ]; then
    log_warn "一部の放送局で処理中にエラーが発生しました。"
    exit 1
else
    log "すべての放送局の処理が正常に完了しました。"
fi
