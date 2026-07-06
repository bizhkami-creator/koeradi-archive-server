import re


class VoiceCommandService:
    """音声認識テキストを共通クライアント向けコマンドへ変換するサービス。"""

    PLAY_COMMANDS = {'再生', '最新'}
    PAUSE_COMMANDS = {'止めて'}
    STATUS_COMMANDS = {'状態'}
    SEARCH_SUFFIXES = (
        'を再生',
        'を探して',
        'を聞きたい',
        'を聴きたい',
        '聞きたい',
        '聴きたい',
        '再生',
        '探して',
    )
    STATION_ALIASES = {
        'TBS': ('TBSラジオ', ('TBSラジオ', 'TBS')),
        'tbs': ('TBSラジオ', ('TBSラジオ', 'TBS')),
        'TBSラジオ': ('TBSラジオ', ('TBSラジオ', 'TBS')),
        '文化放送': ('文化放送', ('文化放送', 'QRR')),
        'QRR': ('文化放送', ('文化放送', 'QRR')),
        'qrr': ('文化放送', ('文化放送', 'QRR')),
        'ニッポン放送': ('ニッポン放送', ('ニッポン放送', 'LFR')),
        'LFR': ('ニッポン放送', ('ニッポン放送', 'LFR')),
        'lfr': ('ニッポン放送', ('ニッポン放送', 'LFR')),
        'ラジオ日本': ('ラジオ日本', ('ラジオ日本', 'RF')),
        'RF': ('ラジオ日本', ('ラジオ日本', 'RF')),
        'rf': ('ラジオ日本', ('ラジオ日本', 'RF')),
    }
    PERSONALITY_ALIASES = {
        '安住': '安住紳一郎',
        '安住さん': '安住紳一郎',
        '辛坊': '辛坊治郎',
        '伊集院': '伊集院光',
    }

    def __init__(self, latest_recording_provider, recording_search_provider=None):
        self.latest_recording_provider = latest_recording_provider
        self.recording_search_provider = recording_search_provider

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

        search_query = self._extract_search_query(command)
        if search_query:
            return self._play_search_result(search_query)

        return self._play_search_result(command)

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

    def _play_search_result(self, search_query):
        if not self.recording_search_provider:
            return {'ok': False, 'message': '対応していない音声コマンドです'}

        display_query, search_terms = self._normalize_search_query(search_query)
        results = []
        for term in search_terms:
            results = self.recording_search_provider(term)
            if results:
                break

        if not results:
            return {'ok': False, 'message': f'{display_query}の録音が見つかりません'}

        recording = results[0]
        return {
            'ok': True,
            'action': 'play',
            'message': f'{display_query}を再生します',
            'file_id': recording['file_id'],
        }

    @staticmethod
    def _normalize_query(query):
        return re.sub(r'\s+', '', str(query or '').strip())

    @classmethod
    def _extract_search_query(cls, command):
        for suffix in cls.SEARCH_SUFFIXES:
            if command.endswith(suffix):
                search_query = command[:-len(suffix)]
                return search_query.strip()
        return ''

    @classmethod
    def _normalize_search_query(cls, search_query):
        if search_query in cls.STATION_ALIASES:
            display_query, search_terms = cls.STATION_ALIASES[search_query]
            return display_query, cls._unique_terms(search_terms)

        if search_query in cls.PERSONALITY_ALIASES:
            display_query = cls.PERSONALITY_ALIASES[search_query]
            return display_query, cls._unique_terms((display_query, search_query))

        return search_query, (search_query,)

    @staticmethod
    def _unique_terms(terms):
        unique = []
        for term in terms:
            if term and term not in unique:
                unique.append(term)
        return tuple(unique)
