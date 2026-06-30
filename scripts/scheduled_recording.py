#!/usr/bin/env python3
"""
systemd timer から呼ばれる定期録音エントリーポイント。

config/settings.yaml の scheduler 設定に基づき、対象期間分の録音ジョブを実行します。
"""

import argparse
import datetime
import json
import os
import subprocess
import sys
from pathlib import Path

try:
    import yaml
except ImportError:
    yaml = None


SCRIPT_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = SCRIPT_DIR.parent
SETTINGS_FILE = PROJECT_ROOT / "config" / "settings.yaml"
LOG_FILE = PROJECT_ROOT / "logs" / "scheduler.log"
MOUNT_PATH = Path("/mnt/koeradi")

DEFAULT_SETTINGS = {
    "drive": {
        "enabled": True,
    },
    "scheduler": {
        "enabled": False,
        "mode": "filtered",
        "interval": "daily",
        "hour": 3,
        "minute": 0,
        "lookback_days": 7,
    },
}

VALID_MODES = {"filtered", "full"}
VALID_INTERVALS = {"hourly", "every_6_hours", "daily", "weekly"}
VALID_LOOKBACK_DAYS = {1, 3, 7}


def log_line(message):
    timestamp = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    formatted = f"[{timestamp}] {message}"
    print(formatted)
    LOG_FILE.parent.mkdir(parents=True, exist_ok=True)
    with open(LOG_FILE, "a", encoding="utf-8") as f:
        f.write(formatted + "\n")


def log_event(event):
    event = {
        "timestamp": datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        **event,
    }
    LOG_FILE.parent.mkdir(parents=True, exist_ok=True)
    with open(LOG_FILE, "a", encoding="utf-8") as f:
        f.write(json.dumps(event, ensure_ascii=False) + "\n")


def normalize_settings(raw):
    raw = raw or {}
    scheduler = raw.get("scheduler") or {}
    drive = raw.get("drive") or {}

    mode = scheduler.get("mode", DEFAULT_SETTINGS["scheduler"]["mode"])
    if mode not in VALID_MODES:
        mode = DEFAULT_SETTINGS["scheduler"]["mode"]

    interval = scheduler.get("interval", DEFAULT_SETTINGS["scheduler"]["interval"])
    if interval not in VALID_INTERVALS:
        interval = DEFAULT_SETTINGS["scheduler"]["interval"]

    try:
        hour = int(scheduler.get("hour", DEFAULT_SETTINGS["scheduler"]["hour"]))
    except (TypeError, ValueError):
        hour = DEFAULT_SETTINGS["scheduler"]["hour"]

    try:
        minute = int(scheduler.get("minute", DEFAULT_SETTINGS["scheduler"]["minute"]))
    except (TypeError, ValueError):
        minute = DEFAULT_SETTINGS["scheduler"]["minute"]

    try:
        lookback_days = int(scheduler.get("lookback_days", DEFAULT_SETTINGS["scheduler"]["lookback_days"]))
    except (TypeError, ValueError):
        lookback_days = DEFAULT_SETTINGS["scheduler"]["lookback_days"]
    if lookback_days not in VALID_LOOKBACK_DAYS:
        lookback_days = DEFAULT_SETTINGS["scheduler"]["lookback_days"]

    return {
        "drive": {
            "enabled": bool(drive.get("enabled", DEFAULT_SETTINGS["drive"]["enabled"])),
        },
        "scheduler": {
            "enabled": bool(scheduler.get("enabled", DEFAULT_SETTINGS["scheduler"]["enabled"])),
            "mode": mode,
            "interval": interval,
            "hour": min(max(hour, 0), 23),
            "minute": min(max(minute, 0), 59),
            "lookback_days": lookback_days,
        },
    }


def load_settings():
    if yaml is None:
        log_line("[ERROR] PyYAML is required.")
        return None

    if not SETTINGS_FILE.exists():
        SETTINGS_FILE.parent.mkdir(parents=True, exist_ok=True)
        with open(SETTINGS_FILE, "w", encoding="utf-8") as f:
            yaml.dump(DEFAULT_SETTINGS, f, allow_unicode=True, sort_keys=False)

    try:
        with open(SETTINGS_FILE, "r", encoding="utf-8") as f:
            data = yaml.safe_load(f) or {}
    except Exception as e:
        log_line(f"[ERROR] settings.yaml の読み込みに失敗しました: {e}")
        return None

    settings = normalize_settings(data)
    if settings != data:
        with open(SETTINGS_FILE, "w", encoding="utf-8") as f:
            yaml.dump(settings, f, allow_unicode=True, sort_keys=False)
    return settings


def is_mount_available():
    return MOUNT_PATH.exists() and os.path.ismount(MOUNT_PATH)


def build_target_dates(lookback_days):
    today = datetime.date.today()
    return [
        (today - datetime.timedelta(days=offset)).strftime("%Y-%m-%d")
        for offset in range(1, lookback_days + 1)
    ]


def build_command(target_date, mode, dry_run):
    command = ["bash", "scripts/run_date_all.sh", target_date]
    if mode == "filtered":
        command.append("--filtered")
    if dry_run:
        command.append("--dry-run")
    return command


def main():
    parser = argparse.ArgumentParser(description="KoeRadi scheduled recording runner")
    parser.add_argument("--dry-run", action="store_true", help="録音・同期を行わず実行内容だけ確認します")
    parser.add_argument("--force", action="store_true", help="scheduler.enabled=falseでも手動テストとして実行します")
    args = parser.parse_args()

    log_line("==================================================")
    log_line("=== scheduled_recording.py 実行開始 ===")

    settings = load_settings()
    if settings is None:
        log_event({
            "scheduler_enabled": None,
            "mode": None,
            "interval": None,
            "command": None,
            "status": "failed",
            "message": "settings.yaml の読み込みに失敗しました。",
            "exit_code": 1,
        })
        return 1

    scheduler = settings["scheduler"]
    enabled = scheduler["enabled"]
    mode = scheduler["mode"]
    interval = scheduler["interval"]
    lookback_days = scheduler["lookback_days"]
    target_dates = build_target_dates(lookback_days)

    log_line(f"scheduler.enabled: {enabled}")
    log_line(f"mode: {mode}")
    log_line(f"interval: {interval}")
    log_line(f"lookback_days: {lookback_days}")
    log_line(f"対象日一覧: {', '.join(target_dates)}")
    log_line(f"dry-run: {args.dry_run}")
    log_line(f"force: {args.force}")

    if not enabled and not args.force:
        message = "scheduler.enabled が false のため録音ジョブは実行しません。"
        log_line(message)
        log_event({
            "scheduler_enabled": enabled,
            "mode": mode,
            "interval": interval,
            "lookback_days": lookback_days,
            "target_dates": target_dates,
            "command": None,
            "status": "skipped",
            "message": message,
            "exit_code": 0,
        })
        return 0
    if not enabled and args.force:
        log_line("scheduler.enabled は false ですが、--force のため手動実行します。")

    if not is_mount_available():
        message = f"{MOUNT_PATH} がマウントされていないため録音ジョブを中止します。"
        log_line(f"[ERROR] {message}")
        log_event({
            "scheduler_enabled": enabled,
            "mode": mode,
            "interval": interval,
            "lookback_days": lookback_days,
            "target_dates": target_dates,
            "command": None,
            "status": "failed",
            "message": message,
            "exit_code": 1,
        })
        return 1

    commands = [build_command(target_date, mode, args.dry_run) for target_date in target_dates]
    command_text = " && ".join(" ".join(command) for command in commands)
    log_line(f"実行コマンド一覧: {command_text}")
    log_event({
        "scheduler_enabled": enabled,
        "mode": mode,
        "interval": interval,
        "lookback_days": lookback_days,
        "target_dates": target_dates,
        "command": command_text,
        "status": "running",
        "message": "録音ジョブを開始しました。",
        "exit_code": None,
    })

    success_dates = []
    failed_dates = []
    last_returncode = 0

    try:
        for target_date, command in zip(target_dates, commands):
            per_command_text = " ".join(command)
            log_line(f"--- 対象日開始: {target_date} ---")
            log_line(f"実行コマンド: {per_command_text}")
            with open(LOG_FILE, "a", encoding="utf-8") as log_f:
                log_f.write(f"[{datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] --- command output start: {target_date} ---\n")
                proc = subprocess.run(command, cwd=PROJECT_ROOT, stdout=log_f, stderr=subprocess.STDOUT)
                log_f.write(f"[{datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] --- command output end: {target_date} ---\n")
            last_returncode = proc.returncode
            if proc.returncode == 0:
                success_dates.append(target_date)
                log_line(f"--- 対象日終了: {target_date} 成功 exit_code=0 ---")
            else:
                failed_dates.append(target_date)
                log_line(f"--- 対象日終了: {target_date} 失敗 exit_code={proc.returncode} ---")
    except Exception as e:
        message = f"録音ジョブの起動に失敗しました: {e}"
        log_line(f"[ERROR] {message}")
        log_event({
            "scheduler_enabled": enabled,
            "mode": mode,
            "interval": interval,
            "lookback_days": lookback_days,
            "target_dates": target_dates,
            "command": command_text,
            "status": "failed",
            "message": message,
            "exit_code": 1,
        })
        return 1

    status = "success" if not failed_dates else "failed"
    message = "録音ジョブが正常終了しました。" if not failed_dates else "一部の日付の録音ジョブが失敗しました。"
    exit_code = 0 if not failed_dates else last_returncode or 1
    log_line(f"{message} success_dates={len(success_dates)} failed_dates={len(failed_dates)} exit_code={exit_code}")
    log_event({
        "scheduler_enabled": enabled,
        "mode": mode,
        "interval": interval,
        "lookback_days": lookback_days,
        "target_dates": target_dates,
        "command": command_text,
        "status": status,
        "message": message,
        "success_dates": success_dates,
        "failed_dates": failed_dates,
        "skipped_count": None,
        "exit_code": exit_code,
    })
    log_line("=== scheduled_recording.py 実行終了 ===")
    return exit_code


if __name__ == "__main__":
    sys.exit(main())
