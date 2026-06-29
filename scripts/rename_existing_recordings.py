#!/usr/bin/env python3
"""
rename_existing_recordings.py
-----------------------------
data/audio 内のすべての既存録音ファイルを走査し、
番組表JSONの情報と突き合わせて新しい命名規則:
  YYYY-MM-DD_番組名_パーソナリティ名.m4a (または YYYY-MM-DD_番組名.m4a)
に一括リネームします。
また、リネーム後に metadata.json の再生成と Google Drive の完全同期(rclone sync)を実行します。
"""

import json
import os
import re
import subprocess
import sys
from pathlib import Path
import yaml

SCRIPT_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = SCRIPT_DIR.parent
AUDIO_DIR = PROJECT_ROOT / "data" / "audio"
GUIDES_DIR = PROJECT_ROOT / "data" / "program_guides"
FILTERED_DIR = PROJECT_ROOT / "data" / "filtered_programs"
FETCH_SCRIPT = SCRIPT_DIR / "fetch_program_guide.py"
METADATA_SCRIPT = SCRIPT_DIR / "generate_metadata.py"
STATIONS_FILE = PROJECT_ROOT / "config" / "stations.yaml"
TARGET_EXTENSIONS = {".m4a", ".mp3", ".aac"}
DATE_PATTERN = re.compile(r"^\d{4}-\d{2}-\d{2}$")

def sanitize_title(name: str) -> str:
    clean = re.sub(r'[/\\:*?"<>|\s]', '_', str(name or ''))
    return clean[:50]

def sanitize_personality(name: str) -> str:
    clean = re.sub(r'[/\\:*?"<>|\s]', '_', str(name or ''))
    return clean[:30]

def load_stations_map():
    id_to_name = {}
    name_to_id = {}
    if STATIONS_FILE.exists():
        try:
            with open(STATIONS_FILE, 'r', encoding='utf-8') as f:
                data = yaml.safe_load(f) or {}
                for s in data.get('stations', []):
                    if isinstance(s, dict) and 'station_id' in s and 'station_name' in s:
                        st_id = s['station_id']
                        st_name = s['station_name']
                        id_to_name[st_id] = st_name
                        name_to_id[st_name] = st_id
        except Exception as e:
            print(f"警告: stations.yaml の読み込み失敗: {e}")
    return id_to_name, name_to_id

def find_program_info(station_id: str, date_str: str, current_stem: str):
    """番組表JSONから一致する番組の title と personality を探す"""
    guide_path = GUIDES_DIR / station_id / f"{date_str}.json"
    filt_path = FILTERED_DIR / station_id / f"{date_str}.json"

    # 番組表がない場合は取得を試みる
    if not guide_path.exists():
        try:
            print(f"番組表を自動取得中: {station_id} ({date_str})")
            subprocess.run([sys.executable, str(FETCH_SCRIPT), "--station", station_id, "--date", date_str], check=True, timeout=15)
        except Exception as e:
            print(f"番組表取得エラー: {e}")

    rest = current_stem[len(date_str) + 1:] if len(current_stem) > len(date_str) else current_stem

    for jpath in (filt_path, guide_path):
        if jpath.exists():
            try:
                with open(jpath, 'r', encoding='utf-8') as f:
                    gdata = json.load(f) or {}
                    progs = gdata.get('programs', []) or gdata.get('matched_programs', [])
                    for p in progs:
                        t = p.get('title', '')
                        st_title = sanitize_title(t)
                        per = p.get('personality', '')
                        st_per = sanitize_personality(per) if per else ''

                        # マッチング判定
                        expected1 = f"{st_title}_{st_per}" if st_per else st_title
                        if rest == expected1 or rest == st_title or st_title in rest or rest in st_title:
                            return t, per
            except Exception as e:
                print(f"JSON読み込みエラー ({jpath}): {e}")
    return None, None

def main():
    print("=== 既存録音ファイルの一括リネーム処理を開始します ===")
    id_to_name, name_to_id = load_stations_map()

    renamed_count = 0
    skipped_count = 0

    audio_files = sorted([p for p in AUDIO_DIR.rglob('*') if p.is_file() and p.suffix.lower() in TARGET_EXTENSIONS])

    for file_path in audio_files:
        rel_parts = file_path.relative_to(AUDIO_DIR).parts
        if not rel_parts:
            continue

        station_name = rel_parts[0]
        station_id = name_to_id.get(station_name, station_name)

        stem = file_path.stem
        parts = stem.split('_', 2)

        if not (len(parts) >= 2 and DATE_PATTERN.match(parts[0])):
            print(f"スキップ (日付形式不一致): {file_path.name}")
            skipped_count += 1
            continue

        date_str = parts[0]

        title, personality = find_program_info(station_id, date_str, stem)

        if not title:
            # 探索で見つからなかった場合、既存の stem から分解を試みる
            rest = stem[len(date_str) + 1:]
            if '_' in rest:
                p_parts = rest.rsplit('_', 1)
                title = p_parts[0]
                personality = p_parts[1]
            else:
                title = rest
                personality = ""

        safe_title = sanitize_title(title)
        safe_personality = sanitize_personality(personality)

        if safe_personality:
            new_filename = f"{date_str}_{safe_title}_{safe_personality}{file_path.suffix}"
        else:
            new_filename = f"{date_str}_{safe_title}{file_path.suffix}"

        new_filepath = file_path.parent / new_filename

        if file_path != new_filepath:
            print(f"リネーム: {file_path.name}\n     -> {new_filename}")
            file_path.rename(new_filepath)
            renamed_count += 1
        else:
            print(f"変更なし: {file_path.name}")
            skipped_count += 1

    print(f"\n一括リネーム完了 (変更: {renamed_count} 件, 保持: {skipped_count} 件)")

    print("\n--------------------------------------------------")
    print("メタデータ(metadata.json)の再生成を実行中...")
    subprocess.run([sys.executable, str(METADATA_SCRIPT)], check=True)

    print("\n--------------------------------------------------")
    print("Google Drive 側の完全同期 (rclone sync) を実行中...")
    remote_path = "koeradi-drive:KoeRadiArchive"
    local_data = PROJECT_ROOT / "data"
    sync_cmd = ["rclone", "sync", str(local_data), remote_path, "--progress"]
    try:
        subprocess.run(sync_cmd, check=True)
        print("\nGoogle Drive 側の同期完了 (成功)")
    except Exception as e:
        print(f"\nGoogle Drive 同期失敗: {e}")

    print("==================================================")
    print("=== 全リネーム・クラウド同期処理が完了しました ===")

if __name__ == "__main__":
    main()
