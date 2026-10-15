"""Every setting in one table: tools/make_settings_livecams.py turns it into settings.xml
and strings.po, and read() loads values with the right types and defaults. No Kodi imports.
"""

ADDON_ID = 'screensaver.livecams'
ADDON_NAME = 'Live Cams'
VERSION = '1.0.0'

DATASET = 'https://github.com/william-ricchiuti/Live-Environment-Streams'
CATALOG_URL = 'https://raw.githubusercontent.com/william-ricchiuti/Live-Environment-Streams/main/streams.geojson'


def B(sid, label, default, **kw):
    return dict(id=sid, type='boolean', label=label, default=default, **kw)


def O(sid, label, default, options, **kw):
    return dict(id=sid, type='options', label=label, default=default, options=options, **kw)


def S(sid, label, default, lo, hi, step=1, **kw):
    return dict(id=sid, type='slider', label=label, default=default, min=lo, max=hi, step=step, **kw)


def T(sid, label, default='', **kw):
    return dict(id=sid, type='string', label=label, default=default, **kw)


def M(sid, label, default, options, **kw):
    return dict(id=sid, type='multi', label=label, default=default, options=options, **kw)


def A(sid, label, command, **kw):
    return dict(id=sid, type='action', label=label,
                data='RunScript(special://home/addons/%s/default.py,%s)' % (ADDON_ID, command), **kw)


def G(label):
    return dict(id='', type='group', label=label)


# The dataset's environment values, in the order of the multi-select. Traffic has its own toggle.
ENVIRONMENTS = ['coastal', 'mountain', 'lake', 'nature', 'waterway', 'harbor', 'marina', 'landmark', 'urban',
                'transport']
ENVIRONMENT_LABELS = ['Coast and beaches', 'Mountains', 'Lakes', 'Nature', 'Rivers and canals', 'Harbours',
                      'Marinas', 'Landmarks', 'Towns and cities', 'Airports and stations']
MIN_RES_PX = [0, 480, 720, 1080]
DWELL_SECONDS = [30, 60, 120, 180, 300, 600, 900, 1800, 0]   # 0 = never rotate
DWELL_LABELS = ['30 seconds', '1 minute', '2 minutes', '3 minutes', '5 minutes', '10 minutes', '15 minutes',
                '30 minutes', 'Never rotate']
CUTOFF_SECONDS = [1800, 3600, 7200, 14400, 28800, 0]         # 0 = never
CUTOFF_LABELS = ['30 minutes', '1 hour', '2 hours', '4 hours', '8 hours', 'Never']

CATEGORIES = [
    ('Cameras', [
        M('environments', 'Scenes', list(range(9)), ENVIRONMENT_LABELS),
        B('traffic', 'Include traffic cameras', False),
        O('country_mode', 'Countries', 0, ['All countries', 'Only these countries', 'All except these countries']),
        T('countries', 'Country codes, comma separated (e.g. PT, PL, US)', visible=('country_mode', '!', 0)),
        A('pick_countries', 'Choose countries from the catalogue...', 'pick_countries',
          visible=('country_mode', '!', 0)),
        O('min_res', 'Minimum resolution (unknown resolution is allowed)', 2, ['Any', '480p', '720p', '1080p']),
        B('unverified', 'Include unverified streams', False),
        B('favourites_only', 'Favourites only', False),
        A('fav_last', 'Add the last camera shown to favourites', 'fav_last'),
        A('fav_clear', 'Clear favourites', 'fav_clear'),
    ]),
    ('Rotation', [
        O('dwell', 'Time per camera', 3, DWELL_LABELS),
        B('daylight', 'Prefer daylight', True),
        B('night', 'Allow night cameras', False),
        O('cutoff', 'Stop streaming after (then show a clock)', 2, CUTOFF_LABELS),
    ]),
    ('Display', [
        O('overlay', 'Overlay', 1, ['Off', 'On change (8 s)', 'Always']),
        B('local_time', 'Show local time at the camera', True),
        B('clock', "Show clock (viewer's time)", False),
        B('burnin', 'Burn-in protection (overlay drift)', True),
        B('audio', 'Play audio', False),
    ]),
    ('Advanced', [
        A('status', 'Catalogue and camera count...', 'status'),
        A('preview', 'Preview', 'preview'),
        T('catalog_url', 'Catalogue URL', CATALOG_URL),
        S('refresh_days', 'Catalogue refresh interval (days)', 7, 1, 30),
        B('isa', 'Use inputstream.adaptive', False),
        B('youtube', 'Enable YouTube cameras (needs the YouTube add-on)', False),
        B('data_saver', 'Data saver (cap at the 720p variant)', False),
        B('insecure', 'Allow cameras with incomplete HTTPS certificates', True),
        A('reset', 'Reset camera health and history', 'reset'),
    ]),
]

# On-screen and dialog text, also in strings.po (ids from 32000). tools/make_settings_livecams.py
# appends these after the settings strings.
STRINGS = {
    32000: 'Live cams unavailable',
    32001: 'local time',
    32002: 'Catalogue',
    32003: 'Not downloaded yet',
    32004: '%d cameras match your filters',
    32005: 'Downloaded %s, %d cameras',
    32006: 'Added to favourites',
    32007: 'No camera has been shown yet',
    32008: 'Favourites cleared',
    32009: 'Camera health and history reset',
    32010: 'Download the catalogue first: run the screensaver once',
    32011: 'Choose countries',
    32012: '%d cameras blocked after failures',
    32013: 'Source: %s',
    32014: '(%d in daylight now)',
}


def all_settings():
    for _title, settings in CATEGORIES:
        for s in settings:
            if s['type'] not in ('action', 'group'):
                yield s


def read(getters):
    """Settings as a dict. getters: {'boolean', 'integer', 'number', 'string', 'list'} -> f(id)
    (the Kodi layer passes Addon accessors). Bad or missing values fall back to defaults."""
    out = {}
    for s in all_settings():
        kind = s['type']
        try:
            if kind == 'boolean':
                value = bool(getters['boolean'](s['id']))
            elif kind == 'multi':
                value = [int(v) for v in getters['list'](s['id'])]
                value = [v for v in value if 0 <= v < len(s['options'])]
            elif kind in ('options', 'slider'):
                value = int(getters['integer'](s['id']))
                if kind == 'options' and not 0 <= value < len(s['options']):
                    value = s['default']
                if kind == 'slider':
                    value = min(s['max'], max(s['min'], value))
            else:
                value = (getters['string'](s['id']) or '').strip()
            out[s['id']] = value
        except Exception:
            out[s['id']] = default_of(s)
    if not out.get('catalog_url'):
        out['catalog_url'] = CATALOG_URL
    return out


def default_of(s):
    return list(s['default']) if s['type'] == 'multi' else s['default']


def defaults():
    return dict((s['id'], default_of(s)) for s in all_settings())


def country_codes(text):
    """'pt, PL;us' -> {'PT', 'PL', 'US'}."""
    import re
    return set(c.upper() for c in re.split(r'[\s,;|]+', text or '') if len(c) == 2 and c.isalpha())
