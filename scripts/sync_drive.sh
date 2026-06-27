#!/bin/bash

# ==============================================================================
# sync_drive.sh
# ------------------------------------------------------------------------------
# rclone を使用して、ローカルのアーカイブデータ (data/) を
# Google Drive 上の KoeRadiArchive フォルダへ同期するスクリプトです。
# ==============================================================================

set -euo pipefail

# プロジェクトのルートディレクトリを取得
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(dirname "$SCRIPT_DIR")"
DATA_DIR="$PROJECT_ROOT/data"

# rcloneのリモート名と同期先フォルダ
REMOTE_NAME="koeradi-drive"
DEST_FOLDER="KoeRadiArchive"

echo "=== Google Drive 同期開始 ==="
echo "送信元: $DATA_DIR"
echo "送信先: ${REMOTE_NAME}:${DEST_FOLDER}"

# rclone コマンドの存在確認
if ! command -v rclone &> /dev/null; then
    echo "エラー: rclone がインストールされていません。"
    echo "Raspberry Piに rclone をインストールし、'rclone config' で ${REMOTE_NAME} を設定してください。"
    exit 1
fi

# 同期処理の実行
rclone sync "$DATA_DIR" "${REMOTE_NAME}:${DEST_FOLDER}" --progress

echo "=== Google Drive 同期完了 ==="
