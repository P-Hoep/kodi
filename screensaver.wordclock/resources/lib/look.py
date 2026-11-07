"""Colours, day and night, effects and layout geometry. No Kodi imports.

Colours are Kodi's 'AARRGGBB' hex strings. Geometry is in Kodi's 1920x1080 skin pixels.
"""

import colorsys
import math

from . import config, grid

W, H = 1920, 1080
CARD_PITCH = 0.0672        # cell pitch as a fraction of the card side (from the reference)
GLOW_SCALE = 1.5           # the glow image covers 1.5 cells
DOT_INSET = 0.055          # minute dots: centre this far in from each corner (fraction of the side)
DOT_SIZE = 0.02
DRIFT_PX = 24
FAINT = 0.55               # 'Faint' unlit letters: this far from the unlit colour toward the card
GLOW_ALPHA = [0, 0x60, 0xB0]
CYCLE_SECONDS = 600.0
BLEND_SECONDS = 8.0
# Each word keeps one hue in 'Each word a different colour'.
WORD_HUES = {
    'IT': 0.58, 'IS': 0.58, 'AM': 0.12, 'PM': 0.12, 'A': 0.83, 'QUARTER': 0.83, 'TWENTY': 0.0,
    'M_FIVE': 0.08, 'HALF': 0.75, 'M_TEN': 0.33, 'TO': 0.5, 'PAST': 0.5,
    'ONE': 0.95, 'TWO': 0.03, 'THREE': 0.1, 'FOUR': 0.16, 'FIVE': 0.27, 'SIX': 0.4, 'SEVEN': 0.47,
    'EIGHT': 0.54, 'NINE': 0.62, 'TEN': 0.7, 'ELEVEN': 0.78, 'TWELVE': 0.88, 'MIDNIGHT': 0.66,
    'OCLOCK': 0.45,
}


# ------------------------------------------------------------------ colour maths

def rgb(c):
    c = int(c, 16)
    return (c >> 24) & 255, (c >> 16) & 255, (c >> 8) & 255, c & 255


def hexa(a, r, g, b):
    return '%02X%02X%02X%02X' % tuple(max(0, min(255, int(round(v)))) for v in (a, r, g, b))


def blend(c1, c2, t):
    """c1 at t=0, c2 at t=1."""
    p, q = rgb(c1), rgb(c2)
    return hexa(*[p[i] + (q[i] - p[i]) * t for i in range(4)])


def scale(c, f):
    a, r, g, b = rgb(c)
    return hexa(a, r * f, g * f, b * f)


def with_alpha(c, alpha):
    _a, r, g, b = rgb(c)
    return hexa(alpha, r, g, b)


def luminance(c):
    _a, r, g, b = rgb(c)
    return (0.2126 * r + 0.7152 * g + 0.0722 * b) / 255.0


def hue_colour(hue, lit):
    """A colour of this hue that reads on the card as well as the palette's lit colour does."""
    if luminance(lit) < 0.5:   # dark letters on a light card
        r, g, b = colorsys.hsv_to_rgb(hue % 1.0, 0.85, 0.6)
    else:
        r, g, b = colorsys.hsv_to_rgb(hue % 1.0, 0.55, 1.0)
    return hexa(255, r * 255, g * 255, b * 255)


# ------------------------------------------------------------------ day and night

def minutes(hhmm):
    h, m = hhmm.split(':')
    return int(h) * 60 + int(m)


def is_day_hours(s, now):
    """Between 'Day starts' and 'Night starts' (either may be the later one)."""
    t = now.hour * 60 + now.minute
    a, b = minutes(s['day_start']), minutes(s['night_start'])
    if a == b:
        return True
    return a <= t < b if a < b else (t >= a or t < b)


def phase(s, now):
    """'day' or 'night': which palette to use now."""
    if s['mode'] == 0:
        return 'night'
    if s['mode'] == 1:
        return 'day'
    return 'day' if is_day_hours(s, now) else 'night'


def palette(s, which):
    """{'bg', 'card', 'lit', 'unlit'} for 'day' or 'night', before effects and dimming."""
    index = s['%s_palette' % which]
    if index == config.CUSTOM:
        return dict((k, s['%s_%s' % (which, k)]) for k in ('bg', 'card', 'lit', 'unlit'))
    _name, bg, card, lit, unlit = config.PALETTES[index]
    return {'bg': 'FF' + bg, 'card': 'FF' + card, 'lit': 'FF' + lit, 'unlit': 'FF' + unlit}


def mix(p1, p2, t):
    return dict((k, blend(p1[k], p2[k], t)) for k in p1)


def dim_factor(s, now):
    f = 1.0 - s['dim'] / 100.0
    if not is_day_hours(s, now):
        f *= 1.0 - s['night_dim'] / 100.0
    return f


def finish(s, pal, factor):
    """Apply the unlit, frame, glow and dimming settings to a palette."""
    out = dict(pal)
    if s['unlit'] == 1:
        out['unlit'] = blend(pal['unlit'], pal['card'], FAINT)
    elif s['unlit'] == 2:
        out['unlit'] = '00000000'
    if s['frame'] == 2:
        out['bg'] = pal['card']
    out = dict((k, scale(v, factor)) for k, v in out.items())
    out['glow'] = with_alpha(out['lit'], GLOW_ALPHA[s['glow']])
    return out


def word_colour(s, word, lit, seconds):
    """The lit colour for a word under the 'Lit letter colour' setting."""
    if s['lit_effect'] == 1:
        return hue_colour(WORD_HUES[word], lit)
    if s['lit_effect'] == 2:
        return hue_colour(seconds / CYCLE_SECONDS, lit)
    return lit


# ------------------------------------------------------------------ layout

def drift(s, elapsed):
    """(dx, dy) in pixels: a slow Lissajous path, one step a minute."""
    if not s['drift']:
        return 0, 0
    t = int(elapsed // 60)
    side = card_side(s)
    room_y = DRIFT_PX if s['frame'] == 2 else min(DRIFT_PX, max(0, (H - side) // 2))
    return (int(round(DRIFT_PX * math.sin(2 * math.pi * t / 37.0))),
            int(round(room_y * math.sin(2 * math.pi * t / 23.0 + 1.0))))


def card_side(s):
    return int(round(H * s['size'] / 100.0))


class Layout(object):
    """Where everything goes for one size, letter size and drift offset."""

    def __init__(self, s, offset=(0, 0)):
        self.side = side = card_side(s)
        dx, dy = offset
        self.card = ((W - side) // 2 + dx, (H - side) // 2 + dy, side, side)
        self.pitch = side * CARD_PITCH
        self.cx, self.cy = W / 2.0 + dx, H / 2.0 + dy
        self.box = self.pitch * s['letter_size'] / 100.0

    def cell_centre(self, index):
        row, col = divmod(index, grid.SIZE)
        return (self.cx + (col - 5) * self.pitch, self.cy + (row - 5) * self.pitch)

    def letter_rect(self, index, k=1.0):
        x, y = self.cell_centre(index)
        b = self.box * k
        return int(round(x - b / 2)), int(round(y - b / 2)), int(round(b)), int(round(b))

    def glow_rect(self, index):
        return self.letter_rect(index, GLOW_SCALE)

    def dot_rects(self):
        """Top left, top right, bottom right, bottom left (the order they light)."""
        x0, y0, side, _ = self.card
        d = max(4, int(round(side * DOT_SIZE)))
        inset = side * DOT_INSET
        out = []
        for fx, fy in ((0, 0), (1, 0), (1, 1), (0, 1)):
            cx = x0 + (inset if fx == 0 else side - inset)
            cy = y0 + (inset if fy == 0 else side - inset)
            out.append((int(round(cx - d / 2.0)), int(round(cy - d / 2.0)), d, d))
        return out
