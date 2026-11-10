"""Every setting, string and colour in one table. No Kodi imports, so the tests can use it.

tools/make_hackernews_settings.py turns SETTINGS and STRINGS into resources/settings.xml and
resources/language/resource.language.en_gb/strings.po; read() loads the values with the right
types, defaults and clamping.
"""

ADDON_ID = 'screensaver.hackernews'
ADDON_NAME = 'Hacker News'
ADDON_VERSION = '0.1.0'

# The story lists, in the order of the setting's options.
LIST_KEYS = ['top', 'best', 'new', 'ask', 'show']
LIST_LABEL_IDS = [30102, 30103, 30104, 30105, 30106]   # Top, Best, New, Ask, Show

STRINGS = {
    30100: 'Content',
    30101: 'Story list',
    30102: 'Top',
    30103: 'Best',
    30104: 'New',
    30105: 'Ask',
    30106: 'Show',
    30107: 'Number of stories',
    30108: 'Comments per story',
    30109: 'Include the first reply under each comment',
    30110: 'Minimum comment characters',
    30111: 'Maximum comment characters',
    30112: 'Timing',
    30113: 'Story slide seconds',
    30114: 'Minimum comment seconds',
    30115: 'Maximum comment seconds',
    30116: 'Reading speed (words per minute)',
    30117: 'Data refresh interval (minutes)',
    30118: 'Appearance',
    30119: 'Theme',
    30120: 'Dark',
    30121: 'OLED black',
    30122: 'Light',
    30123: 'Font scale (percent)',
    30124: 'Show clock',
    30125: 'Burn-in drift',
    30126: 'Show score, author and age',
    30127: 'Advanced',
    30128: 'Randomize starting story',
    30129: 'Use Algolia for comments',
    30130: 'Clear cache',
    30131: 'Debug logging',
    32000: 'Hacker News',
    32001: 'Loading Hacker News…',
    32002: "Can't reach Hacker News",
    32003: 'offline, showing cached data',
    32004: '%d / %d',
    32005: '%d comments',
    32006: '%d points',
    32007: 'by %s',
    32008: '%s ago',
    32009: 'No stories to show',
    32010: 'Cached stories cleared',
    32011: 'just now',
}


def B(sid, label, default):
    return dict(id=sid, type='boolean', label=label, default=default)


def O(sid, label, default, options):
    """A spinner. The value stored is the index of the chosen option."""
    return dict(id=sid, type='options', label=label, default=default, options=options)


def S(sid, label, default, lo, hi, step=1):
    return dict(id=sid, type='slider', label=label, default=default, min=lo, max=hi, step=step)


def A(sid, label, command):
    return dict(id=sid, type='action', label=label, command=command)


CATEGORIES = [
    (30100, [
        O('list', 30101, 0, LIST_LABEL_IDS),
        S('stories', 30107, 15, 5, 50),
        S('comments', 30108, 3, 0, 10),
        B('include_reply', 30109, False),
        S('min_chars', 30110, 40, 0, 400, 10),
        S('max_chars', 30111, 700, 200, 2000, 50),
    ]),
    (30112, [
        S('story_seconds', 30113, 8, 3, 60),
        S('comment_min', 30114, 6, 3, 60),
        S('comment_max', 30115, 30, 10, 180, 5),
        S('wpm', 30116, 220, 120, 400, 10),
        S('refresh_minutes', 30117, 30, 5, 240, 5),
    ]),
    (30118, [
        O('theme', 30119, 0, [30120, 30121, 30122]),
        S('font_scale', 30123, 100, 80, 120, 10),
        B('clock', 30124, True),
        B('drift', 30125, True),
        B('meta', 30126, True),
    ]),
    (30127, [
        B('randomize', 30128, True),
        B('use_algolia', 30129, True),
        A('clear_cache', 30130, 'clear_cache'),
        B('debug', 30131, False),
    ]),
]

# ARGB colours for the skin: background, body text, secondary text, accent, progress track.
THEMES = [
    dict(bg='FF101214', text='FFEDEBE8', dim='FF8E8C88', accent='FFFF6600', track='33FFFFFF'),
    dict(bg='FF000000', text='FFF2F0ED', dim='FF8A8884', accent='FFFF6600', track='33FFFFFF'),
    dict(bg='FFF5F2EC', text='FF1A1A1A', dim='FF5E5C58', accent='FFFF6600', track='33000000'),
]


def all_settings():
    for _label, settings in CATEGORIES:
        for setting in settings:
            if setting['type'] != 'action':
                yield setting


def defaults():
    return dict((s['id'], s['default']) for s in all_settings())


def read(getters):
    """Settings as a dict. getters: {'boolean', 'integer', 'string'} -> f(setting id);
    the Kodi layer passes Addon accessors. Bad or missing values fall back to defaults."""
    out = {}
    for s in all_settings():
        kind = s['type']
        try:
            if kind == 'boolean':
                value = bool(getters['boolean'](s['id']))
            else:
                value = int(getters['integer'](s['id']))
                if kind == 'options' and not 0 <= value < len(s['options']):
                    value = s['default']
                elif kind == 'slider':
                    value = max(s['min'], min(s['max'], value))
        except Exception:
            value = s['default']
        out[s['id']] = value
    return out


def list_key(settings):
    index = settings.get('list', 0)
    if not 0 <= index < len(LIST_KEYS):
        index = 0
    return LIST_KEYS[index]


def source_label_id(settings):
    index = settings.get('list', 0)
    if not 0 <= index < len(LIST_LABEL_IDS):
        index = 0
    return LIST_LABEL_IDS[index]


def theme_colours(settings):
    index = settings.get('theme', 0)
    if not 0 <= index < len(THEMES):
        index = 0
    return THEMES[index]


def refresh_seconds(settings):
    return max(1, settings.get('refresh_minutes', 30)) * 60
