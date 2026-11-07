"""Every setting, font and palette in one place. tools/make_settings_wordclock.py turns the
table into settings.xml and strings.po; read() loads values with the right types and
defaults. No Kodi imports.
"""

ADDON_ID = 'screensaver.wordclock'

# (setting label, folder under media/fonts) -- see tools/make_wordclock_media.py for weights.
FONTS = [
    ('Modern sans: Inter (as pictured)', 'inter'),
    ('Geometric: Montserrat', 'montserrat'),
    ('Elegant thin: Raleway', 'raleway'),
    ('Serif: Playfair Display', 'playfair'),
    ('Monospace: JetBrains Mono', 'jetbrains'),
    ('Rounded: Comfortaa', 'comfortaa'),
    ('Dot matrix: Doto', 'doto'),
    ('Stencil: Big Shoulders', 'stencil'),
]

# name, background, card, lit, unlit (RRGGBB)
PALETTES = [
    ('Graphite (as pictured)', '000000', '1B1B1D', 'FFFFFF', '474749'),
    ('Paper', 'D9D5CC', 'F4F1EA', '1A1A1A', 'D2CDC2'),
    ('Midnight blue', '000000', '0E1628', '8FD3FF', '22304C'),
    ('Amber LED', '000000', '140C04', 'FFB347', '33240F'),
    ('Terminal green', '000000', '050D07', '4CFF7A', '163520'),
    ('Rose', '120A0E', '2A1520', 'FFC2D4', '4D2E3C'),
    ('Walnut', '0F0A06', '3B2A1E', 'FFF1D6', '5A4332'),
    ('Steel', '0B0F11', '263238', 'E0F7FA', '3E4F57'),
]
CUSTOM = len(PALETTES)
PALETTE_NAMES = [p[0] for p in PALETTES] + ['Custom']
GRAPHITE, PAPER = 0, 1


def B(sid, label, default, **kw):
    return dict(id=sid, type='boolean', label=label, default=default, **kw)


def O(sid, label, default, options, **kw):
    return dict(id=sid, type='options', label=label, default=default, options=options, **kw)


def S(sid, label, default, lo, hi, step=1, **kw):
    return dict(id=sid, type='slider', label=label, default=default, min=lo, max=hi, step=step, **kw)


def C(sid, label, default, **kw):
    return dict(id=sid, type='colour', label=label, default=default, **kw)


def G(label):
    return dict(id='', type='group', label=label)


def custom_colours(mode, palette_index):
    _name, bg, card, lit, unlit = PALETTES[palette_index]
    when = ('%s_palette' % mode, str(CUSTOM))
    title = mode.capitalize()
    return [
        G('Custom %s colours' % mode),
        C('%s_bg' % mode, '%s: background' % title, 'FF' + bg, visible=when),
        C('%s_card' % mode, '%s: card' % title, 'FF' + card, visible=when),
        C('%s_lit' % mode, '%s: lit letters' % title, 'FF' + lit, visible=when),
        C('%s_unlit' % mode, '%s: unlit letters' % title, 'FF' + unlit, visible=when),
    ]


CATEGORIES = [
    ('Clock', [
        O('rounding', 'Rounding', 0, ['Down (1:58 is FIVE TO TWO)', "Nearest (1:58 is TWO O'CLOCK)"]),
        B('it_is', 'Light IT IS', True),
        B('quarter_a', 'Say A QUARTER (not just QUARTER)', True),
        B('ampm', 'Light AM and PM', True),
        B('midnight', 'Say MIDNIGHT instead of TWELVE at night', True),
        B('dots', 'Minute dots in the corners (1 to 4 minutes past)', False, visible=('rounding', '0')),
    ]),
    ('Letters', [
        O('font', 'Font', 0, [f[0] for f in FONTS]),
        O('weight', 'Lit letters', 0, ['Bold (as pictured)', 'Same weight as the other letters']),
        O('unlit', 'Unlit letters', 0, ['Shown (as pictured)', 'Faint', 'Hidden']),
        O('glow', 'Glow around lit letters', 0, ['Off (as pictured)', 'Soft', 'Strong']),
        S('letter_size', 'Letter size (%)', 100, 70, 140, 10),
    ]),
    ('Colours', [
        O('night_palette', 'Night colours', GRAPHITE, PALETTE_NAMES),
        O('day_palette', 'Day colours', PAPER, PALETTE_NAMES),
        O('lit_effect', 'Lit letter colour', 0, ['From the colours above', 'Each word a different colour',
                                                 'Slowly cycle through the rainbow']),
    ] + custom_colours('night', GRAPHITE) + custom_colours('day', PAPER)),
    ('Day and night', [
        O('mode', 'Colour mode', 0, ['Night colours all the time (as pictured)', 'Day colours all the time',
                                     'Day and night by the clock']),
        dict(id='day_start', type='time', label='Day starts at', default='07:00'),
        dict(id='night_start', type='time', label='Night starts at', default='21:00'),
        S('night_dim', 'Dim at night (%)', 0, 0, 80, 10),
    ]),
    ('Screen', [
        O('frame', 'Frame', 0, ['Rounded card (as pictured)', 'Square card', 'Full screen, no card']),
        S('size', 'Clock size (% of the screen height)', 80, 40, 100, 5),
        O('transition', 'When the time changes', 0, ['Fade', 'Ripple across the grid', 'Cut']),
        S('dim', 'Dim (%)', 0, 0, 80, 10),
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


def clock_options(s):
    return dict((k, s[k]) for k in ('rounding', 'it_is', 'quarter_a', 'ampm', 'midnight', 'dots'))
