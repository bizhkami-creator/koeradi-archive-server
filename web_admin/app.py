import os
import re
import sys
import json
import gzip
import hashlib
import shutil
import datetime
import difflib
import subprocess
import base64
import secrets
import urllib.request
import urllib.parse
import csv
import functools
import hmac
import io
import math
import time
import xml.etree.ElementTree as ET
from pathlib import Path
import yaml
from flask import Flask, render_template, request, redirect, url_for, jsonify, send_from_directory, send_file, abort, Response, stream_with_context, g, session, got_request_exception
from voice_command_service import VoiceCommandService
from access_log_store import AccessLogStore, client_ip, device_name, masked_query, json_details

# Flaskアプリケーションの初期化
app = Flask(__name__)
app.secret_key = os.environ.get('KOERADI_SECRET_KEY') or secrets.token_hex(32)

# プロジェクトのルートディレクトリおよび各種パスの設定
BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
RULES_FILE = os.path.join(BASE_DIR, 'config', 'recording_rules.yaml')
STATIONS_FILE = os.path.join(BASE_DIR, 'config', 'stations.yaml')
SETTINGS_FILE = os.path.join(BASE_DIR, 'config', 'settings.yaml')
DATA_DIR = os.path.join(BASE_DIR, 'data')
LOGS_DIR = os.path.join(BASE_DIR, 'logs')
SETTINGS_JOBS_LOG = os.path.join(LOGS_DIR, 'settings_jobs.log')
DELETE_RECORDINGS_LOG = os.path.join(LOGS_DIR, 'delete_recordings.log')
TRASH_EMPTY_LOG = os.path.join(LOGS_DIR, 'trash_empty.log')
LIVE_STREAM_LOG = os.path.join(LOGS_DIR, 'live_stream.log')
ACCESS_LOG_DB = os.path.join(LOGS_DIR, 'access_logs.sqlite3')
AUDIO_EXTENSIONS = ('.m4a', '.mp3', '.wav', '.aac')
RADIKO_AUTHKEY_VALUE = 'bcd151073c03b352e1ef2fd66c32209da9ca0afa'
JST = datetime.timezone(datetime.timedelta(hours=9))

ADMIN_NAV = [
    {'key': 'dashboard', 'label': 'ダッシュボード', 'endpoint': 'dashboard'},
    {'key': 'live', 'label': 'ライブ再生', 'endpoint': 'live_page'},
    {'key': 'jobs', 'label': '録音管理', 'endpoint': 'jobs_page'},
    {'key': 'files', 'label': 'ファイル管理', 'endpoint': 'files_page'},
    {'key': 'access_logs', 'label': 'アクセスログ', 'endpoint': 'access_logs_page'},
    {'key': 'settings', 'label': '設定', 'endpoint': 'settings_page'},
    {'key': 'logs', 'label': 'ログ', 'endpoint': 'logs_page'},
]

DEFAULT_SETTINGS = {
    'drive': {
        'enabled': True
    },
    'scheduler': {
        'enabled': False,
        'mode': 'filtered',
        'interval': 'daily',
        'hour': 3,
        'minute': 0,
        'lookback_days': 7
    },
    'storage': {
        'trash_dir': 'data/trash'
    },
    'access_logs': {
        'retention_days': 90,
        'search_query_policy': 'full'
    }
}

VALID_SCHEDULER_MODES = {'filtered', 'full'}
VALID_SCHEDULER_INTERVALS = {'hourly', 'every_6_hours', 'daily', 'weekly'}
VALID_LOOKBACK_DAYS = {1, 3, 7}
VALID_ACCESS_LOG_RETENTION_DAYS = {30, 90, 180, None}
VALID_SEARCH_QUERY_POLICIES = {'full', 'none', 'masked'}

JOB_COMMANDS = {
    'dry_run_yesterday': {
        'label': '対象期間Dry Run',
        'command': ['python3', 'scripts/scheduled_recording.py', '--dry-run', '--force'],
        'requires_drive': False,
    },
    'record_yesterday': {
        'label': '対象期間録音',
        'command': ['python3', 'scripts/scheduled_recording.py', '--force'],
        'requires_drive': False,
    },
    'sync_now': {
        'label': '今すぐ同期',
        'command': ['bash', 'scripts/sync_drive.sh'],
        'requires_drive': True,
    },
    'scheduler_dry_run': {
        'label': 'Scheduler dry-run',
        'command': ['python3', 'scripts/scheduled_recording.py', '--dry-run'],
        'requires_drive': False,
    },
    'scheduler_run_now': {
        'label': 'Run scheduler now',
        'command': ['python3', 'scripts/scheduled_recording.py'],
        'requires_drive': False,
    },
}

def merge_settings(raw):
    """settings.yaml の不足・不正値をデフォルトで補完する"""
    raw = raw or {}
    drive = raw.get('drive') or {}
    scheduler = raw.get('scheduler') or {}
    storage = raw.get('storage') or {}
    access_logs = raw.get('access_logs') or {}

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

    try:
        lookback_days = int(scheduler.get('lookback_days', DEFAULT_SETTINGS['scheduler']['lookback_days']))
    except (TypeError, ValueError):
        lookback_days = DEFAULT_SETTINGS['scheduler']['lookback_days']
    if lookback_days not in VALID_LOOKBACK_DAYS:
        lookback_days = DEFAULT_SETTINGS['scheduler']['lookback_days']

    retention_raw = access_logs.get('retention_days', DEFAULT_SETTINGS['access_logs']['retention_days'])
    if retention_raw in ('unlimited', 'none', '', None):
        retention_days = None
    else:
        try:
            retention_days = int(retention_raw)
        except (TypeError, ValueError):
            retention_days = DEFAULT_SETTINGS['access_logs']['retention_days']
        if retention_days not in VALID_ACCESS_LOG_RETENTION_DAYS:
            retention_days = DEFAULT_SETTINGS['access_logs']['retention_days']

    query_policy = access_logs.get('search_query_policy', DEFAULT_SETTINGS['access_logs']['search_query_policy'])
    if query_policy not in VALID_SEARCH_QUERY_POLICIES:
        query_policy = DEFAULT_SETTINGS['access_logs']['search_query_policy']

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
            'lookback_days': lookback_days,
        },
        'storage': {
            'trash_dir': str(storage.get('trash_dir') or DEFAULT_SETTINGS['storage']['trash_dir'])
        },
        'access_logs': {
            'retention_days': retention_days,
            'search_query_policy': query_policy,
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

def get_enabled_stations():
    """ライブ再生・録音対象として有効な放送局一覧を返す"""
    return [s for s in load_stations() if s.get('enabled', True) and s.get('station_id')]

def find_station(station_id):
    """station_id から設定済み放送局を検索する"""
    target = (station_id or '').strip().upper()
    return next((s for s in load_stations() if s.get('station_id', '').upper() == target), None)

def log_live_stream(event):
    """ライブ再生関連の状態をJSON Linesで記録する"""
    os.makedirs(LOGS_DIR, exist_ok=True)
    payload = {
        'timestamp': datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
        **event,
    }
    with open(LIVE_STREAM_LOG, 'a', encoding='utf-8') as f:
        f.write(json.dumps(payload, ensure_ascii=False) + '\n')

def radiko_request(url, headers=None, timeout=10):
    req = urllib.request.Request(url, headers=headers or {})
    with urllib.request.urlopen(req, timeout=timeout) as res:
        return res.read(), res.headers

def get_radiko_auth():
    """radikoのエリア認証を行い、ffmpeg用ヘッダ情報を返す"""
    auth1_headers = {
        'X-Radiko-App': 'pc_html5',
        'X-Radiko-App-Version': '0.0.1',
        'X-Radiko-Device': 'pc',
        'X-Radiko-User': 'dummy_user',
    }
    _, headers = radiko_request('https://radiko.jp/v2/api/auth1', headers=auth1_headers)
    authtoken = headers.get('X-Radiko-AuthToken')
    keyoffset = headers.get('X-Radiko-KeyOffset')
    keylength = headers.get('X-Radiko-KeyLength')
    if not authtoken or keyoffset is None or keylength is None:
        raise RuntimeError('radiko auth1 response did not include required headers')

    offset = int(keyoffset)
    length = int(keylength)
    partial_key = base64.b64encode(RADIKO_AUTHKEY_VALUE[offset:offset + length].encode('ascii')).decode('ascii')
    auth2_headers = {
        'X-Radiko-Device': 'pc',
        'X-Radiko-User': 'dummy_user',
        'X-Radiko-AuthToken': authtoken,
        'X-Radiko-PartialKey': partial_key,
    }
    body, _ = radiko_request('https://radiko.jp/v2/api/auth2', headers=auth2_headers)
    auth2_text = body.decode('utf-8', errors='ignore').strip()
    if not auth2_text or auth2_text == 'OUT':
        raise RuntimeError('radiko auth2 failed: area could not be detected or access is outside Japan')

    area_id = auth2_text.splitlines()[0].split(',')[0].strip()
    if not area_id:
        raise RuntimeError('radiko auth2 response did not include area_id')
    return {'authtoken': authtoken, 'area_id': area_id}

def get_radiko_live_playlist_urls(station_id):
    """radikoのライブHLS playlist URL候補を取得する"""
    xml_url = f'https://radiko.jp/v3/station/stream/pc_html5/{station_id}.xml'
    body, _ = radiko_request(xml_url)
    root = ET.fromstring(body)
    urls = []
    fallback_urls = []

    for url_node in root.findall('.//url'):
        playlist_node = url_node.find('playlist_create_url')
        playlist_url = (playlist_node.text or '').strip() if playlist_node is not None else ''
        if not playlist_url:
            continue
        if url_node.get('timefree') == '0' and url_node.get('areafree') == '0':
            urls.append(playlist_url)
        else:
            fallback_urls.append(playlist_url)

    return urls or fallback_urls

def build_radiko_live_hls_url(station_id, playlist_url):
    """radikoライブHLSで必要なクエリを付与する"""
    lsid = secrets.token_hex(16)
    query = urllib.parse.urlencode({
        'station_id': station_id,
        'l': '15',
        'lsid': lsid,
        'type': 'b',
    })
    separator = '&' if '?' in playlist_url else '?'
    return f'{playlist_url}{separator}{query}'

def build_live_ffmpeg_command(station_id, hls_url, auth):
    ffmpeg_path = shutil.which('ffmpeg')
    if not ffmpeg_path:
        raise RuntimeError('ffmpeg command was not found')
    ffmpeg_header = f"X-Radiko-Authtoken: {auth['authtoken']}\r\nX-Radiko-AreaId: {auth['area_id']}\r\n"
    return [
        ffmpeg_path,
        '-nostdin',
        '-loglevel', 'warning',
        '-headers', ffmpeg_header,
        '-http_seekable', '0',
        '-seekable', '0',
        '-i', build_radiko_live_hls_url(station_id, hls_url),
        '-vn',
        '-acodec', 'libmp3lame',
        '-b:a', '128k',
        '-f', 'mp3',
        'pipe:1',
    ]

def parse_radiko_datetime(dt_str):
    """radikoのYYYYMMDDHHMMSSをJSTのaware datetimeに変換する"""
    return datetime.datetime.strptime(dt_str, '%Y%m%d%H%M%S').replace(tzinfo=JST)

def format_live_program_time(dt):
    return dt.astimezone(JST).strftime('%H:%M')

def load_cached_program_guide(station_id, date_str):
    guide_path = os.path.join(DATA_DIR, 'program_guides', station_id, f'{date_str}.json')
    if not os.path.exists(guide_path):
        return None
    with open(guide_path, 'r', encoding='utf-8') as f:
        return json.load(f)

def save_program_guide(station_id, date_str, programs):
    output_dir = os.path.join(DATA_DIR, 'program_guides', station_id)
    os.makedirs(output_dir, exist_ok=True)
    output_path = os.path.join(output_dir, f'{date_str}.json')
    payload = {
        'station_id': station_id,
        'date': date_str,
        'programs': programs,
    }
    with open(output_path, 'w', encoding='utf-8') as f:
        json.dump(payload, f, ensure_ascii=False, indent=2)

def fetch_program_guide_data(station_id, date_str):
    """radiko番組表XMLを取得し、既存JSON形式に近いリストへ変換する"""
    clean_date = date_str.replace('-', '')
    if len(clean_date) != 8:
        raise ValueError('date_str must be YYYY-MM-DD')

    url = f'https://radiko.jp/v3/program/station/date/{clean_date}/{station_id}.xml'
    req = urllib.request.Request(url, headers={
        'User-Agent': 'KoeRadi-Archive/1.0',
        'Accept-Encoding': 'gzip',
    })
    with urllib.request.urlopen(req, timeout=10) as res:
        xml_data = res.read()
        content_encoding = res.headers.get('Content-Encoding', '')
        if content_encoding == 'gzip' or xml_data.startswith(b'\x1f\x8b'):
            xml_data = gzip.decompress(xml_data)

    root = ET.fromstring(xml_data)
    programs = []
    for prog in root.findall('.//prog'):
        ft = prog.attrib.get('ft')
        to = prog.attrib.get('to')
        if not ft or not to:
            continue
        try:
            start_dt = parse_radiko_datetime(ft)
            end_dt = parse_radiko_datetime(to)
        except ValueError:
            continue

        programs.append({
            'title': prog.findtext('title', default='').strip(),
            'start_time': start_dt.strftime('%Y-%m-%dT%H:%M:%S'),
            'end_time': end_dt.strftime('%Y-%m-%dT%H:%M:%S'),
            'duration_minutes': int((end_dt - start_dt).total_seconds() // 60),
            'personality': prog.findtext('pfm', default='').strip(),
            'description': prog.findtext('desc', default='').strip(),
        })
    save_program_guide(station_id, date_str, programs)
    return {'station_id': station_id, 'date': date_str, 'programs': programs}

def parse_guide_time(value):
    if not value:
        return None
    try:
        if re.fullmatch(r'\d{14}', value):
            return parse_radiko_datetime(value)
        return datetime.datetime.strptime(value[:19], '%Y-%m-%dT%H:%M:%S').replace(tzinfo=JST)
    except ValueError:
        return None

def find_current_program_in_guide(guide_data, now):
    for prog in guide_data.get('programs', []):
        start_dt = parse_guide_time(prog.get('start_time') or prog.get('ft'))
        end_dt = parse_guide_time(prog.get('end_time') or prog.get('to'))
        if start_dt and end_dt and start_dt <= now < end_dt:
            return prog, start_dt, end_dt
    return None, None, None

def get_current_program(station_id, now=None):
    station = find_station(station_id)
    if not station or not station.get('enabled', True):
        return None, 'Station not found'

    now = (now or datetime.datetime.now(JST)).astimezone(JST)
    target_dates = [
        now.strftime('%Y-%m-%d'),
        (now - datetime.timedelta(days=1)).strftime('%Y-%m-%d'),
    ]
    last_error = None

    for date_str in target_dates:
        guide_data = load_cached_program_guide(station['station_id'], date_str)
        if guide_data is None:
            try:
                guide_data = fetch_program_guide_data(station['station_id'], date_str)
            except Exception as e:
                last_error = str(e)
                continue

        prog, start_dt, end_dt = find_current_program_in_guide(guide_data, now)
        if prog:
            performer = prog.get('personality') or prog.get('performer') or ''
            return {
                'station_id': station['station_id'],
                'station_name': station.get('station_name') or station['station_id'],
                'title': prog.get('title') or prog.get('program_name') or '',
                'start_time': format_live_program_time(start_dt),
                'end_time': format_live_program_time(end_dt),
                'performer': performer,
                'personality': performer,
            }, None

    if last_error:
        return None, f'Current program not found: {last_error}'
    return None, 'Current program not found'

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

def build_scheduler_target_dates(lookback_days):
    today = datetime.date.today()
    return [
        (today - datetime.timedelta(days=offset)).strftime('%Y-%m-%d')
        for offset in range(0, lookback_days + 1)
    ]

def append_settings_job_event(job_name, command, drive_enabled, status, message, exit_code=None, extra=None):
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
    if extra:
        event.update(extra)
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

def run_status_command(cmd, timeout=5):
    """systemctl系の状態取得を安全に実行する"""
    try:
        res = subprocess.run(
            cmd,
            cwd=BASE_DIR,
            capture_output=True,
            text=True,
            timeout=timeout
        )
        output = (res.stdout or res.stderr or '').strip()
        return {
            'ok': res.returncode == 0,
            'returncode': res.returncode,
            'output': output if output else '-'
        }
    except Exception as e:
        return {
            'ok': False,
            'returncode': None,
            'output': f'取得できません: {e}'
        }

def get_scheduler_log_tail(max_lines=50):
    """scheduler.log の末尾を取得する"""
    log_path = os.path.join(LOGS_DIR, 'scheduler.log')
    if not os.path.exists(log_path):
        return 'logs/scheduler.log はまだ存在しません。'
    try:
        with open(log_path, 'r', encoding='utf-8', errors='ignore') as f:
            return ''.join(f.readlines()[-max_lines:])
    except Exception as e:
        return f'ログ読み込みエラー: {e}'

def get_scheduler_systemd_status():
    """Settings画面用に systemd timer/service 状態を取得する"""
    timer_active = run_status_command(['systemctl', 'is-active', 'koeradi-scheduler.timer'])
    service_active = run_status_command(['systemctl', 'is-active', 'koeradi-scheduler.service'])
    timers = run_status_command(['systemctl', 'list-timers', '--all', 'koeradi-scheduler.timer', '--no-pager'])

    next_run = '-'
    if timers['output'] and timers['output'] != '-':
        for line in timers['output'].splitlines():
            if 'koeradi-scheduler.timer' in line:
                parts = line.split()
                if len(parts) >= 4:
                    next_run = ' '.join(parts[:4])
                elif len(parts) >= 2:
                    next_run = ' '.join(parts[:2])
                else:
                    next_run = line
                break

    return {
        'timer_status': timer_active['output'],
        'timer_ok': timer_active['ok'],
        'service_status': service_active['output'],
        'service_ok': service_active['ok'],
        'next_run_time': next_run,
        'timer_list': timers['output'],
        'last_run_log': get_scheduler_log_tail(50),
    }

def start_settings_job(job_key):
    """Settings画面からのジョブをバックグラウンド起動する"""
    settings = load_settings()
    job = JOB_COMMANDS.get(job_key)
    if not job:
        return False, '不明なジョブです。'

    drive_enabled = settings['drive']['enabled']
    command_text = ' '.join(job['command'])
    scheduler_extra = None
    if 'scheduled_recording.py' in command_text:
        lookback_days = settings['scheduler']['lookback_days']
        scheduler_extra = {
            'lookback_days': lookback_days,
            'target_dates': build_scheduler_target_dates(lookback_days),
        }

    if job.get('requires_drive') and not drive_enabled:
        msg = 'Google Drive同期は無効です。'
        append_settings_job_event(job['label'], command_text, drive_enabled, 'disabled', msg, extra=scheduler_extra)
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
        append_settings_job_event(job['label'], command_text, drive_enabled, 'running', f"Job started: {job['label']}", extra=scheduler_extra)
        return True, f"Job started: {job['label']}"
    except Exception as e:
        append_settings_job_event(job['label'], command_text, drive_enabled, 'failed', f"起動失敗: {e}", 1, extra=scheduler_extra)
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

def is_path_inside(child, parent):
    """child が parent 配下にあるか、resolve 済みパスで判定する"""
    try:
        return os.path.commonpath([str(child), str(parent)]) == str(parent)
    except ValueError:
        return False

def get_configured_trash_dir():
    """settings.yaml の storage.trash_dir からゴミ箱ディレクトリを取得する"""
    settings = load_settings()
    trash_value = ((settings.get('storage') or {}).get('trash_dir') or '').strip()
    if not trash_value:
        return None, 'ゴミ箱パスが未設定です。'

    raw_path = Path(trash_value).expanduser()
    if not raw_path.is_absolute():
        raw_path = Path(BASE_DIR) / raw_path

    try:
        trash_path = raw_path.resolve()
    except Exception as e:
        return None, f'ゴミ箱パスを解決できません: {e}'

    base_path = Path(BASE_DIR).resolve()
    data_path = Path(DATA_DIR).resolve()
    audio_path = (data_path / 'audio').resolve()
    home_path = Path.home().resolve()
    forbidden_paths = {Path('/').resolve(), home_path, base_path, data_path, audio_path}
    if trash_path in forbidden_paths:
        return None, 'ゴミ箱パスが危険な場所を指しています。'
    if trash_path == trash_path.parent:
        return None, 'ゴミ箱パスが不正です。'

    return trash_path, None

def get_trash_stats():
    """ゴミ箱配下の容量とファイル件数を取得する"""
    trash_dir, error = get_configured_trash_dir()
    if error or not trash_dir.exists():
        return {'count': 0, 'size_bytes': 0, 'size': format_size(0), 'path': '', 'error': error}

    count = 0
    size_bytes = 0
    stack = [trash_dir]
    while stack:
        current = stack.pop()
        try:
            entries = list(current.iterdir())
        except OSError:
            continue
        for entry in entries:
            try:
                stat_result = entry.lstat()
                if entry.is_symlink() or entry.is_file():
                    size_bytes += stat_result.st_size
                    count += 1
                elif entry.is_dir():
                    stack.append(entry)
            except OSError:
                pass
    return {
        'count': count,
        'size_bytes': size_bytes,
        'size': format_size(size_bytes),
        'path': os.path.relpath(trash_dir, BASE_DIR),
        'error': None,
    }

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

def log_delete_recordings(event):
    """録音削除操作ログをJSON Linesで記録する"""
    os.makedirs(LOGS_DIR, exist_ok=True)
    payload = {
        'timestamp': datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
        **event,
    }
    with open(DELETE_RECORDINGS_LOG, 'a', encoding='utf-8') as f:
        f.write(json.dumps(payload, ensure_ascii=False) + '\n')

def log_trash_empty(event, level='INFO'):
    """ゴミ箱完全削除操作ログをJSON Linesで記録する"""
    os.makedirs(LOGS_DIR, exist_ok=True)
    payload = {
        'timestamp': datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
        'level': level,
        **event,
    }
    with open(TRASH_EMPTY_LOG, 'a', encoding='utf-8') as f:
        f.write(json.dumps(payload, ensure_ascii=False) + '\n')

def resolve_audio_relative_path(relative_path):
    """metadata由来の relative_path が data/audio 配下の実ファイルか検証して返す"""
    rel = (relative_path or '').strip().replace('\\', '/')
    if not rel or rel.startswith('/') or '..' in rel.split('/'):
        return None, None, '不正なパスです。'
    if not rel.startswith('audio/'):
        return None, None, 'audio配下ではないパスです。'

    audio_dir = os.path.realpath(os.path.join(DATA_DIR, 'audio'))
    abs_path = os.path.realpath(os.path.join(DATA_DIR, rel))
    if not abs_path.startswith(audio_dir + os.sep):
        return None, None, 'audio配下ではないパスです。'
    if not os.path.exists(abs_path) or os.path.isdir(abs_path):
        return rel, abs_path, 'ファイルが存在しません。'
    return rel, abs_path, None

def assert_trash_child_path(path, trash_root):
    """削除対象がゴミ箱配下にあることを確認する"""
    try:
        if path.is_symlink():
            parent = path.parent.resolve()
            if parent == trash_root or is_path_inside(parent, trash_root):
                return True, None
            return False, 'シンボリックリンクがゴミ箱外にあります。'

        resolved = path.resolve()
        if resolved == trash_root or is_path_inside(resolved, trash_root):
            return True, None
        return False, '削除対象がゴミ箱外を指しています。'
    except Exception as e:
        return False, str(e)

def empty_trash_directory():
    """ゴミ箱ディレクトリの中身だけを完全削除する"""
    trash_root, error = get_configured_trash_dir()
    if error:
        event = {
            'operation': 'empty_trash',
            'success_count': 0,
            'failure_count': 1,
            'failures': [{'path': '', 'error': error}],
            'success': False,
        }
        log_trash_empty(event, level='ERROR')
        return {**event, 'empty': False, 'error': error}

    if trash_root.exists() and trash_root.is_symlink():
        error = 'ゴミ箱ディレクトリがシンボリックリンクです。'
        event = {
            'operation': 'empty_trash',
            'trash_dir': str(trash_root),
            'success_count': 0,
            'failure_count': 1,
            'failures': [{'path': str(trash_root), 'error': error}],
            'success': False,
        }
        log_trash_empty(event, level='ERROR')
        return {**event, 'empty': False, 'error': error}

    if not trash_root.exists():
        event = {
            'operation': 'empty_trash',
            'trash_dir': str(trash_root),
            'success_count': 0,
            'failure_count': 0,
            'failures': [],
            'success': True,
        }
        log_trash_empty(event, level='INFO')
        return {**event, 'empty': True}

    if not trash_root.is_dir():
        error = 'ゴミ箱パスがディレクトリではありません。'
        event = {
            'operation': 'empty_trash',
            'trash_dir': str(trash_root),
            'success_count': 0,
            'failure_count': 1,
            'failures': [{'path': str(trash_root), 'error': error}],
            'success': False,
        }
        log_trash_empty(event, level='ERROR')
        return {**event, 'empty': False, 'error': error}

    success_count = 0
    failures = []

    def delete_entry(path):
        nonlocal success_count
        safe, safe_error = assert_trash_child_path(path, trash_root)
        if not safe:
            failures.append({'path': str(path), 'error': safe_error})
            return

        try:
            if path.is_symlink() or path.is_file():
                path.unlink()
                success_count += 1
                return
            if path.is_dir():
                for child in list(path.iterdir()):
                    delete_entry(child)
                try:
                    path.rmdir()
                except Exception as e:
                    failures.append({'path': str(path), 'error': str(e)})
                return
            path.unlink()
            success_count += 1
        except Exception as e:
            failures.append({'path': str(path), 'error': str(e)})

    try:
        entries = list(trash_root.iterdir())
    except Exception as e:
        event = {
            'operation': 'empty_trash',
            'trash_dir': str(trash_root),
            'success_count': 0,
            'failure_count': 1,
            'failures': [{'path': str(trash_root), 'error': str(e)}],
            'success': False,
        }
        log_trash_empty(event, level='ERROR')
        return {**event, 'empty': False, 'error': str(e)}

    if not entries:
        event = {
            'operation': 'empty_trash',
            'trash_dir': str(trash_root),
            'success_count': 0,
            'failure_count': 0,
            'failures': [],
            'success': True,
        }
        log_trash_empty(event, level='INFO')
        return {**event, 'empty': True}

    for entry in entries:
        delete_entry(entry)

    failure_count = len(failures)
    event = {
        'operation': 'empty_trash',
        'trash_dir': str(trash_root),
        'success_count': success_count,
        'failure_count': failure_count,
        'failures': failures,
        'success': failure_count == 0,
    }
    if failure_count:
        log_trash_empty(event, level='WARNING' if success_count else 'ERROR')
    else:
        log_trash_empty(event, level='INFO')
    return {**event, 'empty': False}

def delete_remote_recording(relative_path):
    """Google Drive側の対象ファイルを削除する"""
    remote_path = f"koeradi-drive:KoeRadiArchive/{relative_path}"
    cmd = ['rclone', 'delete', remote_path]
    res = subprocess.run(cmd, cwd=BASE_DIR, capture_output=True, text=True, timeout=120)
    output = (res.stdout or '') + (res.stderr or '')
    return {
        'command': ' '.join(cmd),
        'returncode': res.returncode,
        'output': output.strip(),
        'success': res.returncode == 0,
    }

def regenerate_metadata():
    """generate_metadata.py を実行して metadata.json を再生成する"""
    gen_script = os.path.join(BASE_DIR, 'scripts', 'generate_metadata.py')
    return subprocess.run([sys.executable, gen_script], cwd=BASE_DIR, capture_output=True, text=True, timeout=300)

def move_recordings_to_trash(relative_paths, delete_drive=False):
    """選択された録音ファイルを trash へ移動し、必要ならGoogle Drive側も削除する"""
    timestamp = datetime.datetime.now().strftime('%Y-%m-%d_%H%M%S')
    trash_dir, trash_error = get_configured_trash_dir()

    deleted = []
    failures = []
    drive_results = []

    if trash_error:
        failures.append({'relative_path': 'trash_dir', 'error': trash_error})
        event = {
            'requested_count': len(relative_paths),
            'deleted_count': 0,
            'deleted_files': deleted,
            'trash_dir': '',
            'delete_drive': delete_drive,
            'drive_results': drive_results,
            'metadata_result': None,
            'success': False,
            'failures': failures,
        }
        log_delete_recordings(event)
        return event

    trash_root = trash_dir / timestamp
    os.makedirs(trash_root, exist_ok=True)

    for raw_rel in relative_paths:
        rel, abs_path, error = resolve_audio_relative_path(raw_rel)
        if error:
            failures.append({'relative_path': raw_rel, 'error': error})
            continue

        dest_path = trash_root / rel
        os.makedirs(dest_path.parent, exist_ok=True)
        try:
            shutil.move(abs_path, dest_path)
            deleted.append({'relative_path': rel, 'trash_path': os.path.relpath(dest_path, BASE_DIR)})
        except Exception as e:
            failures.append({'relative_path': rel, 'error': f'trash移動失敗: {e}'})
            continue

        if delete_drive:
            try:
                drive_result = delete_remote_recording(rel)
            except Exception as e:
                drive_result = {
                    'command': f'rclone delete koeradi-drive:KoeRadiArchive/{rel}',
                    'returncode': None,
                    'output': str(e),
                    'success': False,
                }
            drive_result['relative_path'] = rel
            drive_results.append(drive_result)
            if not drive_result['success']:
                failures.append({'relative_path': rel, 'error': f"Google Drive削除失敗: {drive_result['output']}"})

    metadata_result = None
    if deleted:
        try:
            res = regenerate_metadata()
            metadata_result = {
                'returncode': res.returncode,
                'success': res.returncode == 0,
                'output': ((res.stdout or '') + (res.stderr or '')).strip()[-2000:],
            }
            if res.returncode != 0:
                failures.append({'relative_path': 'metadata.json', 'error': 'metadata再生成失敗'})
        except Exception as e:
            metadata_result = {'returncode': None, 'success': False, 'output': str(e)}
            failures.append({'relative_path': 'metadata.json', 'error': f'metadata再生成失敗: {e}'})

    event = {
        'requested_count': len(relative_paths),
        'deleted_count': len(deleted),
        'deleted_files': deleted,
        'trash_dir': os.path.relpath(trash_root, BASE_DIR),
        'delete_drive': delete_drive,
        'drive_results': drive_results,
        'metadata_result': metadata_result,
        'success': bool(deleted) and not failures,
        'failures': failures,
    }
    log_delete_recordings(event)
    return event

access_log_store = AccessLogStore(ACCESS_LOG_DB)
try:
    access_log_store.initialize()
except Exception as exc:
    print(f'access log database initialization failed: {exc}', file=sys.stderr)

_last_access_log_cleanup_date = None
ACCESS_LOG_EXCLUDED_PATHS = {
    '/api/health',
    '/favicon.ico',
    '/admin/access-logs',
    '/admin/access-logs/export.csv',
}


def access_log_admin_required(view):
    """Protect sensitive log views when admin credentials are configured."""
    @functools.wraps(view)
    def wrapped(*args, **kwargs):
        expected_user = os.environ.get('KOERADI_ADMIN_USERNAME')
        expected_password = os.environ.get('KOERADI_ADMIN_PASSWORD')
        if not expected_user or not expected_password:
            return Response(
                'アクセスログを有効にするには KOERADI_ADMIN_USERNAME と KOERADI_ADMIN_PASSWORD を設定してください。',
                503,
            )
        auth = request.authorization
        valid = bool(auth and hmac.compare_digest(auth.username or '', expected_user)
                     and hmac.compare_digest(auth.password or '', expected_password))
        if not valid:
            return Response('管理者認証が必要です。', 401, {'WWW-Authenticate': 'Basic realm="KoeRadi Admin"'})
        return view(*args, **kwargs)
    return wrapped


def csrf_token():
    token = session.get('_access_log_csrf')
    if not token:
        token = secrets.token_urlsafe(32)
        session['_access_log_csrf'] = token
    return token


def valid_csrf_token():
    expected = session.get('_access_log_csrf', '')
    supplied = request.form.get('csrf_token', '')
    return bool(expected and supplied and hmac.compare_digest(expected, supplied))


def classify_access_event():
    path = request.path
    if request.endpoint == 'api_search' or path == '/api/search':
        return 'SEARCH'
    if request.endpoint in {'api_stream', 'serve_audio', 'api_live_stream'}:
        return 'PLAY'
    if request.endpoint == 'api_files':
        return 'FILE_LIST'
    if request.endpoint == 'api_file_detail':
        return 'FILE_DETAIL'
    if path.startswith('/api/'):
        return 'API_ACCESS'
    if path.startswith('/admin') or request.endpoint in {
        'dashboard', 'settings_page', 'jobs_page', 'files_page', 'recordings_page',
        'logs_page', 'stations_page', 'manual_recording_page', 'program_guide_page',
    }:
        return 'ADMIN_ACCESS'
    return 'API_ACCESS'


@app.before_request
def begin_access_logging():
    global _last_access_log_cleanup_date
    g.access_log_started = time.perf_counter()
    g.access_log_exception = None
    g.access_log_details = {}
    g.skip_access_log = (
        request.path.startswith('/static/') or
        request.path in ACCESS_LOG_EXCLUDED_PATHS or
        request.endpoint in {'access_log_detail', 'delete_access_logs'}
    )
    today = datetime.date.today()
    if _last_access_log_cleanup_date != today:
        _last_access_log_cleanup_date = today
        try:
            access_log_store.cleanup(load_settings()['access_logs']['retention_days'])
        except Exception as exc:
            print(f'access log cleanup failed: {exc}', file=sys.stderr)


@got_request_exception.connect_via(app)
def remember_access_log_exception(sender, exception, **extra):
    g.access_log_exception = exception


@app.after_request
def finish_access_logging(response):
    if getattr(g, 'skip_access_log', True):
        return response
    try:
        event_type = classify_access_event()
        if response.status_code >= 400:
            event_type = 'ERROR'
        details = getattr(g, 'access_log_details', {}) or {}
        settings = load_settings()['access_logs']
        query_value = request.args.get('q', '') if event_type == 'SEARCH' else ''
        error = getattr(g, 'access_log_exception', None)
        status_error = response.status if response.status_code >= 400 else None
        trusted_proxies = os.environ.get('KOERADI_TRUSTED_PROXIES', '').split(',')
        access_log_store.insert({
            'timestamp': datetime.datetime.now(JST).strftime('%Y-%m-%d %H:%M:%S.%f'),
            'event_type': event_type,
            'http_method': request.method,
            'path': request.path[:1000],
            'status_code': response.status_code,
            'ip_address': client_ip(request.remote_addr, request.headers.get('X-Forwarded-For'), trusted_proxies),
            'user_agent': request.user_agent.string[:512],
            'device_name': device_name(request.user_agent.string),
            'response_time_ms': round((time.perf_counter() - g.access_log_started) * 1000, 2),
            'query': masked_query(query_value, settings['search_query_policy']),
            'radio_station': details.get('radio_station'),
            'program_name': details.get('program_name'),
            'broadcast_date': details.get('broadcast_date'),
            'file_path': details.get('file_path'),
            'file_name': details.get('file_name'),
            'range_header': request.headers.get('Range', '')[:255] or None,
            'response_size': response.calculate_content_length(),
            'error_type': type(error).__name__ if error else ('HTTPError' if status_error else None),
            'error_message': str(error)[:500] if error else status_error,
            'details_json': json_details(details.get('extra')),
        })
    except Exception as exc:
        # Observability must never break search, API access, or audio playback.
        print(f'access log write failed: {exc}', file=sys.stderr)
    return response


@app.context_processor
def inject_admin_nav():
    return {'admin_nav': ADMIN_NAV, 'csrf_token': csrf_token}

@app.route('/')
def legacy_dashboard():
    """既存トップURLは新しい管理トップへ転送する"""
    return redirect(url_for('dashboard'))

@app.route('/admin')
def dashboard():
    """トップページ: 運用状態ダッシュボード"""
    settings = load_settings()
    hdd = get_hdd_usage()
    gdrive = get_gdrive_sync_status()
    recorded_count = get_recorded_count()
    trash_stats = get_trash_stats()
    keywords_summary = get_keywords_summary()
    today_matched = get_today_matched_programs()
    recent_recordings = get_recent_recordings()
    try:
        access_summary = access_log_store.today_summary()
    except Exception:
        access_summary = {'total': 0, 'api': 0, 'searches': 0, 'plays': 0, 'errors': 0, 'last_access': None, 'devices': 0}

    return render_template(
        'dashboard.html',
        active_nav='dashboard',
        hdd=hdd,
        gdrive=gdrive,
        settings=settings,
        recorded_count=recorded_count,
        trash_stats=trash_stats,
        keywords_summary=keywords_summary,
        today_matched=today_matched,
        recent_recordings=recent_recordings,
        access_summary=access_summary,
    )

@app.route('/admin/live')
def live_page():
    """管理者向けライブ再生ページ"""
    stations = get_enabled_stations()
    selected_station = request.args.get('station', '').strip()
    if selected_station and not find_station(selected_station):
        selected_station = ''
    if not selected_station and stations:
        selected_station = stations[0]['station_id']
    return render_template(
        'live.html',
        active_nav='live',
        stations=stations,
        selected_station=selected_station,
    )

@app.route('/remote')
def remote_home():
    """音声クライアント向けRemote Playerトップページ"""
    recordings = get_recording_items()
    latest_recording = serialize_recording_item(recordings[0]) if recordings else None
    api_files_preview = [serialize_recording_item(item) for item in recordings[:5]]
    return render_template(
        'remote/index.html',
        service_status='Remote Player Ready',
        api_status='OK',
        file_count=len(recordings),
        latest_recording=latest_recording,
        api_files_preview=api_files_preview
    )

@app.route('/remote/player')
def remote_player():
    """音声クライアント向けHTML5 audio再生ページ"""
    file_id = request.args.get('file_id', '').strip()
    recordings = get_recording_items()
    latest_recording = serialize_recording_item(recordings[0]) if recordings else None
    item = find_recording_by_file_id(file_id) if file_id else None

    error = None
    if not file_id:
        error = 'file_id が指定されていません'
    elif not item:
        error = '指定された音声ファイルが見つかりません。'
    elif not recordings:
        error = '再生できる音声ファイルが見つかりません。'

    return render_template(
        'remote/player.html',
        file_id=file_id,
        item=serialize_recording_item(item, detail=True) if item else None,
        audio_mimetype=get_audio_mimetype(item.get('filename') or item.get('relative_path')) if item else '',
        latest_recording=latest_recording,
        error=error
    )

@app.route('/settings', methods=['GET', 'POST'])
@app.route('/admin/settings', methods=['GET', 'POST'])
def settings_page():
    """運用設定ページ"""
    message = None
    message_type = 'info'

    if request.method == 'POST':
        action = request.form.get('action', '')
        if action == 'save_settings':
            current_settings = load_settings()
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
                    'lookback_days': request.form.get('scheduler_lookback_days', 7),
                },
                'storage': current_settings['storage'],
                'access_logs': current_settings['access_logs'],
            }
            save_settings(settings)
            message = 'Settings saved.'
            message_type = 'success'
        elif action == 'save_access_log_settings':
            settings = load_settings()
            settings['access_logs'] = {
                'retention_days': request.form.get('access_log_retention_days', '90'),
                'search_query_policy': request.form.get('search_query_policy', 'full'),
            }
            save_settings(settings)
            message = 'アクセスログ設定を保存しました。'
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
    scheduler_status = get_scheduler_systemd_status()

    return render_template(
        'settings.html',
        active_nav='settings',
        settings=settings,
        gdrive=gdrive,
        job_status=job_status,
        scheduler_status=scheduler_status,
        message=message,
        message_type=message_type,
        scheduler_modes=sorted(VALID_SCHEDULER_MODES),
        scheduler_intervals=['hourly', 'every_6_hours', 'daily', 'weekly']
    )

@app.route('/admin/jobs')
def jobs_page():
    """録音ルール管理ページ"""
    rules = load_rules()
    return render_template('jobs.html', active_nav='jobs', rules=rules)

@app.route('/rules')
def rules_page():
    """旧URL互換: 録音ルール管理ページ"""
    return jobs_page()

@app.route('/admin/jobs/new')
def job_form_page():
    """録音ルール追加ページ"""
    return render_template('job_form.html', active_nav='jobs')

@app.route('/stations')
@app.route('/admin/settings/stations')
def stations_page():
    """対象放送局管理ページ"""
    stations = load_stations()
    return render_template('stations.html', active_nav='settings', stations=stations)

@app.route('/stations/toggle/<int:index>', methods=['POST'])
@app.route('/admin/settings/stations/toggle/<int:index>', methods=['POST'])
def toggle_station(index):
    """放送局の有効/無効切り替え"""
    stations = load_stations()
    if 0 <= index < len(stations):
        stations[index]['enabled'] = not stations[index].get('enabled', True)
        save_stations(stations)
    return redirect(url_for('stations_page'))

@app.route('/rules/add', methods=['POST'])
@app.route('/admin/jobs/add', methods=['POST'])
def add_rule():
    """新しい録音ルールを追加"""
    name = request.form.get('name', '').strip()
    keyword = request.form.get('keyword', '').strip()
    enabled = request.form.get('enabled') == 'on'
    if name and keyword:
        rules = load_rules()
        rules.append({'name': name, 'keyword': keyword, 'enabled': enabled})
        save_rules(rules)
    return redirect(url_for('jobs_page'))

@app.route('/rules/toggle/<int:index>', methods=['POST'])
@app.route('/admin/jobs/toggle/<int:index>', methods=['POST'])
def toggle_rule(index):
    """ルールの有効/無効切り替え"""
    rules = load_rules()
    if 0 <= index < len(rules):
        rules[index]['enabled'] = not rules[index].get('enabled', False)
        save_rules(rules)
    return redirect(url_for('jobs_page'))

@app.route('/rules/delete/<int:index>', methods=['POST'])
@app.route('/admin/jobs/delete/<int:index>', methods=['POST'])
def delete_rule(index):
    """ルールの削除"""
    rules = load_rules()
    if 0 <= index < len(rules):
        rules.pop(index)
        save_rules(rules)
    return redirect(url_for('jobs_page'))

@app.route('/run-dry-run', methods=['POST'])
def run_dry_run():
    """dry-run 実行エンドポイント (高速キーワード抽出シミュレーション)"""
    target_dates = build_scheduler_target_dates(1)
    all_stations = load_stations()
    stations = [s['station_id'] for s in all_stations if s.get('enabled', True) and s.get('station_id')]
    
    filter_script = os.path.join(BASE_DIR, 'scripts', 'filter_programs.py')
    output_lines = [f"=== 当日＋昨日のキーワード抽出 dry-run シミュレーション (対象日: {', '.join(target_dates)}) ===\n"]
    total_matched = 0
    
    for target_date in target_dates:
        output_lines.append(f"--- 対象日: {target_date} ---")
        for station in stations:
            try:
                res = subprocess.run(
                    ['python3', filter_script, '--station', station, '--date', target_date, '--dry-run'],
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
    output_lines.append(f"対象日 {len(target_dates)}日・全対象局 ({len(stations)}局) の確認完了: 合計 {total_matched} 件の番組が録音対象として抽出されました。")
    
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

def get_audio_mimetype(path):
    """音声ファイル拡張子からMIMEタイプを返す"""
    return {
        '.m4a': 'audio/mp4',
        '.mp3': 'audio/mpeg',
        '.wav': 'audio/wav',
        '.aac': 'audio/aac',
    }.get(os.path.splitext(path or '')[1].lower(), 'application/octet-stream')

def make_file_id(relative_path):
    """公開URLに実パスを出さないため、audio配下の相対パスから安定IDを生成する"""
    normalized = (relative_path or '').replace('\\', '/')
    return hashlib.sha256(normalized.encode('utf-8')).hexdigest()[:24]

def normalize_recording_item(item):
    """管理画面/metadata由来のitemをAPIでも扱いやすい形に整える"""
    relative_path = (item.get('relative_path') or '').replace('\\', '/')
    filename = item.get('file_name') or item.get('filename') or os.path.basename(relative_path)
    title = item.get('program_name') or item.get('title') or ''
    station = item.get('station_name') or item.get('station') or item.get('station_id') or ''
    date_str = item.get('date') or ''
    abs_path = os.path.realpath(os.path.join(DATA_DIR, relative_path)) if relative_path else ''
    size_bytes = None
    if abs_path and os.path.exists(abs_path) and os.path.isfile(abs_path):
        size_bytes = os.path.getsize(abs_path)

    normalized = {
        **item,
        'file_id': make_file_id(relative_path),
        'filename': filename,
        'file_name': filename,
        'title': title,
        'program_name': title,
        'station': station,
        'station_name': station,
        'date': date_str,
        'path': relative_path,
        'relative_path': relative_path,
        'size': size_bytes,
        'size_bytes': size_bytes,
        'file_size': item.get('file_size') or format_size(size_bytes),
    }
    normalized['stream_url'] = f"/api/stream/{normalized['file_id']}"
    return normalized

def get_recording_items():
    """metadata.json と実ファイル走査を統合して録音ファイル一覧を返す"""
    meta_file = os.path.join(DATA_DIR, 'metadata', 'metadata.json')

    if not os.path.exists(meta_file):
        try:
            gen_script = os.path.join(BASE_DIR, 'scripts', 'generate_metadata.py')
            subprocess.run(['python3', gen_script], check=True)
        except Exception as e:
            print(f"metadata.json 生成失敗: {e}")

    items = []
    seen_paths = set()

    if os.path.exists(meta_file):
        try:
            with open(meta_file, 'r', encoding='utf-8') as f:
                raw_items = json.load(f) or []
                for item in raw_items:
                    rel_path = (item.get('relative_path') or '').replace('\\', '/')
                    rel, abs_path, error = resolve_audio_relative_path(rel_path)
                    if error:
                        continue
                    normalized = normalize_recording_item({
                        'file_name': item.get('file_name', ''),
                        'station_id': item.get('station_id', ''),
                        'station_name': item.get('station_name', item.get('station_id', 'unknown')),
                        'program_name': item.get('program_name', ''),
                        'personality': item.get('personality', ''),
                        'date': item.get('date', 'unknown'),
                        'year': item.get('year', ''),
                        'month': item.get('month', ''),
                        'relative_path': rel,
                        'file_size': format_size(os.path.getsize(abs_path)),
                    })
                    items.append(normalized)
                    seen_paths.add(rel)
        except Exception as e:
            print(f"metadata.json 読み込み失敗: {e}")

    for item in scan_audio_recording_items():
        if item['relative_path'] in seen_paths:
            continue
        normalized = normalize_recording_item(item)
        items.append(normalized)
        seen_paths.add(item['relative_path'])

    items.sort(key=lambda x: (x.get('date', ''), x.get('filename', '')), reverse=True)
    return items

def find_recording_by_file_id(file_id):
    """file_id から現在存在する録音ファイルを解決する"""
    if not re.match(r'^[0-9a-f]{24}$', file_id or ''):
        return None
    return next((item for item in get_recording_items() if item['file_id'] == file_id), None)

def serialize_recording_item(item, detail=False):
    """APIレスポンス用の録音ファイルJSONを作る"""
    payload = {
        'file_id': item['file_id'],
        'filename': item['filename'],
        'title': item['title'],
        'station': item['station'],
        'station_id': item.get('station_id', ''),
        'date': item.get('date', ''),
        'path': item.get('path', ''),
        'size': item.get('size'),
        'size_label': item.get('file_size', ''),
        'stream_url': item['stream_url'],
    }
    if detail:
        payload.update({
            'personality': item.get('personality', ''),
            'year': item.get('year', ''),
            'month': item.get('month', ''),
            'relative_path': item.get('relative_path', ''),
        })
    return payload

def search_recording_items(query):
    """録音一覧を単純なキーワード部分一致で検索する"""
    q_lower = (query or '').strip().lower()
    if not q_lower:
        return []

    results = []
    for item in get_recording_items():
        haystack = ' '.join([
            item.get('title', ''),
            item.get('station', ''),
            item.get('filename', ''),
            item.get('path', ''),
        ]).lower()
        if q_lower in haystack:
            results.append(item)
    return results

def parse_audio_item_from_path(abs_path, station_map):
    """metadata.json が古い場合でも実ファイルから一覧用メタデータを作る"""
    audio_dir = os.path.join(DATA_DIR, 'audio')
    rel_to_audio = os.path.relpath(abs_path, audio_dir).replace('\\', '/')
    rel_parts = rel_to_audio.split('/')
    file_name = os.path.basename(abs_path)
    stem, _ = os.path.splitext(file_name)

    station_name = rel_parts[0] if rel_parts else 'unknown'
    station_id = station_map.get(station_name, station_name)

    date_str = 'unknown'
    year = ''
    month = ''
    program_name = stem
    personality = ''

    parts = stem.split('_', 1)
    if len(parts) == 2 and re.match(r'^\d{4}-\d{2}-\d{2}$', parts[0]):
        date_str = parts[0]
        year = date_str[:4]
        month = date_str[5:7]
        rest = parts[1]
        guide_match = find_program_metadata_from_guides(station_id, date_str, rest)
        if guide_match:
            program_name = guide_match.get('title', rest)
            personality = guide_match.get('personality', '')
        elif '_' in rest:
            program_name, personality = rest.rsplit('_', 1)
        else:
            program_name = rest

    return {
        'file_name': file_name,
        'station_id': station_id,
        'station_name': station_name,
        'program_name': program_name,
        'personality': personality,
        'date': date_str,
        'year': year,
        'month': month,
        'relative_path': f"audio/{rel_to_audio}",
        'file_size': format_size(os.path.getsize(abs_path)),
    }

def find_program_metadata_from_guides(station_id, date_str, filename_rest):
    """番組表JSONからファイル名に対応する番組名・出演者を補完する"""
    for base in ('filtered_programs', 'program_guides'):
        json_path = os.path.join(DATA_DIR, base, station_id, f'{date_str}.json')
        if not os.path.exists(json_path):
            continue
        try:
            with open(json_path, 'r', encoding='utf-8') as f:
                data = json.load(f) or {}
        except Exception:
            continue

        programs = data.get('matched_programs', []) or data.get('programs', [])
        for prog in programs:
            safe_title = re.sub(r'[/\\:*?"<>|\s]', '_', str(prog.get('title', '')))[:50]
            safe_person = re.sub(r'[/\\:*?"<>|\s]', '_', str(prog.get('personality', '')))[:30]
            expected = f"{safe_title}_{safe_person}" if safe_person else safe_title
            if filename_rest in {expected, safe_title}:
                return prog
    return None

def scan_audio_recording_items():
    """data/audio 配下の実ファイルを走査して録音一覧用itemを返す"""
    audio_dir = os.path.join(DATA_DIR, 'audio')
    if not os.path.exists(audio_dir):
        return []

    stations = load_stations()
    station_map = {s.get('station_name', ''): s.get('station_id', '') for s in stations if s.get('station_name')}
    items = []
    for root, dirs, files in os.walk(audio_dir):
        for file in files:
            if not file.lower().endswith(AUDIO_EXTENSIONS):
                continue
            abs_path = os.path.join(root, file)
            try:
                items.append(parse_audio_item_from_path(abs_path, station_map))
            except Exception as e:
                print(f"録音ファイル解析スキップ: {abs_path}: {e}")
    return items

@app.route('/recordings')
@app.route('/admin/recordings')
def recordings_page():
    """録音一覧ページ (検索・フィルター・再生)"""
    sort_options = [
        ('date_desc', '日付が新しい順'),
        ('date_asc', '日付が古い順'),
        ('name_asc', 'ファイル名 昇順'),
        ('name_desc', 'ファイル名 降順'),
        ('size_desc', 'サイズが大きい順'),
        ('size_asc', 'サイズが小さい順'),
    ]
    valid_sort_keys = {key for key, _label in sort_options}
    selected_station = request.args.get('station', '').strip()
    selected_date = request.args.get('date', '').strip()
    query = request.args.get('q', '').strip()
    selected_sort = request.args.get('sort', 'date_desc').strip()
    if selected_sort not in valid_sort_keys:
        selected_sort = 'date_desc'
    deleted_count = request.args.get('deleted', '').strip()
    delete_errors = request.args.get('delete_errors', '').strip()
    trash_dir = request.args.get('trash_dir', '').strip()
    trash_message = request.args.get('trash_message', '').strip()
    trash_message_type = request.args.get('trash_message_type', 'info').strip()
    if trash_message_type not in {'success', 'warning', 'danger', 'info'}:
        trash_message_type = 'info'

    items = get_recording_items()
    trash_stats = get_trash_stats()
    stations_set = {item['station_name'] for item in items if item['station_name'] and item['station_name'] != 'unknown'}
    dates_set = {item['date'] for item in items if item['date'] and item['date'] != 'unknown'}

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
        
    sort_handlers = {
        'date_desc': (lambda x: (x.get('date', ''), x.get('file_name', '')), True),
        'date_asc': (lambda x: (x.get('date', ''), x.get('file_name', '')), False),
        'name_asc': (lambda x: (x.get('file_name', '').lower(), x.get('date', '')), False),
        'name_desc': (lambda x: (x.get('file_name', '').lower(), x.get('date', '')), True),
        'size_desc': (lambda x: (x.get('size_bytes') or 0, x.get('date', ''), x.get('file_name', '')), True),
        'size_asc': (lambda x: (x.get('size_bytes') or 0, x.get('date', ''), x.get('file_name', '')), False),
    }
    sort_key, sort_reverse = sort_handlers[selected_sort]
    filtered_items.sort(key=sort_key, reverse=sort_reverse)
    
    stations_list = sorted(list(stations_set))
    dates_list = sorted(list(dates_set), reverse=True)
    
    template_name = 'files.html' if request.path.startswith('/admin/files') else 'recordings.html'

    return render_template(
        template_name,
        active_nav='files',
        recordings=filtered_items,
        stations=stations_list,
        dates=dates_list,
        selected_station=selected_station,
        selected_date=selected_date,
        selected_sort=selected_sort,
        sort_options=sort_options,
        query=query,
        total_count=len(filtered_items),
        deleted_count=deleted_count,
        delete_errors=delete_errors,
        trash_dir=trash_dir,
        trash_stats=trash_stats,
        trash_message=trash_message,
        trash_message_type=trash_message_type
    )

@app.route('/recordings/delete', methods=['POST'])
@app.route('/admin/files/delete', methods=['POST'])
def delete_recordings():
    """選択された録音ファイルを data/trash へ移動し、metadataを再生成する"""
    selected_paths = request.form.getlist('recording_paths')
    delete_drive = request.form.get('delete_drive') == 'on'

    if not selected_paths:
        return redirect(url_for('files_page', delete_errors='対象が選択されていません。'))

    result = move_recordings_to_trash(selected_paths, delete_drive=delete_drive)
    args = {
        'deleted': str(result['deleted_count']),
        'trash_dir': result['trash_dir'],
    }
    if result['failures']:
        args['delete_errors'] = f"{len(result['failures'])}件のエラーがあります。logs/delete_recordings.log を確認してください。"
    return redirect(url_for('files_page', **args))

@app.route('/trash/empty', methods=['POST'])
@app.route('/admin/files/trash/empty', methods=['POST'])
def empty_trash():
    """ゴミ箱の中身を完全削除する。GETでは実行しない。"""
    result = empty_trash_directory()
    success_count = result.get('success_count', 0)
    failure_count = result.get('failure_count', 0)

    if result.get('empty') and failure_count == 0:
        message = 'ゴミ箱は空です。'
        message_type = 'info'
    elif failure_count == 0:
        message = f'ゴミ箱内の{success_count}件のファイルを完全に削除しました。'
        message_type = 'success'
    elif success_count > 0:
        message = f'{success_count}件を削除しました。{failure_count}件の削除に失敗しました。'
        message_type = 'warning'
    else:
        message = 'ゴミ箱を空にできませんでした。ログを確認してください。'
        message_type = 'danger'

    return redirect(url_for('files_page', trash_message=message, trash_message_type=message_type))

@app.route('/admin/files')
def files_page():
    """新しいファイル管理URL。実体は既存の録音一覧ビューを利用する。"""
    return recordings_page()

@app.route('/audio/<path:filepath>')
def serve_audio(filepath):
    """録音音声ファイルの配信 (Path Traversal防止)"""
    g.access_log_details = {'file_path': f'audio/{filepath}', 'file_name': os.path.basename(filepath)}
    audio_dir = os.path.realpath(os.path.join(DATA_DIR, 'audio'))
    
    # 配信対象の完全パスを作成
    requested_path = os.path.realpath(os.path.join(audio_dir, filepath))
    
    # requested_path が audio_dir の配下に存在するか厳格にチェック
    if not requested_path.startswith(audio_dir + os.sep) and requested_path != audio_dir:
        abort(403)
        
    if not os.path.exists(requested_path) or os.path.isdir(requested_path):
        abort(404)
        
    return send_from_directory(audio_dir, filepath)

@app.route('/api/health')
def api_health():
    """クライアント向け稼働確認API"""
    return jsonify({
        'ok': True,
        'data': {
            'status': 'ok',
            'timestamp': datetime.datetime.now(datetime.timezone.utc).isoformat(),
            'service': 'koeradi-archive-server',
        }
    })

@app.route('/api/live/stations')
def api_live_stations():
    """管理画面ライブ再生用の放送局一覧API"""
    stations = [
        {
            'station_id': s.get('station_id', ''),
            'station_name': s.get('station_name') or s.get('station_id', ''),
            'enabled': s.get('enabled', True),
            'stream_url': url_for('api_live_stream', station_id=s.get('station_id', '')),
        }
        for s in get_enabled_stations()
    ]
    return jsonify({'ok': True, 'data': {'count': len(stations), 'stations': stations}})

@app.route('/api/live/current-program/<station_id>')
def api_live_current_program(station_id):
    """選択中の放送局で現在放送中の番組情報を返す"""
    data, error = get_current_program(station_id)
    if error:
        return jsonify({'ok': False, 'error': error})
    return jsonify({'ok': True, 'data': data})

@app.route('/api/live/stream/<station_id>')
def api_live_stream(station_id):
    """radikoライブ音声をブラウザ向けMP3としてプロキシする"""
    station = find_station(station_id)
    g.access_log_details = {'radio_station': station_id, 'file_path': f'live:{station_id}'}
    if not station or not station.get('enabled', True):
        log_live_stream({'station_id': station_id, 'status': 'failed', 'error': 'station not found or disabled'})
        return jsonify({'ok': False, 'error': 'Station not found'}), 404

    station_id = station['station_id']
    try:
        auth = get_radiko_auth()
        hls_urls = get_radiko_live_playlist_urls(station_id)
        if not hls_urls:
            raise RuntimeError('radiko live playlist URL was not found')
        hls_url = hls_urls[0]
        cmd = build_live_ffmpeg_command(station_id, hls_url, auth)
    except Exception as e:
        log_live_stream({'station_id': station_id, 'status': 'failed', 'error': str(e)})
        return jsonify({'ok': False, 'error': f'Live stream setup failed: {e}'}), 502

    log_live_stream({
        'station_id': station_id,
        'station_name': station.get('station_name', station_id),
        'status': 'starting',
        'hls_url': hls_url,
        'mode': 'ffmpeg_mp3_proxy',
    })

    try:
        proc = subprocess.Popen(
            cmd,
            cwd=BASE_DIR,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            bufsize=0,
        )
    except Exception as e:
        log_live_stream({'station_id': station_id, 'status': 'failed', 'error': f'ffmpeg start failed: {e}'})
        return jsonify({'ok': False, 'error': f'ffmpeg start failed: {e}'}), 502

    def generate():
        total_bytes = 0
        error_tail = b''
        try:
            while True:
                chunk = proc.stdout.read(8192)
                if not chunk:
                    break
                total_bytes += len(chunk)
                yield chunk
        finally:
            if proc.poll() is None:
                proc.terminate()
                try:
                    proc.wait(timeout=3)
                except subprocess.TimeoutExpired:
                    proc.kill()
                    proc.wait(timeout=3)
            returncode = proc.poll()
            if proc.stderr:
                try:
                    error_tail = proc.stderr.read()[-2000:]
                except Exception:
                    error_tail = b''
            log_live_stream({
                'station_id': station_id,
                'status': 'closed',
                'returncode': returncode,
                'bytes_sent': total_bytes,
                'ffmpeg_error_tail': error_tail.decode('utf-8', errors='ignore'),
            })

    headers = {
        'Cache-Control': 'no-store',
        'X-Accel-Buffering': 'no',
    }
    return Response(stream_with_context(generate()), mimetype='audio/mpeg', headers=headers)

@app.route('/api/files')
def api_files():
    """録音ファイル一覧API"""
    files = [serialize_recording_item(item) for item in get_recording_items()]
    return jsonify({
        'ok': True,
        'data': {
            'count': len(files),
            'files': files,
        }
    })

@app.route('/api/voice-command')
def api_voice_command():
    """音声クライアント共通のコマンド判定API"""
    def latest_recording():
        recordings = get_recording_items()
        return serialize_recording_item(recordings[0]) if recordings else None

    def search_recordings(query):
        return [serialize_recording_item(item) for item in search_recording_items(query)]

    def list_recordings():
        return [serialize_recording_item(item) for item in get_recording_items()]

    service = VoiceCommandService(latest_recording, search_recordings, list_recordings)
    return jsonify(service.handle(request.args.get('q', '')))

@app.route('/api/search')
def api_search():
    """録音ファイル検索API"""
    query = request.args.get('q', '').strip()
    if not query:
        return jsonify({'ok': True, 'results': [], 'data': {'count': 0, 'results': []}})

    results = [serialize_recording_item(item) for item in search_recording_items(query)]

    return jsonify({
        'ok': True,
        'results': results,
        'data': {
            'count': len(results),
            'results': results,
        }
    })

@app.route('/api/files/<file_id>')
def api_file_detail(file_id):
    """指定録音ファイルの詳細API"""
    item = find_recording_by_file_id(file_id)
    if not item:
        return jsonify({'ok': False, 'error': 'File not found'}), 404
    g.access_log_details = {
        'radio_station': item.get('station'), 'program_name': item.get('title'),
        'broadcast_date': item.get('date'), 'file_path': item.get('relative_path'),
        'file_name': item.get('filename'),
    }
    return jsonify({'ok': True, 'data': serialize_recording_item(item, detail=True)})

@app.route('/api/stream/<file_id>')
def api_stream(file_id):
    """file_id指定の音声ストリーミングAPI"""
    item = find_recording_by_file_id(file_id)
    if not item:
        g.access_log_details = {'file_path': f'file_id:{file_id}'}
        return jsonify({'ok': False, 'error': 'File not found'}), 404

    g.access_log_details = {
        'radio_station': item.get('station'), 'program_name': item.get('title'),
        'broadcast_date': item.get('date'), 'file_path': item.get('relative_path'),
        'file_name': item.get('filename'),
    }

    rel, abs_path, error = resolve_audio_relative_path(item.get('relative_path'))
    if error:
        return jsonify({'ok': False, 'error': 'File not found'}), 404

    return send_file(
        abs_path,
        mimetype=get_audio_mimetype(abs_path),
        as_attachment=False,
        download_name=item.get('filename') or os.path.basename(abs_path),
        conditional=True,
    )

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
@app.route('/admin/manual-record', methods=['GET', 'POST'])
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
        active_nav='jobs',
        enabled_stations=enabled_stations,
        selected_date=selected_date,
        selected_stations=selected_stations,
        preview_items=preview_items,
        message=message,
        message_type=message_type,
        logs_text=logs_text
    )

@app.route('/manual-recording/logs')
@app.route('/admin/manual-record/logs')
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
@app.route('/admin/program-guide', methods=['GET', 'POST'])
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
        active_nav='jobs',
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

def read_log_tail(filename, max_lines=160):
    """logs配下の指定ログ末尾を返す"""
    safe_name = os.path.basename(filename)
    path = os.path.join(LOGS_DIR, safe_name)
    if not os.path.exists(path):
        return f'logs/{safe_name} はまだ存在しません。'
    try:
        with open(path, 'r', encoding='utf-8', errors='ignore') as f:
            return ''.join(f.readlines()[-max_lines:])
    except Exception as e:
        return f'ログ読み込みエラー: {e}'


def access_log_filters():
    quick = request.args.get('filter', 'all')
    event_type = request.args.get('event_type', '').upper()
    errors_only = request.args.get('errors_only') == '1'
    if quick == 'search':
        event_type = 'SEARCH'
    elif quick == 'play':
        event_type = 'PLAY'
    elif quick == 'error':
        event_type, errors_only = '', True
    return {
        'date_from': request.args.get('date_from', ''),
        'date_to': request.args.get('date_to', ''),
        'event_type': event_type,
        'status_code': request.args.get('status_code', ''),
        'ip_address': request.args.get('ip_address', '').strip(),
        'keyword': request.args.get('keyword', '').strip(),
        'errors_only': errors_only,
        'filter': quick,
    }


@app.route('/admin/access-logs')
@access_log_admin_required
def access_logs_page():
    """Searchable, newest-first access log list."""
    filters = access_log_filters()
    try:
        page = max(1, int(request.args.get('page', 1)))
    except ValueError:
        page = 1
    try:
        per_page = int(request.args.get('per_page', 50))
    except ValueError:
        per_page = 50
    if per_page not in {25, 50, 100}:
        per_page = 50
    rows, total = access_log_store.list(filters, page, per_page)
    pages = max(1, math.ceil(total / per_page))
    if page > pages:
        page = pages
        rows, total = access_log_store.list(filters, page, per_page)
    return render_template(
        'access_logs.html', active_nav='access_logs', logs=rows, filters=filters,
        page=page, pages=pages, per_page=per_page, total=total,
        event_types=['SEARCH', 'PLAY', 'FILE_LIST', 'FILE_DETAIL', 'API_ACCESS', 'ADMIN_ACCESS', 'ERROR'],
    )


@app.route('/admin/access-logs/<int:log_id>')
@access_log_admin_required
def access_log_detail(log_id):
    entry = access_log_store.get(log_id)
    if not entry:
        abort(404)
    return render_template('access_log_detail.html', active_nav='access_logs', log=entry)


def csv_safe(value):
    text = '' if value is None else str(value)
    return "'" + text if text.startswith(('=', '+', '-', '@')) else text


@app.route('/admin/access-logs/export.csv')
@access_log_admin_required
def export_access_logs_csv():
    output = io.StringIO(newline='')
    output.write('\ufeff')
    writer = csv.writer(output)
    writer.writerow(['日時', '種別', 'メソッド', 'URL', 'ステータスコード', 'IPアドレス', '端末情報', '処理時間(ms)', '対象ファイル', 'エラー'])
    for row in access_log_store.iter_all(access_log_filters()):
        writer.writerow([csv_safe(value) for value in (
            row['timestamp'], row['event_type'], row['http_method'], row['path'], row['status_code'],
            row['ip_address'], row['device_name'] or row['user_agent'], row['response_time_ms'],
            row['file_name'] or row['file_path'], row['error_message'],
        )])
    return Response(
        output.getvalue(), mimetype='text/csv; charset=utf-8',
        headers={'Content-Disposition': 'attachment; filename=koeradi-access-logs.csv', 'Cache-Control': 'no-store'},
    )


@app.route('/admin/access-logs/delete', methods=['GET', 'POST'])
@access_log_admin_required
def delete_access_logs():
    if request.method == 'GET':
        return render_template('access_log_delete.html', active_nav='access_logs')
    if not valid_csrf_token():
        abort(400, description='CSRF token is invalid')
    mode = request.form.get('mode')
    if mode == 'all':
        count = access_log_store.delete_all()
    elif mode == 'before':
        before_date = request.form.get('before_date', '')
        try:
            datetime.datetime.strptime(before_date, '%Y-%m-%d')
        except ValueError:
            abort(400, description='削除基準日が不正です。')
        count = access_log_store.delete_before(before_date + ' 00:00:00')
    else:
        abort(400, description='削除方法が不正です。')
    return redirect(url_for('access_logs_page', deleted=count))

@app.route('/admin/logs')
def logs_page():
    """管理画面ログ確認ページ"""
    log_files = [
        {'key': 'app', 'label': 'アプリログ', 'filename': 'app.log'},
        {'key': 'scheduler', 'label': '録音ジョブログ', 'filename': 'scheduler.log'},
        {'key': 'manual', 'label': '手動録音ログ', 'filename': 'manual_recording.log'},
        {'key': 'settings', 'label': '設定ジョブログ', 'filename': 'settings_jobs.log'},
        {'key': 'delete', 'label': 'ファイル削除ログ', 'filename': 'delete_recordings.log'},
        {'key': 'trash', 'label': 'ゴミ箱完全削除ログ', 'filename': 'trash_empty.log'},
        {'key': 'sync', 'label': '同期ログ', 'filename': 'sync_drive.log'},
    ]
    selected = request.args.get('log', 'scheduler')
    selected_file = next((item for item in log_files if item['key'] == selected), log_files[1])
    return render_template(
        'logs.html',
        active_nav='logs',
        log_files=log_files,
        selected_log=selected_file,
        logs_text=read_log_tail(selected_file['filename'])
    )

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=8080, debug=False, threaded=True)
