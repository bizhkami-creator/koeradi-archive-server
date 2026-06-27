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

# 対象とする音声ファイルの拡張子
TARGET_EXTENSIONS = {'.m4a', '.mp3', '.aac'}

# 日付フォーマットの判定用正規表現 (YYYY-MM-DD)
DATE_PATTERN = re.compile(r'^\d{4}-\d{2}-\d{2}$')

def parse_filename(file_name: str):
    """
    ファイル名から日付、放送局ID、番組名を抽出します。
    想定フォーマット: YYYY-MM-DD_STATION_PROGRAM.ext
    
    フォーマットに合致しない場合は、エラーにせず unknown として処理します。
    """
    # 拡張子を除いたベース名を取得
    stem, _ = os.path.splitext(file_name)
    
    # アンダースコアで最大3つの要素に分割 (日付, 放送局ID, 番組名)
    parts = stem.split('_', 2)
    
    if len(parts) == 3 and DATE_PATTERN.match(parts[0]):
        return {
            "date": parts[0],
            "station_id": parts[1],
            "program_name": parts[2]
        }
    else:
        # フォーマットに合わない場合は unknown とする
        return {
            "date": "unknown",
            "station_id": "unknown",
            "program_name": "unknown"
        }

def generate_metadata():
    # スクリプトの配置場所からプロジェクトのルートディレクトリを取得
    script_dir = Path(__file__).resolve().parent
    base_dir = script_dir.parent
    
    audio_dir = base_dir / "data" / "audio"
    output_file = base_dir / "data" / "metadata" / "metadata.json"
    
    metadata_list = []
    
    # data/audio ディレクトリが存在するか確認
    if not audio_dir.exists():
        print(f"警告: 音声ディレクトリが存在しません: {audio_dir}")
        return

    # ディレクトリ内を再帰的に走査
    # sortedでソートしておくことで出力順序を安定させます
    for path in sorted(audio_dir.rglob('*')):
        if path.is_file() and path.suffix.lower() in TARGET_EXTENSIONS:
            file_name = path.name
            # data/audio からの相対パスを取得 (POSIX形式のファイルパス文字列にする)
            relative_path = str(path.relative_to(audio_dir).as_posix())
            
            # ファイル名の解析
            info = parse_filename(file_name)
            
            # メタデータ要素の構築
            item = {
                "file_name": file_name,
                "station_id": info["station_id"],
                "program_name": info["program_name"],
                "date": info["date"],
                "relative_path": relative_path
            }
            metadata_list.append(item)
            print(f"検出: {relative_path}")

    # 出力先ディレクトリを作成（存在しない場合）
    output_file.parent.mkdir(parents=True, exist_ok=True)
    
    # JSONファイルへ書き出し
    with open(output_file, 'w', encoding='utf-8') as f:
        json.dump(metadata_list, f, ensure_ascii=False, indent=2)
        
    print(f"\n成功: メタデータを生成しました -> {output_file}")
    print(f"合計 {len(metadata_list)} 件の音声ファイルを登録しました。")

if __name__ == "__main__":
    generate_metadata()
