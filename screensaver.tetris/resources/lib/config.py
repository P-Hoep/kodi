"""Every setting, colour scheme and screen constant in one place.

tools/make_settings_tetris.py turns the table into settings.xml and strings.po; read() loads
values with the right types and defaults. No Kodi imports.
"""

ADDON_ID = 'screensaver.tetris'

# The skin's coordinate system, as in the other screensavers here. The playfield is always 18
# rows tall and fills the screen, and the block size decides how many columns fit across it:
# at the default 96 px, 20 x 18 cells of 96 x 60 pixels cover the screen exactly. Smaller
# blocks mean more, narrower columns, which keeps them from looking huge on a wide screen.
W, H = 1920, 1080
ROWS = 18
BLOCK_W = 96
BLOCK_W_MIN, BLOCK_W_MAX, BLOCK_W_STEP = 32, 96, 4

PIECES = ('I', 'O', 'T', 'S', 'Z', 'J', 'L')

# Playback, at 100% and level 1. The speed setting divides these; the level shortens them.
THINK_SECONDS = 0.12
MOVE_SECONDS = 0.045
DROP_SECONDS = 0.020

LEVEL_LINES = 10            # lines per level
MAX_LEVEL = 20

# Colour schemes: the seven Tetris pieces in the order of PIECES, as RRGGBB.
SCHEMES = [
    # The seven classic colours, as in the modern Tetris Guideline and every Tetris since.
    ('Classic', ('00F0F0', 'F0F000', 'A000F0', '00F000', 'F00000', '0000F0', 'F0A000')),
    # The muted NES palette's take on the same seven.
    ('NES', ('00A8A8', 'A8A800', 'A800A8', '00A800', 'A80000', '0000A8', 'A85000')),
    ('Neon', ('00FFFF', 'FFF700', 'D000FF', '39FF14', 'FF1E56', '2E5BFF', 'FF9E00')),
    ('Pastel', ('9EE7E3', 'F7EE9B', 'D5B3E8', 'A8DFA3', 'F2A6A6', '9DB8F0', 'F6C79A')),
    ('Monochrome', ('FFFFFF', 'E4E9F2', 'C9D0DC', 'AEB6C4', '939CAD', '788294', '5D6779')),
    ('Game Boy', ('9BBC0F', '8BAC0F', '7B9A0E', '6A890C', '59780A', '486708', '375606')),
    ('Sunset', ('FF8E72', 'FFD166', 'C44D9B', '7BD389', 'E84855', '6C5CE7', 'FFA63D')),
    ('Ocean', ('00D2FF', 'FFD166', '00C9A7', '3A7BD5', '0077B6', '035AA6', '2EC4B6')),
    ('Vaporwave', ('00F0FF', 'FFE66D', 'B026FF', '39FF88', 'FF2E63', '7B2FF7', 'FF6EC7')),
]
SCHEME_CUSTOM = len(SCHEMES)

DEFAULT_CUSTOM = ('00F0F0', 'F0F000', 'A000F0', '00F000', 'F00000', '0000F0', 'F0A000')

GRID_ALPHA = 0x16            # grid lines, out of 255
VIGNETTE_ALPHA = 0.55

SKILLS = ('Perfect', 'Expert', 'Skilled', 'Average', 'Beginner')

CLOCK_TEXT = 0
CLOCK_BLOCKS = 1
CLOCK_STYLES = ('Text', 'Tetris blocks')

CLOCK_BOTTOM = 0
CLOCK_SUSPENDED = 1
CLOCK_POSITIONS = ('Bottom', 'Suspended')


def B(sid, label, default, **kw):
    return dict(id=sid, type='boolean', label=label, default=default, **kw)


def O(sid, label, default, options, **kw):
    return dict(id=sid, type='options', label=label, default=default, options=options, **kw)


def S(sid, label, default, lo, hi, step=1, **kw):
    return dict(id=sid, type='slider', label=label, default=default, min=lo, max=hi, step=step, **kw)


def C(sid, label, default, **kw):
    return dict(id=sid, type='colour', label=label, default=default, **kw)


CUSTOM_SETTINGS = [C('custom_%s' % p, 'Custom %s colour' % p, 'FF' + d,
                     visible=('scheme', str(SCHEME_CUSTOM)))
                   for p, d in zip(PIECES, DEFAULT_CUSTOM)]

CATEGORIES = [
    ('Game', [
        O('skill', 'AI skill', 0, list(SKILLS)),
        S('speed', 'Overall speed (%)', 100, 25, 400, 25),
        S('start_level', 'Starting level', 1, 1, 10, 1),
        B('progressive', 'Speed up as lines are cleared', True),
        B('ghost', 'Show the landing ghost', True),
        B('show_next', 'Show the next piece', True),
    ]),
    ('Look', [
        O('scheme', 'Colour scheme', 0, [name for name, _c in SCHEMES] + ['Custom']),
        S('block_size', 'Block size (pixels)', BLOCK_W, BLOCK_W_MIN, BLOCK_W_MAX, BLOCK_W_STEP),
        B('show_grid', 'Show the grid', True),
        B('show_hud', 'Show the score, lines and level', True),
        S('hud_opacity', 'HUD panel opacity (%)', 60, 0, 90, 10, visible='show_hud'),
        C('background', 'Background colour', 'FF06080F'),
    ] + CUSTOM_SETTINGS),
    ('Clock', [
        B('show_clock', 'Show the clock', True),
        O('clock_style', 'Clock style', CLOCK_TEXT, list(CLOCK_STYLES), visible='show_clock'),
        B('clock_seconds', 'Show seconds', False, visible='show_clock'),
        B('clock_24h', 'Use 24-hour time', False, visible='show_clock'),
        O('clock_position', 'Block clock position', CLOCK_BOTTOM, list(CLOCK_POSITIONS),
          visible=('<dependencies><dependency type="visible" setting="show_clock">true</dependency>'
                   '<dependency type="visible" setting="clock_style">%d</dependency></dependencies>'
                   % CLOCK_BLOCKS)),
        C('clock_colour', 'Block clock colour', 'FFE8ECF4',
          visible=('<dependencies><dependency type="visible" setting="show_clock">true</dependency>'
                   '<dependency type="visible" setting="clock_style">%d</dependency></dependencies>'
                   % CLOCK_BLOCKS)),
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


def read(getters):
    """Settings as a dict. getters: {'boolean': f(id), 'integer': f(id), 'string': f(id)}
    (the Kodi layer passes Addon accessors). Bad or missing values fall back to defaults."""
    out = {}
    for s in all_settings():
        try:
            if s['type'] == 'boolean':
                out[s['id']] = bool(getters['boolean'](s['id']))
            elif s['type'] == 'colour':
                out[s['id']] = valid_colour(getters['string'](s['id'])) or s['default']
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


# ---------------------------------------------------------------- colours

def _argb(rgb):
    return 'FF' + rgb.upper()


def piece_colours(s):
    """The seven piece colours as AARRGGBB, for the chosen scheme or the custom colours."""
    if s['scheme'] == SCHEME_CUSTOM:
        return dict((p, valid_colour(s['custom_%s' % p]) or 'FFFFFFFF') for p in PIECES)
    _name, colours = SCHEMES[min(s['scheme'], len(SCHEMES) - 1)]
    return dict(zip(PIECES, (_argb(c) for c in colours)))


def ghost_colour(colour, alpha=0x50):
    """The same colour, mostly transparent, for the landing preview."""
    return '%02X%s' % (alpha, colour[2:])


def hud_colour(s):
    alpha = int(round(s['hud_opacity'] * 2.55))
    return '%02X000000' % alpha


# ---------------------------------------------------------------- layout

def columns_for(block_width):
    """How many columns fit across the screen at this block width."""
    return max(10, int(round(W / float(block_width))))


def columns(s):
    return columns_for(s['block_size'])


def board_size(s):
    """(columns, rows) of the playfield."""
    return columns(s), ROWS


def block_widths():
    return range(BLOCK_W_MIN, BLOCK_W_MAX + 1, BLOCK_W_STEP)


def column_counts():
    """Every column count the block size slider can produce (for the grid images)."""
    return sorted(set(columns_for(w) for w in block_widths()))


def board_rect(s):
    """(left, top, width, height) of the playfield on screen: always the whole screen."""
    return 0, 0, W, H


def cell_rect(s, x, y):
    """The screen rectangle of board cell (x, y) as (left, top, width, height). Rounded so the
    cells tile the board exactly, with no gaps or overlaps."""
    cols = columns(s)
    left, top, bw, bh = board_rect(s)
    x0 = left + int(round(bw * x / float(cols)))
    x1 = left + int(round(bw * (x + 1) / float(cols)))
    y0 = top + int(round(bh * y / float(ROWS)))
    y1 = top + int(round(bh * (y + 1) / float(ROWS)))
    return x0, y0, x1 - x0, y1 - y0


def speed_factor(s, level):
    factor = s['speed'] / 100.0
    if s['progressive']:
        factor *= min(2.6, 1.0 + 0.10 * (level - 1))
    return factor


def delays(s, level):
    """(think, move one cell, drop one row) in seconds."""
    factor = speed_factor(s, level)
    return (max(0.030, THINK_SECONDS / factor),
            max(0.008, MOVE_SECONDS / factor),
            max(0.006, DROP_SECONDS / factor))


def clock_text(now, twenty_four_hour, seconds=False):
    """`now` is a time.struct_time (what time.localtime returns in Kodi)."""
    if twenty_four_hour:
        if seconds:
            return '%02d:%02d:%02d' % (now.tm_hour, now.tm_min, now.tm_sec)
        return '%02d:%02d' % (now.tm_hour, now.tm_min)
    hour = now.tm_hour % 12 or 12
    if seconds:
        return '%d:%02d:%02d %s' % (hour, now.tm_min, now.tm_sec,
                                    'AM' if now.tm_hour < 12 else 'PM')
    return '%d:%02d %s' % (hour, now.tm_min, 'AM' if now.tm_hour < 12 else 'PM')
