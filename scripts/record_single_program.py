#!/usr/bin/env python3
"""
record_single_program.py
------------------------
指定された単一番組の情報（放送局ID、日付、開始日時、録音時間、番組名、パーソナリティ名）を受け取り、
radikoタイムフリー録音(record_test.sh)を実行して録音・メタデータ更新・クラウド同期を行います。

使い方:
  python3 scripts/record_single_program.py \
    --station LFR \
    --date 2026-06-27 \
    --start 202606272500 \
    --duration 120 \
    --title "オードリーのオールナイトニッポン" \
    --personality "オードリー"
"""

import argparse
import datetime
import os
import re
import subprocess
import sys
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = SCRIPT_DIR.parent
LOG_FILE = PROJECT_ROOT / "logs" / "record_single_program.log"
RECORD_SCRIPT = SCRIPT_DIR / "record_test.sh"
METADATA_SCRIPT = SCRIPT_DIR / "generate_metadata.py"
SYNC_DRIVE_SH = SCRIPT_DIR / "sync_drive.sh"

def log_msg(msg: str):
    timestamp = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    formatted = f"[{timestamp}] {msg}"
    print(formatted)
    LOG_FILE.parent.mkdir(parents=True, exist_ok=True)
    with open(LOG_FILE, "a", encoding="utf-8") as f:
        f.write(formatted + "\n")

def sanitize_title(name: str) -> str:
    clean = re.sub(r'[/\\:*?"<>|\s]', '_', str(name or ''))
    return clean[:50]

def sanitize_personality(name: str) -> str:
    clean = re.sub(r'[/\\:*?"<>|\s]', '_', str(name or ''))
    return clean[:30]

def load_station_map():
    stations_path = PROJECT_ROOT / "config" / "stations.yaml"
    if not stations_path.exists():
        return {}
    try:
        import yaml
        with open(stations_path, "r", encoding="utf-8") as f:
            data = yaml.safe_load(f) or {}
        return {s['station_id']: s['station_name'] for s in data.get('stations', []) if isinstance(s, dict)}
    except Exception:
        return {}

def main():
    parser = argparse.ArgumentParser(description="単一番組即時録音スクリプト")
    parser.add_argument("--station", required=True, help="放送局ID (例: LFR)")
    parser.add_argument("--date", required=True, help="対象日付 (YYYY-MM-DD)")
    parser.add_argument("--start", required=True, help="開始日時文字列 (YYYYMMDDHHMM)")
    parser.add_argument("--duration", required=True, help="録音時間(分)")
    parser.add_argument("--title", required=True, help="番組名")
    parser.add_argument("--personality", default="", help="パーソナリティ名")
    args = parser.parse_args()

    station_id = args.station.strip().upper()
    date_str = args.date.strip()
    start_datetime = args.start.strip()
    duration = str(args.duration).strip()
    raw_title = args.title.strip()
    raw_personality = args.personality.strip()

    safe_title = sanitize_title(raw_title)
    safe_person = sanitize_personality(raw_personality)

    if safe_person:
        prog_filename_part = f"{safe_title}_{safe_person}"
    else:
        prog_filename_part = safe_title

    station_map = load_station_map()
    station_name = station_map.get(station_id, station_id)
    year = date_str[:4]
    month = date_str[5:7]

    rel_output_path = f"data/audio/{station_name}/{year}/{month}/{date_str}_{prog_filename_part}.m4a"
    abs_output_path = PROJECT_ROOT / rel_output_path

    log_msg("=== record_single_program.py 実行開始 ===")
    log_msg(f"対象局: {station_id} ({station_name})")
    log_msg(f"番組名: {raw_title}")
    log_msg(f"パーソナリティ: {raw_personality}")
    log_msg(f"保存予定パス: {rel_output_path}")

    if abs_output_path.exists():
        log_msg(f"SKIP: ファイルが既に存在します ({rel_output_path})")
    else:
        log_msg(f"録音開始: {station_id} - {raw_title} (日時: {start_datetime}, 時間: {duration}分)")
        cmd = ["bash", str(RECORD_SCRIPT), station_id, start_datetime, duration, prog_filename_part]
        try:
            subprocess.run(cmd, check=True)
            log_msg("録音成功")
        except subprocess.CalledProcessError as e:
            log_msg(f"[ERROR] 録音失敗 (Exit Code: {e.returncode})")
            sys.exit(e.returncode)

    log_msg("メタデータ(metadata.json)の自動更新を実行中...")
    try:
        subprocess.run([sys.executable, str(METADATA_SCRIPT)], check=True)
        log_msg("メタデータ自動更新成功")
    except Exception as e:
        log_msg(f"[ERROR] メタデータ自動更新失敗: {e}")

    log_msg("Google Drive 同期を実行中...")
    try:
        subprocess.run(["bash", str(SYNC_DRIVE_SH)], check=True)
        log_msg("Google Drive 同期成功")
    except Exception as e:
        log_msg(f"[ERROR] Google Drive 同期失敗: {e}")

    log_msg("=== record_single_program.py 実行完了 ===\n")

if __name__ == "__main__":
    main()
