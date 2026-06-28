#!/usr/bin/env python3
"""
filter_programs.py
-------------------
radiko番組表JSONとキーワードルール設定(recording_rules.yaml)を読み込み、
条件に一致した番組のみを抽出して data/filtered_programs/{station}/{date}.json に保存します。(Day14)

使い方:
  python3 scripts/filter_programs.py --station LFR --date 2026-06-27
  python3 scripts/filter_programs.py --station LFR --date 2026-06-27 --dry-run
"""

import argparse
import datetime
import difflib
import json
import os
import re
import subprocess
import sys
from pathlib import Path

try:
    import yaml
except ImportError:
    print("[ERROR] PyYAML Package is required.")
    sys.exit(1)

# パス設定
SCRIPT_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = SCRIPT_DIR.parent
LOG_FILE = PROJECT_ROOT / "logs" / "filter_programs.log"
FETCH_SCRIPT = SCRIPT_DIR / "fetch_program_guide.py"
PROGRAM_GUIDES_DIR = PROJECT_ROOT / "data" / "program_guides"
FILTERED_PROGRAMS_DIR = PROJECT_ROOT / "data" / "filtered_programs"
RULES_FILE = PROJECT_ROOT / "config" / "recording_rules.yaml"


def log_message(msg: str):
    """ログファイルおよび標準出力にメッセージを出力するヘルパー関数"""
    timestamp = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    formatted_msg = f"[{timestamp}] {msg}"
    print(formatted_msg)

    LOG_FILE.parent.mkdir(parents=True, exist_ok=True)
    with open(LOG_FILE, "a", encoding="utf-8") as f:
        f.write(formatted_msg + "\n")


def normalize(text) -> str:
    """大文字小文字統一、空白除去、前後スペース削除を行う正規化関数"""
    if not text:
        return ""
    text_str = str(text).strip().lower()
    return re.sub(r'\s+', '', text_str)


def check_match(keyword: str, text: str, threshold: float = 0.75):
    """
    キーワードとテキストの照合を行う。
    部分一致または difflib.SequenceMatcher による類似度が threshold 以上の場合に True を返す。
    """
    norm_kw = normalize(keyword)
    norm_text = normalize(text)
    if not norm_kw or not norm_text:
        return False, 0.0

    # 1. 部分一致判定
    if norm_kw in norm_text:
        return True, 1.0

    # 2. SequenceMatcher による類似度判定 (スライディングウィンドウ)
    kw_len = len(norm_kw)
    best_ratio = 0.0

    if len(norm_text) >= kw_len:
        for delta in (0, -1, 1):
            w_size = kw_len + delta
            if w_size <= 0:
                continue
            for i in range(len(norm_text) - w_size + 1):
                window = norm_text[i:i + w_size]
                ratio = difflib.SequenceMatcher(None, norm_kw, window).ratio()
                if ratio > best_ratio:
                    best_ratio = ratio
    else:
        best_ratio = difflib.SequenceMatcher(None, norm_kw, norm_text).ratio()

    if best_ratio >= threshold:
        return True, best_ratio

    return False, best_ratio


def main():
    parser = argparse.ArgumentParser(description="番組表JSONキーワード抽出スクリプト")
    parser.add_argument("--station", required=True, help="放送局ID (例: LFR, TBS)")
    parser.add_argument("--date", required=True, help="対象日付 (形式: YYYY-MM-DD)")
    parser.add_argument("--dry-run", action="store_true", help="ファイル保存を行わず抽出結果の確認のみ行います")
    args = parser.parse_args()

    station_id = args.station.strip().upper()
    date_str = args.date.strip()

    log_message("=== filter_programs.py 実行開始 ===")
    log_message(f"station_id: {station_id}")
    log_message(f"date: {date_str}")
    log_message(f"dry-run: {args.dry_run}")

    # 1. ルール設定ファイルの読み込み
    if not RULES_FILE.exists():
        log_message(f"[ERROR] ルール設定ファイルが存在しません: {RULES_FILE}")
        sys.exit(1)

    try:
        with open(RULES_FILE, "r", encoding="utf-8") as f:
            rules_data = yaml.safe_load(f) or {}
    except Exception as e:
        log_message(f"[ERROR] ルール設定ファイルの読み込みに失敗しました: {e}")
        sys.exit(1)

    all_rules = rules_data.get("rules", [])
    enabled_rules = [r for r in all_rules if r.get("enabled", True)]

    log_message(f"読み込んだルール数: {len(all_rules)}")
    log_message(f"enabledルール数: {len(enabled_rules)}")

    # 2. 番組表JSONの存在確認と取得
    json_path = PROGRAM_GUIDES_DIR / station_id / f"{date_str}.json"
    if not json_path.exists():
        log_message(f"番組表JSONが存在しません: {json_path}")
        log_message("fetch_program_guide.py を呼び出して番組表を取得します...")
        cmd_fetch = [sys.executable, str(FETCH_SCRIPT), "--station", station_id, "--date", date_str]
        try:
            subprocess.run(cmd_fetch, check=True)
            log_message("番組表の自動取得に成功しました。")
        except subprocess.CalledProcessError as e:
            log_message(f"[ERROR] 番組表の自動取得に失敗しました (Exit Code: {e.returncode})")
            sys.exit(1)

    try:
        with open(json_path, "r", encoding="utf-8") as f:
            guide_data = json.load(f)
    except Exception as e:
        log_message(f"[ERROR] 番組表JSONの読み込みに失敗しました: {e}")
        sys.exit(1)

    programs = guide_data.get("programs", [])
    log_message(f"番組数: {len(programs)}")

    # 3. フィルタリング処理
    matched_programs = []
    search_fields = ["title", "personality", "description"]

    for prog in programs:
        matched = False
        for rule in enabled_rules:
            rule_name = rule.get("name", "")
            keyword = rule.get("keyword", "")
            if not keyword:
                continue

            for field in search_fields:
                field_value = prog.get(field, "")
                is_match, score = check_match(keyword, field_value)
                if is_match:
                    prog_copy = dict(prog)
                    prog_copy["matched_rule"] = rule_name
                    prog_copy["matched_keyword"] = keyword
                    prog_copy["matched_field"] = field
                    matched_programs.append(prog_copy)
                    matched = True
                    break
            if matched:
                break

    log_message(f"ヒット番組数: {len(matched_programs)}")
    for p in matched_programs:
        log_message(f"  - ヒット番組名: {p.get('title')} | matched_rule: {p.get('matched_rule')} | matched_field: {p.get('matched_field')}")

    # 4. 結果の保存 (dry-run でない場合)
    output_dir = FILTERED_PROGRAMS_DIR / station_id
    output_path = output_dir / f"{date_str}.json"

    if args.dry_run:
        log_message(f"[DRY-RUN] 保存をスキップします (保存予定先: {output_path})")
    else:
        output_dir.mkdir(parents=True, exist_ok=True)
        result_data = {
            "station_id": station_id,
            "date": date_str,
            "matched_programs": matched_programs
        }
        try:
            with open(output_path, "w", encoding="utf-8") as f:
                json.dump(result_data, f, ensure_ascii=False, indent=2)
            log_message(f"抽出結果を保存しました: {output_path}")
        except Exception as e:
            log_message(f"[ERROR] 抽出結果の保存に失敗しました: {e}")
            sys.exit(1)

    log_message("=== filter_programs.py 実行完了 ===\n")


if __name__ == "__main__":
    main()
