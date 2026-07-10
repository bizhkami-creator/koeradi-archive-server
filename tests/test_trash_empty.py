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


class TrashEmptyTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.data_dir = self.root / 'data'
        self.trash_dir = self.data_dir / 'trash'
        self.logs_dir = self.root / 'logs'
        self.config_dir = self.root / 'config'
        self.settings_file = self.config_dir / 'settings.yaml'
        self.config_dir.mkdir()
        self.logs_dir.mkdir()
        self.trash_dir.mkdir(parents=True)
        self._write_settings('data/trash')

        self.patches = [
            mock.patch.object(web_app, 'BASE_DIR', str(self.root)),
            mock.patch.object(web_app, 'DATA_DIR', str(self.data_dir)),
            mock.patch.object(web_app, 'LOGS_DIR', str(self.logs_dir)),
            mock.patch.object(web_app, 'SETTINGS_FILE', str(self.settings_file)),
            mock.patch.object(web_app, 'TRASH_EMPTY_LOG', str(self.logs_dir / 'trash_empty.log')),
        ]
        for patcher in self.patches:
            patcher.start()

    def tearDown(self):
        for patcher in reversed(self.patches):
            patcher.stop()
        self.tmp.cleanup()

    def _write_settings(self, trash_dir):
        data = {
            'drive': {'enabled': False},
            'scheduler': {
                'enabled': False,
                'mode': 'filtered',
                'interval': 'daily',
                'hour': 3,
                'minute': 0,
                'lookback_days': 7,
            },
            'storage': {'trash_dir': trash_dir},
        }
        self.settings_file.write_text(yaml.dump(data, sort_keys=False), encoding='utf-8')

    def test_empty_trash_deletes_multiple_files_and_keeps_root(self):
        (self.trash_dir / 'a.m4a').write_text('aaa', encoding='utf-8')
        (self.trash_dir / 'b.mp3').write_text('bbb', encoding='utf-8')

        result = web_app.empty_trash_directory()

        self.assertEqual(result['success_count'], 2)
        self.assertEqual(result['failure_count'], 0)
        self.assertTrue(self.trash_dir.exists())
        self.assertEqual(list(self.trash_dir.iterdir()), [])

    def test_empty_trash_handles_empty_directory(self):
        result = web_app.empty_trash_directory()

        self.assertTrue(result['empty'])
        self.assertEqual(result['success_count'], 0)
        self.assertEqual(result['failure_count'], 0)
        self.assertTrue(self.trash_dir.exists())

    def test_empty_trash_deletes_subdirectories_without_deleting_root(self):
        subdir = self.trash_dir / 'batch' / 'audio'
        subdir.mkdir(parents=True)
        (subdir / 'nested.m4a').write_text('audio', encoding='utf-8')

        result = web_app.empty_trash_directory()

        self.assertEqual(result['success_count'], 1)
        self.assertEqual(result['failure_count'], 0)
        self.assertTrue(self.trash_dir.exists())
        self.assertEqual(list(self.trash_dir.iterdir()), [])

    def test_empty_trash_unlinks_symlink_without_touching_target(self):
        target = self.root / 'outside.txt'
        target.write_text('keep', encoding='utf-8')
        (self.trash_dir / 'linked.txt').symlink_to(target)

        result = web_app.empty_trash_directory()

        self.assertEqual(result['success_count'], 1)
        self.assertFalse((self.trash_dir / 'linked.txt').exists())
        self.assertEqual(target.read_text(encoding='utf-8'), 'keep')

    def test_invalid_trash_path_does_not_delete(self):
        audio_dir = self.data_dir / 'audio'
        audio_dir.mkdir()
        protected = audio_dir / 'recording.m4a'
        protected.write_text('keep', encoding='utf-8')
        self._write_settings('data/audio')

        result = web_app.empty_trash_directory()

        self.assertFalse(result['success'])
        self.assertEqual(result['success_count'], 0)
        self.assertTrue(protected.exists())

    def test_partial_failure_continues_with_other_files(self):
        good = self.trash_dir / 'good.m4a'
        bad = self.trash_dir / 'bad.m4a'
        good.write_text('good', encoding='utf-8')
        bad.write_text('bad', encoding='utf-8')
        original_unlink = Path.unlink

        def fake_unlink(path, missing_ok=False):
            if path == bad:
                raise OSError('permission denied')
            return original_unlink(path, missing_ok=missing_ok)

        with mock.patch.object(Path, 'unlink', new=fake_unlink):
            result = web_app.empty_trash_directory()

        self.assertEqual(result['success_count'], 1)
        self.assertGreaterEqual(result['failure_count'], 1)
        self.assertFalse(good.exists())
        self.assertTrue(bad.exists())

    def test_post_route_redirects_and_get_does_not_delete(self):
        file_path = self.trash_dir / 'route.m4a'
        file_path.write_text('audio', encoding='utf-8')
        client = web_app.app.test_client()

        get_response = client.get('/trash/empty')
        self.assertEqual(get_response.status_code, 405)
        self.assertTrue(file_path.exists())

        post_response = client.post('/trash/empty')
        self.assertEqual(post_response.status_code, 302)
        self.assertFalse(file_path.exists())

    def test_template_contains_empty_trash_confirmation(self):
        client = web_app.app.test_client()
        with mock.patch.object(web_app, 'get_recording_items', return_value=[]):
            response = client.get('/admin/files')

        body = response.get_data(as_text=True)
        self.assertIn('ゴミ箱を空にする', body)
        self.assertIn('この操作は元に戻せません', body)

    def test_empty_trash_writes_log(self):
        (self.trash_dir / 'logged.m4a').write_text('audio', encoding='utf-8')

        result = web_app.empty_trash_directory()

        self.assertEqual(result['success_count'], 1)
        log_text = (self.logs_dir / 'trash_empty.log').read_text(encoding='utf-8')
        self.assertIn('"level": "INFO"', log_text)
        self.assertIn('"success_count": 1', log_text)


if __name__ == '__main__':
    unittest.main()
