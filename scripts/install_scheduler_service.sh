#!/bin/bash
# ==============================================================================
# install_scheduler_service.sh
# ------------------------------------------------------------------------------
# KoeRadi Scheduler の systemd service/timer をインストールして有効化します。
# ==============================================================================

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(dirname "$SCRIPT_DIR")"

SERVICE_SRC="$PROJECT_ROOT/systemd/koeradi-scheduler.service"
TIMER_SRC="$PROJECT_ROOT/systemd/koeradi-scheduler.timer"
SERVICE_DEST="/etc/systemd/system/koeradi-scheduler.service"
TIMER_DEST="/etc/systemd/system/koeradi-scheduler.timer"

if [ ! -f "$SERVICE_SRC" ]; then
    echo "[ERROR] service file not found: $SERVICE_SRC" >&2
    exit 1
fi

if [ ! -f "$TIMER_SRC" ]; then
    echo "[ERROR] timer file not found: $TIMER_SRC" >&2
    exit 1
fi

echo "Installing KoeRadi scheduler systemd files..."
sudo cp "$SERVICE_SRC" "$SERVICE_DEST"
sudo cp "$TIMER_SRC" "$TIMER_DEST"

echo "Reloading systemd..."
sudo systemctl daemon-reload

echo "Enabling and starting koeradi-scheduler.timer..."
sudo systemctl enable koeradi-scheduler.timer
sudo systemctl start koeradi-scheduler.timer

echo
echo "Timer status:"
systemctl status koeradi-scheduler.timer --no-pager

echo
echo "KoeRadi timers:"
systemctl list-timers --all | grep koeradi || true
