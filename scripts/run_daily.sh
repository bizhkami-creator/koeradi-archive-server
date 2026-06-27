#!/bin/bash
# ==============================================================================
# run_daily.sh
# ------------------------------------------------------------------------------
# KoeRadi Archive Server の一括実行運用スクリプトです。
# 番組設定に基づく自動録音 (record_from_config.py) と
# Google Drive への同期 (sync_drive.sh) を順番に実行します。
#
# 使い方:
#   bash scripts/run_daily.sh --yesterday
#   bash scripts/run_daily.sh --today
#   bash scripts/run_daily.sh --date 2026-06-27
#   bash scripts/run_daily.sh --yesterday --dry-run
# ==============================================================================

set -euo pipefail

# プロジェクトルートとログパスの設定
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(dirname "$SCRIPT_DIR")"
LOG_FILE="$PROJECT_ROOT/logs/run_daily.log"
RECORD_CONFIG_SCRIPT="$SCRIPT_DIR/record_from_config.py"
SYNC_DRIVE_SCRIPT="$SCRIPT_DIR/sync_drive.sh"

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
DATE_MODE=""
DATE_VAL=""
IS_DRY_RUN=false
DATE_COUNT=0

while [[ $# -gt 0 ]]; do
    case "$1" in
        --today)
            DATE_MODE="today"
            DATE_COUNT=$((DATE_COUNT + 1))
            shift
            ;;
        --yesterday)
            DATE_MODE="yesterday"
            DATE_COUNT=$((DATE_COUNT + 1))
            shift
            ;;
        --date)
            DATE_MODE="date"
            DATE_VAL="${2:-}"
            if [ -z "$DATE_VAL" ]; then
                log_error "--date オプションには日付 (YYYY-MM-DD) を指定してください。"
                exit 1
            fi
            DATE_COUNT=$((DATE_COUNT + 1))
            shift 2
            ;;
        --dry-run)
            IS_DRY_RUN=true
            shift
            ;;
        *)
            log_error "不明な引数です: $1"
            log_error "使い方: bash $0 [--today|--yesterday|--date YYYY-MM-DD] [--dry-run]"
            exit 1
            ;;
    esac
done

# 複数指定のチェック
if [ "$DATE_COUNT" -gt 1 ]; then
    log_error "--today, --yesterday, --date は複数同時指定できません。"
    exit 1
fi

# デフォルトは --yesterday (将来cronで深夜実行する想定)
if [ "$DATE_COUNT" -eq 0 ]; then
    DATE_MODE="yesterday"
fi

# 実行パラメータの構築
RECORD_ARGS=""
if [ "$DATE_MODE" == "today" ]; then
    RECORD_ARGS="--today"
elif [ "$DATE_MODE" == "yesterday" ]; then
    RECORD_ARGS="--yesterday"
elif [ "$DATE_MODE" == "date" ]; then
    RECORD_ARGS="--date $DATE_VAL"
fi

DRY_RUN_ARG=""
if [ "$IS_DRY_RUN" = true ]; then
    DRY_RUN_ARG="--dry-run"
fi

log "=================================================="
log "=== run_daily.sh 一括実行ワークフロー開始 ==="
log "=================================================="
log "対象モード: $DATE_MODE ${DATE_VAL:+(日付: $DATE_VAL)}"
log "dry-run: $IS_DRY_RUN"

# 1. 録音処理 (record_from_config.py) の実行
log "--- [ステップ 1/2] 録音処理開始 ---"
set +e
python3 "$RECORD_CONFIG_SCRIPT" $RECORD_ARGS $DRY_RUN_ARG 2>&1 | tee -a "$LOG_FILE"
RECORD_EXIT="${PIPESTATUS[0]}"
set -e

if [ "$RECORD_EXIT" -ne 0 ]; then
    log_error "録音処理が異常終了しました (Exit Code: $RECORD_EXIT)。Google Drive 同期はスキップします。"
    log "=== ワークフロー中断 (録音失敗) ==="
    exit "$RECORD_EXIT"
fi

log "--- 録音処理完了 ---"

# 2. Google Drive 同期処理 (sync_drive.sh) の実行
log "--- [ステップ 2/2] Google Drive 同期処理開始 ---"
set +e
bash "$SYNC_DRIVE_SCRIPT" $DRY_RUN_ARG 2>&1 | tee -a "$LOG_FILE"
SYNC_EXIT="${PIPESTATUS[0]}"
set -e

if [ "$SYNC_EXIT" -eq 0 ]; then
    log "--- Google Drive 同期完了 ---"
    log "=================================================="
    log "=== ワークフロー正常完了 (録音・同期成功) ==="
    log "=================================================="
else
    log_warn "Google Drive 同期処理が失敗またはスキップされました (Exit Code: $SYNC_EXIT)。"
    log_warn "※ 'koeradi-drive:' リモートが未設定の場合は docs/rclone_setup.md を参照して設定してください。"
    log "=================================================="
    log "=== ワークフロー一部完了 (録音成功 / 同期未完了) ==="
    log "=================================================="
fi
