#!/usr/bin/env python3
"""
radiko番組表取得スクリプト (Day9)

指定された放送局(station_id)と日付(date)のradiko番組表XMLを取得し、
解析した結果をJSONファイルとして保存します。
"""

import argparse
import gzip
import json
import logging
import os
import sys
import urllib.error
import urllib.request
import xml.etree.ElementTree as ET
from datetime import datetime


def setup_logger(log_filepath):
    """
    ログ出力の設定を行う関数
    ファイルとコンソールの両方にログを出力します。
    """
    os.makedirs(os.path.dirname(log_filepath), exist_ok=True)
    logger = logging.getLogger("fetch_program_guide")
    logger.setLevel(logging.INFO)

    # 重複してハンドラが登録されるのを防ぐ
    if logger.hasHandlers():
        logger.handlers.clear()

    formatter = logging.Formatter('%(asctime)s - %(levelname)s - %(message)s')

    # ファイル出力用ハンドラ
    file_handler = logging.FileHandler(log_filepath, encoding="utf-8")
    file_handler.setFormatter(formatter)
    logger.addHandler(file_handler)

    # コンソール出力用ハンドラ
    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setFormatter(formatter)
    logger.addHandler(console_handler)

    return logger


def format_radiko_datetime(dt_str):
    """
    radikoのYYYYMMDDHHMMSS形式の文字列をISO 8601風(YYYY-MM-DDTHH:MM:SS)に変換し、
    datetimeオブジェクトと変換後文字列を返します。
    """
    dt = datetime.strptime(dt_str, "%Y%m%d%H%M%S")
    return dt, dt.strftime("%Y-%m-%dT%H:%M:%S")


def fetch_program_guide(station_id, date_str, logger):
    """
    radikoから番組表XMLを取得し、解析してJSONに保存するメイン処理関数
    """
    # 日付文字列の正規化 (YYYY-MM-DD -> YYYYMMDD および YYYY-MM-DD 形式の保持)
    clean_date_str = date_str.replace("-", "")
    if len(clean_date_str) != 8:
        logger.error(f"日付の形式が正しくありません: {date_str} (YYYY-MM-DD 形式で指定してください)")
        sys.exit(1)

    formatted_date = f"{clean_date_str[:4]}-{clean_date_str[4:6]}-{clean_date_str[6:8]}"

    # radiko番組表XMLのURL構築
    url = f"https://radiko.jp/v3/program/station/date/{clean_date_str}/{station_id}.xml"
    logger.info(f"番組表取得開始 - Station: {station_id}, Date: {formatted_date}")
    logger.info(f"取得URL: {url}")

    # HTTPリクエストの実行
    req = urllib.request.Request(url, headers={
        "User-Agent": "KoeRadi-Archive/1.0",
        "Accept-Encoding": "gzip"
    })
    try:
        with urllib.request.urlopen(req, timeout=10) as response:
            status_code = response.getcode()
            xml_data = response.read()
            
            # Content-Encodingがgzipの場合、またはマジックナンバーで判定して解凍
            content_encoding = response.headers.get("Content-Encoding", "")
            if content_encoding == "gzip" or xml_data.startswith(b'\x1f\x8b'):
                xml_data = gzip.decompress(xml_data)

            logger.info(f"HTTP取得成功 (ステータスコード: {status_code})")
    except urllib.error.HTTPError as e:
        logger.error(f"HTTP取得失敗: ステータスコード {e.code} ({e.reason})")
        sys.exit(1)
    except urllib.error.URLError as e:
        logger.error(f"HTTP取得失敗: 通信エラー ({e.reason})")
        sys.exit(1)
    except Exception as e:
        logger.error(f"予期せぬエラーが発生しました: {e}")
        sys.exit(1)

    # XMLデータの解析
    try:
        root = ET.fromstring(xml_data)
    except ET.ParseError as e:
        logger.error(f"XMLパースエラー: {e}")
        sys.exit(1)

    programs = []
    # radiko XML内のすべてのprog要素を取得
    prog_elements = root.findall(".//prog")
    
    for prog in prog_elements:
        ft = prog.attrib.get("ft")
        to = prog.attrib.get("to")
        
        if not ft or not to:
            continue

        try:
            start_dt, start_time_iso = format_radiko_datetime(ft)
            end_dt, end_time_iso = format_radiko_datetime(to)
            duration_minutes = int((end_dt - start_dt).total_seconds() // 60)
        except ValueError as e:
            logger.warning(f"日時変換スキップ (ft={ft}, to={to}): {e}")
            continue

        title = prog.findtext("title", default="").strip()
        personality = prog.findtext("pfm", default="").strip()
        description = prog.findtext("desc", default="").strip()

        programs.append({
            "title": title,
            "start_time": start_time_iso,
            "end_time": end_time_iso,
            "duration_minutes": duration_minutes,
            "personality": personality,
            "description": description
        })

    logger.info(f"取得番組数: {len(programs)} 件")

    # JSON保存先のディレクトリとパス作成
    output_dir = os.path.join("data", "program_guides", station_id)
    os.makedirs(output_dir, exist_ok=True)
    output_path = os.path.join(output_dir, f"{formatted_date}.json")

    json_data = {
        "station_id": station_id,
        "date": formatted_date,
        "programs": programs
    }

    try:
        with open(output_path, "w", encoding="utf-8") as f:
            json.dump(json_data, f, ensure_ascii=False, indent=2)
        logger.info(f"保存先JSONパス: {output_path}")
    except Exception as e:
        logger.error(f"JSON保存失敗: {e}")
        sys.exit(1)


def main():
    parser = argparse.ArgumentParser(description="radikoの番組表を取得してJSONに保存します。")
    parser.add_argument("--station", required=True, help="放送局ID (例: LFR, TBS)")
    parser.add_argument("--date", required=True, help="日付 (例: 2026-06-27)")

    args = parser.parse_args()

    log_filepath = os.path.join("logs", "fetch_program_guide.log")
    logger = setup_logger(log_filepath)

    fetch_program_guide(args.station, args.date, logger)


if __name__ == "__main__":
    main()
