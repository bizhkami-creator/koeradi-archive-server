#!/usr/bin/env python3
"""
Settings画面から起動する長時間ジョブのラッパー。

Flaskリクエストをブロックしないよう、web_admin/app.py から Popen で起動され、
開始・終了状態を logs/settings_jobs.log にJSON Lines形式で記録します。
"""

import argparse
import datetime
import json
import subprocess
import sys
from pathlib import Path


SCRIPT_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = SCRIPT_DIR.parent
LOG_FILE = PROJECT_ROOT / "logs" / "settings_jobs.log"


def log_event(job_name, command, drive_enabled, status, message, exit_code=None):
    LOG_FILE.parent.mkdir(parents=True, exist_ok=True)
    event = {
        "timestamp": datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "job_name": job_name,
        "command": command,
        "drive_enabled": drive_enabled,
        "status": status,
        "message": message,
        "exit_code": exit_code,
    }
    with open(LOG_FILE, "a", encoding="utf-8") as f:
        f.write(json.dumps(event, ensure_ascii=False) + "\n")


def main():
    parser = argparse.ArgumentParser(description="Settings job runner")
    parser.add_argument("--job-name", required=True)
    parser.add_argument("--drive-enabled", required=True, choices=["true", "false"])
    parser.add_argument("command", nargs=argparse.REMAINDER)
    args = parser.parse_args()

    command = args.command
    if command and command[0] == "--":
        command = command[1:]

    if not command:
        log_event(args.job_name, "", args.drive_enabled == "true", "failed", "実行コマンドが指定されていません。", 2)
        return 2

    command_text = " ".join(command)
    drive_enabled = args.drive_enabled == "true"
    log_event(args.job_name, command_text, drive_enabled, "running", "Job started")

    try:
        with open(LOG_FILE, "a", encoding="utf-8") as log_f:
            log_f.write(f"[{datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] --- command output start: {args.job_name} ---\n")
            proc = subprocess.run(command, cwd=PROJECT_ROOT, stdout=log_f, stderr=subprocess.STDOUT)
            log_f.write(f"[{datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] --- command output end: {args.job_name} ---\n")
        status = "success" if proc.returncode == 0 else "failed"
        message = "Job completed" if proc.returncode == 0 else "Job failed"
        log_event(args.job_name, command_text, drive_enabled, status, message, proc.returncode)
        return proc.returncode
    except Exception as e:
        log_event(args.job_name, command_text, drive_enabled, "failed", f"起動失敗: {e}", 1)
        return 1


if __name__ == "__main__":
    sys.exit(main())
