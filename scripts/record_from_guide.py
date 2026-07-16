#!/usr/bin/env python3
"""
record_from_guide.py
---------------------
radiko番組表JSONを取り込み、指定された放送局(station_id)と日付(date)の
全番組(または --limit で指定した件数、--filtered-only でフィルタ抽出した番組)を
自動的に録音するスクリプトです。(Day10 / Day14更新)

使い方:
  python3 scripts/record_from_guide.py --station LFR --date 2026-06-27
  python3 scripts/record_from_guide.py --station LFR --date 2026-06-27 --filtered-only
  python3 scripts/record_from_guide.py --station LFR --date 2026-06-27 --dry-run
  python3 scripts/record_from_guide.py --station LFR --date 2026-06-27 --limit 2
"""

import argparse
import datetime
import json
import os
import re
import subprocess
import sys
from pathlib import Path
import yaml
from recording_runtime import calculate_timeout_seconds, load_recording_settings, run_process_group

# プロジェクトのルートディレクトリおよび関連パスの取得
SCRIPT_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = SCRIPT_DIR.parent
LOG_FILE = PROJECT_ROOT / "logs" / "record_from_guide.log"
RECORD_SCRIPT = SCRIPT_DIR / "record_test.sh"
FETCH_SCRIPT = SCRIPT_DIR / "fetch_program_guide.py"
FILTER_SCRIPT = SCRIPT_DIR / "filter_programs.py"
PROGRAM_GUIDES_DIR = PROJECT_ROOT / "data" / "program_guides"
FILTERED_PROGRAMS_DIR = PROJECT_ROOT / "data" / "filtered_programs"


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


def log_message(msg: str):
    """ログファイルおよび標準出力にメッセージを出力するヘルパー関数"""
    timestamp = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    formatted_msg = f"[{timestamp}] {msg}"
    print(formatted_msg)

    LOG_FILE.parent.mkdir(parents=True, exist_ok=True)
    with open(LOG_FILE, "a", encoding="utf-8") as f:
        f.write(formatted_msg + "\n")


def sanitize_title(name: str) -> str:
    clean = re.sub(r'[/\\:*?"<>|\s]', '_', str(name or ''))
    return clean[:50]

def sanitize_personality(name: str) -> str:
    clean = re.sub(r'[/\\:*?"<>|\s]', '_', str(name or ''))
    return clean[:30]

def parse_start_datetime(start_time_iso: str) -> str:
    """
    ISO 8601風形式 (例: 2026-06-27T11:00:00) を
    radiko用日時文字列 (YYYYMMDDHHMM 形式, 例: 202606271100) に変換します。
    """
    dt = datetime.datetime.fromisoformat(start_time_iso)
    return dt.strftime("%Y%m%d%H%M")


def parse_program_datetimes(prog):
    start_iso = prog.get("start_time")
    end_iso = prog.get("end_time")
    start_dt = datetime.datetime.fromisoformat(start_iso) if start_iso else None
    end_dt = datetime.datetime.fromisoformat(end_iso) if end_iso else None
    if end_dt is None and start_dt is not None:
        duration = int(prog.get("duration_minutes", 0) or 0)
        end_dt = start_dt + datetime.timedelta(minutes=duration)
    return start_dt, end_dt


def is_program_finished(prog, now=None):
    now = now or datetime.datetime.now()
    _, end_dt = parse_program_datetimes(prog)
    return end_dt is not None and end_dt <= now


def main():
    parser = argparse.ArgumentParser(description="radiko番組表JSONに基づく全番組自動録音スクリプト")
    parser.add_argument("--station", required=True, help="放送局ID (例: LFR, TBS)")
    parser.add_argument("--date", required=True, help="対象日付 (形式: YYYY-MM-DD)")
    parser.add_argument("--dry-run", action="store_true", help="録音を実行せずに対象番組の確認のみ行います")
    parser.add_argument("--limit", type=int, default=None, help="録音対象とする番組数の上限 (テスト用)")
    parser.add_argument("--filtered-only", action="store_true", help="キーワードフィルターにマッチした番組のみ録音対象にします")
    args = parser.parse_args()

    station_id = args.station.strip().upper()
    date_str = args.date.strip()
    recording_settings = load_recording_settings()

    # 日付フォーマットの検証
    try:
        datetime.datetime.strptime(date_str, "%Y-%m-%d")
    except ValueError:
        log_message(f"[ERROR] 日付フォーマットが不正です。YYYY-MM-DD 形式で指定してください: {date_str}")
        sys.exit(1)

    station_map = load_station_map()
    station_name = station_map.get(station_id, station_id)
    year = date_str[:4]
    month = date_str[5:7]

    log_message("=== record_from_guide.py 実行開始 ===")
    log_message(f"対象局: {station_id} ({station_name})")
    log_message(f"対象日: {date_str}")
    log_message(f"dry-run: {args.dry_run}")
    log_message(f"filtered-only: {args.filtered_only}")
    if args.limit is not None:
        log_message(f"録音上限(limit): {args.limit} 件")

    programs = []

    if args.filtered_only:
        filtered_json_path = FILTERED_PROGRAMS_DIR / station_id / f"{date_str}.json"
        if not filtered_json_path.exists():
            log_message(f"filtered_programs JSON が存在しません: {filtered_json_path}")
            log_message("filter_programs.py を呼び出して抽出処理を実行します...")
            cmd_filter = [sys.executable, str(FILTER_SCRIPT), "--station", station_id, "--date", date_str]
            try:
                subprocess.run(cmd_filter, check=True, timeout=180)
                log_message("抽出処理の自動実行に成功しました。")
            except subprocess.CalledProcessError as e:
                log_message(f"[ERROR] 抽出処理の自動実行に失敗しました (Exit Code: {e.returncode})")
                sys.exit(1)

        try:
            with open(filtered_json_path, "r", encoding="utf-8") as f:
                filtered_data = json.load(f)
            programs = filtered_data.get("matched_programs", [])
            log_message(f"filtered-only モード: 抽出番組数 {len(programs)} 件")
        except Exception as e:
            log_message(f"[ERROR] filtered_programs JSONの読み込みに失敗しました: {e}")
            sys.exit(1)
    else:
        # 1. 番組表JSONの存在確認と取得
        json_path = PROGRAM_GUIDES_DIR / station_id / f"{date_str}.json"
        if not json_path.exists():
            log_message(f"番組表JSONが存在しません: {json_path}")
            log_message("fetch_program_guide.py を呼び出して番組表を取得します...")
            cmd_fetch = [sys.executable, str(FETCH_SCRIPT), "--station", station_id, "--date", date_str]
            try:
                subprocess.run(cmd_fetch, check=True, timeout=180)
                log_message("番組表の自動取得に成功しました。")
            except subprocess.CalledProcessError as e:
                log_message(f"[ERROR] 番組表の自動取得に失敗しました (Exit Code: {e.returncode})")
                sys.exit(1)
        else:
            log_message(f"既存の番組表JSONを使用します: {json_path}")

        # 2. JSONファイルの読み込み
        try:
            with open(json_path, "r", encoding="utf-8") as f:
                guide_data = json.load(f)
        except Exception as e:
            log_message(f"[ERROR] 番組表JSONの読み込みに失敗しました: {e}")
            sys.exit(1)

        programs = guide_data.get("programs", [])
        total_in_guide = len(programs)
        log_message(f"番組表内の総番組数: {total_in_guide} 件")

    # limitオプションの適用
    if args.limit is not None and args.limit > 0:
        programs = programs[:args.limit]
        log_message(f"録音対象を先頭 {len(programs)} 件に制限しました。")

    target_count = len(programs)
    log_message(f"録音対象番組数: {target_count} 件")

    # 3. dry-run処理または本番録音処理
    if args.dry_run:
        print(f"\nTarget station: {station_id} ({station_name})")
        print(f"Target date: {date_str}")
        print(f"Programs: {target_count}\n")
        print("Would record:")

        for idx, prog in enumerate(programs, 1):
            raw_title = prog.get("title", "無題")
            raw_person = prog.get("personality", "")
            safe_title = sanitize_title(raw_title)
            safe_person = sanitize_personality(raw_person)
            prog_filename_part = f"{safe_title}_{safe_person}" if safe_person else safe_title
            
            start_iso = prog.get("start_time")
            duration = str(prog.get("duration_minutes", 0))
            start_datetime = parse_start_datetime(start_iso)

            rel_output_path = f"data/audio/{station_name}/{year}/{month}/{date_str}_{prog_filename_part}.m4a"
            abs_output_path = PROJECT_ROOT / rel_output_path
            if abs_output_path.exists():
                status = "already_exists_skip"
            elif not is_program_finished(prog):
                status = "not_finished_skip"
            else:
                status = "will_record"

            print(f"{idx}. {raw_title}")
            print(f"   start_datetime: {start_datetime}")
            print(f"   duration_minutes: {duration}")
            print(f"   output_path: {rel_output_path}")
            print(f"   status: {status}\n")

            log_message(f"[DRY-RUN] [{idx}/{target_count}] 番組: {raw_title} | 日時: {start_datetime} | パス: {rel_output_path} | ステータス: {status}")

    else:
        success_count = 0
        fail_count = 0
        timeout_count = 0
        auth_fail_count = 0
        unexpected_count = 0
        skip_count = 0

        for idx, prog in enumerate(programs, 1):
            raw_title = prog.get("title", "無題")
            raw_person = prog.get("personality", "")
            safe_title = sanitize_title(raw_title)
            safe_person = sanitize_personality(raw_person)
            prog_filename_part = f"{safe_title}_{safe_person}" if safe_person else safe_title

            start_iso = prog.get("start_time")
            duration = str(prog.get("duration_minutes", 0))
            timeout_seconds = calculate_timeout_seconds(duration, recording_settings)
            start_datetime = parse_start_datetime(start_iso)

            rel_output_path = f"data/audio/{station_name}/{year}/{month}/{date_str}_{prog_filename_part}.m4a"
            abs_output_path = PROJECT_ROOT / rel_output_path

            log_message(f"[{idx}/{target_count}] 処理中: {raw_title}")
            log_message(f"保存予定パス: {rel_output_path}")

            if abs_output_path.exists():
                log_message(f"SKIP: already_exists_skip ({rel_output_path})")
                skip_count += 1
            elif not is_program_finished(prog):
                _, end_dt = parse_program_datetimes(prog)
                end_text = end_dt.strftime("%Y-%m-%d %H:%M") if end_dt else "不明"
                log_message(f"SKIP: not_finished_skip (終了予定: {end_text})")
                skip_count += 1
            else:
                log_message(f"録音開始: station={station_id} program={raw_title} broadcast={start_datetime} duration_minutes={duration} timeout_seconds={timeout_seconds} output={rel_output_path}")
                cmd = ["bash", str(RECORD_SCRIPT), station_id, start_datetime, duration, prog_filename_part]
                try:
                    outer_timeout = timeout_seconds + recording_settings["terminate_grace_seconds"] + 60
                    result = run_process_group(cmd, outer_timeout, recording_settings["terminate_grace_seconds"])
                    returncode, _, _, python_timeout, kill_sent, elapsed, pid = result
                    if returncode == 0:
                        log_message(f"録音成功: station={station_id} program={raw_title} pid={pid} elapsed_seconds={elapsed:.1f} exit_code=0")
                        success_count += 1
                    elif returncode == 124 or python_timeout:
                        log_message(f"[ERROR] classification=RECORDING_TIMEOUT station={station_id} program={raw_title} pid={pid} elapsed_seconds={elapsed:.1f} timeout_seconds={outer_timeout} sigterm_sent=true sigkill_sent={str(kill_sent).lower()}")
                        timeout_count += 1
                    elif returncode == 65:
                        log_message(f"[ERROR] classification=AUTH_FAILURE station={station_id} program={raw_title} pid={pid} elapsed_seconds={elapsed:.1f} exit_code={returncode} retry=false")
                        auth_fail_count += 1
                    else:
                        log_message(f"[ERROR] classification=RECORDING_FAILED station={station_id} program={raw_title} pid={pid} elapsed_seconds={elapsed:.1f} exit_code={returncode} retry=false")
                        fail_count += 1
                except Exception as e:
                    log_message(f"[ERROR] classification=UNEXPECTED_EXCEPTION station={station_id} program={raw_title} error={type(e).__name__}: {e}")
                    unexpected_count += 1

        # 最終サマリーの出力
        log_message("=== 最終サマリー ===")
        log_message(f"対象番組数: {target_count}")
        log_message(f"成功: {success_count}")
        log_message(f"失敗: {fail_count}")
        log_message(f"認証失敗: {auth_fail_count}")
        log_message(f"タイムアウト: {timeout_count}")
        log_message(f"想定外例外: {unexpected_count}")
        log_message(f"スキップ (既存): {skip_count}")

    log_message("=== record_from_guide.py 実行完了 ===\n")


if __name__ == "__main__":
    main()
