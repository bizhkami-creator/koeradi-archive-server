#!/usr/bin/env python3
"""
record_from_config.py
---------------------
config/programs.yaml の設定に基づき、指定された日付・曜日に合致する録音対象番組を
自動判定して radiko タイムフリー録音(record_test.sh)を実行するスクリプトです。

使い方:
  python3 scripts/record_from_config.py --date 2026-06-27
  python3 scripts/record_from_config.py --date 2026-06-27 --dry-run
"""

import argparse
import datetime
import os
import subprocess
import sys
from pathlib import Path
import yaml

# プロジェクトのルートディレクトリの取得
SCRIPT_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = SCRIPT_DIR.parent
CONFIG_PATH = PROJECT_ROOT / "config" / "programs.yaml"
LOG_FILE = PROJECT_ROOT / "logs" / "record_from_config.log"
RECORD_SCRIPT = SCRIPT_DIR / "record_test.sh"
METADATA_SCRIPT = SCRIPT_DIR / "generate_metadata.py"

def log_message(msg: str):
    """ログファイルおよび標準出力にメッセージを出力するヘルパー関数"""
    timestamp = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    formatted_msg = f"[{timestamp}] {msg}"
    print(formatted_msg)
    
    # ログディレクトリの作成と書き込み
    LOG_FILE.parent.mkdir(parents=True, exist_ok=True)
    with open(LOG_FILE, "a", encoding="utf-8") as f:
        f.write(formatted_msg + "\n")

def load_config():
    """設定ファイルを読み込む"""
    if not CONFIG_PATH.exists():
        log_message(f"[ERROR] 設定ファイルが存在しません: {CONFIG_PATH}")
        sys.exit(1)
    with open(CONFIG_PATH, "r", encoding="utf-8") as f:
        return yaml.safe_load(f)

def format_start_datetime(date_str: str, start_time_str: str) -> str:
    """
    date (YYYY-MM-DD) と start_time (HH:MM) から radiko用日時文字列 (YYYYMMDDHHMM) を生成
    例: "2026-06-27", "10:00" -> "202606271000"
    """
    clean_date = date_str.replace("-", "")
    clean_time = start_time_str.replace(":", "")
    return f"{clean_date}{clean_time}"

def main():
    parser = argparse.ArgumentParser(description="config/programs.yaml に基づく番組録音スクリプト")
    parser.add_argument("--date", required=True, help="録音対象の日付 (形式: YYYY-MM-DD)")
    parser.add_argument("--dry-run", action="store_true", help="録音を実行せずに対象番組の確認のみ行います")
    args = parser.parse_args()

    # 日付の妥当性検証と曜日取得
    try:
        target_date = datetime.datetime.strptime(args.date, "%Y-%m-%d")
    except ValueError:
        log_message(f"[ERROR] 日付フォーマットが不正です。YYYY-MM-DD 形式で指定してください: {args.date}")
        sys.exit(1)

    day_of_week = target_date.strftime("%A")  # 例: "Saturday", "Sunday"
    
    log_message("=== record_from_config.py 実行開始 ===")
    log_message(f"指定日: {args.date} ({day_of_week})")
    if args.dry_run:
        log_message("[MODE] dry-run モードで実行中 (実際の録音は行われません)")

    config_data = load_config()
    programs = config_data.get("programs", [])
    
    # 対象番組の抽出 (enabled == True かつ 曜日が一致)
    matched_programs = []
    for prog in programs:
        enabled = prog.get("enabled", False)
        prog_day = prog.get("day_of_week", "")
        if enabled and prog_day.lower() == day_of_week.lower():
            matched_programs.append(prog)

    log_message(f"対象番組数: {len(matched_programs)} 件")

    recorded_any = False

    for prog in matched_programs:
        station_id = prog["station_id"]
        program_name = prog["program_name"]
        start_time = str(prog["start_time"])
        duration = str(prog["duration_minutes"])
        
        start_datetime = format_start_datetime(args.date, start_time)

        if args.dry_run:
            print("\nWould record:")
            print(f"station_id: {station_id}")
            print(f"program_name: {program_name}")
            print(f"start_datetime: {start_datetime}")
            print(f"duration_minutes: {duration}\n")
            log_message(f"[DRY-RUN] 対象番組検出: {station_id} / {program_name} ({start_datetime})")
        else:
            log_message(f"録音開始: {station_id} - {program_name} (日時: {start_datetime}, 録音時間: {duration}分)")
            
            # record_test.sh を呼び出す
            cmd = ["bash", str(RECORD_SCRIPT), station_id, start_datetime, duration, program_name]
            try:
                result = subprocess.run(cmd, check=True)
                log_message(f"録音成功: {station_id} - {program_name}")
                recorded_any = True
            except subprocess.CalledProcessError as e:
                # 失敗しても他の番組処理を継続できるようにする
                log_message(f"[ERROR] 録音失敗 (Exit Code: {e.returncode}): {station_id} - {program_name}")
            except Exception as e:
                log_message(f"[ERROR] 予期せぬエラーで録音失敗: {e}")

    # 実際の録音が行われた場合、または dry-run ではなく対象が存在した場合に metadata を自動更新
    if not args.dry_run and len(matched_programs) > 0:
        log_message("metadata.json の自動更新を実行中...")
        try:
            subprocess.run(["python3", str(METADATA_SCRIPT)], check=True)
            log_message("metadata更新成功")
        except Exception as e:
            log_message(f"[ERROR] metadata更新失敗: {e}")

    log_message("=== record_from_config.py 実行完了 ===\n")

if __name__ == "__main__":
    main()
