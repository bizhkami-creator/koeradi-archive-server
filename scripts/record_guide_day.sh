#!/bin/bash
# ==============================================================================
# record_guide_day.sh
# ------------------------------------------------------------------------------
# KoeRadi Archive Server の radiko番組表JSONに基づくバッチ録音スクリプトです。(Day10 / Day14更新)
# 指定した放送局・日付の全番組(または--filtered-onlyで抽出した番組)を録音し、metadata更新および Google Drive 同期を行います。
#
# 使い方:
#   bash scripts/record_guide_day.sh LFR 2026-06-27
#   bash scripts/record_guide_day.sh LFR 2026-06-27 --filtered-only
#   bash scripts/record_guide_day.sh LFR 2026-06-27 --dry-run
#   bash scripts/record_guide_day.sh LFR 2026-06-27 --limit 2
# ==============================================================================

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(dirname "$SCRIPT_DIR")"
LOG_FILE="$PROJECT_ROOT/logs/record_guide_day.log"

RECORD_PY="$SCRIPT_DIR/record_from_guide.py"
METADATA_PY="$SCRIPT_DIR/generate_metadata.py"
SYNC_SH="$SCRIPT_DIR/sync_drive.sh"

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

if [ "$#" -lt 2 ]; then
    log_error "引数が不足しています。"
    log_error "使い方: bash $0 <station_id> <YYYY-MM-DD> [--dry-run] [--limit N] [--filtered-only]"
    log_error "例: bash $0 LFR 2026-06-27 --dry-run --filtered-only"
    exit 1
fi

STATION_ID="$1"
TARGET_DATE="$2"
shift 2

IS_DRY_RUN=false
EXTRA_ARGS=()

while [ "$#" -gt 0 ]; do
    case "$1" in
        --dry-run)
            IS_DRY_RUN=true
            EXTRA_ARGS+=("--dry-run")
            shift
            ;;
        --limit)
            if [ -n "${2:-}" ]; then
                EXTRA_ARGS+=("--limit" "$2")
                shift 2
            else
                log_error "--limit オプションの後に数値が必要です。"
                exit 1
            fi
            ;;
        --filtered|--filtered-only)
            EXTRA_ARGS+=("--filtered-only")
            shift
            ;;
        *)
            log_warn "不明なオプションです: $1"
            shift
            ;;
    esac
done

log "=================================================="
log "=== record_guide_day.sh バッチ処理開始 ==="
log "=================================================="
log "対象局: $STATION_ID"
log "対象日: $TARGET_DATE"
log "dry-run: $IS_DRY_RUN"
if [ "${#EXTRA_ARGS[@]}" -gt 0 ]; then
    log "追加引数: ${EXTRA_ARGS[*]}"
fi

# 1. 録音処理 (record_from_guide.py)
log "--- [ステップ 1/3] 番組表JSONに基づく録音処理開始 ---"
set +e
python3 "$RECORD_PY" --station "$STATION_ID" --date "$TARGET_DATE" "${EXTRA_ARGS[@]}" 2>&1 | tee -a "$LOG_FILE"
RECORD_EXIT="${PIPESTATUS[0]}"
set -e

if [ "$RECORD_EXIT" -ne 0 ]; then
    log_error "録音処理が異常終了しました (Exit Code: $RECORD_EXIT)。以降の処理を中断します。"
    exit "$RECORD_EXIT"
fi

log "--- 番組表録音処理完了 ---"

# 2. メタデータ更新 (generate_metadata.py)
log "--- [ステップ 2/3] メタデータ更新処理開始 ---"
if [ "$IS_DRY_RUN" = true ]; then
    log "[DRY-RUN] メタデータ更新はスキップされます"
else
    set +e
    python3 "$METADATA_PY" 2>&1 | tee -a "$LOG_FILE"
    META_EXIT="${PIPESTATUS[0]}"
    set -e
    if [ "$META_EXIT" -eq 0 ]; then
        log "メタデータ更新成功"
    else
        log_error "メタデータ更新失敗 (Exit Code: $META_EXIT)"
    fi
fi

# 3. Google Drive 同期 (sync_drive.sh)
log "--- [ステップ 3/3] Google Drive 同期処理開始 ---"
SYNC_DRY_RUN_ARG=""
if [ "$IS_DRY_RUN" = true ]; then
    SYNC_DRY_RUN_ARG="--dry-run"
fi

set +e
bash "$SYNC_SH" $SYNC_DRY_RUN_ARG 2>&1 | tee -a "$LOG_FILE"
SYNC_EXIT="${PIPESTATUS[0]}"
set -e

if [ "$SYNC_EXIT" -eq 0 ]; then
    log "--- Google Drive 同期完了 ---"
    log "=================================================="
    log "=== バッチ処理正常完了 (録音・同期成功) ==="
    log "=================================================="
else
    log_warn "Google Drive 同期処理が失敗または警告終了しました (Exit Code: $SYNC_EXIT)。"
    log "=================================================="
    log "=== バッチ処理一部完了 (録音成功 / 同期未完了) ==="
    log "=================================================="
fi
