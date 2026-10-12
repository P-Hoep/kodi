"""Every setting in one table: tools/make_settings_couch.py turns it into settings.xml and
strings.po, and read() loads values with the right types and defaults. No Kodi imports."""

ADDON_ID = 'screensaver.couchstronomy'

MAG_LIMITS = (3.0, 4.0, 5.0, 5.5, 6.0, 6.5, 7.0, 7.5, 8.0)
UPDATE_SECONDS = (None, 1.0, 2.0, 5.0, 10.0)      # None = automatic
TIME_SPEEDS = (1, 10, 60, 600)
SAT_GROUPS = (
    # (label, CelesTrak GP group)
    ('Space stations (ISS, Tiangong)', 'stations'),
    ('Brightest satellites (about 150)', 'visual'),
    ('Launched in the last 30 days', 'last-30-days'),
    ('Starlink (thousands; heavy on a Fire TV)', 'starlink'),
)
SAT_REFRESH_HOURS = (6, 12, 24, 48)
SAT_MAX_AGE_DAYS = (3, 7, 14, 30)
SAT_RATES = (1, 2, 5)
LABEL_MODES = ('Natural: no labels', 'Named objects: bright stars, planets, Moon, satellites',
               'Explorer: names, constellations, deep sky, details')
NATURAL, NAMED, EXPLORER = 0, 1, 2


def B(sid, label, default, **kw):
    return dict(id=sid, type='boolean', label=label, default=default, **kw)


def O(sid, label, default, options, **kw):
    return dict(id=sid, type='options', label=label, default=default, options=list(options), **kw)


def S(sid, label, default, lo, hi, step=1, **kw):
    return dict(id=sid, type='slider', label=label, default=default, min=lo, max=hi, step=step, **kw)


def N(sid, label, default, **kw):
    return dict(id=sid, type='number', label=label, default=default, **kw)


CATEGORIES = [
    ('Location', [
        dict(id='place', type='string', label='Place name (shown with the clock)', default='Home'),
        N('lat', 'Latitude (degrees, north positive)', '44.9031'),
        N('lon', 'Longitude (degrees, east positive, west negative)', '-93.3096'),
        N('elevation', 'Elevation above sea level (metres)', '260'),
    ]),
    ('TV orientation', [
        S('azimuth', 'Compass heading the TV faces (0 N, 90 E, 180 S, 270 W)', 180, 0, 359),
        O('heading_type', 'Heading measured with', 0, ['True north (map)', 'Magnetic compass']),
        N('declination', 'Magnetic declination (degrees, east positive)', '0.0',
          visible=('heading_type', 1)),
        S('tilt', 'Vertical tilt (-90 down, 0 level, 90 straight up)', 0, -90, 90),
        O('fov_mode', 'Field of view from', 0, ['An angle', 'Screen width and viewing distance']),
        S('hfov', 'Horizontal field of view (degrees)', 60, 10, 170, visible=('fov_mode', 0)),
        S('screen_cm', 'Screen width (cm)', 144, 40, 400, visible=('fov_mode', 1)),
        S('distance_cm', 'Viewing distance (cm)', 300, 50, 1000, 10, visible=('fov_mode', 1)),
        O('rotation', 'Screen rotation (TV turned clockwise)', 0, ['0°', '90°', '180°', '270°']),
        S('roll', 'Fine roll correction (degrees, clockwise)', 0, -15, 15),
        O('projection', 'Projection', 0, ['Automatic (perspective, stereographic above 120°)',
                                          'Perspective (rectilinear)', 'Stereographic',
                                          'Angular (equidistant fisheye)']),
    ]),
    ('Sky', [
        O('look', 'Rendering', 0, ['Realistic (what the eye would see)',
                                   'Enhanced (brighter faint stars, larger Moon and planets)']),
        O('enhance', 'Enhancement strength', 0, ['Mild', 'Strong'], visible=('look', 1)),
        O('mag_limit', 'Faintest stars (limiting magnitude)', 5, ['%.1f' % m for m in MAG_LIMITS]),
        S('star_brightness', 'Star brightness (%)', 100, 50, 200, 10),
        O('star_colours', 'Star colours', 0, ['Natural (subtle)', 'Vivid', 'White']),
        B('twinkle', 'Subtle twinkling of bright stars', False),
        S('light_pollution', 'Light pollution (0 dark site, 100 city centre)', 20, 0, 100, 5),
        O('daytime', 'By day', 0, ['Realistic daylight and twilight', 'Keep the sky dark (stars by day)']),
        O('horizon', 'Below the horizon', 0, ['Ground', 'Fade to black',
                                             'See through the Earth (planetarium mode)']),
        B('extinction', 'Atmospheric extinction (dimmer near the horizon)', True),
        B('refraction', 'Atmospheric refraction', True),
    ]),
    ('Objects', [
        B('show_sun_moon', 'Sun and Moon', True),
        B('show_planets', 'Planets', True),
        B('show_dsos', 'Deep-sky objects (Messier and bright NGC)', True),
        B('messier_photos', "Messier photos (Fred Espenak, AstroPixels.com)", True, visible='show_dsos'),
        B('show_lines', 'Constellation lines', False),
        B('show_borders', 'Constellation boundaries', False),
        B('show_satellites', 'Satellites', True),
        dict(id='sat_groups', type='multi', label='Which satellites', default=[0, 1, 2],
             options=[g[0] for g in SAT_GROUPS], visible='show_satellites'),
        B('sat_shadowed', "Also show satellites in the Earth's shadow (dimmed)", False,
          visible='show_satellites'),
        O('sat_rate', 'Satellite updates per second', 1, [str(r) for r in SAT_RATES],
          visible='show_satellites'),
    ]),
    ('Labels & overlays', [
        O('labels', 'Labels', 0, LABEL_MODES),
        B('constellation_names', 'Constellation names', True, visible=('labels', '!', 0)),
        B('satellite_labels', 'Satellite names', True, visible=('labels', '!', 0)),
        B('spotlight', 'Spotlight an object every half minute (Explorer)', True, visible=('labels', 2)),
        B('show_clock', 'Local date and time', False),
        B('show_compass', 'Direction at the centre of the screen', False),
        B('show_status', 'Status text at the bottom (view mode, satellite data age)', False),
        S('dim', 'Dim everything (%)', 0, 0, 80, 10),
    ]),
    ('Data & updates', [
        B('auto_update', 'Download satellite orbital data automatically', True),
        O('sat_refresh', 'Refresh orbital data every', 1, ['%d hours' % h for h in SAT_REFRESH_HOURS],
          visible='auto_update'),
        O('sat_max_age', 'Hide satellites whose orbital data is older than', 1,
          ['%d days' % d for d in SAT_MAX_AGE_DAYS]),
        dict(id='update_now', type='action', label='Download satellite data now',
             data='RunScript(special://home/addons/%s/default.py,update_satellites)' % ADDON_ID),
        dict(id='clear_cache', type='action', label='Delete downloaded data',
             data='RunScript(special://home/addons/%s/default.py,clear_cache)' % ADDON_ID),
    ]),
    ('Advanced', [
        O('update', 'Star field update interval', 0, ['Automatic'] + ['%g s' % s for s in UPDATE_SECONDS[1:]]),
        O('quality', 'Render resolution', 0, ['Full HD (1920 × 1080)', 'HD (1280 × 720, lighter)']),
        S('time_offset', 'Time offset (hours; for previews)', 0, -48, 48),
        O('time_speed', 'Time-lapse speed (satellites hidden above 1×)', 0, ['%d×' % s for s in TIME_SPEEDS]),
        B('show_perf', 'Show performance figures', False),
    ]),
]


def all_settings():
    for _title, settings in CATEGORIES:
        for s in settings:
            if s['type'] != 'action':
                yield s


def defaults():
    out = {}
    for s in all_settings():
        d = s['default']
        out[s['id']] = float(d) if s['type'] == 'number' else d
    return out


def read(getters):
    """Settings as a dict. getters: {'boolean', 'integer', 'number', 'string', 'list'} ->
    f(id) (the Kodi layer passes Addon accessors). Bad or missing values fall back to
    defaults."""
    out = {}
    for s in all_settings():
        try:
            kind = s['type']
            if kind == 'boolean':
                out[s['id']] = bool(getters['boolean'](s['id']))
            elif kind == 'number':
                out[s['id']] = float(getters['number'](s['id']))
            elif kind == 'string':
                out[s['id']] = getters['string'](s['id'])
            elif kind == 'multi':
                vals = [int(v) for v in getters['list'](s['id'])]
                out[s['id']] = [v for v in vals if 0 <= v < len(s['options'])]
            else:
                value = int(getters['integer'](s['id']))
                if kind == 'options' and not 0 <= value < len(s['options']):
                    value = s['default']
                if kind == 'slider':
                    value = min(s['max'], max(s['min'], value))
                out[s['id']] = value
        except Exception:
            d = s['default']
            out[s['id']] = float(d) if s['type'] == 'number' else d
    return out
