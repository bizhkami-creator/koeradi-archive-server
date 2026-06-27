#!/usr/bin/env python3
"""
record_station_day.py
---------------------
特定放送局(station_id)と日付(date)を指定して、
config/programs.yaml に登録された対象番組をまとめて録音するスクリプトです。

使い方:
  python3 scripts/record_station_day.py --station LFR --date 2026-06-27
  python3 scripts/record_station_day.py --station LFR --date 2026-06-27 --dry-run
"""

import argparse
import datetime
import os
import re
import subprocess
import sys
from pathlib import Path
import yaml

# プロジェクトのルートディレクトリの取得
SCRIPT_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = SCRIPT_DIR.parent
CONFIG_PATH = PROJECT_ROOT / "config" / "programs.yaml"
LOG_FILE = PROJECT_ROOT / "logs" / "record_station_day.log"
RECORD_SCRIPT = SCRIPT_DIR / "record_test.sh"

def log_message(msg: str):
    """ログファイルおよび標準出力にメッセージを出力するヘルパー関数"""
    timestamp = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    formatted_msg = f"[{timestamp}] {msg}"
    print(formatted_msg)
    
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

def sanitize_filename(name: str) -> str:
    r"""
    番組名に含まれるファイル名として使えない禁忌文字やスペースを安全な文字(_)に置換します。
    """
    return re.sub(r'[/\\:*?"<>|\s]', '_', name)

def format_start_datetime(date_str: str, start_time_str: str) -> str:
    """
    date (YYYY-MM-DD) と start_time (HH:MM) から radiko用日時文字列 (YYYYMMDDHHMM) を生成
    """
    clean_date = date_str.replace("-", "")
    clean_time = start_time_str.replace(":", "")
    return f"{clean_date}{clean_time}"

def main():
    parser = argparse.ArgumentParser(description="局別・日付別のバッチ録音スクリプト")
    parser.add_argument("--station", required=True, help="放送局ID (例: LFR, TBS)")
    parser.add_argument("--date", required=True, help="録音対象の日付 (形式: YYYY-MM-DD)")
    parser.add_argument("--dry-run", action="store_true", help="録音を実行せずに対象番組の確認のみ行います")
    args = parser.parse_args()

    station_id_target = args.station.strip()
    date_str = args.date.strip()

    try:
        target_date = datetime.datetime.strptime(date_str, "%Y-%m-%d").date()
    except ValueError:
        log_message(f"[ERROR] 日付フォーマットが不正です。YYYY-MM-DD 形式で指定してください: {date_str}")
        sys.exit(1)

    day_of_week = target_date.strftime("%A")  # 例: "Saturday", "Sunday"
    
    log_message("=== record_station_day.py 実行開始 ===")
    log_message(f"対象局: {station_id_target}")
    log_message(f"対象日: {date_str}")
    log_message(f"対象曜日: {day_of_week}")
    log_message(f"dry-run: {args.dry_run}")

    config_data = load_config()
    programs = config_data.get("programs", [])
    
    # 抽出条件: station_idが一致、enabledがTrue、day_of_weekが指定日の曜日と一致
    matched_programs = []
    for prog in programs:
        st_id = str(prog.get("station_id", "")).strip()
        enabled = prog.get("enabled", False)
        prog_day = str(prog.get("day_of_week", "")).strip()
        
        if st_id.lower() == station_id_target.lower() and enabled and prog_day.lower() == day_of_week.lower():
            matched_programs.append(prog)

    log_message(f"対象番組数: {len(matched_programs)} 件")

    if args.dry_run:
        print(f"\nTarget station: {station_id_target}")
        print(f"Target date: {date_str}")
        print(f"Target weekday: {day_of_week}")
        print(f"Target programs: {len(matched_programs)}\n")
        
        if len(matched_programs) == 0:
            print("Would record:\n(No matching programs found)")
        else:
            print("Would record:")
            for idx, prog in enumerate(matched_programs, 1):
                raw_prog_name = prog["program_name"]
                safe_prog_name = sanitize_filename(raw_prog_name)
                start_time = str(prog["start_time"])
                duration = str(prog["duration_minutes"])
                start_datetime = format_start_datetime(date_str, start_time)
                
                rel_output_path = f"data/audio/{station_id_target}/{date_str}_{station_id_target}_{safe_prog_name}.m4a"
                abs_output_path = PROJECT_ROOT / rel_output_path
                file_exists = abs_output_path.exists()
                status = "already_exists_skip" if file_exists else "will_record"

                print(f"{idx}. {raw_prog_name}")
                print(f"   start_datetime: {start_datetime}")
                print(f"   duration_minutes: {duration}")
                print(f"   output_path: {rel_output_path}")
                print(f"   status: {status}\n")
                log_message(f"[DRY-RUN] 番組: {raw_prog_name} | 日時: {start_datetime} | パス: {rel_output_path} | ステータス: {status}")

    else:
        if len(matched_programs) == 0:
            log_message("録音対象はありません")
        
        for prog in matched_programs:
            raw_prog_name = prog["program_name"]
            safe_prog_name = sanitize_filename(raw_prog_name)
            start_time = str(prog["start_time"])
            duration = str(prog["duration_minutes"])
            start_datetime = format_start_datetime(date_str, start_time)
            
            rel_output_path = f"data/audio/{station_id_target}/{date_str}_{station_id_target}_{safe_prog_name}.m4a"
            abs_output_path = PROJECT_ROOT / rel_output_path
            
            log_message(f"保存予定パス: {rel_output_path}")
            if abs_output_path.exists():
                log_message(f"SKIP: already exists ({rel_output_path})")
            else:
                log_message(f"録音開始: {station_id_target} - {raw_prog_name} (日時: {start_datetime}, 録音時間: {duration}分)")
                cmd = ["bash", str(RECORD_SCRIPT), station_id_target, start_datetime, duration, safe_prog_name]
                try:
                    subprocess.run(cmd, check=True)
                    log_message(f"録音成功: {station_id_target} - {raw_prog_name}")
                except subprocess.CalledProcessError as e:
                    log_message(f"[ERROR] 録音失敗 (Exit Code: {e.returncode}): {station_id_target} - {raw_prog_name}")
                except Exception as e:
                    log_message(f"[ERROR] 予期せぬエラーで録音失敗: {e}")

    log_message("=== record_station_day.py 実行完了 ===\n")

if __name__ == "__main__":
    main()
