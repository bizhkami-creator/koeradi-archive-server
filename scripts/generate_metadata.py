#!/usr/bin/env python3
"""
generate_metadata.py
--------------------
data/audio ディレクトリ内の音声ファイルを走査し、
Androidアプリ「こえラジ」等で利用するためのメタデータ(metadata.json)を生成するスクリプトです。
"""

import json
import os
import re
from pathlib import Path
import yaml

# 対象とする音声ファイルの拡張子
TARGET_EXTENSIONS = {'.m4a', '.mp3', '.aac'}

# 日付フォーマットの判定用正規表現 (YYYY-MM-DD)
DATE_PATTERN = re.compile(r'^\d{4}-\d{2}-\d{2}$')

def load_stations_info(base_dir: Path):
    """
    stations.yaml を読み込み、
    station_id <-> station_name の相互マッピング辞書を返します。
    """
    stations_file = base_dir / "config" / "stations.yaml"
    id_to_name = {}
    name_to_id = {}
    if stations_file.exists():
        try:
            with open(stations_file, 'r', encoding='utf-8') as f:
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

def parse_audio_file(path: Path, audio_dir: Path, base_dir: Path, id_to_name: dict, name_to_id: dict):
    """
    ファイルパスおよびファイル名からメタデータ要素を構築します。
    フォーマット: YYYY-MM-DD_番組名_パーソナリティ名.m4a または YYYY-MM-DD_番組名.m4a
    """
    file_name = path.name
    rel_parts = path.relative_to(audio_dir).parts
    relative_path = f"audio/{path.relative_to(audio_dir).as_posix()}"
    
    stem, _ = os.path.splitext(file_name)
    
    # 局名・局IDの判定
    station_name = "unknown"
    station_id = "unknown"
    
    if len(rel_parts) > 0:
        top_dir = rel_parts[0]
        if top_dir in name_to_id:
            station_name = top_dir
            station_id = name_to_id[top_dir]
        elif top_dir in id_to_name:
            station_id = top_dir
            station_name = id_to_name[top_dir]
        else:
            station_name = top_dir

    date_str = "unknown"
    year_str = "unknown"
    month_str = "unknown"
    program_name = "unknown"
    personality = ""
    
    parts = stem.split('_', 2)
    if len(parts) >= 2 and DATE_PATTERN.match(parts[0]):
        date_str = parts[0]
        year_str = date_str[:4]
        month_str = date_str[5:7]
        
        if len(parts) == 3 and (parts[1] in id_to_name or parts[1] == station_id):
            # 旧フォーマット: YYYY-MM-DD_STATION_番組名
            if station_id == "unknown":
                station_id = parts[1]
                station_name = id_to_name.get(station_id, station_id)
            program_name = parts[2]
        else:
            # YYYY-MM-DD_番組名_パーソナリティ名 または YYYY-MM-DD_番組名
            rest = stem[len(date_str) + 1:]
            
            # 番組ガイドJSONからの検索を試みる
            guide_json = base_dir / "data" / "program_guides" / station_id / f"{date_str}.json"
            filt_json = base_dir / "data" / "filtered_programs" / station_id / f"{date_str}.json"
            
            found_match = False
            for jpath in (filt_json, guide_json):
                if jpath.exists():
                    try:
                        with open(jpath, 'r', encoding='utf-8') as f:
                            gdata = json.load(f)
                            progs = gdata.get('programs', []) or gdata.get('matched_programs', [])
                            for p in progs:
                                t = p.get('title', '')
                                st_title = re.sub(r'[/\\:*?"<>|\s]', '_', t)[:50]
                                per = p.get('personality', '')
                                st_per = re.sub(r'[/\\:*?"<>|\s]', '_', per)[:30] if per else ''
                                
                                expected_stem = f"{st_title}_{st_per}" if st_per else st_title
                                if rest == expected_stem or rest == st_title:
                                    program_name = t
                                    personality = per
                                    found_match = True
                                    break
                    except Exception:
                        pass
                if found_match:
                    break
            
            if not found_match:
                # ファイル名からのフォールバック解析
                if '_' in rest:
                    p_name, p_pers = rest.rsplit('_', 1)
                    program_name = p_name
                    personality = p_pers
                else:
                    program_name = rest
    else:
        program_name = stem

    return {
        "file_name": file_name,
        "station_id": station_id,
        "station_name": station_name,
        "program_name": program_name,
        "personality": personality,
        "date": date_str,
        "year": year_str,
        "month": month_str,
        "relative_path": relative_path
    }

def generate_metadata():
    script_dir = Path(__file__).resolve().parent
    base_dir = script_dir.parent
    
    audio_dir = base_dir / "data" / "audio"
    output_file = base_dir / "data" / "metadata" / "metadata.json"
    
    id_to_name, name_to_id = load_stations_info(base_dir)
    
    metadata_list = []
    
    if not audio_dir.exists():
        print(f"警告: 音声ディレクトリが存在しません: {audio_dir}")
        return

    for path in sorted(audio_dir.rglob('*')):
        if path.is_file() and path.suffix.lower() in TARGET_EXTENSIONS:
            item = parse_audio_file(path, audio_dir, base_dir, id_to_name, name_to_id)
            metadata_list.append(item)
            print(f"検出: {item['relative_path']}")

    output_file.parent.mkdir(parents=True, exist_ok=True)
    
    with open(output_file, 'w', encoding='utf-8') as f:
        json.dump(metadata_list, f, ensure_ascii=False, indent=2)
        
    print(f"\n成功: メタデータを生成しました -> {output_file}")
    print(f"合計 {len(metadata_list)} 件の音声ファイルを登録しました。")

if __name__ == "__main__":
    generate_metadata()
