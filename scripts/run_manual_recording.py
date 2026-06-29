#!/usr/bin/env python3
"""
run_manual_recording.py
------------------------
Web管理画面の Manual Recording からバックグラウンド起動され、
指定された日付と放送局リストに対してキーワード抽出・自動録音・
メタデータ更新・Google Drive同期を一括実行するスクリプトです。

ログは logs/manual_recording.log に書き込まれます。
"""

import argparse
import datetime
import os
import subprocess
import sys
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = SCRIPT_DIR.parent
LOG_FILE = PROJECT_ROOT / "logs" / "manual_recording.log"
RECORD_GUIDE_SH = SCRIPT_DIR / "record_guide_day.sh"
METADATA_SCRIPT = SCRIPT_DIR / "generate_metadata.py"
SYNC_DRIVE_SH = SCRIPT_DIR / "sync_drive.sh"

def log_msg(msg: str, mode: str = "a"):
    timestamp = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    formatted = f"[{timestamp}] {msg}"
    print(formatted)
    LOG_FILE.parent.mkdir(parents=True, exist_ok=True)
    with open(LOG_FILE, mode, encoding="utf-8") as f:
        f.write(formatted + "\n")

def main():
    parser = argparse.ArgumentParser(description="手動録音バックグラウンド実行ランナー")
    parser.add_argument("--date", required=True, help="対象日付 (YYYY-MM-DD)")
    parser.add_argument("--stations", nargs="+", required=True, help="対象放送局IDリスト")
    args = parser.parse_args()

    date_str = args.date.strip()
    stations = args.stations

    log_msg("==================================================", mode="a")
    log_msg("=== Web管理画面からの手動録音ジョブ開始 ===")
    log_msg(f"対象日: {date_str}")
    log_msg(f"対象局: {', '.join(stations)}")
    log_msg(f"実行コマンド: python3 scripts/run_manual_recording.py --date {date_str} --stations {' '.join(stations)}")

    success_count = 0
    fail_count = 0

    for station in stations:
        log_msg("--------------------------------------------------")
        log_msg(f">>> [放送局: {station}] 録音処理実行中...")
        cmd = ["bash", str(RECORD_GUIDE_SH), station, date_str, "--filtered"]
        try:
            res = subprocess.run(cmd, capture_output=True, text=True, check=True)
            if res.stdout:
                with open(LOG_FILE, "a", encoding="utf-8") as f:
                    f.write(res.stdout + "\n")
            log_msg(f">>> [放送局: {station}] 録音処理成功")
            success_count += 1
        except subprocess.CalledProcessError as e:
            if e.stdout:
                with open(LOG_FILE, "a", encoding="utf-8") as f:
                    f.write(e.stdout + "\n")
            if e.stderr:
                with open(LOG_FILE, "a", encoding="utf-8") as f:
                    f.write(f"[ERROR] {e.stderr}\n")
            log_msg(f"[ERROR] >>> [放送局: {station}] 録音処理失敗 (Exit Code: {e.returncode})")
            fail_count += 1

    log_msg("--------------------------------------------------")
    log_msg("メタデータ(metadata.json)の自動更新を実行中...")
    try:
        subprocess.run([sys.executable, str(METADATA_SCRIPT)], check=True)
        log_msg("メタデータ自動更新成功")
    except Exception as e:
        log_msg(f"[ERROR] メタデータ自動更新失敗: {e}")

    log_msg("--------------------------------------------------")
    log_msg("Google Drive 同期を実行中...")
    try:
        subprocess.run(["bash", str(SYNC_DRIVE_SH)], check=True)
        log_msg("Google Drive 同期成功")
    except Exception as e:
        log_msg(f"[ERROR] Google Drive 同期失敗: {e}")

    log_msg("==================================================")
    log_msg(f"=== 手動録音ジョブ完了サマリー (成功局: {success_count}, 失敗局: {fail_count}) ===")
    log_msg("==================================================\n")

if __name__ == "__main__":
    main()
