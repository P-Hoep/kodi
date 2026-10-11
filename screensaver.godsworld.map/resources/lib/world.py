"""The world in geographic space: base map, day/night, city lights and weather overlays,
all as equirectangular images. No Kodi imports.

Projections never see these steps: everything is composed here in longitude/latitude, so
a new projection or rendering style automatically gets every layer, correctly aligned.

Day/night is a blend of two complete images, 'day' (the base map, optionally with city
lights) and 'night' (the base map darkened, with city lights). Each row of the composite is
cut into spans of equal twilight level around the subsolar meridian; a span is either a
straight copy or one table lookup per byte (raster.pair_map), so the whole image is
recomposed in C-speed pieces as the terminator moves.
"""

import json
import math
import os
import re
from array import array

from . import events, landclass, overlays, raster, sources, sun

SW, SH = 2048, 1024          # base map size
CW, CH = 1024, 512           # land class / overlay / ASCII sampling size
LEVELS = 12                  # twilight steps between night and day
LIGHT_COLOR = (255, 196, 120)
NIGHT_TINT = (0.62, 0.72, 1.0)
BORDER = (255, 255, 255, 0.35)
COAST = (180, 230, 255, 0.45)


def _blend_tables():
    """LEVELS + 1 tables for pair_map: level k mixes day (low byte) and night (high byte)."""
    tables = []
    for k in range(LEVELS + 1):
        rows = []
        for n in range(256):
            base = n * (LEVELS - k)
            rows.append(bytes((d * k + base + LEVELS // 2) // LEVELS for d in range(256)))
        tables.append(b''.join(rows))
    return tables


def _inverse_smoothstep(f):
    return 0.5 - math.sin(math.asin(1 - 2 * f) / 3)


# sin(solar altitude) above which the daylight level is at least k (k = 1 .. LEVELS).
LEVEL_SIN = [sun.SIN_NIGHT + _inverse_smoothstep((k - 0.5) / LEVELS) * (sun.SIN_DAY - sun.SIN_NIGHT)
             for k in range(1, LEVELS + 1)]


class World(object):
    def __init__(self, media, store, log=lambda msg: None):
        self.media = media
        self.store = store
        self.log = log
        folder = os.path.join(media, 'world')
        self.lights = raster.read(os.path.join(folder, 'lights.png'), want=1).data
        self.lines = raster.read(os.path.join(folder, 'lines.png'), want=1).data
        classes = raster.read(os.path.join(folder, 'landclass.png'), want=1).data
        self.classes = bytes(classes) + bytes((landclass.OCEAN,))
        self.lights_small = self._downsample(self.lights) + b'\x00'
        self.lines_small = self._lines_small() + b'\x00'
        self.base_id = None
        self.base_attribution = ''
        self.base_pending = False
        self.day = self.night = None
        self.composite = None
        self.composite_time = None
        self.overlays = {}       # name -> array('I') words, CW x CH (+ sentinel)
        self.overlay_rgba = {}   # name -> bytes, for ASCII sampling
        self.weather = None
        self.storms = []
        self.quakes = []
        self.volcanoes = []
        self.masks = {}          # 'fires' / 'lightning' -> CW x CH bytes (+ sentinel), for ASCII
        self.iss = None
        self._tables = None
        self.options = {}

    # ------------------------------------------------------------ static data

    @staticmethod
    def _downsample(data):
        """2:1 in both directions (every other pixel), SW x SH bytes -> CW x CH."""
        return b''.join(bytes(data[y * 2 * SW:(y * 2 + 1) * SW])[::2] for y in range(CH))

    def _lines_small(self):
        """Lines at CW x CH, OR-pooled and thickened by a pixel so that the coarse ASCII
        grid still hits thin borders. Bitwise ORs on whole rows (big ints) keep it fast."""
        rows = []
        for y in range(CH):
            a = int.from_bytes(bytes(self.lines[y * 2 * SW:(y * 2 + 1) * SW]), 'big')
            b = int.from_bytes(bytes(self.lines[(y * 2 + 1) * SW:(y * 2 + 2) * SW]), 'big')
            row = (a | b).to_bytes(SW, 'big')
            pooled = int.from_bytes(row[0::2], 'big') | int.from_bytes(row[1::2], 'big')
            rows.append(pooled | (pooled << 8) | (pooled >> 8))
        mask = (1 << (CW * 8)) - 1
        out = []
        for y in range(CH):
            v = rows[y]
            if y > 0:
                v |= rows[y - 1]
            if y < CH - 1:
                v |= rows[y + 1]
            out.append((v & mask).to_bytes(CW, 'big'))
        return b''.join(out)

    # ------------------------------------------------------------ base map

    def load_base(self, base_id, options):
        """Prepare day and night images for a base map. Returns False when the base map is
        still downloading (Blue Marble is shown meanwhile)."""
        self.options = dict(options)
        img, ok = self._base_image(base_id)
        entry = [b for b in sources.BASEMAPS if b[0] == (base_id if ok else 'bluemarble')][0]
        self.base_attribution = entry[3]
        self.base_id = base_id if ok else 'bluemarble'
        self.base_pending = not ok
        data = img.data
        if options.get('borders'):
            data = self._draw_lines(bytearray(data))
        lights_on = options.get('lights', True)
        bright = options.get('lights_brightness', 70) / 70.0
        darkness = options.get('night_darkness', 80) / 100.0
        night_k = [(1 - 0.9 * darkness) * t for t in NIGHT_TINT]
        day = data
        if lights_on and not options.get('lights_night_only', True):
            day = self._add_lights(data, [0.0, 0.0, 0.0], [c / 255.0 * 0.55 * bright for c in LIGHT_COLOR], keep=True)
        self.day = day
        if options.get('daynight', True):
            light_k = [c / 255.0 * bright for c in LIGHT_COLOR] if lights_on else [0.0, 0.0, 0.0]
            self.night = self._add_lights(data, night_k, light_k)
        else:
            self.night = None
        self.composite = None
        return ok

    def _base_image(self, base_id):
        if base_id in ('atlas', 'atlas_dark'):
            colors = landclass.ATLAS if base_id == 'atlas' else landclass.DARK
            classes = self.classes[:-1]
            small = bytearray(CW * CH * 4)
            for c in range(3):
                small[c::4] = classes.translate(bytes(colors[i][c] if i < len(colors) else 0 for i in range(256)))
            small[3::4] = b'\xff' * (CW * CH)
            return raster.Raster(SW, SH, 4, raster.upsample2(small, CW, CH, 4)), True
        if base_id != 'bluemarble':
            data, _meta = self.store.get(base_id)
            if data:
                try:
                    img = raster.decode(data, want=4)
                    if (img.w, img.h) == (SW, SH):
                        return img, True
                    self.log('base map %s has size %dx%d' % (base_id, img.w, img.h))
                except Exception as error:
                    self.log('base map %s unreadable: %s' % (base_id, error))
        return raster.read(os.path.join(self.media, 'world', 'bluemarble.png'), want=4), base_id == 'bluemarble'

    def _add_lights(self, data, base_k, light_k, keep=False):
        """Per channel: base * base_k + lights * light_k (clamped), via one table per channel."""
        out = bytearray(len(data))
        for c in range(3):
            bk, lk = base_k[c], light_k[c]
            if keep:
                bk = 1.0
            table = b''.join(bytes(min(255, int(b * bk + l * lk + 0.5)) for b in range(256)) for l in range(256))
            out[c::4] = raster.pair_map(bytes(data[c::4]), self.lights, table)
        out[3::4] = b'\xff' * (SW * SH)
        return out

    def _draw_lines(self, data):
        for m in re.finditer(b'[\x01-\xff]', bytes(self.lines)):
            i = m.start()
            r, g, b, a = BORDER if self.lines[i] == 1 else COAST
            p = i * 4
            data[p] = int(data[p] + (r - data[p]) * a)
            data[p + 1] = int(data[p + 1] + (g - data[p + 1]) * a)
            data[p + 2] = int(data[p + 2] + (b - data[p + 2]) * a)
        return data

    # ------------------------------------------------------------ day and night

    def update_composite(self, t):
        """Recompose day and night for time t. Returns the composite as words."""
        if self.night is None:
            words = array('I')
            words.frombytes(bytes(self.day))
            if not raster.LITTLE:
                words.byteswap()
            words.append(0)
            self.composite, self.composite_time = words, t
            return words
        if self._tables is None:
            self._tables = _blend_tables()
        tables = self._tables
        s = sun.Sun(t)
        day, night = self.day, self.night
        out = bytearray(night)
        stride = SW * 4
        xs = (s.lon + 180.0) / 360.0 * SW
        half = SW / 2.0

        def paint(row, a, b, k):
            """Columns [a, b) (any integers, wrapping) of this row at twilight level k."""
            if b <= a:
                return
            if b - a >= SW:
                a, b = 0, SW
            a0 = a % SW
            pieces = [(a0, min(SW, a0 + (b - a)))]
            if a0 + (b - a) > SW:
                pieces.append((0, a0 + (b - a) - SW))
            for p, q in pieces:
                lo, hi = row + p * 4, row + q * 4
                if k == LEVELS:
                    out[lo:hi] = day[lo:hi]
                else:
                    out[lo:hi] = raster.pair_map(bytes(day[lo:hi]), bytes(night[lo:hi]), tables[k])

        for y in range(SH):
            lat = 90.0 - (y + 0.5) * 180.0 / SH
            A, B = s.row(lat)
            widths = []
            for sk in LEVEL_SIN:
                if B < 1e-9:
                    widths.append(half if A >= sk else -1.0)
                    continue
                c = (sk - A) / B
                widths.append(half if c <= -1 else (-1.0 if c >= 1 else math.acos(c) / (2 * math.pi) * SW))
            # widths[k - 1]: half-width (columns) of the region at level k or brighter.
            # Level k fills the ring between that and the next level's half-width.
            row = y * stride
            for k in range(1, LEVELS + 1):
                outer = widths[k - 1]
                if outer < 0:
                    break
                outer = min(outer, half)
                inner = widths[k] if k < LEVELS else -1.0
                if inner < 0:
                    paint(row, int(round(xs - outer)), int(round(xs + outer)), k)
                else:
                    inner = min(inner, half)
                    paint(row, int(round(xs + inner)), int(round(xs + outer)), k)
                    paint(row, int(round(xs - outer)), int(round(xs - inner)), k)
        words = array('I')
        words.frombytes(bytes(out))
        if not raster.LITTLE:
            words.byteswap()
        words.append(0)
        self.composite, self.composite_time = words, t
        return words

    def sample_color(self, idx2, daylight):
        """Base colour at a base-map pixel for the ASCII image mode, with day/night."""
        p = idx2 * 4
        d = self.day
        if self.night is None or daylight >= 1:
            return (d[p], d[p + 1], d[p + 2])
        n = self.night
        if daylight <= 0:
            return (n[p], n[p + 1], n[p + 2])
        return (int(n[p] + (d[p] - n[p]) * daylight), int(n[p + 1] + (d[p + 1] - n[p + 1]) * daylight),
                int(n[p + 2] + (d[p + 2] - n[p + 2]) * daylight))

    # ------------------------------------------------------------ weather

    def set_overlay(self, name, img):
        self.overlays[name] = img.words()
        self.overlay_rgba[name] = bytes(img.data) + b'\x00\x00\x00\x00'

    def drop_overlay(self, name):
        self.overlays.pop(name, None)
        self.overlay_rgba.pop(name, None)
        self.masks.pop(name, None)

    def load_feed(self, name):
        """Turn a stored feed into overlay data. Returns True when something changed."""
        data, _meta = self.store.get(name)
        if not data:
            return False
        if name == 'clouds':
            self.set_overlay('clouds', overlays.clouds_image(data))
        elif name == 'precip':
            self.set_overlay('precip', overlays.precipitation_image(data))
        elif name == 'weather':
            lats, lons = overlays.grid_points()
            self.weather = overlays.parse_open_meteo(json.loads(data.decode('utf-8')), lats, lons)
            self.set_overlay('temp', overlays.temperature_image(self.weather))
        elif name in ('fires', 'lightning'):
            img, mask = (events.fire_overlay if name == 'fires' else events.lightning_overlay)(data)
            self.overlays[name] = img.words()
            self.masks[name] = bytes(mask) + b'\x00'
        elif name == 'quakes':
            self.quakes = events.parse_quakes(data)
        elif name == 'volcanoes':
            self.volcanoes = events.parse_volcanoes(data)
        elif name == 'iss':
            self.iss = events.Orbit(data.decode('ascii', 'replace'))
        elif name == 'storms':
            self.storms = [s for s in json.loads(data.decode('utf-8'))
                           if s.get('lat') is not None and s.get('lon') is not None]
        return True
