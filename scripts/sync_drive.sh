#!/bin/bash
# ==============================================================================
# sync_drive.sh
# ------------------------------------------------------------------------------
# ローカルのアーカイブデータ (data/) を Google Drive (koeradi-drive:KoeRadiArchive)
# へ同期するスクリプトです。同期前に自動で generate_metadata.py を実行します。
#
# 使い方:
#   bash scripts/sync_drive.sh
#   bash scripts/sync_drive.sh --dry-run
# ==============================================================================

set -euo pipefail

# プロジェクトのルートディレクトリとパスの設定
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(dirname "$SCRIPT_DIR")"
DATA_DIR="$PROJECT_ROOT/data"
LOG_FILE="$PROJECT_ROOT/logs/sync_drive.log"
METADATA_SCRIPT="$SCRIPT_DIR/generate_metadata.py"

REMOTE_NAME="koeradi-drive"
DEST_FOLDER="KoeRadiArchive"

mkdir -p "$PROJECT_ROOT/logs"

log() {
    echo "[$(date '+%Y-%m-%d %H:%M:%S')] $*" | tee -a "$LOG_FILE"
}

log_error() {
    echo "[$(date '+%Y-%m-%d %H:%M:%S')] [ERROR] $*" | tee -a "$LOG_FILE" >&2
}

# 引数の解析 (--dry-run)
DRY_RUN_FLAG=""
IS_DRY_RUN=false
for arg in "$@"; do
    if [ "$arg" == "--dry-run" ]; then
        DRY_RUN_FLAG="--dry-run"
        IS_DRY_RUN=true
    fi
done

log "=== Google Drive 同期スクリプト開始 ==="
if [ "$IS_DRY_RUN" = true ]; then
    log "[MODE] dry-run モードで実行中 (実際の転送は行われません)"
fi

# 1. rclone コマンドの存在確認
if ! command -v rclone &> /dev/null; then
    log_error "rclone がインストールされていません。"
    log_error "Raspberry Pi に rclone をインストールしてください: sudo apt install rclone"
    exit 1
fi

# 2. koeradi-drive: リモートの設定確認
if ! rclone listremotes 2>/dev/null | grep -q "^${REMOTE_NAME}:"; then
    log_error "rclone リモート '${REMOTE_NAME}:' が設定されていません。"
    log_error "'rclone config' を実行し、Google Drive リモートとして '${REMOTE_NAME}' を作成してください。"
    log_error "詳細な設定手順は docs/rclone_setup.md を参照してください。"
    exit 1
fi

# 3. 同期前にメタデータを更新
log "同期前のメタデータ自動更新を実行中..."
if python3 "$METADATA_SCRIPT"; then
    log "メタデータ自動更新完了"
else
    log_error "メタデータ自動更新に失敗しました"
    exit 1
fi

# 4. 同期処理の実行
log "送信元: $DATA_DIR"
log "送信先: ${REMOTE_NAME}:${DEST_FOLDER}"

set +e
rclone sync "$DATA_DIR" "${REMOTE_NAME}:${DEST_FOLDER}" --progress $DRY_RUN_FLAG 2>&1 | tee -a "$LOG_FILE"
EXIT_CODE="${PIPESTATUS[0]}"
set -e

if [ "$EXIT_CODE" -eq 0 ]; then
    log "=== Google Drive 同期完了 (成功) ==="
else
    log_error "=== Google Drive 同期失敗 (Exit Code: $EXIT_CODE) ==="
    exit "$EXIT_CODE"
fi
