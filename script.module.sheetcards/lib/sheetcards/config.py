"""Every setting of both front-ends in one table. tools/make_settings_sheetcards.py turns it
into each add-on's settings.xml and strings.po; read() loads values with the right types and
defaults. No Kodi imports.

Each row says which add-on has it: 'both', 'app' (script.sheetcards) or 'ss' (the screensaver).
"""

from . import APP_ID, LIBRARY_ID, SCREENSAVER_ID
from .theme import ACCENT_NAMES, CUSTOM

MODE_FLASH, MODE_CHOICE, MODE_MIXED = 0, 1, 2
DIR_QA, DIR_AQ, DIR_BOTH = 0, 1, 2
OPTION_COUNTS = [3, 4]
SESSION_LENGTHS = [10, 20, 30, 50, None]


def B(sid, label, default, who='both', **kw):
    return dict(id=sid, type='boolean', label=label, default=default, who=who, **kw)


def O(sid, label, default, options, who='both', **kw):
    return dict(id=sid, type='options', label=label, default=default, options=options, who=who, **kw)


def S(sid, label, default, lo, hi, step=1, who='both', **kw):
    return dict(id=sid, type='slider', label=label, default=default, min=lo, max=hi, step=step, who=who, **kw)


def T(sid, label, default='', who='both', **kw):
    return dict(id=sid, type='string', label=label, default=default, who=who, **kw)


def A(sid, label, command, who='both', **kw):
    return dict(id=sid, type='action', label=label, command=command, who=who, **kw)


CATEGORIES = [
    ('Source', [
        B('use_app_settings', 'Use the Sheetcards app\'s settings', True, who='ss', local=True),
        T('sheet_id', 'Google Sheet ID or link'),
        A('choose_decks', 'Choose decks...', 'choose_decks'),
        T('decks', 'Decks', level=4),
        O('header_row', 'First row is a header', 0, ['Auto', 'Yes', 'No']),
        T('tab_names', 'Tab names if they cannot be found (comma separated)'),
        S('refresh_hours', 'Refresh from Google every (hours, 0 = every start)', 6, 0, 72),
    ]),
    ('Study', [
        O('mode', 'Mode', MODE_MIXED, ['Flashcard', 'Multiple choice', 'Mixed']),
        S('mix_ratio', 'Mixed: share of multiple choice (%)', 50, 10, 90, 10, visible=('mode', MODE_MIXED)),
        O('direction', 'Direction', DIR_QA, ['Question -> Answer', 'Answer -> Question', 'Both']),
        O('options', 'Multiple choice options', 1, ['3', '4']),
        O('distractor_scope', 'Wrong answers come from', 0, ['This deck', 'All selected decks']),
        S('question_seconds', 'Question shows for (seconds)', 8, 3, 30, who='ss', local=True),
        S('answer_seconds', 'Answer shows for (seconds)', 6, 2, 20, who='ss', local=True),
        B('show_timer_bar', 'Show the timer bar', True, who='ss', local=True),
        O('order', 'Card order', 0, ['Smart (spaced repetition)', 'Shuffle', 'Sheet order', 'Hardest first'],
          who='app'),
        O('cards_per_session', 'Cards per session', 1, ['10', '20', '30', '50', 'All'], who='app'),
        B('srs_enabled', 'Spaced repetition', True, who='app'),
        S('new_per_session', 'New cards per session', 10, 0, 50, who='app', visible='srs_enabled'),
        B('auto_advance', 'Move on automatically after an answer', True, who='app'),
        S('advance_ms_correct', 'After a correct answer (ms)', 900, 300, 3000, 100, who='app',
          visible='auto_advance'),
        S('advance_ms_wrong', 'After a wrong answer (ms)', 2200, 500, 6000, 100, who='app', visible='auto_advance'),
    ]),
    ('Look', [
        O('theme_mode', 'Theme', 0, ['Night', 'Day', 'Auto']),
        dict(id='day_starts', type='time', label='Day starts at', default='07:00', who='both', visible=('theme_mode', 2)),
        dict(id='night_starts', type='time', label='Night starts at', default='19:00', who='both',
             visible=('theme_mode', 2)),
        O('accent', 'Accent colour', 0, ACCENT_NAMES),
        T('accent_custom', 'Custom accent colour (hex RRGGBB)', visible=('accent', CUSTOM)),
        T('bg_custom', 'Custom background colour (hex RRGGBB, empty = theme)'),
        T('card_custom', 'Custom card colour (hex RRGGBB, empty = theme)'),
        O('background_style', 'Background', 1, ['Solid', 'Soft glow']),
        B('show_clock', 'Show a clock', False, who='ss', local=True),
        S('dim_after_minutes', 'Dim after (minutes, 0 = never)', 0, 0, 120, 5, who='ss', local=True),
    ]),
    ('Advanced', [
        T('api_key', 'Google API key (optional, for tab discovery)', hidden=True),
        A('refresh_now', 'Refresh now', 'refresh', who='app'),
        A('reset_progress', 'Reset progress...', 'reset_progress', who='app'),
        A('clear_cache', 'Clear cache', 'clear_cache'),
        B('debug_log', 'Debug logging', False),
    ]),
]

# On-screen text, in the library's strings.po (ids from 32000).
STRINGS = {
    32000: 'Add your Google Sheet ID in settings',
    32001: 'Open the Sheetcards settings and paste the sheet\'s ID or its link.',
    32002: 'This sheet isn\'t shared',
    32003: 'Set sharing to Anyone with the link -> Viewer.',
    32004: 'Sheet not found',
    32005: 'Check the ID in settings.',
    32006: 'No cards yet',
    32007: 'Couldn\'t reach Google Sheets. Check the network.',
    32008: 'Open settings',
    32009: 'Retry',
    32010: 'Loading cards...',
    32011: 'No cards in this sheet',
    32012: 'Column A is the question, column B the answer.',
    32013: 'Start',
    32014: 'Refresh',
    32015: 'Settings',
    32016: 'Flashcard',
    32017: 'Multiple choice',
    32018: 'Mixed',
    32019: '%d cards',
    32020: '%d due',
    32021: 'Offline · updated %s',
    32022: 'Missed it',
    32023: 'Got it',
    32024: 'Score',
    32025: 'Streak',
    32026: 'Paused',
    32027: 'Resume',
    32028: 'End session',
    32029: 'Quit',
    32030: 'Accuracy',
    32031: 'Best streak',
    32032: 'Time',
    32033: 'Missed cards',
    32034: 'Review missed',
    32035: 'New session',
    32036: 'Decks',
    32037: 'Box %d of 5',
    32038: 'New card',
    32039: 'Seen %d times',
    32040: 'Last answer: correct',
    32041: 'Last answer: wrong',
    32042: 'Press Select to flip',
    32043: 'Select decks, then Start',
    32044: 'Best streak %d · %d sessions · %s accuracy',
    32045: 'Refreshing...',
    32046: 'Updated %s',
    32047: 'Some decks have too few different answers for multiple choice; they run as flashcards.',
    32048: 'Nothing missed. Well done!',
    32049: 'Choose decks',
    32050: 'Reset all progress for this sheet?',
    32051: 'Progress reset',
    32052: 'Cache cleared',
    32053: 'Cards refreshed: %d decks, %d cards',
    32054: 'just now',
    32055: '%d min ago',
    32056: '%d h ago',
    32057: '%d days ago',
    32058: 'Answer',
    32059: 'Question',
    32060: 'Due now',
    32061: 'Due %s',
    32062: 'Session complete',
    32063: 'Something went wrong loading the sheet.',
    32064: 'Press Select to continue',
    32065: '%d / %d',
}


def rows(who=None):
    for title, settings in CATEGORIES:
        for s in settings:
            if who is None or s['who'] in ('both', who):
                yield title, s


def all_settings(who=None):
    for _title, s in rows(who):
        if s['type'] != 'action':
            yield s


def shared_ids():
    """Settings the screensaver takes from the app when use_app_settings is on."""
    return [s['id'] for s in all_settings() if s['who'] == 'both']


def default_of(s):
    return s['default']


def defaults(who=None):
    return dict((s['id'], default_of(s)) for s in all_settings(who))


def read(getters, who):
    """Settings for one add-on as a dict. getters: {'boolean', 'integer', 'string'} -> f(id),
    the Kodi layer passes Addon accessors. Bad or missing values fall back to defaults."""
    out = {}
    for s in all_settings(who):
        kind = s['type']
        try:
            if kind == 'boolean':
                value = bool(getters['boolean'](s['id']))
            elif kind in ('options', 'slider'):
                value = int(getters['integer'](s['id']))
                if kind == 'options' and not 0 <= value < len(s['options']):
                    value = s['default']
                if kind == 'slider':
                    value = min(s['max'], max(s['min'], value))
            else:
                value = (getters['string'](s['id']) or '').strip()
                if kind == 'time' and not value:
                    value = s['default']
            out[s['id']] = value
        except Exception:
            out[s['id']] = default_of(s)
    return out


def option_count(settings):
    return OPTION_COUNTS[settings.get('options', 1)] if 0 <= settings.get('options', 1) < 2 else 4


def session_length(settings):
    i = settings.get('cards_per_session', 1)
    return SESSION_LENGTHS[i] if 0 <= i < len(SESSION_LENGTHS) else 20


ADDONS = {APP_ID: 'app', SCREENSAVER_ID: 'ss'}
LIBRARY = LIBRARY_ID
