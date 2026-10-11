"""The ASCII rendering modes: a grid of characters drawn from a bitmap glyph atlas into a
palette PNG. No Kodi imports.

Kodi skins have no guaranteed monospace font, so characters are not drawn as Kodi text:
tools/make_world_data.py rasterises CHARSET into media/glyphs/glyphs_<w>x<h>.png and each
frame is assembled here from cached glyph rows (bytes joins, all in C)."""

from . import landclass, raster

# Every character any mode can draw; the atlas holds them in this order.
CHARSET = (' .,:;\'"`^-=+*#%@~_!?|/\\()[]{}<>&$0123456789'
           'abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ'
           '≈·∙░▒▓█♣♠τΓ∩▲∧'
           '←↑→↓↖↗↘↙§☼•°'
           '◎○●‼♦¤')
BLOCKS = '░▒▓█'
INDEX = dict((c, i) for i, c in enumerate(CHARSET))
CELL_SIZES = [(16, 24), (12, 18), (8, 12)]  # density low, medium, high

RAMPS = [
    ' .:-=+*#%@',
    ' ░▒▓█',
    ' .\'`^",:;!i><~+_-?][}{1)(|\\/tfjrxnuvczXYUJCLQ0OZmwqpdbkhao*#MW&8%B@$',
]
# Wind arrows by the direction the wind blows towards, clockwise from north.
ARROWS = '↑↗→↘↓↙←↖'
ARROWS_PLAIN = '^/>\\v/<\\'


# ---------------------------------------------------------------- palettes

CLASSIC16 = [(0, 0, 0), (0, 0, 170), (0, 170, 0), (0, 170, 170), (170, 0, 0), (170, 0, 170),
             (170, 85, 0), (170, 170, 170), (85, 85, 85), (85, 85, 255), (85, 255, 85),
             (85, 255, 255), (255, 85, 85), (255, 85, 255), (255, 255, 85), (255, 255, 255)]
RAMP_STOPS = {
    'neon': [(10, 0, 30), (120, 0, 160), (255, 40, 200), (40, 220, 255), (240, 255, 255)],
    'sepia': [(20, 12, 6), (90, 60, 30), (170, 120, 70), (230, 200, 150), (255, 248, 230)],
    'green': [(0, 10, 0), (0, 90, 20), (40, 200, 70), (150, 255, 160)],
    'amber': [(16, 6, 0), (110, 50, 0), (255, 160, 20), (255, 230, 160)],
    'white': [(8, 8, 8), (90, 90, 90), (200, 200, 200), (255, 255, 255)],
    'blue': [(0, 4, 20), (10, 50, 140), (60, 150, 255), (200, 235, 255)],
}
COLOR_PALETTES = ['natural', 'classic', 'neon', 'sepia']
MONO_PALETTES = ['green', 'amber', 'white', 'blue']


def _ramp(stops, n):
    out = []
    for i in range(n):
        t = i / float(n - 1) * (len(stops) - 1)
        k = min(int(t), len(stops) - 2)
        f = t - k
        a, b = stops[k], stops[k + 1]
        out.append(tuple(int(a[c] + (b[c] - a[c]) * f + 0.5) for c in range(3)))
    return out


class Palette(object):
    """Maps RGB colours to palette indexes. Index 0 is reserved for transparency."""

    def __init__(self, name):
        self.name = name
        self.cache = {}
        if name == 'natural':
            self.kind = 'cube'
            self.colors = [(0, 0, 0)] + [(r * 51, g * 51, b * 51) for r in range(6) for g in range(6) for b in range(6)]
        elif name == 'classic':
            self.kind = 'nearest'
            self.colors = [(0, 0, 0)] + CLASSIC16
        else:
            self.kind = 'ramp'
            self.colors = [(0, 0, 0)] + _ramp(RAMP_STOPS[name], 48)
        self.black = self.index((0, 0, 0))

    def index(self, rgb):
        key = (rgb[0] >> 2, rgb[1] >> 2, rgb[2] >> 2)
        hit = self.cache.get(key)
        if hit is not None:
            return hit
        r, g, b = rgb
        if self.kind == 'cube':
            i = 1 + ((r * 5 + 127) // 255) * 36 + ((g * 5 + 127) // 255) * 6 + (b * 5 + 127) // 255
        elif self.kind == 'nearest':
            best, i = None, 1
            for k, c in enumerate(self.colors[1:], 1):
                d = (2 * (r - c[0]) ** 2 + 4 * (g - c[1]) ** 2 + 3 * (b - c[2]) ** 2)
                if best is None or d < best:
                    best, i = d, k
        else:
            lum = (r * 299 + g * 587 + b * 114) / 1000.0
            # Stretch so that dim terrain still reads; ramps start near black.
            i = 1 + min(47, int((lum / 255.0) ** 0.8 * 47 + 0.5))
        self.cache[key] = i
        return i


# ---------------------------------------------------------------- glyph atlas

class Atlas(object):
    def __init__(self, path, cw, ch):
        img = raster.read(path, want=1)
        self.cw, self.ch = cw, ch
        self.bits = []
        for g in range(len(CHARSET)):
            rows = []
            for y in range(ch):
                start = y * img.w + g * cw
                rows.append(tuple(v > 127 for v in img.data[start:start + cw]))
            self.bits.append(rows)
        self.rows_cache = {}

    def rows(self, g, fg, bg):
        key = (g, fg, bg)
        hit = self.rows_cache.get(key)
        if hit is None:
            f, b = bytes((fg,)), bytes((bg,))
            hit = tuple(b''.join(f if on else b for on in row) for row in self.bits[g])
            if len(self.rows_cache) > 20000:
                self.rows_cache.clear()
            self.rows_cache[key] = hit
        return hit

    def encode(self, cells, cols, rows, palette):
        """cells: list of (glyph, fg, bg) row by row -> palette PNG bytes."""
        lines = []
        get = self.rows
        for r in range(rows):
            row_cells = [get(*cell) for cell in cells[r * cols:(r + 1) * cols]]
            for line in zip(*row_cells):
                lines.append(b''.join(line))
        return raster.encode_indexed(cols * self.cw, rows * self.ch, b''.join(lines), palette.colors,
                                     transparent=(0,), level=6)


# ---------------------------------------------------------------- composing cells

def mix(a, b, t):
    return (int(a[0] + (b[0] - a[0]) * t), int(a[1] + (b[1] - a[1]) * t), int(a[2] + (b[2] - a[2]) * t))


def scale(c, k):
    return (min(255, int(c[0] * k)), min(255, int(c[1] * k)), min(255, int(c[2] * k)))


def cell_hash(i):
    """Stable pseudo-random value 0..65535 for a source pixel index."""
    i = (i * 2654435761) & 0xFFFFFFFF
    return (i ^ (i >> 16)) & 0xFFFF


def geographic_cell(cls, geo_index, unicode_glyphs=True):
    glyphs_u, glyphs_a, color = landclass.ASCII[cls]
    glyphs = glyphs_u if unicode_glyphs else glyphs_a
    return glyphs[cell_hash(geo_index) % len(glyphs)], color


def image_cell(rgb, ramp):
    lum = (rgb[0] * 299 + rgb[1] * 587 + rgb[2] * 114) / 1000.0
    k = int(lum / 256.0 * len(ramp))
    return ramp[min(len(ramp) - 1, k)], rgb


def arrow(direction_deg, unicode_glyphs=True):
    """Glyph for wind blowing FROM direction_deg (meteorological convention)."""
    towards = (direction_deg + 180.0) % 360.0
    k = int((towards + 22.5) // 45) % 8
    return (ARROWS if unicode_glyphs else ARROWS_PLAIN)[k]


def brightness(rgb):
    return (rgb[0] * 299 + rgb[1] * 587 + rgb[2] * 114) / 255000.0
