#!/bin/bash
# ==============================================================================
# run_yesterday_all.sh
# ------------------------------------------------------------------------------
# 昨日の全対象局(LFR, TBS)の番組表JSONに基づく自動録音・メタデータ更新・
# Google Drive同期をワンコマンドで一括実行する運用スクリプトです。(Day10追加)
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

# 対象局一覧 (ハードコード)
STATIONS=(
    "LFR"
    "TBS"
)

DRY_RUN_ARG=""
if [ "$IS_DRY_RUN" = true ]; then
    DRY_RUN_ARG="--dry-run"
fi

log "=================================================="
log "=== run_yesterday_all.sh 一括運用処理開始 ==="
log "=================================================="
log "対象日: $TARGET_DATE"
log "対象局: ${STATIONS[*]}"
log "dry-run: $IS_DRY_RUN"

SUCCESS_COUNT=0
FAIL_COUNT=0

for station in "${STATIONS[@]}"; do
    log "--------------------------------------------------"
    log ">>> [放送局: $station] 処理開始 (日付: $TARGET_DATE)"
    log "--------------------------------------------------"
    
    set +e
    bash "$RECORD_GUIDE_DAY_SH" "$station" "$TARGET_DATE" $DRY_RUN_ARG 2>&1 | tee -a "$LOG_FILE"
    STATION_EXIT="${PIPESTATUS[0]}"
    set -e

    if [ "$STATION_EXIT" -eq 0 ]; then
        log ">>> [放送局: $station] 処理成功"
        SUCCESS_COUNT=$((SUCCESS_COUNT + 1))
    else
        log_error ">>> [放送局: $station] 処理失敗 (Exit Code: $STATION_EXIT)"
        FAIL_COUNT=$((FAIL_COUNT + 1))
    fi
done

log "=================================================="
log "=== 最終運用サマリー ==="
log "=================================================="
log "対象日: $TARGET_DATE"
log "総対象局数: ${#STATIONS[@]}"
log "成功局数: $SUCCESS_COUNT"
log "失敗局数: $FAIL_COUNT"
log "=================================================="

if [ "$FAIL_COUNT" -gt 0 ]; then
    log_warn "一部の放送局で処理中にエラーが発生しました。"
    exit 1
else
    log "すべての放送局の処理が正常に完了しました。"
fi
