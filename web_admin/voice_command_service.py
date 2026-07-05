import re


class VoiceCommandService:
    """音声認識テキストを共通クライアント向けコマンドへ変換するサービス。"""

    PLAY_COMMANDS = {'再生', '最新'}
    PAUSE_COMMANDS = {'止めて'}
    STATUS_COMMANDS = {'状態'}

    def __init__(self, latest_recording_provider):
        self.latest_recording_provider = latest_recording_provider

    def handle(self, query):
        command = self._normalize_query(query)
        if not command:
            return {'ok': False, 'message': '音声コマンドが空です'}

        if command in self.PLAY_COMMANDS:
            return self._play_latest()

        if command in self.PAUSE_COMMANDS:
            return {
                'ok': True,
                'action': 'pause',
                'message': '再生を停止します',
            }

        if command in self.STATUS_COMMANDS:
            return {
                'ok': True,
                'action': 'status',
                'message': '状態を確認します',
            }

        return {'ok': False, 'message': '対応していない音声コマンドです'}

    def _play_latest(self):
        latest = self.latest_recording_provider()
        if not latest:
            return {'ok': False, 'message': '録音が見つかりません'}

        return {
            'ok': True,
            'action': 'play',
            'message': '最新の録音を再生します',
            'file_id': latest['file_id'],
        }

    @staticmethod
    def _normalize_query(query):
        return re.sub(r'\s+', '', str(query or '').strip())
