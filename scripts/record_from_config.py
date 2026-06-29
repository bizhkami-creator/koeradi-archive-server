#!/usr/bin/env python3
"""
record_from_config.py
---------------------
config/programs.yaml の設定に基づき、指定された日付・曜日に合致する録音対象番組を
自動判定して radiko タイムフリー録音(record_test.sh)を実行するスクリプトです。

使い方:
  python3 scripts/record_from_config.py --today --dry-run
  python3 scripts/record_from_config.py --yesterday --dry-run
  python3 scripts/record_from_config.py --date 2026-06-27
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

def load_station_map():
    """stations.yaml から station_id -> station_name のマッピングを取得"""
    stations_path = PROJECT_ROOT / "config" / "stations.yaml"
    if not stations_path.exists():
        return {}
    with open(stations_path, "r", encoding="utf-8") as f:
        data = yaml.safe_load(f) or {}
    mapping = {}
    for s in data.get("stations", []):
        if isinstance(s, dict) and "station_id" in s and "station_name" in s:
            mapping[s["station_id"]] = s["station_name"]
    return mapping

def sanitize_filename(name: str) -> str:
    r"""
    番組名に含まれるファイル名として使えない禁忌文字やスペースを安全な文字(_)に置換します。
    対象禁忌文字: / \ : * ? " < > | および空白文字
    """
    return re.sub(r'[/\\:*?"<>|\s]', '_', name)

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
    
    # 相互排他的な日付指定オプション
    group = parser.add_mutually_exclusive_group()
    group.add_argument("--today", action="store_true", help="実行日の日付を使用します")
    group.add_argument("--yesterday", action="store_true", help="実行日の前日の日付を使用します")
    group.add_argument("--date", help="録音対象の日付 (形式: YYYY-MM-DD)")
    
    parser.add_argument("--dry-run", action="store_true", help="録音を実行せずに対象番組の確認のみ行います")
    args = parser.parse_args()

    # 日付とモードの決定
    if args.yesterday:
        mode = "yesterday"
        target_date = datetime.date.today() - datetime.timedelta(days=1)
        date_str = target_date.strftime("%Y-%m-%d")
    elif args.date:
        mode = "date"
        date_str = args.date
        try:
            target_date = datetime.datetime.strptime(date_str, "%Y-%m-%d").date()
        except ValueError:
            log_message(f"[ERROR] 日付フォーマットが不正です。YYYY-MM-DD 形式で指定してください: {date_str}")
            sys.exit(1)
    else:
        # --today または何も指定されなかった場合
        mode = "today"
        target_date = datetime.date.today()
        date_str = target_date.strftime("%Y-%m-%d")

    day_of_week = target_date.strftime("%A")  # 例: "Saturday", "Sunday"
    
    log_message("=== record_from_config.py 実行開始 ===")
    log_message(f"モード: {mode}")
    log_message(f"対象日: {date_str}")
    log_message(f"対象曜日: {day_of_week}")
    log_message(f"dry-run: {args.dry_run}")

    config_data = load_config()
    station_map = load_station_map()
    programs = config_data.get("programs", [])
    
    # 対象番組の抽出 (enabled == True かつ 曜日が一致)
    matched_programs = []
    for prog in programs:
        enabled = prog.get("enabled", False)
        prog_day = prog.get("day_of_week", "")
        if enabled and prog_day.lower() == day_of_week.lower():
            matched_programs.append(prog)

    log_message(f"対象番組数: {len(matched_programs)} 件")

    if len(matched_programs) == 0:
        log_message("録音対象はありません")
        log_message("=== record_from_config.py 実行完了 ===\n")
        return

    recorded_any = False

    for prog in matched_programs:
        station_id = prog["station_id"]
        station_name = station_map.get(station_id, station_id)
        raw_program_name = prog["program_name"]
        safe_program_name = sanitize_filename(raw_program_name)
        start_time = str(prog["start_time"])
        duration = str(prog["duration_minutes"])
        
        start_datetime = format_start_datetime(date_str, start_time)
        
        # 保存予定パスの構築 (data/audio/station_name/YYYY/MM/YYYY-MM-DD_番組名.m4a)
        year = date_str[:4]
        month = date_str[5:7]
        rel_output_path = f"data/audio/{station_name}/{year}/{month}/{date_str}_{safe_program_name}.m4a"
        abs_output_path = PROJECT_ROOT / rel_output_path
        
        file_exists = abs_output_path.exists()
        status = "already_exists_skip" if file_exists else "will_record"

        if args.dry_run:
            print("\nWould record:")
            print(f"station_id: {station_id}")
            print(f"station_name: {station_name}")
            print(f"program_name: {raw_program_name}")
            print(f"start_datetime: {start_datetime}")
            print(f"duration_minutes: {duration}")
            print(f"output_path: {rel_output_path}")
            print(f"status: {status}\n")
            log_message(f"[DRY-RUN] 対象番組: {station_id}({station_name}) / {raw_program_name} | パス: {rel_output_path} | ステータス: {status}")
        else:
            log_message(f"保存予定パス: {rel_output_path}")
            if file_exists:
                log_message(f"SKIP: already exists ({rel_output_path})")
            else:
                log_message(f"録音開始: {station_id} - {raw_program_name} (日時: {start_datetime}, 録音時間: {duration}分)")
                
                # record_test.sh を呼び出す (安全化された番組名を渡す)
                cmd = ["bash", str(RECORD_SCRIPT), station_id, start_datetime, duration, safe_program_name]
                try:
                    subprocess.run(cmd, check=True)
                    log_message(f"録音成功: {station_id} - {raw_program_name}")
                    recorded_any = True
                except subprocess.CalledProcessError as e:
                    log_message(f"[ERROR] 録音失敗 (Exit Code: {e.returncode}): {station_id} - {raw_program_name}")
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
