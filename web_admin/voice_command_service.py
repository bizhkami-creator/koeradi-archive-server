import datetime
import re


# Single-user in-memory candidate state for Raspberry Pi home use.
# Future multi-client support should key this by session_id or client_id.
LAST_CANDIDATES = []


class VoiceCommandService:
    """音声認識テキストを共通クライアント向けコマンドへ変換するサービス。"""

    PLAY_COMMANDS = {'再生', '最新'}
    PAUSE_COMMANDS = {'止めて'}
    STATUS_COMMANDS = {'状態'}
    HELP_COMMANDS = {'使い方', '何ができる', 'ヘルプ'}
    HELP_MESSAGE = '番組名だけで再生できます。例えば、辛坊、TBS、昨日の辛坊、と話してください。候補が複数ある場合は、1番、2番、と話してください。停止するときは、止めて、と話してください。'
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

    JST = datetime.timezone(datetime.timedelta(hours=9))
    RELATIVE_DATE_KEYWORDS = (
        ('一昨日', 2),
        ('昨日', 1),
        ('今日', 0),
    )
    ABSOLUTE_DATE_PATTERN = re.compile(r'((?:(\d{4})年)?(\d{1,2})月(\d{1,2})日)の?')
    RECORDING_DATE_PATTERNS = (
        re.compile(r'(?<!\d)(\d{4})-(\d{1,2})-(\d{1,2})(?!\d)'),
        re.compile(r'(?<!\d)(\d{4})/(\d{1,2})/(\d{1,2})(?!\d)'),
        re.compile(r'(?<!\d)(\d{4})(\d{2})(\d{2})(?!\d)'),
    )
    MAX_STORED_CANDIDATES = 5
    MAX_SPOKEN_CANDIDATES = 3
    SELECTION_COMMANDS = {
        '1番': 1,
        '一番': 1,
        'いちばん': 1,
        '2番': 2,
        '二番': 2,
        'にばん': 2,
        '3番': 3,
        '三番': 3,
        'さんばん': 3,
    }
    LATEST_SELECTION_COMMAND = '最新'
    CANCEL_SELECTION_COMMAND = 'キャンセル'

    def __init__(
        self,
        latest_recording_provider,
        recording_search_provider=None,
        recording_list_provider=None,
        now_provider=None,
    ):
        self.latest_recording_provider = latest_recording_provider
        self.recording_search_provider = recording_search_provider
        self.recording_list_provider = recording_list_provider
        self.now_provider = now_provider

    def handle(self, query):
        command = self._normalize_query(query)
        if not command:
            return {'ok': False, 'message': '音声コマンドが空です'}

        if command in self.HELP_COMMANDS:
            return {
                'ok': True,
                'action': 'none',
                'message': self.HELP_MESSAGE,
            }

        selection_response = self._handle_candidate_selection(command)
        if selection_response:
            return selection_response

        if command in self.PLAY_COMMANDS:
            self._clear_candidates()
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

        date_condition, command_without_date = self._extract_date_condition(command, self._current_date_jst())
        search_query = self._extract_search_query(command_without_date)
        if search_query:
            return self._play_search_result(search_query, date_condition)

        if date_condition and not command_without_date:
            self._clear_candidates()
            return {'ok': False, 'message': '検索語が空です'}

        return self._play_search_result(command_without_date, date_condition)

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

    def _play_search_result(self, search_query, date_condition=None):
        if not self.recording_search_provider and not self.recording_list_provider:
            return {'ok': False, 'message': '対応していない音声コマンドです'}

        display_query, search_terms = self._normalize_search_query(search_query)
        results = self._search_recordings(search_terms, date_condition)

        if not results:
            self._clear_candidates()
            return {'ok': False, 'message': f'{self._format_display_query(display_query, date_condition)}の録音が見つかりません'}

        if len(results) > 1:
            return self._select_from_search_results(results)

        self._clear_candidates()
        recording = results[0]
        return {
            'ok': True,
            'action': 'play',
            'message': f'{self._format_display_query(display_query, date_condition)}を再生します',
            'file_id': recording['file_id'],
        }

    def _handle_candidate_selection(self, command):
        if command == self.CANCEL_SELECTION_COMMAND:
            self._clear_candidates()
            return {
                'ok': True,
                'action': 'none',
                'message': 'キャンセルしました',
            }

        index = self.SELECTION_COMMANDS.get(command)
        if command == self.LATEST_SELECTION_COMMAND and LAST_CANDIDATES:
            index = 1
        if not index:
            return None

        if not LAST_CANDIDATES:
            return {'ok': False, 'message': '選択できる候補がありません'}
        if index > len(LAST_CANDIDATES):
            return {'ok': False, 'message': f'{index}番の候補はありません'}

        recording = LAST_CANDIDATES[index - 1]
        self._clear_candidates()
        return {
            'ok': True,
            'action': 'play',
            'message': f'{index}番を再生します',
            'file_id': recording['file_id'],
        }

    def _select_from_search_results(self, results):
        stored_candidates = results[:self.MAX_STORED_CANDIDATES]
        self._set_candidates(stored_candidates)

        spoken_candidates = stored_candidates[:self.MAX_SPOKEN_CANDIDATES]
        spoken_parts = [
            f'{index}番、{self._format_candidate_label(recording)}。'
            for index, recording in enumerate(spoken_candidates, start=1)
        ]
        return {
            'ok': True,
            'action': 'select',
            'message': f'{len(results)}件見つかりました。{"".join(spoken_parts)}番号を選んでください。',
            'candidates': [
                self._serialize_candidate(index, recording)
                for index, recording in enumerate(stored_candidates, start=1)
            ],
        }

    @staticmethod
    def _set_candidates(candidates):
        LAST_CANDIDATES.clear()
        LAST_CANDIDATES.extend(candidates)

    @staticmethod
    def _clear_candidates():
        LAST_CANDIDATES.clear()

    @classmethod
    def _serialize_candidate(cls, index, recording):
        return {
            'index': index,
            'file_id': recording.get('file_id', ''),
            'title': recording.get('title') or recording.get('program_name') or '',
            'station': recording.get('station') or recording.get('station_name') or '',
            'date': recording.get('date') or cls._extract_recording_date(recording),
        }

    @classmethod
    def _format_candidate_label(cls, recording):
        title = recording.get('title') or recording.get('program_name') or recording.get('file_name') or recording.get('filename') or '録音'
        date_label = cls._format_candidate_date(recording.get('date') or cls._extract_recording_date(recording))
        if date_label:
            return f'{title} {date_label}'
        return title

    @staticmethod
    def _format_candidate_date(date_value):
        match = re.fullmatch(r'(\d{4})-(\d{1,2})-(\d{1,2})', str(date_value or '').strip())
        if not match:
            return ''
        return f'{int(match.group(2))}月{int(match.group(3))}日'

    def _search_recordings(self, search_terms, date_condition=None):
        if self.recording_list_provider and (date_condition or not self.recording_search_provider):
            candidates = self.recording_list_provider()
            if date_condition:
                candidates = self._filter_recordings_by_date(
                    candidates,
                    date_condition['date'],
                )
            return [
                item for item in candidates
                if self._recording_matches_terms(item, search_terms)
            ]

        results = []
        for term in search_terms:
            results = self.recording_search_provider(term)
            if results:
                break

        if date_condition:
            results = self._filter_recordings_by_date(results, date_condition['date'])
        return results

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
    def _extract_date_condition(cls, command, today=None):
        today = today or cls._today_jst()

        for keyword, days_ago in cls.RELATIVE_DATE_KEYWORDS:
            match = re.search(f'{keyword}の?', command)
            if not match:
                continue
            target_date = today - datetime.timedelta(days=days_ago)
            return (
                {
                    'date': target_date.isoformat(),
                    'label': keyword,
                },
                cls._remove_match(command, match),
            )

        match = cls.ABSOLUTE_DATE_PATTERN.search(command)
        if match:
            year = int(match.group(2)) if match.group(2) else today.year
            month = int(match.group(3))
            day = int(match.group(4))
            try:
                target_date = datetime.date(year, month, day)
            except ValueError:
                return None, command
            return (
                {
                    'date': target_date.isoformat(),
                    'label': match.group(1),
                },
                cls._remove_match(command, match),
            )

        return None, command

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

    @classmethod
    def _today_jst(cls):
        return datetime.datetime.now(cls.JST).date()

    def _current_date_jst(self):
        if self.now_provider:
            now = self.now_provider()
            if isinstance(now, datetime.datetime):
                return now.astimezone(self.JST).date() if now.tzinfo else now.date()
            if isinstance(now, datetime.date):
                return now
        return self._today_jst()

    @staticmethod
    def _remove_match(command, match):
        return f'{command[:match.start()]}{command[match.end():]}'.strip()

    @staticmethod
    def _format_display_query(display_query, date_condition=None):
        if not date_condition:
            return display_query
        return f"{date_condition['label']}の{display_query}"

    @classmethod
    def _filter_recordings_by_date(cls, recordings, target_date):
        return [
            item for item in recordings
            if cls._extract_recording_date(item) == target_date
        ]

    @classmethod
    def _extract_recording_date(cls, item):
        date_value = str(item.get('date') or '').strip()
        if re.fullmatch(r'\d{4}-\d{1,2}-\d{1,2}', date_value):
            return cls._normalize_date_parts(*date_value.split('-'))

        for key in ('filename', 'file_name', 'path', 'relative_path'):
            value = str(item.get(key) or '')
            for pattern in cls.RECORDING_DATE_PATTERNS:
                match = pattern.search(value)
                if match:
                    return cls._normalize_date_parts(*match.groups())
        return ''

    @staticmethod
    def _normalize_date_parts(year, month, day):
        try:
            return datetime.date(int(year), int(month), int(day)).isoformat()
        except ValueError:
            return ''

    @staticmethod
    def _recording_matches_terms(item, search_terms):
        haystack = ' '.join([
            str(item.get('title', '')),
            str(item.get('program_name', '')),
            str(item.get('station', '')),
            str(item.get('station_name', '')),
            str(item.get('filename', '')),
            str(item.get('file_name', '')),
            str(item.get('path', '')),
            str(item.get('relative_path', '')),
        ]).lower()
        return any(str(term).lower() in haystack for term in search_terms)
