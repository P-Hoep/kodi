"""Every setting in one table: tools/make_settings_skywatch.py turns it into settings.xml
and strings.po, and read() loads values with the right types and defaults. No Kodi imports.
"""

ADDON_ID = 'screensaver.skywatch'
ADDON_NAME = 'SkyWatch'


def B(sid, label, default, **kw):
    return dict(id=sid, type='boolean', label=label, default=default, **kw)


def O(sid, label, default, options, **kw):
    return dict(id=sid, type='options', label=label, default=default, options=options, **kw)


def S(sid, label, default, lo, hi, step=1, **kw):
    return dict(id=sid, type='slider', label=label, default=default, min=lo, max=hi, step=step, **kw)


def T(sid, label, default='', **kw):
    return dict(id=sid, type='string', label=label, default=default, **kw)


def N(sid, label, default, **kw):
    return dict(id=sid, type='number', label=label, default=default, **kw)


def A(sid, label, command):
    return dict(id=sid, type='action', label=label,
                data='RunScript(special://home/addons/%s/default.py,%s)' % (ADDON_ID, command))


def G(label):
    return dict(id='', type='group', label=label)


# Scenes: (id, name, show default, duration default s, show options). The show setting is
# 0 Off, 1 On, 2 Auto, where Auto means the scene's own condition (see player.py).
OFF_ON = ['Off', 'On']
SCENES = [
    ('local', 'Local radar loop', 1, 60, OFF_ON),
    ('regional', 'Regional radar with warnings', 1, 30, OFF_ON),
    ('national', 'National mosaic', 0, 20, OFF_ON),
    ('satellite', 'Satellite + radar', 0, 30, OFF_ON),
    ('future', 'Future radar: what\'s coming', 1, 30, ['Off', 'On', 'Auto (US only)']),
    ('current', 'Current conditions', 1, 20, OFF_ON),
    ('nexthours', 'Next 2 hours', 2, 20, ['Off', 'On', 'Auto (when precipitation is expected)']),
    ('hourly', 'Hourly graph', 1, 25, OFF_ON),
    ('daily', 'Daily forecast', 1, 25, OFF_ON),
    ('climate', 'Climate: today vs normal', 1, 25, OFF_ON),
    ('year', 'Year in temperature', 0, 25, OFF_ON),
    ('fishing', 'Fishing forecast', 0, 25, OFF_ON),
    ('sunmoon', 'Sun and moon', 0, 15, OFF_ON),
    ('air', 'Air quality and pollen', 0, 15, OFF_ON),
    ('marine', 'Marine and tides', 2, 20, ['Off', 'On', 'Auto (when near a tide station)']),
    ('discussion', 'Forecast discussion', 0, 40, OFF_ON),
    ('ambient', 'Ambient clock', 0, 30, OFF_ON),
]
SCENE_IDS = [s[0] for s in SCENES]
MAP_SCENES = ('local', 'regional', 'national', 'satellite', 'future')


def scene_settings():
    out = []
    for i, (sid, name, show, duration, modes) in enumerate(SCENES):
        out.append(G('%d. %s' % (i + 1, name)))
        out.append(O('scene_%s' % sid, 'Show', show, modes))
        out.append(S('dur_%s' % sid, 'Duration (seconds)', duration, 10, 120, 5,
                     visible=('scene_%s' % sid, '!', 0)))
        out.append(S('pos_%s' % sid, 'Position in playlist', i + 1, 1, len(SCENES),
                     visible=('scene_%s' % sid, '!', 0)))
    return out


BASEMAPS = ['Dark', 'Light', 'Street (OpenStreetMap)', 'Satellite', 'Terrain (needs map key)']
PAST_MINUTES = [30, 60, 90, 120]
FUTURE_HOURS = [1, 2, 4, 6, 12, 18]
FUTURE_SOURCES = ['Auto (HRRR in the US, Rainbow.ai with a key)', 'HRRR (US)', 'Rainbow.ai (key)',
                  'LibreWXR (your server)', 'Off']
COLOR_SCHEMES = ['NWS classic', 'Precipitation type (HRRR REFP)', 'Universal Blue (RainViewer/LibreWXR)']
SPECIES = ['General', 'Bass', 'Walleye', 'Trout', 'Panfish', 'Saltwater']
PROFILES = ['Auto-detect', 'Low (Raspberry Pi)', 'Balanced', 'High (4K)']

CATEGORIES = [
    ('Location', [
        A('find_location', 'Find home location by name or ZIP...', 'find_location'),
        N('lat', 'Latitude', '0.0'),
        N('lon', 'Longitude', '0.0'),
        T('location_name', 'Display name'),
        G('Fishing spot'),
        O('fish_spot', 'Fishing spot', 0, ['Same as home', 'Custom latitude/longitude',
                                            'USGS river gauge', 'NOAA tide station']),
        N('fish_lat', 'Fishing spot latitude', '0.0', visible=('fish_spot', 1)),
        N('fish_lon', 'Fishing spot longitude', '0.0', visible=('fish_spot', 1)),
        T('fish_gauge', 'USGS gauge ID (e.g. 05331000)', visible=('fish_spot', 2)),
        T('fish_station', 'CO-OPS station ID (e.g. 8447930)', visible=('fish_spot', 3)),
        T('fish_name', 'Fishing spot name'),
    ]),
    ('Map', [
        S('zoom', 'Local zoom (4 region, 8 metro, 12 neighbourhood)', 8, 4, 12),
        S('regional_offset', 'Regional view: zoom levels out', 2, 1, 4),
        O('basemap', 'Base map style', 0, BASEMAPS),
        O('center', 'Map centre', 0, ['Centre on home', 'Upwind (home off-centre so incoming weather shows)']),
        B('labels_above', 'Roads and labels above the radar', True),
    ]),
    ('Radar', [
        O('past_minutes', 'Past loop length', 3, ['%d min' % m for m in PAST_MINUTES]),
        O('future_source', 'Future radar source', 0, FUTURE_SOURCES),
        O('future_hours', 'Future length', 1, ['%d h' % h for h in FUTURE_HOURS]),
        O('color_scheme', 'Colour scheme', 0, COLOR_SCHEMES),
        S('radar_opacity', 'Radar opacity (%)', 75, 40, 100, 5),
        S('fps', 'Frame rate (frames per second)', 5, 2, 10),
        S('now_pause', 'Pause on the NOW frame (tenths of a second)', 15, 0, 30, 5),
        B('smooth', 'Smooth frames (crossfade)', True),
        B('warnings', 'NWS warning polygons (regional view, US)', True),
    ]),
    ('Scenes', [
        B('shuffle', 'Shuffle the scenes after the radar', False),
        O('transition', 'Transition', 0, ['Crossfade', 'Slide', 'Cut']),
    ] + scene_settings()),
    ('Overlay', [
        B('ov_clock', 'Clock', True),
        O('clock24', 'Clock format', 0, ['12 hour', '24 hour'], visible='ov_clock'),
        B('ov_date', 'Date', True),
        B('ov_location', 'Location name', True),
        B('ov_age', 'Data age ("updated 3 min ago")', True),
        B('ov_chip', 'Mini conditions (temperature and icon) on other scenes', True),
        B('ov_legend', 'Radar legend', True),
        B('ov_credits', 'Attribution footer', True),
    ]),
    ('Alerts', [
        O('alert_level', 'Alert banner', 1, ['Warnings only', 'Warnings + watches',
                                             'Warnings + watches + advisories', 'Off']),
        B('alert_promote', 'Show a warning scene first while a warning is active', True),
    ]),
    ('Units', [
        O('u_temp', 'Temperature', 0, ['°F', '°C']),
        O('u_wind', 'Wind', 0, ['mph', 'km/h', 'm/s', 'knots']),
        O('u_pressure', 'Pressure', 0, ['inHg', 'hPa', 'mmHg']),
        O('u_precip', 'Precipitation', 0, ['in', 'mm']),
        O('u_distance', 'Distance', 0, ['mi', 'km']),
    ]),
    ('Fishing', [
        O('species', 'Target species', 0, SPECIES),
        G('Factor weights (they are scaled to add up to 100)'),
        S('w_solunar', 'Solunar periods', 30, 0, 100, 5),
        S('w_pressure', 'Barometric trend', 25, 0, 100, 5),
        S('w_moon', 'Moon phase', 15, 0, 100, 5),
        S('w_wind', 'Wind', 15, 0, 100, 5),
        S('w_cloud', 'Cloud and light', 10, 0, 100, 5),
        S('w_water', 'Water temperature trend', 5, 0, 100, 5),
    ]),
    ('Display', [
        B('oled', 'OLED protection (pixel shift, rotating layout)', False),
        B('interactive', 'Interactive mode (left/right scenes, up/down zoom, OK pause, Back exits)', False),
        O('daily_days', 'Daily forecast cards', 0, ['7 days', '10 days']),
    ]),
    ('Data', [
        T('nws_email', 'Your email for the NWS User-Agent (US weather.gov asks for a contact)'),
        T('rainbow_key', 'Rainbow.ai API key (free tier)'),
        S('rainbow_cap', 'Monthly Rainbow.ai tile cap (thousands)', 27, 1, 30),
        T('map_key', 'Stadia Maps API key (terrain base map)'),
        T('librewxr_url', 'LibreWXR base URL (e.g. http://192.168.1.10:8080)'),
        O('refresh', 'Refresh while the screensaver is off', 2, ['Never', 'Hourly', 'Smart (just before it starts)']),
    ]),
    ('Advanced', [
        O('profile', 'Performance profile', 0, PROFILES),
        S('cache_mb', 'Cache size limit (MB)', 500, 100, 2000, 100),
        B('debug', 'Debug overlay (fps, cache, requests)', False),
        A('test_sources', 'Test all sources...', 'test_sources'),
        A('clear_cache', 'Clear cache', 'clear_cache'),
    ]),
]


def all_settings():
    for _title, settings in CATEGORIES:
        for s in settings:
            if s['type'] not in ('action', 'group'):
                yield s


def read(getters):
    """Settings as a dict. getters: {'boolean','integer','number','string'} -> f(id) (the Kodi
    layer passes Addon accessors). Bad or missing values fall back to defaults."""
    out = {}
    for s in all_settings():
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
            elif kind == 'number':
                value = float(getters['number'](s['id']))
            else:
                value = (getters['string'](s['id']) or '').strip()
                if kind == 'time' and not value:
                    value = s['default']
            out[s['id']] = value
        except Exception:
            out[s['id']] = default_of(s)
    return out


def default_of(s):
    if s['type'] == 'number':
        return float(s['default'])
    return s['default']


def defaults():
    return dict((s['id'], default_of(s)) for s in all_settings())
