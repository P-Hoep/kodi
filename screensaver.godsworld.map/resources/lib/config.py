"""Every setting in one table: tools/make_settings_godsworld.py turns it into settings.xml
and strings.po, and read() uses it to load values with the right types and defaults.
No Kodi imports."""

from . import ascii, projections, sources

ADDON_ID = 'screensaver.godsworld.map'

# Looks that style cycling can choose from: a base map, or one of the ASCII modes.
STYLES = [(b[0], b[1]) for b in sources.BASEMAPS] + [('ascii_geo', 'ASCII: geographic'),
                                                     ('ascii_image', 'ASCII: from imagery')]
STYLE_IDS = [s[0] for s in STYLES]
RENDER_MODES = ['Map', 'ASCII: geographic', 'ASCII: from imagery', 'ASCII: alternate both']


def B(sid, label, default, **kw):
    return dict(id=sid, type='boolean', label=label, default=default, **kw)


def O(sid, label, default, options, **kw):
    return dict(id=sid, type='options', label=label, default=default, options=options, **kw)


def S(sid, label, default, lo, hi, step=1, **kw):
    return dict(id=sid, type='slider', label=label, default=default, min=lo, max=hi, step=step, **kw)


CATEGORIES = [
    ('Base map', [
        O('basemap', 'Base map', 0, [b[1] for b in sources.BASEMAPS]),
        B('borders', 'Draw country borders and coastlines', False),
    ]),
    ('Projection', [
        O('projection', 'Projection', 1, [p.name for p in projections.ALL]),
        S('tilt', 'Centre latitude', 20, -60, 60, 5),
        S('center_lon', 'Centre longitude', 0, -180, 180, 5),
    ]),
    ('Movement', [
        O('movement', 'Movement', 3, ['Static', 'Pan across the map', 'Rotate', 'Automatic']),
        S('speed', 'Speed', 3, 1, 10),
        O('direction', 'Rotation direction', 0, ['West to east (like the Earth)', 'East to west']),
        O('pan_pattern', 'Pan pattern', 0, ['Wander', 'Sweep side to side', 'Orbit']),
        S('zoom', 'Zoom (%)', 100, 100, 250, 10),
        B('auto_zoom', 'Vary the zoom automatically', True),
    ]),
    ('Cycling', [
        B('cycle_projections', 'Cycle through projections', True),
        dict(id='projection_list', type='multi', label='Projections to cycle through',
             default=list(range(len(projections.ALL))), options=[p.name for p in projections.ALL]),
        B('cycle_styles', 'Cycle through visual styles', False),
        dict(id='style_list', type='multi', label='Styles to cycle through', default=[0, 1, 5, 7, 8],
             options=[s[1] for s in STYLES]),
        S('cycle_minutes', 'Minutes between changes', 5, 1, 60),
        O('cycle_order', 'Order', 1, ['Fixed sequence (as listed)', 'Random (no quick repeats)']),
        O('transition', 'Transition', 0, ['Fade', 'Cut']),
    ]),
    ('Rendering style', [
        O('render_mode', 'Rendering style', 0, RENDER_MODES),
    ]),
    ('ASCII appearance', [
        O('ascii_color', 'Colours', 0, ['Colour', 'Monochrome']),
        O('ascii_palette', 'Colour palette', 0, ['Natural', 'Classic 16 colours', 'Neon', 'Sepia'],
          visible=('ascii_color', 0)),
        O('ascii_mono', 'Monochrome colour', 0, ['Green phosphor', 'Amber', 'White', 'Blue'],
          visible=('ascii_color', 1)),
        O('ascii_density', 'Character density', 1, ['Low (120 columns)', 'Medium (160 columns)',
                                                     'High (240 columns)']),
        O('ascii_charset', 'Characters', 0, ['Symbols (≈ ♣ ▲)', 'Plain ASCII']),
        O('ascii_ramp', 'Brightness to character (imagery mode)', 0,
          ['Classic  .:-=+*#%@', 'Blocks  ░▒▓█', 'Detailed (70 steps)']),
        B('ascii_borders', 'Show country borders', True),
        B('ascii_urban', 'Show cities', True),
    ]),
    ('Weather', [
        B('layer_clouds', 'Clouds (infrared satellite)', True),
        B('layer_precip', 'Precipitation', True),
        B('layer_temp', 'Temperature', False),
        B('layer_wind', 'Wind (moving particles)', True),
        B('layer_storms', 'Tropical storms', True),
        S('weather_opacity', 'Overlay opacity (%)', 70, 20, 100, 10),
        S('wind_particles', 'Wind particles', 200, 50, 400, 50, visible='layer_wind'),
    ]),
    ('Hazards and space', [
        B('layer_quakes', 'Earthquakes', True),
        O('quake_feed', 'Which earthquakes', 0, ['Past day, magnitude 2.5+', 'Past week, magnitude 4.5+',
                                                  'Significant, past month'], visible='layer_quakes'),
        B('layer_volcanoes', 'Erupting volcanoes', True),
        B('layer_fires', "Wildfires (yesterday's satellite detections)", True),
        B('layer_lightning', 'Lightning (mostly the Americas)', True),
        B('layer_iss', 'International Space Station', True),
        B('animate_events', 'Animate quakes, volcanoes and hazards', True),
    ]),
    ('Day and night', [
        B('daynight', 'Show day and night', True),
        S('night_darkness', 'Night shading (%)', 75, 20, 95, 5, visible='daynight'),
    ]),
    ('City lights', [
        B('lights', 'Show city lights', True),
        S('lights_brightness', 'Brightness (%)', 70, 10, 100, 10, visible='lights'),
        B('lights_night_only', 'Only on the night side', True, visible='lights'),
    ]),
    ('Display', [
        O('background', 'Background', 0, ['Stars', 'Plain black']),
        B('show_info', 'Show projection, style and clock', True),
        B('show_status', 'Show weather data age', True),
        B('show_legend', 'Show temperature scale', True),
        B('show_credits', 'Show data credits', True),
        S('dim', 'Dim everything (%)', 0, 0, 80, 10),
    ]),
    ('Performance', [
        O('quality', 'Rendering quality', 0, ['Automatic', 'High', 'Medium', 'Low']),
        S('max_fps', 'Frame limit for rotating views (frames per second)', 12, 1, 30),
        B('crossfade', 'Blend between frames of rotating views', True),
        B('show_perf', 'Show performance figures', False),
    ]),
    ('Data and cache', [
        S('refresh_minutes', 'Check clouds and precipitation every (minutes)', 60, 30, 360, 30),
        O('max_age', 'Hide weather older than', 2, ['3 hours', '6 hours', '12 hours', '24 hours', 'Never hide']),
        dict(id='clear_cache', type='action', label='Clear downloaded data and cached projections',
             data='RunScript(special://home/addons/%s/default.py,clear_cache)' % ADDON_ID),
    ]),
]

MAX_AGE_HOURS = [3, 6, 12, 24, None]
QUALITY_SCALE = [None, 1.0, 0.75, 0.5]


def all_settings():
    for _title, settings in CATEGORIES:
        for s in settings:
            if s['type'] != 'action':
                yield s


def read(getters):
    """Settings as a dict. getters: {'boolean': f(id), 'integer': f(id), 'list': f(id)}
    (the Kodi layer passes Addon accessors). Bad or missing values fall back to defaults."""
    out = {}
    for s in all_settings():
        kind = s['type']
        try:
            if kind == 'boolean':
                out[s['id']] = bool(getters['boolean'](s['id']))
            elif kind in ('options', 'slider'):
                value = int(getters['integer'](s['id']))
                if kind == 'options' and not 0 <= value < len(s['options']):
                    value = s['default']
                out[s['id']] = value
            elif kind == 'multi':
                values = [int(v) for v in getters['list'](s['id'])]
                values = [v for v in values if 0 <= v < len(s['options'])]
                out[s['id']] = values or list(s['default'])
            else:
                out[s['id']] = getters['string'](s['id'])
        except Exception:
            out[s['id']] = s['default']
    return out


def defaults():
    return dict((s['id'], s['default']) for s in all_settings())


def ascii_options(s):
    return {
        'density': s['ascii_density'],
        'mono': s['ascii_color'] == 1,
        'palette': ascii.COLOR_PALETTES[s['ascii_palette']],
        'mono_palette': ascii.MONO_PALETTES[s['ascii_mono']],
        'unicode': s['ascii_charset'] == 0,
        'ramp': s['ascii_ramp'],
        'borders': s['ascii_borders'],
        'urban': s['ascii_urban'],
    }
