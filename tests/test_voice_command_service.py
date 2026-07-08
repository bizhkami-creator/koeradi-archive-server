import os
import sys
import unittest


ROOT_DIR = os.path.dirname(os.path.dirname(__file__))
WEB_ADMIN_DIR = os.path.join(ROOT_DIR, 'web_admin')
sys.path.insert(0, WEB_ADMIN_DIR)

from voice_command_service import LAST_CANDIDATES, VoiceCommandService


def make_recording(index, date):
    return {
        'file_id': f'file-{index}',
        'title': '辛坊治郎 ズーム そこまで言うか！',
        'station': 'ニッポン放送',
        'date': date,
    }


class VoiceCommandServiceTest(unittest.TestCase):
    def setUp(self):
        LAST_CANDIDATES.clear()

    def tearDown(self):
        LAST_CANDIDATES.clear()

    def make_service(self, search_results=None, latest=None):
        latest_recording = latest or make_recording(0, '2026-07-07')
        results = search_results if search_results is not None else []
        return VoiceCommandService(
            latest_recording_provider=lambda: latest_recording,
            recording_search_provider=lambda query: results,
        )

    def test_multiple_search_results_return_select_response(self):
        service = self.make_service([
            make_recording(1, '2026-07-06'),
            make_recording(2, '2026-07-05'),
            make_recording(3, '2026-07-04'),
            make_recording(4, '2026-07-03'),
            make_recording(5, '2026-07-02'),
            make_recording(6, '2026-07-01'),
        ])

        response = service.handle('辛坊')

        self.assertTrue(response['ok'])
        self.assertEqual(response['action'], 'select')
        self.assertEqual(len(response['candidates']), 5)
        self.assertEqual(response['candidates'][0]['index'], 1)
        self.assertEqual(response['candidates'][0]['file_id'], 'file-1')
        self.assertIn('6件見つかりました', response['message'])
        self.assertIn('1番', response['message'])
        self.assertIn('2番', response['message'])
        self.assertIn('3番', response['message'])
        self.assertNotIn('4番', response['message'])
        self.assertEqual(len(LAST_CANDIDATES), 5)

    def test_selection_command_plays_saved_candidate_and_clears_state(self):
        service = self.make_service([
            make_recording(1, '2026-07-06'),
            make_recording(2, '2026-07-05'),
        ])
        service.handle('辛坊')

        response = service.handle('2番')

        self.assertTrue(response['ok'])
        self.assertEqual(response['action'], 'play')
        self.assertEqual(response['message'], '2番を再生します')
        self.assertEqual(response['file_id'], 'file-2')
        self.assertEqual(LAST_CANDIDATES, [])

    def test_selection_command_variants(self):
        variants = [
            ('1番', 'file-1'),
            ('一番', 'file-1'),
            ('いちばん', 'file-1'),
            ('2番', 'file-2'),
            ('二番', 'file-2'),
            ('にばん', 'file-2'),
            ('3番', 'file-3'),
            ('三番', 'file-3'),
            ('さんばん', 'file-3'),
            ('最新', 'file-1'),
        ]

        for command, expected_file_id in variants:
            with self.subTest(command=command):
                service = self.make_service([
                    make_recording(1, '2026-07-06'),
                    make_recording(2, '2026-07-05'),
                    make_recording(3, '2026-07-04'),
                ])
                service.handle('辛坊')

                response = service.handle(command)

                self.assertTrue(response['ok'])
                self.assertEqual(response['action'], 'play')
                self.assertEqual(response['file_id'], expected_file_id)

    def test_cancel_clears_candidates(self):
        service = self.make_service([
            make_recording(1, '2026-07-06'),
            make_recording(2, '2026-07-05'),
        ])
        service.handle('辛坊')

        response = service.handle('キャンセル')

        self.assertTrue(response['ok'])
        self.assertEqual(response['action'], 'none')
        self.assertEqual(response['message'], 'キャンセルしました')
        self.assertEqual(LAST_CANDIDATES, [])

    def test_selection_without_candidates_returns_error(self):
        service = self.make_service()

        response = service.handle('2番')

        self.assertFalse(response['ok'])
        self.assertEqual(response['message'], '選択できる候補がありません')

    def test_single_search_result_still_returns_play(self):
        service = self.make_service([make_recording(1, '2026-07-06')])

        response = service.handle('辛坊')

        self.assertTrue(response['ok'])
        self.assertEqual(response['action'], 'play')
        self.assertEqual(response['file_id'], 'file-1')

    def test_latest_without_candidates_still_plays_latest_recording(self):
        service = self.make_service(search_results=[], latest=make_recording(9, '2026-07-07'))

        response = service.handle('最新')

        self.assertTrue(response['ok'])
        self.assertEqual(response['action'], 'play')
        self.assertEqual(response['file_id'], 'file-9')

    def test_help_commands_return_spoken_guidance_without_action(self):
        service = self.make_service()

        for command in ('使い方', '何ができる', 'ヘルプ'):
            with self.subTest(command=command):
                response = service.handle(command)

                self.assertTrue(response['ok'])
                self.assertEqual(response['action'], 'none')
                self.assertEqual(response['message'], VoiceCommandService.HELP_MESSAGE)


if __name__ == '__main__':
    unittest.main()
