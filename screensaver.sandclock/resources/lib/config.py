"""Every setting, font and palette in one place. tools/make_settings_sandclock.py turns the
table into settings.xml and strings.po; read() loads values with the right types and
defaults. No Kodi imports.
"""

ADDON_ID = 'screensaver.sandclock'

# (setting label, folder under media/fonts) -- see tools/make_sandclock_media.py for the files.
FONTS = [
    ('Modern sans: Inter', 'inter'),
    ('Geometric: Montserrat', 'montserrat'),
    ('Digital: Orbitron', 'orbitron'),
    ('Pixel: Pixelify Sans', 'pixelify'),
    ('Dot matrix: Doto', 'doto'),
    ('Monospace: JetBrains Mono', 'jetbrains'),
    ('Rounded: Comfortaa', 'comfortaa'),
    ('Serif: Playfair Display', 'playfair'),
    ('Stencil: Big Shoulders', 'stencil'),
]
WEIGHTS = ['Light', 'Regular', 'Bold']

# Colours a new digit can take, picked at random (never the same twice in a row). RRGGBB.
PALETTES = [
    ('Neon (as in video)', ['FF5FA2', 'D45CFF', '5C9DFF', '3FE0E8', '45E07A', 'FFB38A', 'FF5C6C']),
    ('Desert sand', ['E8C27A', 'D9A25F', 'C98A4B', 'F2D7A0', 'B5734A', 'E3B58C', 'A86A3D']),
    ('Ocean', ['3FA9F5', '1F6FD1', '45D6C9', '8FE3FF', '2A9D8F', '6C8CFF', 'B8F2E6']),
    ('Sunset', ['FF7A45', 'FFB347', 'FF4F70', 'C2448F', '8A4FD1', 'FFD166', 'F25C54']),
    ('Candy', ['FF9CEE', 'B28DFF', '85E3FF', 'BFFCC6', 'FFF5BA', 'FFABAB', 'ACE7FF']),
    ('Forest', ['6BBF59', '2E8B57', 'A3D977', 'D4C36A', '8C6A43', '4FA36C', 'C9E4A6']),
    ('Ice', ['FFFFFF', 'D6F1FF', 'A9DEFF', '7CC8F2', 'C9D6FF', 'E8F7FF', '9FB8D9']),
    ('Greyscale', ['FFFFFF', 'D9D9D9', 'B3B3B3', '8C8C8C', 'EDEDED', 'A6A6A6', 'C7C7C7']),
]
PALETTE_NAMES = [p[0] for p in PALETTES]

COLOUR_EVERY_CHANGE, COLOUR_PER_DIGIT, COLOUR_ONE, COLOUR_RAINBOW = range(4)


def B(sid, label, default, **kw):
    return dict(id=sid, type='boolean', label=label, default=default, **kw)


def O(sid, label, default, options, **kw):
    return dict(id=sid, type='options', label=label, default=default, options=options, **kw)


def S(sid, label, default, lo, hi, step=1, **kw):
    return dict(id=sid, type='slider', label=label, default=default, min=lo, max=hi, step=step, **kw)


def C(sid, label, default, **kw):
    return dict(id=sid, type='colour', label=label, default=default, **kw)


def T(sid, label, default, **kw):
    return dict(id=sid, type='time', label=label, default=default, **kw)


USES_PALETTE = ('<dependencies><dependency type="visible"><and>'
                '<condition setting="colour_mode" operator="!is">2</condition>'
                '<condition setting="colour_mode" operator="!is">3</condition>'
                '</and></dependency></dependencies>')
BY_THE_CLOCK = ('<dependencies><dependency type="visible"><or>'
                '<condition setting="night_palette" operator="!is">0</condition>'
                '<condition setting="night_dim" operator="!is">0</condition>'
                '</or></dependency></dependencies>')

CATEGORIES = [
    ('Clock', [
        B('seconds', 'Show seconds (crumbles every second)', True),
        O('hours', 'Hours', 0, ['24 hour (17:52)', '12 hour (5:52)']),
        O('crumble', 'What crumbles', 1, ['Only digits that change', 'Whole clock (as in video)']),
        O('speed', 'Crumble speed', 1, ['Slow', 'Normal', 'Quick']),
    ]),
    ('Font', [
        O('font', 'Font', 0, [f[0] for f in FONTS]),
        O('weight', 'Weight', 2, WEIGHTS),
        S('size', 'Clock width (% of the screen)', 80, 40, 95, 5),
        O('position', 'Clock position', 0, ['Upper part of the screen', 'Centre']),
    ]),
    ('Sand', [
        O('grain', 'Grain size', 1, ['Fine', 'Medium', 'Coarse']),
        O('grain_look', 'Grains look like', 0, ['Sand', 'Flat squares', 'Round beads']),
        O('gravity', 'Gravity', 1, ['Floaty', 'Normal', 'Heavy']),
        S('pile', 'Pile height (% of the screen)', 30, 10, 50, 5),
    ]),
    ('Colours', [
        O('colour_mode', 'Colour', 0, ['New colour each change', 'New colour per digit', 'One colour',
                                       'Slow rainbow']),
        O('palette', 'Colours to pick from', 0, PALETTE_NAMES, visible=USES_PALETTE),
        C('colour', 'Colour of the clock and sand', 'FFE8C27A', visible=('colour_mode', '2')),
        C('background', 'Background', 'FF000000'),
    ]),
    ('Day and night', [
        O('night_palette', 'Colours at night', 0, ['Same as by day'] + PALETTE_NAMES),
        S('night_dim', 'Dim at night (%)', 0, 0, 80, 10),
        T('day_start', 'Day starts at', '07:00', visible=BY_THE_CLOCK),
        T('night_start', 'Night starts at', '21:00', visible=BY_THE_CLOCK),
        S('dim', 'Dim all the time (%)', 0, 0, 80, 10),
        B('drift', 'Slowly drift the clock (protects OLED/plasma screens)', True),
    ]),
]


def all_settings():
    for _title, settings in CATEGORIES:
        for s in settings:
            if s['type'] not in ('action', 'group'):
                yield s


def valid_colour(value):
    v = (value or '').strip().lstrip('#').upper()
    if len(v) == 6:
        v = 'FF' + v
    try:
        int(v, 16)
    except ValueError:
        return None
    return v if len(v) == 8 else None


def valid_time(value):
    try:
        h, m = [int(p) for p in value.strip().split(':')[:2]]
    except (ValueError, AttributeError):
        return None
    return '%02d:%02d' % (h, m) if 0 <= h < 24 and 0 <= m < 60 else None


def read(getters):
    """Settings as a dict. getters: {'boolean': f(id), 'integer': f(id), 'string': f(id)} (the
    Kodi layer passes Addon accessors). Bad or missing values fall back to defaults."""
    out = {}
    for s in all_settings():
        try:
            if s['type'] == 'boolean':
                out[s['id']] = bool(getters['boolean'](s['id']))
            elif s['type'] == 'colour':
                out[s['id']] = valid_colour(getters['string'](s['id'])) or s['default']
            elif s['type'] == 'time':
                out[s['id']] = valid_time(getters['string'](s['id'])) or s['default']
            else:
                value = int(getters['integer'](s['id']))
                if s['type'] == 'options' and not 0 <= value < len(s['options']):
                    value = s['default']
                if s['type'] == 'slider':
                    value = min(s['max'], max(s['min'], value))
                out[s['id']] = value
        except Exception:
            out[s['id']] = s['default']
    return out


def defaults():
    return dict((s['id'], s['default']) for s in all_settings())
