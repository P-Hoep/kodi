"""What the clock shows and where: rows, their values and puzzles, colours, and the
screen rectangles of every glyph, in Kodi's 1920x1080 coordinates. No Kodi imports, so
tools and tests can draw the same face with Pillow.
"""

import math

from . import equations, texmath

W, H = 1920, 1080
MARGIN_Y = 70
MAX_EXPR_W = 1440          # leaves room at the right for the row labels
LABEL_RIGHT = 1840
RULE_HALF_W = 660

# kind -> (label, variable letter, variable letter with distinct letters)
ROWS = {
    'year': ('year', 'y', 'y'), 'month': ('month', 'm', 'M'), 'day': ('day', 'd', 'd'),
    'hours': ('hours', 'h', 'h'), 'minutes': ('minutes', 'm', 'm'), 'seconds': ('seconds', 's', 's'),
}
DATE_ORDERS = [('year', 'month', 'day'), ('month', 'day', 'year'), ('day', 'month', 'year')]

# (background, text, label, separator, badge) as AARRGGBB; the original page used
# Bootstrap's #333 text on white, firebrick labels, #eee rules and an olive 24h icon.
LIGHT = ('FFFFFFFF', 'FF333333', 'FFB22222', 'FFE4E4E4', 'FF4B5320')
DARK = ('FF000000', 'FFEEEEEE', 'FFC03030', 'FF262626', 'FF7D8C35')


def rows(s):
    out = list(DATE_ORDERS[s['date_order']]) if s['date'] else []
    out += ['hours', 'minutes']
    if s['seconds']:
        out.append('seconds')
    return out


def value(kind, now, military):
    """now is a datetime (or anything with the same fields)."""
    if kind == 'hours':
        return now.hour if military else (now.hour + 11) % 12 + 1
    return {'year': now.year, 'month': now.month, 'day': now.day,
            'minutes': now.minute, 'seconds': now.second}[kind]


def puzzle(kind, now, s, rng):
    label, var, distinct = ROWS[kind]
    gens = equations.SETS[s['equation_set']]
    return equations.make(value(kind, now, s['military']), distinct if s['variables'] else var, gens, rng)


def is_dark(s, now):
    if s['colours'] == 2:
        return not 8 <= now.hour <= 16       # the original's day/night rule
    return s['colours'] == 1


def _mix(fg, bg, amount):
    """fg moved `amount` (0..1) of the way towards bg."""
    out = 'FF'
    for i in (2, 4, 6):
        a, b = int(fg[i:i + 2], 16), int(bg[i:i + 2], 16)
        out += '%02X' % int(round(a + (b - a) * amount))
    return out


def palette(s, now):
    bg, fg, label, rule, badge = DARK if is_dark(s, now) else LIGHT
    k = s['dim'] / 100.0
    return {'bg': bg, 'text': _mix(fg, bg, k), 'label': _mix(label, bg, k),
            'rule': _mix(rule, bg, k), 'badge': _mix(badge, bg, k)}


def drift(s, t):
    """A slow Lissajous wander of up to 36 x 24 px, so nothing burns in."""
    if not s['drift']:
        return 0, 0
    return int(round(36 * math.sin(t / 397.0))), int(round(24 * math.sin(t / 263.0 + 1.3)))


class Geometry(object):
    """Row centres, the em size and separator positions for n rows."""

    def __init__(self, n, text_size=100, offset=(0, 0)):
        self.n = n
        self.dx, self.dy = offset
        self.pitch = (H - 2 * MARGIN_Y) / float(n)
        self.em = min(self.pitch * 0.5, 125.0) * text_size / 100.0
        self.label_em = max(26.0, self.em * 0.32)

    def centre(self, i):
        return MARGIN_Y + self.pitch * (i + 0.5) + self.dy

    def rects(self, box, i):
        """Screen rectangles (glyph, x, y, w, h) for a typeset Box centred in row i."""
        em = self.em
        em = min(em, MAX_EXPR_W / max(box.width, 0.01), self.pitch * 0.92 / max(box.height + box.depth, 0.01))
        x0 = W / 2.0 + self.dx - box.width * em / 2.0
        base = self.centre(i) + (box.height - box.depth) / 2.0 * em
        return to_screen(box, x0, base, em)

    def label(self, text, i):
        box = texmath.layout(('word', 'ord', text), 'D')
        em = self.label_em
        top = self.centre(i) - self.pitch / 2.0 + 10
        return to_screen(box, LABEL_RIGHT + self.dx - box.width * em, top + box.height * em, em)

    def separators(self):
        """(x, y, w, h) of the lines between rows."""
        out = []
        for i in range(1, self.n):
            y = MARGIN_Y + self.pitch * i + self.dy
            out.append((int(W / 2 + self.dx - RULE_HALF_W), int(round(y)) - 1, 2 * RULE_HALF_W, 2))
        return out

    def badge(self):
        box = texmath.typeset('24')
        word = texmath.layout(('word', 'ord', 'h'), 'D')
        em = 56.0
        x = W - LABEL_RIGHT + self.dx        # top left, clear of the row labels
        base = 34 + self.dy + 0.7 * em
        return to_screen(box, x, base, em) + to_screen(word, x + box.width * em, base, em)


def to_screen(box, x0, base, em):
    out = []
    for name, left, top, w, h in box.items:
        x, y = x0 + left * em, base - top * em
        out.append((name, int(round(x)), int(round(y)),
                    max(1, int(round(x + w * em)) - int(round(x))), max(1, int(round(y + h * em)) - int(round(y)))))
    return out
