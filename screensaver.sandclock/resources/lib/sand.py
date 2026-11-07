"""The clock's layout, its digits as grains of sand, the falling-sand physics and the colours.
No Kodi imports, so all of it runs (and is tested) outside Kodi.

Geometry is in Kodi's 1920x1080 skin pixels. Sand lives on a grid of square cells `g` pixels
wide that is fixed to the screen: column 0 starts at X0, row 0 sits on the floor (the bottom
edge) and rows count upward. A digit turns into one grain per cell whose centre is inside the
glyph, so the grains line up with the pile they fall into.
"""

import colorsys
import json
import math
import random

from . import config

W, H = 1920, 1080
GRAIN_PX = [6, 9, 14]                 # Fine, Medium, Coarse
GRAVITY = [1400.0, 3000.0, 6000.0]    # px/s^2: Floaty, Normal, Heavy
SPREAD = [0.7, 0.45, 0.3]             # s over which a digit's grains let go: Slow, Normal, Quick
LEAD_EXTRA = 0.12                     # the last grain lets go this long before the new time shows
SLIDE_MS = 45                         # per cell a grain slides down the side of the pile
RUN_BLOCK = 32                        # pile strips are cut at every 32nd row (strip textures go to 32)
DRIFT_PX = 30
GRAIN_BUDGET = 1000                   # most grains one crumble may drop (whole clock)
RAINBOW_SECONDS = 120.0               # one trip round the colour wheel
CLOCK_HEIGHT_MAX = 0.42               # of the screen height
CLOCK_CENTRE_Y = [0.30, 0.42]         # 'Upper part', 'Centre'


# ------------------------------------------------------------------ fonts and layout

class Font(object):
    """Glyph boxes and masks for one font and weight, from media/fonts/fonts.json (written by
    tools/make_sandclock_media.py). Each glyph image is `h` px tall; digits share one width
    (tabular), the colon has its own. A mask is the glyph's ink at mask_h rows, run-length coded."""

    def __init__(self, data):
        self.h = float(data['h'])
        self.widths = {':': float(data['colon_w'])}
        self.masks = {}
        for ch, (mw, rows) in data['masks'].items():
            if ch != ':':
                self.widths[ch] = float(data['digit_w'])
            grid = []
            for runs in rows:
                row = bytearray(mw)
                for start, length in runs:
                    row[start:start + length] = b'\x01' * length
                grid.append(row)
            self.masks[ch] = grid

    @staticmethod
    def load(path, folder, weight):
        with open(path) as handle:
            return Font(json.load(handle)[folder][str(weight)])

    def width(self, text):
        return sum(self.widths[ch] for ch in text)


def lead(s):
    """How long before the time changes the old digits start to crumble."""
    return SPREAD[s['speed']] + LEAD_EXTRA


def time_text(s, hour, minute, second):
    h = hour if s['hours'] == 0 else (hour % 12 or 12)
    text = ('%02d:%02d' if s['hours'] == 0 else '%d:%02d') % (h, minute)
    return text + (':%02d' % second if s['seconds'] else '')


def widest_text(s):
    return '88:88:88' if s['seconds'] else '88:88'


def layout(s, font, text, offset=(0, 0)):
    """[(x, y, w, h)] for each character of text. The scale comes from the widest text the
    clock can show, so it never changes size; a shorter text (9:05 after 12:59) is centred."""
    scale = min(W * s['size'] / 100.0 / font.width(widest_text(s)), H * CLOCK_HEIGHT_MAX / font.h)
    h = font.h * scale
    x = (W - font.width(text) * scale) / 2.0 + offset[0]
    y = H * CLOCK_CENTRE_Y[s['position']] - h / 2.0 + offset[1]
    boxes = []
    for ch in text:
        w = font.widths[ch] * scale
        boxes.append((x, y, w, h))
        x += w
    return boxes


class Grid(object):
    def __init__(self, g):
        self.g = g
        self.cols = int(W // g)
        self.x0 = (W - self.cols * g) // 2

    def x(self, col):
        return self.x0 + col * self.g

    def y(self, row):
        """Top of a cell in this row."""
        return H - (row + 1) * self.g

    def col_at(self, x):
        return int(math.floor((x - self.x0) / self.g))

    def row_at(self, y):
        return int(math.floor((H - y) / self.g))

    def rows_below(self, y):
        """How many whole rows fit between y and the floor."""
        return int((H - y) // self.g)


def grains(font, ch, box, grid):
    """The grains of a glyph drawn in box: (col, y) for each cell, on the screen grid, whose
    centre is inside the glyph; y is the top of the cell."""
    x, y, w, h = box
    mask = font.masks[ch]
    mh, mw = len(mask), len(mask[0])
    g = grid.g
    out = []
    for col in range(max(0, grid.col_at(x)), min(grid.cols, grid.col_at(x + w) + 1)):
        cx = grid.x(col) + g / 2.0
        u = int((cx - x) / w * mw)
        if not 0 <= u < mw:
            continue
        for row in range(grid.row_at(y + h), grid.row_at(y) + 1):
            cy = H - (row + 0.5) * g
            v = int((cy - y) / h * mh)
            if 0 <= v < mh and mask[v][u]:
                out.append((col, H - (row + 1) * g))
    return out


def grain_px(s, font):
    """The grain size in px. Crumbling the whole clock at once can make too many grains for a
    small box like a Fire TV Stick, so it steps up to coarser grains until one crumble fits
    GRAIN_BUDGET."""
    index = s['grain']
    while index < len(GRAIN_PX) - 1 and s['crumble'] == 1:
        text = widest_text(s)
        grid = Grid(GRAIN_PX[index])
        if sum(len(grains(font, ch, box, grid)) for ch, box in zip(text, layout(s, font, text))) <= GRAIN_BUDGET:
            break
        index += 1
    return GRAIN_PX[index]


def pile_target(s, font, g):
    """How tall (px) the pile should get: the setting, but always clear of the clock."""
    _x, y, _w, h = layout(s, font, widest_text(s), (0, DRIFT_PX))[0]
    return max(3 * g, min(H * s['pile'] / 100.0, H - (y + h) - 4 * g))


def sink_speed(inflow, height, target, footprint):
    """How fast (px/s) the pile should sink to stay near its target height. inflow: px^2 of
    sand landing per second; footprint: px of floor the pile covers. Sinking at inflow /
    footprint holds the pile steady, so scale that by how tall it is against its target."""
    return inflow / max(footprint, 200.0) * max(0.0, min(3.0, height / float(target)))


def speed_changed(new, current):
    """Worth rescheduling? (Every change restarts every strip's animation.)"""
    return abs(new - current) > max(3.0, 0.15 * current)


# ------------------------------------------------------------------ physics

class Flight(object):
    """One grain's trip, in ms after its batch starts: it waits `delay`, falls `fall_px` while
    drifting `scatter_px` sideways (`fall_ms`), slides (dx, dy) down the side of the pile
    (`slide_ms`) and lands at `land_ms` in cell (col, row), then sinks with the pile."""
    __slots__ = ('x', 'y', 'col', 'row', 'colour', 'delay', 'fall_px', 'scatter_px', 'fall_ms',
                 'dx', 'dy', 'slide_ms', 'land_ms', 'land_y')

    def __repr__(self):
        return 'Flight(%d,%d -> %d,%d at %dms)' % (self.x, self.y, self.col, self.row, self.land_ms)


def fall_ms(px, gravity):
    return 1000.0 * math.sqrt(2.0 * max(0.0, px) / gravity)


class Pile(object):
    """Where the sand is (cell by cell) and how it sinks.

    The floor is a slow drain: the whole pile sinks at `speed` px/s, so a cell's top is at
    y = H - (row + 1) * g + sunk(t) on screen. Rows are numbered from where the floor was at
    the start and never renumbered; heights[col] is the next free row in each column."""

    def __init__(self, grid, rng=None, t=0.0):
        self.grid = grid
        self.heights = [0] * grid.cols
        self.cells = {}             # col -> {row: (colour, land time)}
        self.rng = rng or random.Random()
        self.base_t, self.base_sunk, self.speed = t, 0.0, 0.0
        self.change = None          # (time, speed) of a scheduled speed change

    # -- sinking

    def sunk(self, t):
        """How far the pile has sunk by time t, in px. A scheduled speed change is part of
        it, so sand planned now lands right even if it lands after the change."""
        if self.change and t > self.change[0]:
            at, speed = self.change
            return self.base_sunk + self.speed * (at - self.base_t) + speed * (t - at)
        return self.base_sunk + self.speed * (t - self.base_t)

    def speed_at(self, t):
        return self.change[1] if self.change and t > self.change[0] else self.speed

    def schedule(self, at, speed):
        """Change the sinking speed at time `at` (after every grain in the air has landed)."""
        self.commit(at)
        self.change = (at, speed)

    def commit(self, t):
        """Make a scheduled change that is due by t the current speed."""
        if self.change and t >= self.change[0]:
            at, speed = self.change
            self.base_sunk, self.base_t, self.speed = self.sunk(at), at, speed
            self.change = None

    def cell_y(self, row, t):
        return H - (row + 1) * self.grid.g + self.sunk(t)

    def floor_row(self, t):
        """The lowest row whose cells are still wholly on screen."""
        return int(math.ceil(self.sunk(t) / self.grid.g - 1e-9))

    def top(self, col, t):
        return max(self.heights[col], self.floor_row(t))

    def footprint(self, t):
        """How much of the floor (px) the pile covers."""
        floor = self.floor_row(t)
        return max(1, sum(1 for top in self.heights if top > floor + 1)) * self.grid.g

    def height_px(self, t):
        """How far the tallest landed sand reaches above the bottom of the screen."""
        tallest = 0.0
        for column in self.cells.values():
            rows = [r for r, (_c, landed) in column.items() if landed <= t]
            if rows:
                tallest = max(tallest, H - self.cell_y(max(rows), t))
        return tallest

    # -- falling

    def drop(self, cells, colour, t0, gravity, spread):
        """Plan the fall of a crumbling glyph: cells are its grains as (col, y) with y the top
        of the grain on screen, t0 the time it starts crumbling. Grains let go over `spread`
        seconds, lower ones first with a random scatter, drift a little sideways as they fall,
        land on the pile and slide down its side while a neighbour column is lower (which makes
        the 45 degree slopes of dry sand). Returns [Flight] in landing order and books their
        cells, so the next glyph lands on top of this one."""
        rng, g, h = self.rng, self.grid.g, self.heights
        if not cells:
            return []
        ys = [y for _c, y in cells]
        low, span = max(ys), max(1.0, max(ys) - min(ys))
        planned = []
        for col, y in cells:
            delay = 1000.0 * spread * (0.5 * rng.random() + 0.5 * (low - y) / span)
            drift = int(round(rng.gauss(0, 0.6 + (H - y) / 900.0)))
            land_col = min(self.grid.cols - 1, max(0, col + drift))
            est = delay + fall_ms(self.cell_y(self.top(land_col, t0), t0) - y, gravity)
            planned.append((est, rng.random(), col, y, land_col, delay))
        planned.sort()
        flights = []
        for est, _r, col, y, land_col, delay in planned:
            # Where it meets the pile: the pile sinks while the grain falls, so look twice.
            t_hit = t0 + est / 1000.0
            for _ in range(2):
                top = self.top(land_col, t_hit)
                fall = self.cell_y(top, t_hit) - y
                t_hit = t0 + (delay + fall_ms(fall, gravity)) / 1000.0
            if fall <= 0:                     # the pile is up to the glyph: this grain is lost
                continue
            f = Flight()
            f.x, f.y, f.colour, f.delay = self.grid.x(col), y, colour, int(delay)
            f.fall_px, f.scatter_px = fall, (land_col - col) * g
            f.fall_ms = int(fall_ms(fall, gravity))
            cur, steps, floor = land_col, 0, self.floor_row(t_hit)
            while True:
                here = max(h[cur], floor)
                lower = [n for n in (cur - 1, cur + 1) if 0 <= n < len(h) and max(h[n], floor) < here]
                if not lower:
                    break
                cur = rng.choice(lower)
                steps += 1
            f.col, f.row = cur, max(h[cur], floor)
            h[cur] = f.row + 1
            f.slide_ms = steps * SLIDE_MS + (int(fall_ms((top - f.row) * g, gravity)) if steps else 0)
            f.land_ms = f.delay + f.fall_ms + f.slide_ms
            t_land = t0 + f.land_ms / 1000.0
            f.land_y = self.cell_y(f.row, t_land)
            f.dx = (cur - land_col) * g
            f.dy = f.land_y - (y + fall)
            self.cells.setdefault(cur, {})[f.row] = (colour, t_land)
            flights.append(f)
        flights.sort(key=lambda fl: fl.land_ms)
        return flights

    # -- drawing

    def prune(self, t):
        """Forget cells a whole strip block below the floor."""
        gone = self.floor_row(t) - RUN_BLOCK
        for col in list(self.cells):
            column = self.cells[col]
            for row in [r for r in column if r < gone]:
                del column[row]
            if not column:
                del self.cells[col]

    def strips(self, col, t):
        """[(row, length, colour)] bottom up: runs of same-coloured landed grains in a column,
        cut at every RUN_BLOCK rows (so the strip textures stay short, and a strip's grains
        keep their shades as the bottom of the pile sinks out of sight)."""
        column = self.cells.get(col, {})
        out = []
        for row in sorted(column):
            colour, landed = column[row]
            if landed > t:
                continue
            if out:
                r0, n, c0 = out[-1]
                if c0 == colour and r0 + n == row and row % RUN_BLOCK != 0:
                    out[-1] = (r0, n + 1, c0)
                    continue
            out.append((row, 1, colour))
        return out


# ------------------------------------------------------------------ colour

def rgb(c):
    c = int(c, 16)
    return (c >> 24) & 255, (c >> 16) & 255, (c >> 8) & 255, c & 255


def hexa(a, r, g, b):
    return '%02X%02X%02X%02X' % tuple(max(0, min(255, int(round(v)))) for v in (a, r, g, b))


def scale(c, f):
    a, r, g, b = rgb(c)
    return hexa(a, r * f, g * f, b * f)


def minutes(hhmm):
    h, m = hhmm.split(':')
    return int(h) * 60 + int(m)


def is_night(s, now):
    """now: a datetime. Between night_start and day_start (which may wrap midnight)."""
    t = now.hour * 60 + now.minute
    day, night = minutes(s['day_start']), minutes(s['night_start'])
    if day == night:
        return False
    if day < night:
        return not day <= t < night
    return night <= t < day


def dim_factor(s, now):
    f = 1.0 - s['dim'] / 100.0
    if is_night(s, now):
        f *= 1.0 - s['night_dim'] / 100.0
    return f


def palette(s, now):
    index = s['palette']
    if s['night_palette'] and is_night(s, now):
        index = s['night_palette'] - 1
    return ['FF' + c for c in config.PALETTES[index][1]]


def pick(colours, avoid, rng):
    choices = [c for c in colours if c != avoid] or colours
    return rng.choice(choices)


def rainbow(seconds):
    r, g, b = colorsys.hsv_to_rgb((seconds / RAINBOW_SECONDS) % 1.0, 0.65, 1.0)
    return hexa(255, r * 255, g * 255, b * 255)


def drift(s, elapsed):
    """(dx, dy) in pixels: a slow Lissajous path, one step a minute."""
    if not s['drift']:
        return 0, 0
    t = int(elapsed // 60)
    return (int(round(DRIFT_PX * math.sin(2 * math.pi * t / 37.0))),
            int(round(DRIFT_PX * math.sin(2 * math.pi * t / 23.0 + 1.0))))
