import datetime
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import yaml

ROOT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
WEB_ADMIN_DIR = os.path.join(ROOT_DIR, 'web_admin')
if WEB_ADMIN_DIR not in sys.path:
    sys.path.insert(0, WEB_ADMIN_DIR)

import app as web_app
from access_log_store import AccessLogStore, client_ip, masked_query


class AccessLogsTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        root = Path(self.tmp.name)
        self.settings_file = root / 'settings.yaml'
        self.settings_file.write_text(yaml.safe_dump({
            **web_app.DEFAULT_SETTINGS,
            'drive': {'enabled': False},
        }, allow_unicode=True, sort_keys=False), encoding='utf-8')
        self.store = AccessLogStore(str(root / 'access.sqlite3'))
        self.store.initialize()
        self.patches = [
            mock.patch.object(web_app, 'access_log_store', self.store),
            mock.patch.object(web_app, 'SETTINGS_FILE', str(self.settings_file)),
            mock.patch.dict(os.environ, {
                'KOERADI_ADMIN_USERNAME': 'admin', 'KOERADI_ADMIN_PASSWORD': 'secret',
                'KOERADI_TRUSTED_PROXIES': '',
            }, clear=False),
        ]
        for patcher in self.patches:
            patcher.start()
        web_app._last_access_log_cleanup_date = None
        web_app.app.config.update(TESTING=True, SECRET_KEY='test-secret')
        self.client = web_app.app.test_client()
        self.auth = {'Authorization': 'Basic YWRtaW46c2VjcmV0'}

    def tearDown(self):
        for patcher in reversed(self.patches):
            patcher.stop()
        self.tmp.cleanup()

    def logs(self, **filters):
        return self.store.list(filters, 1, 100)[0]

    def test_search_is_recorded_with_ip_user_agent_and_timing(self):
        response = self.client.get(
            '/api/search?q=%E4%BC%8A%E9%9B%86%E9%99%A2%E5%85%89',
            headers={'User-Agent': 'KoeRadi-Android/1.0 (Xperia; Android 14)'},
            environ_base={'REMOTE_ADDR': '192.168.1.25'},
        )
        self.assertEqual(response.status_code, 200)
        row = self.logs()[0]
        self.assertEqual(row['event_type'], 'SEARCH')
        self.assertEqual(row['query'], '伊集院光')
        self.assertEqual(row['ip_address'], '192.168.1.25')
        self.assertIn('KoeRadi-Android', row['device_name'])
        self.assertGreaterEqual(row['response_time_ms'], 0)

    def test_file_list_and_missing_file_are_classified(self):
        with mock.patch.object(web_app, 'get_recording_items', return_value=[]):
            self.assertEqual(self.client.get('/api/files').status_code, 200)
            self.assertEqual(self.client.get('/api/files/000000000000000000000000').status_code, 404)
        rows = self.logs()
        self.assertEqual(rows[0]['event_type'], 'ERROR')
        self.assertEqual(rows[0]['status_code'], 404)
        self.assertEqual(rows[1]['event_type'], 'FILE_LIST')

    def test_range_stream_is_recorded_as_play_with_206(self):
        audio = Path(self.tmp.name) / 'sample.mp3'
        audio.write_bytes(b'0123456789')
        item = {
            'file_id': 'a' * 24, 'station': 'TBS', 'title': '番組名', 'date': '2026-07-10',
            'relative_path': 'audio/sample.mp3', 'filename': 'sample.mp3',
        }
        with mock.patch.object(web_app, 'find_recording_by_file_id', return_value=item), \
             mock.patch.object(web_app, 'resolve_audio_relative_path', return_value=('audio/sample.mp3', str(audio), None)):
            response = self.client.get('/api/stream/' + 'a' * 24, headers={'Range': 'bytes=0-3'})
        self.assertEqual(response.status_code, 206)
        response.close()
        row = self.logs()[0]
        self.assertEqual(row['event_type'], 'PLAY')
        self.assertEqual(row['range_header'], 'bytes=0-3')
        self.assertEqual(row['file_name'], 'sample.mp3')

    def test_unexpected_exception_is_recorded_as_500(self):
        with mock.patch.object(web_app, 'get_recording_items', side_effect=RuntimeError('unexpected test error')), \
             mock.patch.dict(web_app.app.config, {'TESTING': False, 'PROPAGATE_EXCEPTIONS': False}):
            response = self.client.get('/api/files')
        self.assertEqual(response.status_code, 500)
        row = self.logs()[0]
        self.assertEqual(row['event_type'], 'ERROR')
        self.assertEqual(row['status_code'], 500)
        self.assertEqual(row['error_type'], 'RuntimeError')

    def test_log_pages_do_not_log_themselves(self):
        initial = len(self.logs())
        self.assertEqual(self.client.get('/admin/access-logs', headers=self.auth).status_code, 200)
        self.assertEqual(self.client.get('/admin/access-logs/export.csv', headers=self.auth).status_code, 200)
        self.assertEqual(len(self.logs()), initial)

    def test_pagination_filter_detail_and_csv(self):
        for index in range(30):
            self.store.insert(self.entry(event_type='SEARCH' if index == 0 else 'API_ACCESS', path=f'/api/{index}'))
        page = self.client.get('/admin/access-logs?filter=search&per_page=25', headers=self.auth)
        self.assertEqual(page.status_code, 200)
        self.assertIn('SEARCH', page.get_data(as_text=True))
        detail = self.client.get('/admin/access-logs/1', headers=self.auth)
        self.assertEqual(detail.status_code, 200)
        csv_response = self.client.get('/admin/access-logs/export.csv?filter=search', headers=self.auth)
        self.assertEqual(csv_response.status_code, 200)
        self.assertIn('text/csv', csv_response.content_type)

    def test_range_play_summary_deduplicates_sixty_seconds(self):
        first = self.entry(event_type='PLAY', path='/api/stream/id', file_path='audio/a.mp3')
        second = dict(first, timestamp='2026-07-11 12:00:30.000000', range_header='bytes=100-')
        first['timestamp'] = '2026-07-11 12:00:00.000000'
        self.store.insert(first)
        self.store.insert(second)
        with mock.patch('access_log_store.datetime') as dt:
            dt.datetime.now.return_value = datetime.datetime(2026, 7, 11, 20, 0, tzinfo=web_app.JST)
            summary = self.store.today_summary()
        self.assertEqual(summary['plays'], 1)
        self.assertEqual(len(self.logs(event_type='PLAY')), 2)

    def test_delete_requires_csrf_and_get_only_confirms(self):
        self.store.insert(self.entry())
        self.assertEqual(self.client.get('/admin/access-logs/delete', headers=self.auth).status_code, 200)
        self.assertEqual(len(self.logs()), 1)
        self.assertEqual(self.client.post('/admin/access-logs/delete', data={'mode': 'all'}, headers=self.auth).status_code, 400)
        with self.client.session_transaction() as session:
            session['_access_log_csrf'] = 'valid'
        response = self.client.post('/admin/access-logs/delete', data={'mode': 'all', 'csrf_token': 'valid'}, headers=self.auth)
        self.assertEqual(response.status_code, 302)
        self.assertEqual(len(self.logs()), 0)

    def test_admin_auth_when_configured(self):
        with mock.patch.dict(os.environ, {'KOERADI_ADMIN_USERNAME': 'admin', 'KOERADI_ADMIN_PASSWORD': 'secret'}):
            self.assertEqual(self.client.get('/admin/access-logs').status_code, 401)
            self.assertEqual(self.client.get('/admin/access-logs', headers={'Authorization': 'Basic YWRtaW46c2VjcmV0'}).status_code, 200)

    def test_log_failure_does_not_break_api(self):
        with mock.patch.object(self.store, 'insert', side_effect=OSError('disk full')):
            response = self.client.get('/api/search?q=test')
        self.assertEqual(response.status_code, 200)

    def test_cleanup_and_privacy_helpers(self):
        old = self.entry(timestamp='2026-01-01 00:00:00.000000')
        self.store.insert(old)
        self.assertEqual(self.store.delete_before('2026-02-01 00:00:00'), 1)
        self.assertIsNone(masked_query('secret', 'none'))
        self.assertEqual(masked_query('secret', 'masked'), 's****t')
        self.assertEqual(client_ip('10.0.0.2', '192.168.1.25', []), '10.0.0.2')
        self.assertEqual(client_ip('10.0.0.2', '192.168.1.25', ['10.0.0.0/8']), '192.168.1.25')
        self.assertEqual(client_ip('10.0.0.2', '1.2.3.4, 192.168.1.25', ['10.0.0.0/8']), '192.168.1.25')

    @staticmethod
    def entry(**overrides):
        entry = {
            'timestamp': '2026-07-11 12:00:00.000000', 'event_type': 'API_ACCESS',
            'http_method': 'GET', 'path': '/api/test', 'status_code': 200,
            'ip_address': '127.0.0.1', 'user_agent': 'test', 'device_name': 'その他',
            'response_time_ms': 1.2,
        }
        entry.update(overrides)
        return entry


if __name__ == '__main__':
    unittest.main()
