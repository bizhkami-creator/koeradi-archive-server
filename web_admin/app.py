import os
import re
import sys
import json
import shutil
import datetime
import difflib
import subprocess
import yaml
from flask import Flask, render_template, request, redirect, url_for, jsonify, send_from_directory, abort

# Flaskアプリケーションの初期化
app = Flask(__name__)

# プロジェクトのルートディレクトリおよび各種パスの設定
BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
RULES_FILE = os.path.join(BASE_DIR, 'config', 'recording_rules.yaml')
STATIONS_FILE = os.path.join(BASE_DIR, 'config', 'stations.yaml')
SETTINGS_FILE = os.path.join(BASE_DIR, 'config', 'settings.yaml')
DATA_DIR = os.path.join(BASE_DIR, 'data')
LOGS_DIR = os.path.join(BASE_DIR, 'logs')
SETTINGS_JOBS_LOG = os.path.join(LOGS_DIR, 'settings_jobs.log')

DEFAULT_SETTINGS = {
    'drive': {
        'enabled': True
    },
    'scheduler': {
        'enabled': False,
        'mode': 'filtered',
        'interval': 'daily',
        'hour': 3,
        'minute': 0
    }
}

VALID_SCHEDULER_MODES = {'filtered', 'full'}
VALID_SCHEDULER_INTERVALS = {'hourly', 'every_6_hours', 'daily', 'weekly'}

JOB_COMMANDS = {
    'dry_run_yesterday': {
        'label': '昨日分Dry Run',
        'command': ['bash', 'scripts/run_yesterday_all.sh', '--filtered', '--dry-run'],
        'requires_drive': False,
    },
    'record_yesterday': {
        'label': '昨日分録音',
        'command': ['bash', 'scripts/run_yesterday_all.sh', '--filtered'],
        'requires_drive': False,
    },
    'sync_now': {
        'label': '今すぐ同期',
        'command': ['bash', 'scripts/sync_drive.sh'],
        'requires_drive': True,
    },
}

def merge_settings(raw):
    """settings.yaml の不足・不正値をデフォルトで補完する"""
    raw = raw or {}
    drive = raw.get('drive') or {}
    scheduler = raw.get('scheduler') or {}

    mode = scheduler.get('mode', DEFAULT_SETTINGS['scheduler']['mode'])
    if mode not in VALID_SCHEDULER_MODES:
        mode = DEFAULT_SETTINGS['scheduler']['mode']

    interval = scheduler.get('interval', DEFAULT_SETTINGS['scheduler']['interval'])
    if interval not in VALID_SCHEDULER_INTERVALS:
        interval = DEFAULT_SETTINGS['scheduler']['interval']

    try:
        hour = int(scheduler.get('hour', DEFAULT_SETTINGS['scheduler']['hour']))
    except (TypeError, ValueError):
        hour = DEFAULT_SETTINGS['scheduler']['hour']
    hour = min(max(hour, 0), 23)

    try:
        minute = int(scheduler.get('minute', DEFAULT_SETTINGS['scheduler']['minute']))
    except (TypeError, ValueError):
        minute = DEFAULT_SETTINGS['scheduler']['minute']
    minute = min(max(minute, 0), 59)

    return {
        'drive': {
            'enabled': bool(drive.get('enabled', DEFAULT_SETTINGS['drive']['enabled']))
        },
        'scheduler': {
            'enabled': bool(scheduler.get('enabled', DEFAULT_SETTINGS['scheduler']['enabled'])),
            'mode': mode,
            'interval': interval,
            'hour': hour,
            'minute': minute,
        }
    }

def load_settings():
    """運用設定(settings.yaml)を読み込み、存在しない場合は自動生成する"""
    if not os.path.exists(SETTINGS_FILE):
        save_settings(DEFAULT_SETTINGS)
    try:
        with open(SETTINGS_FILE, 'r', encoding='utf-8') as f:
            data = yaml.safe_load(f) or {}
    except Exception:
        data = {}
    settings = merge_settings(data)
    if settings != data:
        save_settings(settings)
    return settings

def save_settings(settings):
    """運用設定(settings.yaml)を保存する"""
    os.makedirs(os.path.dirname(SETTINGS_FILE), exist_ok=True)
    normalized = merge_settings(settings)
    with open(SETTINGS_FILE, 'w', encoding='utf-8') as f:
        yaml.dump(normalized, f, allow_unicode=True, sort_keys=False)

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

def append_settings_job_event(job_name, command, drive_enabled, status, message, exit_code=None):
    """Settingsジョブの状態をJSON Linesで記録する"""
    os.makedirs(LOGS_DIR, exist_ok=True)
    event = {
        'timestamp': datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
        'job_name': job_name,
        'command': command,
        'drive_enabled': drive_enabled,
        'status': status,
        'message': message,
        'exit_code': exit_code,
    }
    with open(SETTINGS_JOBS_LOG, 'a', encoding='utf-8') as f:
        f.write(json.dumps(event, ensure_ascii=False) + '\n')

def get_settings_job_status(max_lines=80):
    """settings_jobs.log から最新ステータスと末尾ログを取得する"""
    if not os.path.exists(SETTINGS_JOBS_LOG):
        return {
            'status': 'unknown',
            'job_name': '-',
            'timestamp': '-',
            'command': '-',
            'drive_enabled': None,
            'exit_code': None,
            'message': 'ジョブ履歴はまだありません。',
            'log_tail': 'logs/settings_jobs.log はまだ存在しません。'
        }

    try:
        with open(SETTINGS_JOBS_LOG, 'r', encoding='utf-8', errors='ignore') as f:
            lines = f.readlines()
    except Exception as e:
        return {
            'status': 'failed',
            'job_name': '-',
            'timestamp': '-',
            'command': '-',
            'drive_enabled': None,
            'exit_code': None,
            'message': f'ログ読み込みエラー: {e}',
            'log_tail': ''
        }

    latest_event = None
    for line in reversed(lines):
        line = line.strip()
        if not line or not line.startswith('{'):
            continue
        try:
            latest_event = json.loads(line)
            break
        except json.JSONDecodeError:
            continue

    if latest_event is None:
        latest_event = {
            'status': 'unknown',
            'job_name': '-',
            'timestamp': '-',
            'command': '-',
            'drive_enabled': None,
            'exit_code': None,
            'message': 'JSON形式のジョブ履歴が見つかりません。'
        }

    latest_event['log_tail'] = ''.join(lines[-max_lines:])
    return latest_event

def start_settings_job(job_key):
    """Settings画面からのジョブをバックグラウンド起動する"""
    settings = load_settings()
    job = JOB_COMMANDS.get(job_key)
    if not job:
        return False, '不明なジョブです。'

    drive_enabled = settings['drive']['enabled']
    command_text = ' '.join(job['command'])

    if job.get('requires_drive') and not drive_enabled:
        msg = 'Google Drive同期は無効です。'
        append_settings_job_event(job['label'], command_text, drive_enabled, 'disabled', msg)
        return False, msg

    runner_script = os.path.join(BASE_DIR, 'scripts', 'run_settings_job.py')
    cmd = [
        sys.executable,
        runner_script,
        '--job-name',
        job['label'],
        '--drive-enabled',
        'true' if drive_enabled else 'false',
        '--',
    ] + job['command']

    try:
        subprocess.Popen(cmd, cwd=BASE_DIR)
        append_settings_job_event(job['label'], command_text, drive_enabled, 'running', f"Job started: {job['label']}")
        return True, f"Job started: {job['label']}"
    except Exception as e:
        append_settings_job_event(job['label'], command_text, drive_enabled, 'failed', f"起動失敗: {e}", 1)
        return False, f"ジョブの起動に失敗しました: {e}"

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
    settings = load_settings()
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
        settings=settings,
        recorded_count=recorded_count,
        keywords_summary=keywords_summary,
        today_matched=today_matched,
        recent_recordings=recent_recordings
    )

@app.route('/settings', methods=['GET', 'POST'])
def settings_page():
    """運用設定ページ"""
    message = None
    message_type = 'info'

    if request.method == 'POST':
        action = request.form.get('action', '')
        if action == 'save_settings':
            settings = {
                'drive': {
                    'enabled': request.form.get('drive_enabled') == 'on'
                },
                'scheduler': {
                    'enabled': request.form.get('scheduler_enabled') == 'on',
                    'mode': request.form.get('scheduler_mode', 'filtered'),
                    'interval': request.form.get('scheduler_interval', 'daily'),
                    'hour': request.form.get('scheduler_hour', 3),
                    'minute': request.form.get('scheduler_minute', 0),
                }
            }
            save_settings(settings)
            message = 'Settings saved.'
            message_type = 'success'
        elif action in JOB_COMMANDS:
            success, msg = start_settings_job(action)
            message = msg
            message_type = 'success' if success else 'warning'
        else:
            message = '不明な操作です。'
            message_type = 'danger'

    settings = load_settings()
    gdrive = get_gdrive_sync_status()
    job_status = get_settings_job_status()

    return render_template(
        'settings.html',
        settings=settings,
        gdrive=gdrive,
        job_status=job_status,
        message=message,
        message_type=message_type,
        scheduler_modes=sorted(VALID_SCHEDULER_MODES),
        scheduler_intervals=['hourly', 'every_6_hours', 'daily', 'weekly']
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

def format_size(size_bytes):
    """ファイルサイズを人間が読みやすい形式に変換"""
    if size_bytes is None or size_bytes < 0:
        return "不明"
    if size_bytes < 1024:
        return f"{size_bytes} B"
    elif size_bytes < 1024 * 1024:
        return f"{size_bytes / 1024:.1f} KB"
    elif size_bytes < 1024 * 1024 * 1024:
        return f"{size_bytes / (1024 * 1024):.1f} MB"
    else:
        return f"{size_bytes / (1024 * 1024 * 1024):.1f} GB"

@app.route('/recordings')
def recordings_page():
    """録音一覧ページ (検索・フィルター・再生)"""
    selected_station = request.args.get('station', '').strip()
    selected_date = request.args.get('date', '').strip()
    query = request.args.get('q', '').strip()
    
    meta_file = os.path.join(DATA_DIR, 'metadata', 'metadata.json')
    
    # metadata.json が存在しない場合は自動生成を試みる
    if not os.path.exists(meta_file):
        try:
            gen_script = os.path.join(BASE_DIR, 'scripts', 'generate_metadata.py')
            subprocess.run(['python3', gen_script], check=True)
        except Exception as e:
            print(f"metadata.json 生成失敗: {e}")
            
    items = []
    stations_set = set()
    dates_set = set()
    
    if os.path.exists(meta_file):
        try:
            with open(meta_file, 'r', encoding='utf-8') as f:
                raw_items = json.load(f) or []
                for item in raw_items:
                    st_name = item.get('station_name', item.get('station_id', 'unknown'))
                    st_id = item.get('station_id', '')
                    date_str = item.get('date', 'unknown')
                    prog_name = item.get('program_name', '')
                    file_name = item.get('file_name', '')
                    rel_path = item.get('relative_path', '')
                    
                    if st_name and st_name != 'unknown':
                        stations_set.add(st_name)
                    if date_str and date_str != 'unknown':
                        dates_set.add(date_str)
                    
                    # 実ファイルの存在確認とファイルサイズ取得
                    abs_path = os.path.join(DATA_DIR, rel_path)
                    file_size_str = "不明"
                    if os.path.exists(abs_path):
                        file_size_str = format_size(os.path.getsize(abs_path))
                        
                    items.append({
                        'file_name': file_name,
                        'station_id': st_id,
                        'station_name': st_name,
                        'program_name': prog_name,
                        'date': date_str,
                        'year': item.get('year', ''),
                        'month': item.get('month', ''),
                        'relative_path': rel_path,
                        'file_size': file_size_str
                    })
        except Exception as e:
            print(f"metadata.json 読み込み失敗: {e}")

    # フィルタリング
    filtered_items = []
    for item in items:
        # 局フィルター (station_name または station_id)
        if selected_station:
            if selected_station != item['station_name'] and selected_station != item['station_id']:
                continue
        # 日付フィルター
        if selected_date:
            if selected_date != item['date']:
                continue
        # キーワード検索
        if query:
            q_lower = query.lower()
            if q_lower not in item['program_name'].lower() and q_lower not in item['file_name'].lower():
                continue
        filtered_items.append(item)
        
    # 日付・ファイル名で降順ソート
    filtered_items.sort(key=lambda x: (x['date'], x['file_name']), reverse=True)
    
    stations_list = sorted(list(stations_set))
    dates_list = sorted(list(dates_set), reverse=True)
    
    return render_template(
        'recordings.html',
        recordings=filtered_items,
        stations=stations_list,
        dates=dates_list,
        selected_station=selected_station,
        selected_date=selected_date,
        query=query,
        total_count=len(filtered_items)
    )

@app.route('/audio/<path:filepath>')
def serve_audio(filepath):
    """録音音声ファイルの配信 (Path Traversal防止)"""
    audio_dir = os.path.realpath(os.path.join(DATA_DIR, 'audio'))
    
    # 配信対象の完全パスを作成
    requested_path = os.path.realpath(os.path.join(audio_dir, filepath))
    
    # requested_path が audio_dir の配下に存在するか厳格にチェック
    if not requested_path.startswith(audio_dir + os.sep) and requested_path != audio_dir:
        abort(403)
        
    if not os.path.exists(requested_path) or os.path.isdir(requested_path):
        abort(404)
        
    return send_from_directory(audio_dir, filepath)

def get_manual_recording_logs(max_lines=100):
    """manual_recording.log から最新行を取得"""
    log_path = os.path.join(LOGS_DIR, 'manual_recording.log')
    if not os.path.exists(log_path):
        return "ログファイルはまだ存在しません。"
    try:
        with open(log_path, 'r', encoding='utf-8', errors='ignore') as f:
            lines = f.readlines()
            return ''.join(lines[-max_lines:])
    except Exception as e:
        return f"ログ読み込みエラー: {e}"

def generate_preview(date_str, station_ids):
    """指定された日付と放送局IDの組み合わせに対し、録音プレビュー情報を生成"""
    all_stations = load_stations()
    station_map = {s['station_id']: s.get('station_name', s['station_id']) for s in all_stations}
    
    filtered_dir = os.path.join(DATA_DIR, 'filtered_programs')
    filter_script = os.path.join(BASE_DIR, 'scripts', 'filter_programs.py')
    
    preview_items = []
    
    year = date_str[:4]
    month = date_str[5:7]
    
    for st in station_ids:
        st_name = station_map.get(st, st)
        
        filtered_json_path = os.path.join(filtered_dir, st, f"{date_str}.json")
        if not os.path.exists(filtered_json_path):
            try:
                subprocess.run(['python3', filter_script, '--station', st, '--date', date_str], check=True, timeout=15)
            except Exception as e:
                print(f"filter_programs.py 実行エラー ({st}, {date_str}): {e}")
                
        if os.path.exists(filtered_json_path):
            try:
                with open(filtered_json_path, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                    matched_progs = data.get('matched_programs', [])
                    for prog in matched_progs:
                        raw_title = prog.get('title', '無題')
                        safe_title = re.sub(r'[/\\:*?"<>|\s]', '_', raw_title)[:50]
                        
                        ft = prog.get('ft', '')
                        start_time = f"{ft[8:10]}:{ft[10:12]}" if len(ft) >= 12 else prog.get('start_time', '-')
                        duration = prog.get('duration_minutes', 0)
                        matched_rule = prog.get('matched_rule', '')
                        
                        rel_output_path = f"data/audio/{st_name}/{year}/{month}/{date_str}_{safe_title}.m4a"
                        abs_output_path = os.path.join(BASE_DIR, rel_output_path)
                        
                        file_exists = os.path.exists(abs_output_path)
                        status = "already_exists_skip" if file_exists else "will_record"
                        
                        preview_items.append({
                            'station_id': st,
                            'station_name': st_name,
                            'date': date_str,
                            'start_time': start_time,
                            'program_name': raw_title,
                            'matched_rule': matched_rule,
                            'duration_minutes': duration,
                            'output_path': rel_output_path,
                            'status': status
                        })
            except Exception as e:
                print(f"filtered_programs JSON 読み込みエラー ({st}): {e}")
                
    preview_items.sort(key=lambda x: (0 if x['status'] == 'will_record' else 1, x['start_time']))
    return preview_items

@app.route('/manual-recording', methods=['GET', 'POST'])
def manual_recording_page():
    """手動録音ジョブ実行ページ"""
    all_stations = load_stations()
    enabled_stations = [s for s in all_stations if s.get('enabled', True)]
    
    yesterday_str = (datetime.date.today() - datetime.timedelta(days=1)).strftime('%Y-%m-%d')
    
    selected_date = yesterday_str
    selected_stations = [s['station_id'] for s in enabled_stations]
    
    preview_items = None
    message = None
    message_type = "info"
    
    if request.method == 'POST':
        action = request.form.get('action')
        selected_date = request.form.get('date', yesterday_str).strip()
        selected_stations = request.form.getlist('stations')
        
        if not selected_stations:
            message = "対象の放送局を少なくとも1つ選択してください。"
            message_type = "danger"
        else:
            if action == 'preview':
                preview_items = generate_preview(selected_date, selected_stations)
                if not preview_items:
                    message = "選択された条件にマッチする録音対象番組はありませんでした。"
                    message_type = "warning"
            elif action == 'start':
                runner_script = os.path.join(BASE_DIR, 'scripts', 'run_manual_recording.py')
                cmd = [sys.executable, runner_script, '--date', selected_date, '--stations'] + selected_stations
                try:
                    subprocess.Popen(cmd, cwd=BASE_DIR)
                    message = "Recording job started. Please check logs."
                    message_type = "success"
                except Exception as e:
                    message = f"ジョブの起動に失敗しました: {e}"
                    message_type = "danger"
                preview_items = generate_preview(selected_date, selected_stations)

    logs_text = get_manual_recording_logs(100)
    
    return render_template(
        'manual_recording.html',
        enabled_stations=enabled_stations,
        selected_date=selected_date,
        selected_stations=selected_stations,
        preview_items=preview_items,
        message=message,
        message_type=message_type,
        logs_text=logs_text
    )

@app.route('/manual-recording/logs')
def manual_recording_logs_api():
    """ジョブログの最新行を取得するAPI"""
    return jsonify({'logs': get_manual_recording_logs(100)})

def check_program_recorded(station_id, station_name, date_str, title, personality):
    """番組が録音済みかどうか判定"""
    safe_title = re.sub(r'[/\\:*?"<>|\s]', '_', str(title or ''))[:50]
    safe_person = re.sub(r'[/\\:*?"<>|\s]', '_', str(personality or ''))[:30]
    
    if safe_person:
        prog_filename_part = f"{safe_title}_{safe_person}"
    else:
        prog_filename_part = safe_title
        
    year = date_str[:4]
    month = date_str[5:7]
    
    rel_output_path = f"data/audio/{station_name}/{year}/{month}/{date_str}_{prog_filename_part}.m4a"
    abs_output_path = os.path.join(BASE_DIR, rel_output_path)
    
    rel_output_path_old = f"data/audio/{station_name}/{year}/{month}/{date_str}_{safe_title}.m4a"
    abs_output_path_old = os.path.join(BASE_DIR, rel_output_path_old)
    
    return os.path.exists(abs_output_path) or os.path.exists(abs_output_path_old)

@app.route('/program-guide', methods=['GET', 'POST'])
def program_guide_page():
    """番組表一覧ページ"""
    all_stations = load_stations()
    enabled_stations = [s for s in all_stations if s.get('enabled', True)]
    
    today_str = datetime.date.today().strftime('%Y-%m-%d')
    
    selected_date = request.args.get('date') or request.form.get('date') or today_str
    selected_station = request.args.get('station') or request.form.get('station') or (enabled_stations[0]['station_id'] if enabled_stations else 'LFR')
    
    station_map = {s['station_id']: s.get('station_name', s['station_id']) for s in all_stations}
    station_name = station_map.get(selected_station, selected_station)
    
    guide_items = []
    message = None
    message_type = "info"
    
    guides_dir = os.path.join(DATA_DIR, 'program_guides')
    json_path = os.path.join(guides_dir, selected_station, f"{selected_date}.json")
    
    if request.method == 'POST' or not os.path.exists(json_path):
        try:
            fetch_script = os.path.join(BASE_DIR, 'scripts', 'fetch_program_guide.py')
            subprocess.run(['python3', fetch_script, '--station', selected_station, '--date', selected_date], check=True, timeout=15)
        except Exception as e:
            print(f"fetch_program_guide.py 実行エラー: {e}")
            
    if os.path.exists(json_path):
        try:
            with open(json_path, 'r', encoding='utf-8') as f:
                guide_data = json.load(f) or {}
                raw_progs = guide_data.get('programs', [])
                for prog in raw_progs:
                    title = prog.get('title', '無題')
                    personality = prog.get('personality', '')
                    start_iso = prog.get('start_time', '')
                    end_iso = prog.get('end_time', '')
                    duration = prog.get('duration_minutes', 0)
                    desc = prog.get('description', '')
                    
                    dt_start = datetime.datetime.fromisoformat(start_iso) if start_iso else None
                    dt_end = datetime.datetime.fromisoformat(end_iso) if end_iso else None
                    
                    start_time_fmt = dt_start.strftime('%H:%M') if dt_start else '-'
                    end_time_fmt = dt_end.strftime('%H:%M') if dt_end else '-'
                    start_datetime_str = dt_start.strftime('%Y%m%d%H%M') if dt_start else ''
                    
                    is_recorded = check_program_recorded(selected_station, station_name, selected_date, title, personality)
                    
                    guide_items.append({
                        'title': title,
                        'personality': personality,
                        'description': desc,
                        'start_time': start_time_fmt,
                        'end_time': end_time_fmt,
                        'start_datetime': start_datetime_str,
                        'duration': duration,
                        'recorded': is_recorded,
                        'status': 'recorded' if is_recorded else 'not_recorded'
                    })
        except Exception as e:
            message = f"番組表の読み込みに失敗しました: {e}"
            message_type = "danger"
            
    return render_template(
        'program_guide.html',
        enabled_stations=enabled_stations,
        selected_date=selected_date,
        selected_station=selected_station,
        station_name=station_name,
        guide_items=guide_items,
        message=message,
        message_type=message_type
    )

@app.route('/api/record-single', methods=['POST'])
def api_record_single():
    """単一番組の即時録音実行API"""
    station = request.form.get('station', '').strip()
    date_str = request.form.get('date', '').strip()
    start = request.form.get('start', '').strip()
    duration = request.form.get('duration', '').strip()
    title = request.form.get('title', '').strip()
    personality = request.form.get('personality', '').strip()
    
    if not station or not date_str or not start or not title:
        return jsonify({'success': False, 'message': '必須パラメータが不足しています。'})
        
    script_path = os.path.join(BASE_DIR, 'scripts', 'record_single_program.py')
    cmd = [sys.executable, script_path, '--station', station, '--date', date_str, '--start', start, '--duration', duration, '--title', title, '--personality', personality]
    
    try:
        subprocess.Popen(cmd, cwd=BASE_DIR)
        return jsonify({'success': True, 'message': f"番組「{title}」の録音処理をバックグラウンドで開始しました。"})
    except Exception as e:
        return jsonify({'success': False, 'message': f"録音処理の起動に失敗しました: {e}"})

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=8080, debug=False, threaded=True)
