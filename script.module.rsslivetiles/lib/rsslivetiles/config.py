"""Every setting of both add-ons in one table. tools/make_settings_rsslivetiles.py turns it into
each add-on's settings.xml and strings.po; read() loads values with the right types and
defaults. No Kodi imports.

Each row says which add-on has it: 'both', 'app' (script.rsslivetiles) or 'ss' (the
screensaver). The screensaver takes everything it does not have itself (fetching, per-feed
accents, images ...) from the program when the program is installed, else the defaults.
"""

from . import APP_ID, SCREENSAVER_ID
from .theme import ACCENT_NAMES, CUSTOM, DEFAULT_ACCENT

APP_LAYOUTS = ['feed_groups', 'mixed_wall', 'magazine', 'spotlight', 'mosaic']
SS_LAYOUTS = ['mixed_wall', 'magazine', 'spotlight', 'mosaic']
STYLES = ['classic', 'modern', 'outline']
LAYOUT_LABELS = {'feed_groups': 'Feed groups', 'mixed_wall': 'Mixed wall', 'magazine': 'Magazine',
                 'spotlight': 'Spotlight', 'mosaic': 'Mosaic'}
THEME_LABELS = ['Night', 'Day', 'Scheduled', 'Sunrise / sunset']
SAME = 'Same as program'


def B(sid, label, default, who='app', **kw):
    return dict(id=sid, type='boolean', label=label, default=default, who=who, **kw)


def O(sid, label, default, options, who='app', **kw):
    return dict(id=sid, type='options', label=label, default=default, options=options, who=who, **kw)


def S(sid, label, default, lo, hi, step=1, who='app', **kw):
    return dict(id=sid, type='slider', label=label, default=default, min=lo, max=hi, step=step, who=who, **kw)


def T(sid, label, default='', who='app', **kw):
    return dict(id=sid, type='string', label=label, default=default, who=who, **kw)


def A(sid, label, command, who='app', **kw):
    return dict(id=sid, type='action', label=label, command=command, who=who, **kw)


def TIME(sid, label, default, who='app', **kw):
    return dict(id=sid, type='time', label=label, default=default, who=who, **kw)


def N(sid, label, default, who='app', **kw):
    return dict(id=sid, type='number', label=label, default=default, who=who, **kw)


CATEGORIES = [
    ('Feeds', [
        A('manage_feeds', 'Manage feeds...', 'manage', who='both'),
        A('import_opml', 'Import OPML...', 'import_opml'),
        A('export_opml', 'Export OPML...', 'export_opml'),
        S('refresh_min', 'Default refresh interval (minutes)', 30, 5, 240, 5),
        S('max_items', 'Max items per feed', 30, 5, 100, 5),
        S('max_age_days', 'Max item age (days)', 7, 1, 60),
    ]),
    ('Appearance', [
        O('layout', 'Layout', 0, [LAYOUT_LABELS[n] for n in APP_LAYOUTS]),
        O('style', 'Tile style', 0, ['Classic', 'Modern', 'Outline']),
        O('accent', 'Accent colour', DEFAULT_ACCENT, ACCENT_NAMES),
        T('accent_custom', 'Custom accent colour (hex RRGGBB)', visible=('accent', CUSTOM)),
        B('per_feed_accents', 'Use per-feed accents', True),
        B('shade_variation', 'Tile shade variation', True),
        O('theme_mode', 'Theme mode', 0, THEME_LABELS),
        TIME('day_start', 'Day starts at', '07:00', visible=('theme_mode', 2)),
        TIME('night_start', 'Night starts at', '19:00', visible=('theme_mode', 2)),
        N('latitude', 'Latitude', '51.5', visible=('theme_mode', 3)),
        N('longitude', 'Longitude', '-0.1', visible=('theme_mode', 3)),
        S('sun_offset', 'Sunrise / sunset offset (minutes)', 0, -120, 120, 5, visible=('theme_mode', 3)),
        B('show_images', 'Show images on tiles', True),
        B('og_image', 'Fetch article images (og:image) when a feed has none', False),
        B('show_qr', 'Show QR code for article link', True),
    ]),
    ('Screensaver', [
        O('ss_layout', 'Layout', 0, [LAYOUT_LABELS[n] for n in SS_LAYOUTS], who='ss'),
        O('ss_style', 'Tile style', 0, [SAME, 'Classic', 'Modern', 'Outline'], who='ss'),
        O('ss_accent', 'Accent colour', 0, [SAME] + ACCENT_NAMES, who='ss'),
        T('ss_accent_custom', 'Custom accent colour (hex RRGGBB)', who='ss', visible=('ss_accent', CUSTOM + 1)),
        O('ss_theme_mode', 'Theme mode', 0, [SAME] + THEME_LABELS, who='ss'),
        TIME('ss_day_start', 'Day starts at', '07:00', who='ss', visible=('ss_theme_mode', 3)),
        TIME('ss_night_start', 'Night starts at', '19:00', who='ss', visible=('ss_theme_mode', 3)),
        N('ss_latitude', 'Latitude', '51.5', who='ss', visible=('ss_theme_mode', 4)),
        N('ss_longitude', 'Longitude', '-0.1', who='ss', visible=('ss_theme_mode', 4)),
        S('ss_sun_offset', 'Sunrise / sunset offset (minutes)', 0, -120, 120, 5, who='ss',
          visible=('ss_theme_mode', 4)),
        S('rotation_min', 'Content rotation interval (minutes)', 3, 1, 30, who='ss'),
        B('burn_in', 'Burn-in protection (shift the grid every 2 minutes)', True, who='ss'),
        B('drift', 'Slow drift', False, who='ss'),
        S('night_dim', 'Night dim (%)', 0, 0, 70, 5, who='ss'),
        B('show_clock', 'Show clock tile', True, who='ss'),
    ]),
    ('Motion', [
        O('liveliness', 'Liveliness', 1, ['Calm', 'Normal', 'Lively'], who='both'),
        S('max_active', 'Max simultaneous animations', 2, 1, 4, who='both'),
        B('reduced_motion', 'Reduced motion (fades only)', False, who='both'),
    ]),
    ('Advanced', [
        A('refresh_now', 'Refresh all feeds now', 'refresh', who='both'),
        A('clear_cache', 'Clear cache', 'clear_cache', who='both'),
        S('timeout', 'Network timeout (seconds)', 10, 5, 30),
        B('debug_log', 'Debug logging', False, who='both'),
    ]),
]

ADDONS = {APP_ID: 'app', SCREENSAVER_ID: 'ss'}


def rows(who=None):
    for _title, settings in CATEGORIES:
        for row in settings:
            if who is None or row['who'] in ('both', who):
                yield row


def defaults(who):
    out = {}
    for row in rows(who):
        if row['type'] == 'action':
            continue
        out[row['id']] = row['default']
    return out


def read(getters, who):
    """getters: {'boolean': f, 'integer': f, 'string': f}; each f(id) -> value."""
    out = defaults(who)
    for row in rows(who):
        kind = row['type']
        if kind == 'action':
            continue
        getter = {'boolean': 'boolean', 'options': 'integer', 'slider': 'integer'}.get(kind, 'string')
        try:
            value = getters[getter](row['id'])
        except Exception:
            continue
        if kind == 'number':
            try:
                value = float(value)
            except (TypeError, ValueError):
                value = float(row['default'])
        if kind == 'options' and not 0 <= value < len(row['options']):
            value = row['default']
        if kind in ('string', 'time') and value is None:
            continue
        out[row['id']] = value
    return out


def effective(app, ss=None):
    """Settings the board uses. app: the program's settings (or its defaults); ss: the
    screensaver's own settings, or None for the program."""
    s = dict(app)
    s['layout'] = APP_LAYOUTS[app.get('layout', 0)] if isinstance(app.get('layout', 0), int) else app['layout']
    s['style'] = STYLES[app.get('style', 0)] if isinstance(app.get('style', 0), int) else app['style']
    if ss is None:
        return s
    s['layout'] = SS_LAYOUTS[ss.get('ss_layout', 0)]
    if ss.get('ss_style', 0):
        s['style'] = STYLES[ss['ss_style'] - 1]
    if ss.get('ss_accent', 0):
        s['accent'] = ss['ss_accent'] - 1
        s['accent_custom'] = ss.get('ss_accent_custom', '')
    if ss.get('ss_theme_mode', 0):
        s['theme_mode'] = ss['ss_theme_mode'] - 1
        for key in ('day_start', 'night_start', 'latitude', 'longitude', 'sun_offset'):
            s[key] = ss.get('ss_' + key, s.get(key))
    for key in ('rotation_min', 'burn_in', 'drift', 'night_dim', 'show_clock', 'liveliness', 'max_active',
                'reduced_motion', 'debug_log'):
        if key in ss:
            s[key] = ss[key]
    return s


# On-screen text, in the library's strings.po (ids from 32000).
STRINGS = {
    32000: 'live tiles',
    32001: 'Loading feeds...',
    32002: 'No feeds yet',
    32003: 'Press Menu and choose Manage feeds to add one.',
    32004: 'NOW',
    32005: '%d MIN AGO',
    32006: '%d H AGO',
    32007: 'YESTERDAY',
    32008: '%d DAYS AGO',
    32009: '%d NEW',
    32010: 'UP TO DATE',
    32011: 'OFFLINE',
    32012: 'Couldn\'t load this feed. It will try again later.',
    32013: 'No items yet.',
    32014: 'updating',
    32015: 'offline',
    32020: 'Scan to open on your phone',
    32021: '%d / %d',
    32022: 'Left / Right: previous / next    Up / Down: scroll    Back: close',
    32023: 'Select: play',
    32030: 'Open',
    32031: 'Mark feed read',
    32032: 'Refresh feed',
    32033: 'Edit feed',
    32034: 'Hide item',
    32035: 'Manage feeds...',
    32036: 'Settings...',
    32037: 'Refresh all feeds',
    32038: 'Mark all read',
    32039: 'Layout...',
    32040: 'Manage feeds',
    32041: 'Add feed...',
    32042: 'Import OPML...',
    32043: 'Export OPML...',
    32044: 'Feed URL',
    32045: 'Checking feed...',
    32046: 'That doesn\'t look like a feed:',
    32047: 'Title',
    32048: 'Accent colour',
    32049: 'Max items',
    32050: 'Enabled',
    32051: 'Tile size',
    32052: 'Move up',
    32053: 'Move down',
    32054: 'Delete',
    32055: 'Delete this feed?',
    32056: 'Default',
    32057: 'Automatic',
    32058: 'Imported %d feeds',
    32059: 'Exported %d feeds',
    32060: 'Choose an OPML file',
    32061: 'Choose a folder',
    32062: 'Refresh interval (minutes)',
    32063: 'off',
    32064: 'Feed added',
    32065: 'Done',
    32066: 'Yes',
    32067: 'No',
    32068: 'Cache cleared',
    32069: 'The custom accent is too light for white text',
    32070: 'Refreshing feeds...',
    32071: 'Feeds refreshed',
    32072: 'Small',
    32073: 'Medium',
    32074: 'Wide',
    32075: 'Large',
    32076: 'Hex colour (RRGGBB)',
    32077: 'That feed is already in the list',
    32078: 'Custom...',
}
