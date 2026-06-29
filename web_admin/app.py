import os
import re
import json
import shutil
import datetime
import difflib
import subprocess
import yaml
from flask import Flask, render_template, request, redirect, url_for, jsonify

# Flaskアプリケーションの初期化
app = Flask(__name__)

# プロジェクトのルートディレクトリおよび各種パスの設定
BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
RULES_FILE = os.path.join(BASE_DIR, 'config', 'recording_rules.yaml')
STATIONS_FILE = os.path.join(BASE_DIR, 'config', 'stations.yaml')
DATA_DIR = os.path.join(BASE_DIR, 'data')
LOGS_DIR = os.path.join(BASE_DIR, 'logs')

def load_rules():
    """録音ルール設定ファイル(recording_rules.yaml)を読み込む"""
    if not os.path.exists(RULES_FILE):
        return []
    with open(RULES_FILE, 'r', encoding='utf-8') as f:
        data = yaml.safe_load(f) or {}
        return data.get('rules', [])

def save_rules(rules):
    """録音ルール設定ファイル(recording_rules.yaml)へ書き込む"""
    data = {'rules': rules}
    with open(RULES_FILE, 'w', encoding='utf-8') as f:
        yaml.dump(data, f, allow_unicode=True, sort_keys=False)

def load_stations():
    """放送局設定ファイル(stations.yaml)を読み込む"""
    if not os.path.exists(STATIONS_FILE):
        return []
    with open(STATIONS_FILE, 'r', encoding='utf-8') as f:
        data = yaml.safe_load(f) or {}
        raw_stations = data.get('stations', [])
        result = []
        for s in raw_stations:
            if isinstance(s, dict):
                result.append({
                    'station_id': s.get('station_id', ''),
                    'station_name': s.get('station_name', ''),
                    'enabled': s.get('enabled', True)
                })
            elif isinstance(s, str):
                result.append({
                    'station_id': s,
                    'station_name': s,
                    'enabled': True
                })
        return result

def save_stations(stations):
    """放送局設定ファイル(stations.yaml)へ書き込む"""
    data = {'stations': stations}
    with open(STATIONS_FILE, 'w', encoding='utf-8') as f:
        yaml.dump(data, f, allow_unicode=True, sort_keys=False)

def get_hdd_usage():
    """外付けHDD (dataディレクトリ) の使用率・容量を取得"""
    target_path = DATA_DIR if os.path.exists(DATA_DIR) else BASE_DIR
    try:
        usage = shutil.disk_usage(target_path)
        total_gb = round(usage.total / (1024**3), 1)
        used_gb = round(usage.used / (1024**3), 1)
        free_gb = round(usage.free / (1024**3), 1)
        percent = round((usage.used / usage.total) * 100, 1) if usage.total > 0 else 0
        return {
            'total_gb': total_gb,
            'used_gb': used_gb,
            'free_gb': free_gb,
            'percent': percent
        }
    except Exception:
        return {'total_gb': 0, 'used_gb': 0, 'free_gb': 0, 'percent': 0}

def get_gdrive_sync_status():
    """sync_drive.log から最新のGoogle Drive同期状況を取得(末尾のみ高速読み込み)"""
    log_path = os.path.join(LOGS_DIR, 'sync_drive.log')
    if not os.path.exists(log_path):
        return {'last_sync': 'ログなし', 'status': 'UNKNOWN'}
    
    last_sync = '不明'
    status = 'UNKNOWN'
    try:
        with open(log_path, 'r', encoding='utf-8', errors='ignore') as f:
            f.seek(0, os.SEEK_END)
            size = f.tell()
            f.seek(max(0, size - 8192), os.SEEK_SET)
            lines = f.readlines()
            for line in reversed(lines):
                if '=== Google Drive 同期完了' in line:
                    match = re.search(r'\[(\d{4}-\d{2}-\d{2}\s+\d{2}:\d{2})', line)
                    if match:
                        last_sync = match.group(1)
                    if '成功' in line:
                        status = 'SUCCESS'
                    elif '失敗' in line:
                        status = 'FAILED'
                    break
    except Exception:
        pass
    return {'last_sync': last_sync, 'status': status}

def get_recorded_count():
    """audio/ 配下の録音済み音声ファイル総数を取得"""
    audio_dir = os.path.join(DATA_DIR, 'audio')
    if not os.path.exists(audio_dir):
        return 0
    count = 0
    for root, dirs, files in os.walk(audio_dir):
        for file in files:
            if file.endswith(('.m4a', '.mp3', '.wav', '.aac')):
                count += 1
    return count

def get_keywords_summary():
    """登録キーワードの有効/無効/合計件数を取得"""
    rules = load_rules()
    enabled = sum(1 for r in rules if r.get('enabled', True))
    disabled = sum(1 for r in rules if not r.get('enabled', True))
    total = len(rules)
    return {'enabled': enabled, 'disabled': disabled, 'total': total}

def check_match(keyword: str, text: str, threshold: float = 0.75):
    """キーワード判定用ヘルパー(高速化版)"""
    if not keyword or not text:
        return False
    norm_kw = re.sub(r'\s+', '', str(keyword).strip().lower())
    norm_text = re.sub(r'\s+', '', str(text).strip().lower())
    if not norm_kw or not norm_text:
        return False
    # 高速な部分一致判定
    if norm_kw in norm_text:
        return True
    # 全体比較
    if difflib.SequenceMatcher(None, norm_kw, norm_text).ratio() >= threshold:
        return True
    return False

def get_today_matched_programs():
    """本日の番組表から設定ルールにヒットする番組一覧を取得"""
    today_str = datetime.date.today().strftime('%Y-%m-%d')
    all_stations = load_stations()
    stations = [s['station_id'] for s in all_stations if s.get('enabled', True) and s.get('station_id')]
    if not stations:
        stations = ['LFR', 'TBS']

    rules = load_rules()
    enabled_rules = [r for r in rules if r.get('enabled', True)]
    matched_results = []
    guides_dir = os.path.join(DATA_DIR, 'program_guides')
    fetch_script = os.path.join(BASE_DIR, 'scripts', 'fetch_program_guide.py')

    for station in stations:
        station_dir = os.path.join(guides_dir, station)
        json_path = os.path.join(station_dir, f'{today_str}.json')
        
        if os.path.exists(json_path):
            try:
                with open(json_path, 'r', encoding='utf-8') as f:
                    guide_data = json.load(f)
                    programs = guide_data.get('programs', [])
                    for prog in programs:
                        for rule in enabled_rules:
                            rule_name = rule.get('name', '')
                            keyword = rule.get('keyword', '')
                            if not keyword:
                                continue
                            matched = False
                            for field in ['title', 'personality', 'description']:
                                if check_match(keyword, prog.get(field, '')):
                                    ft = prog.get('ft', '')
                                    start_time = f"{ft[8:10]}:{ft[10:12]}" if len(ft) >= 12 else prog.get('start_time', '-')
                                    matched_results.append({
                                        'station': station,
                                        'start_time': start_time,
                                        'title': prog.get('title', ''),
                                        'matched_rule': rule_name
                                    })
                                    matched = True
                                    break
                            if matched:
                                break
            except Exception:
                pass
    return matched_results

def get_recent_recordings(limit=20):
    """metadata.json から最新録音履歴を最新順に取得"""
    meta_file = os.path.join(DATA_DIR, 'metadata', 'metadata.json')
    if not os.path.exists(meta_file):
        return []
    try:
        with open(meta_file, 'r', encoding='utf-8') as f:
            data = json.load(f) or []
            sorted_data = sorted(data, key=lambda x: (x.get('date', ''), x.get('file_name', '')), reverse=True)
            results = []
            for item in sorted_data[:limit]:
                results.append({
                    'date': item.get('date', ''),
                    'station': item.get('station_id', ''),
                    'program': item.get('program_name', '')
                })
            return results
    except Exception:
        return []

@app.route('/')
def dashboard():
    """トップページ: 運用状態ダッシュボード"""
    hdd = get_hdd_usage()
    gdrive = get_gdrive_sync_status()
    recorded_count = get_recorded_count()
    keywords_summary = get_keywords_summary()
    today_matched = get_today_matched_programs()
    recent_recordings = get_recent_recordings()

    return render_template(
        'dashboard.html',
        hdd=hdd,
        gdrive=gdrive,
        recorded_count=recorded_count,
        keywords_summary=keywords_summary,
        today_matched=today_matched,
        recent_recordings=recent_recordings
    )

@app.route('/rules')
def rules_page():
    """録音ルール管理ページ"""
    rules = load_rules()
    return render_template('rules.html', rules=rules)

@app.route('/stations')
def stations_page():
    """対象放送局管理ページ"""
    stations = load_stations()
    return render_template('stations.html', stations=stations)

@app.route('/stations/toggle/<int:index>', methods=['POST'])
def toggle_station(index):
    """放送局の有効/無効切り替え"""
    stations = load_stations()
    if 0 <= index < len(stations):
        stations[index]['enabled'] = not stations[index].get('enabled', True)
        save_stations(stations)
    return redirect(url_for('stations_page'))

@app.route('/rules/add', methods=['POST'])
def add_rule():
    """新しい録音ルールを追加"""
    name = request.form.get('name', '').strip()
    keyword = request.form.get('keyword', '').strip()
    enabled = request.form.get('enabled') == 'on'
    if name and keyword:
        rules = load_rules()
        rules.append({'name': name, 'keyword': keyword, 'enabled': enabled})
        save_rules(rules)
    return redirect(url_for('rules_page'))

@app.route('/rules/toggle/<int:index>', methods=['POST'])
def toggle_rule(index):
    """ルールの有効/無効切り替え"""
    rules = load_rules()
    if 0 <= index < len(rules):
        rules[index]['enabled'] = not rules[index].get('enabled', False)
        save_rules(rules)
    return redirect(url_for('rules_page'))

@app.route('/rules/delete/<int:index>', methods=['POST'])
def delete_rule(index):
    """ルールの削除"""
    rules = load_rules()
    if 0 <= index < len(rules):
        rules.pop(index)
        save_rules(rules)
    return redirect(url_for('rules_page'))

@app.route('/run-dry-run', methods=['POST'])
def run_dry_run():
    """dry-run 実行エンドポイント (高速キーワード抽出シミュレーション)"""
    yesterday_str = (datetime.date.today() - datetime.timedelta(days=1)).strftime('%Y-%m-%d')
    all_stations = load_stations()
    stations = [s['station_id'] for s in all_stations if s.get('enabled', True) and s.get('station_id')]
    
    filter_script = os.path.join(BASE_DIR, 'scripts', 'filter_programs.py')
    output_lines = [f"=== 昨日のキーワード抽出 dry-run シミュレーション (対象日: {yesterday_str}) ===\n"]
    total_matched = 0
    
    for station in stations:
        try:
            res = subprocess.run(
                ['python3', filter_script, '--station', station, '--date', yesterday_str, '--dry-run'],
                cwd=BASE_DIR, capture_output=True, text=True, timeout=10
            )
            lines = res.stdout.split('\n')
            matched_in_st = [l for l in lines if 'ヒット番組名:' in l]
            if matched_in_st:
                output_lines.append(f"【放送局: {station}】")
                for m in matched_in_st:
                    clean_m = m.replace('  - ヒット番組名: ', '  • ')
                    output_lines.append(clean_m)
                    total_matched += 1
                output_lines.append("")
        except Exception as e:
            output_lines.append(f"【放送局: {station}】 エラー: {e}\n")
            
    output_lines.append(f"==================================================")
    output_lines.append(f"全対象局 ({len(stations)}局) の確認完了: 合計 {total_matched} 件の番組が録音対象として抽出されました。")
    
    return jsonify({'success': True, 'output': '\n'.join(output_lines)})

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=8080, debug=False, threaded=True)
