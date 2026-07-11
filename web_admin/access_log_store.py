"""SQLite-backed, privacy-conscious HTTP access logging."""

import datetime
import ipaddress
import json
import os
import sqlite3
from contextlib import contextmanager


JST = datetime.timezone(datetime.timedelta(hours=9))


class AccessLogStore:
    def __init__(self, db_path):
        self.db_path = db_path

    def connect(self):
        os.makedirs(os.path.dirname(self.db_path), exist_ok=True)
        connection = sqlite3.connect(self.db_path, timeout=0.05)
        connection.row_factory = sqlite3.Row
        connection.execute('PRAGMA journal_mode=WAL')
        connection.execute('PRAGMA busy_timeout=50')
        return connection

    @contextmanager
    def session(self):
        connection = self.connect()
        try:
            with connection:
                yield connection
        finally:
            connection.close()

    def initialize(self):
        with self.session() as db:
            db.executescript('''
                CREATE TABLE IF NOT EXISTS access_logs (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    timestamp TEXT NOT NULL,
                    event_type TEXT NOT NULL,
                    http_method TEXT NOT NULL,
                    path TEXT NOT NULL,
                    status_code INTEGER NOT NULL,
                    ip_address TEXT,
                    user_agent TEXT,
                    device_name TEXT,
                    response_time_ms REAL,
                    query TEXT,
                    radio_station TEXT,
                    program_name TEXT,
                    broadcast_date TEXT,
                    file_path TEXT,
                    file_name TEXT,
                    range_header TEXT,
                    response_size INTEGER,
                    error_type TEXT,
                    error_message TEXT,
                    details_json TEXT
                );
                CREATE INDEX IF NOT EXISTS idx_access_logs_timestamp ON access_logs(timestamp DESC);
                CREATE INDEX IF NOT EXISTS idx_access_logs_event_timestamp ON access_logs(event_type, timestamp DESC);
                CREATE INDEX IF NOT EXISTS idx_access_logs_status_timestamp ON access_logs(status_code, timestamp DESC);
                CREATE INDEX IF NOT EXISTS idx_access_logs_ip_timestamp ON access_logs(ip_address, timestamp DESC);
                CREATE INDEX IF NOT EXISTS idx_access_logs_play_dedupe ON access_logs(event_type, ip_address, file_path, timestamp DESC);
            ''')

    def insert(self, entry):
        columns = [
            'timestamp', 'event_type', 'http_method', 'path', 'status_code',
            'ip_address', 'user_agent', 'device_name', 'response_time_ms',
            'query', 'radio_station', 'program_name', 'broadcast_date',
            'file_path', 'file_name', 'range_header', 'response_size',
            'error_type', 'error_message', 'details_json',
        ]
        values = [entry.get(column) for column in columns]
        with self.session() as db:
            db.execute(
                f"INSERT INTO access_logs ({','.join(columns)}) VALUES ({','.join('?' for _ in columns)})",
                values,
            )

    @staticmethod
    def _where(filters):
        clauses, params = [], []
        event_type = (filters.get('event_type') or '').upper()
        if event_type:
            clauses.append('event_type = ?')
            params.append(event_type)
        if filters.get('status_code'):
            try:
                clauses.append('status_code = ?')
                params.append(int(filters['status_code']))
            except (TypeError, ValueError):
                pass
        if filters.get('ip_address'):
            clauses.append('ip_address LIKE ?')
            params.append(f"%{filters['ip_address'][:64]}%")
        if filters.get('date_from'):
            clauses.append('timestamp >= ?')
            params.append(filters['date_from'][:10] + ' 00:00:00')
        if filters.get('date_to'):
            clauses.append('timestamp <= ?')
            params.append(filters['date_to'][:10] + ' 23:59:59.999999')
        if filters.get('errors_only'):
            clauses.append('(status_code >= 400 OR event_type = \'ERROR\')')
        keyword = (filters.get('keyword') or '').strip()[:200]
        if keyword:
            like = f'%{keyword}%'
            clauses.append('''(path LIKE ? OR query LIKE ? OR file_name LIKE ? OR
                              program_name LIKE ? OR error_message LIKE ? OR user_agent LIKE ?)''')
            params.extend([like] * 6)
        return (' WHERE ' + ' AND '.join(clauses)) if clauses else '', params

    def list(self, filters, page=1, per_page=50):
        where, params = self._where(filters)
        with self.session() as db:
            total = db.execute('SELECT COUNT(*) FROM access_logs' + where, params).fetchone()[0]
            rows = db.execute(
                'SELECT * FROM access_logs' + where + ' ORDER BY timestamp DESC, id DESC LIMIT ? OFFSET ?',
                params + [per_page, (page - 1) * per_page],
            ).fetchall()
        return [dict(row) for row in rows], total

    def get(self, log_id):
        with self.session() as db:
            row = db.execute('SELECT * FROM access_logs WHERE id = ?', (log_id,)).fetchone()
        return dict(row) if row else None

    def iter_all(self, filters):
        where, params = self._where(filters)
        with self.session() as db:
            return [dict(row) for row in db.execute(
                'SELECT * FROM access_logs' + where + ' ORDER BY timestamp DESC, id DESC', params
            ).fetchall()]

    def delete_before(self, cutoff):
        with self.session() as db:
            cursor = db.execute('DELETE FROM access_logs WHERE timestamp < ?', (cutoff,))
            return cursor.rowcount

    def delete_all(self):
        with self.session() as db:
            cursor = db.execute('DELETE FROM access_logs')
            return cursor.rowcount

    def cleanup(self, retention_days):
        if retention_days is None:
            return 0
        cutoff = datetime.datetime.now(JST) - datetime.timedelta(days=retention_days)
        return self.delete_before(cutoff.strftime('%Y-%m-%d %H:%M:%S'))

    def today_summary(self):
        today = datetime.datetime.now(JST).strftime('%Y-%m-%d')
        with self.session() as db:
            row = db.execute('''
                SELECT COUNT(*) AS total,
                       SUM(CASE WHEN path LIKE '/api/%' THEN 1 ELSE 0 END) AS api,
                       SUM(CASE WHEN event_type = 'SEARCH' THEN 1 ELSE 0 END) AS searches,
                       SUM(CASE WHEN status_code >= 400 OR event_type = 'ERROR' THEN 1 ELSE 0 END) AS errors,
                       MAX(timestamp) AS last_access,
                       COUNT(DISTINCT COALESCE(ip_address, '') || '|' || COALESCE(device_name, '')) AS devices
                  FROM access_logs WHERE timestamp >= ?
            ''', (today + ' 00:00:00',)).fetchone()
            # One PLAY per IP/file within 60 seconds; Range requests remain visible in the list.
            plays = db.execute('''
                SELECT COUNT(*) FROM access_logs current
                 WHERE event_type = 'PLAY' AND timestamp >= ?
                   AND NOT EXISTS (
                     SELECT 1 FROM access_logs previous
                      WHERE previous.event_type = 'PLAY'
                        AND COALESCE(previous.ip_address, '') = COALESCE(current.ip_address, '')
                        AND COALESCE(previous.file_path, previous.path) = COALESCE(current.file_path, current.path)
                        AND previous.id < current.id
                        AND previous.timestamp >= datetime(current.timestamp, '-60 seconds')
                        AND previous.timestamp <= current.timestamp
                   )
            ''', (today + ' 00:00:00',)).fetchone()[0]
        return {**dict(row), 'plays': plays}


def client_ip(remote_addr, forwarded_for, trusted_proxy_values):
    """Honor X-Forwarded-For only when the direct peer is configured as trusted."""
    remote = remote_addr or ''
    networks = []
    try:
        networks = [ipaddress.ip_network(value.strip(), strict=False)
                    for value in trusted_proxy_values if value.strip()]
    except ValueError:
        networks = []
    try:
        remote_address = ipaddress.ip_address(remote)
    except ValueError:
        return remote[:64]
    if forwarded_for and any(remote_address in network for network in networks):
        chain = [part.strip() for part in forwarded_for.split(',')] + [remote]
        # Walk from the trusted direct peer toward the client. This prevents a
        # client-supplied leftmost value from winning when a proxy appends XFF.
        for candidate in reversed(chain):
            try:
                address = ipaddress.ip_address(candidate)
            except ValueError:
                continue
            if any(address in network for network in networks):
                continue
            return str(address)
        try:
            return str(ipaddress.ip_address(chain[0]))
        except ValueError:
            return remote[:64]
    return remote[:64]


def device_name(user_agent):
    ua = (user_agent or '')[:512]
    if ua.startswith('KoeRadi-Android/'):
        return ua.split(')', 1)[0] + (')' if ')' in ua else '')
    if 'Android' in ua:
        return 'Android ブラウザ'
    if any(token in ua for token in ('Mozilla/', 'Chrome/', 'Safari/', 'Firefox/')):
        return 'ブラウザ'
    return 'その他' if ua else '不明'


def masked_query(value, policy):
    value = (value or '').strip()[:200]
    if policy == 'none':
        return None
    if policy == 'masked':
        if len(value) <= 2:
            return '*' * len(value)
        return value[0] + ('*' * min(len(value) - 2, 20)) + value[-1]
    return value or None


def json_details(value):
    return json.dumps(value, ensure_ascii=False, separators=(',', ':')) if value else None
