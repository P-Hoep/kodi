"""Point events and hazard rasters: earthquakes, erupting volcanoes, wildfires, lightning
and the International Space Station. No Kodi imports.

Earthquakes and volcanoes are lists of points, drawn as symbols at their projected screen
positions (crisp on any projection). Fires and lightning come as images and are treated
like the weather overlays: geographic rasters reprojected through the lookup tables."""

import json
import math
import time
from datetime import datetime

from . import raster

OW, OH = 1024, 512


# ---------------------------------------------------------------- parsing

def parse_quakes(data):
    """USGS GeoJSON summary feed -> [{lat, lon, mag, time, place}] (time in seconds)."""
    doc = json.loads(data.decode('utf-8'))
    out = []
    for f in doc.get('features', []):
        p = f.get('properties') or {}
        coords = (f.get('geometry') or {}).get('coordinates') or []
        if len(coords) < 2 or p.get('mag') is None:
            continue
        out.append({'lon': coords[0], 'lat': coords[1], 'mag': float(p['mag']),
                    'time': (p.get('time') or 0) / 1000.0, 'place': p.get('place') or ''})
    out.sort(key=lambda q: -q['mag'])
    return out


def parse_volcanoes(data):
    """Smithsonian GVP WFS GeoJSON of continuing eruptions -> [{name, lat, lon, since}]."""
    doc = json.loads(data.decode('utf-8'))
    out, seen = [], set()
    for f in doc.get('features', []):
        p = f.get('properties') or {}
        name = p.get('VolcanoName') or ''
        lat, lon = p.get('LatitudeDecimal'), p.get('LongitudeDecimal')
        if lat is None or lon is None or name in seen:
            continue
        seen.add(name)
        out.append({'name': name, 'lat': float(lat), 'lon': float(lon), 'since': p.get('StartDateYear')})
    return out


def _colored(mask, rgb, alpha):
    """Mask (non-zero = on) -> RGBA bytes in one colour."""
    on = bytes(alpha if i else 0 for i in range(256))
    a = mask.translate(on)
    out = bytearray(len(mask) * 4)
    out[0::4] = bytes((rgb[0],)) * len(mask)
    out[1::4] = bytes((rgb[1],)) * len(mask)
    out[2::4] = bytes((rgb[2],)) * len(mask)
    out[3::4] = a
    return out


FIRE_RGB = (255, 110, 30)
LIGHTNING_RGB = (255, 250, 170)


FIRE_BLOCK = 8          # source pixels per hotspot block side (2048 wide: about 1.4 degrees)
FIRE_MIN = 8            # lit pixels in a block to count as a hotspot (about two detections)
FIRE_STRONG = 16        # ... and as a strong one (shown in ASCII)


def fire_overlay(png_bytes):
    """NASA VIIRS thermal anomalies (2048 x 1024; NASA draws each detection as a 2 x 2 dot)
    -> (RGBA overlay OW x OH, ASCII mask OW x OH).

    Tens of thousands of detections a day would paint whole continents, so detections are
    counted in blocks of about 1.4 degrees and only blocks with a couple of them show, as
    one small dot that goes from orange to yellow as the block gets busier."""
    img = raster.decode(png_bytes, want=4)
    lit = bytes(img.data[3::4]).translate(bytes(0 if i < 128 else 1 for i in range(256)))
    w, h = img.w, img.h
    n = FIRE_BLOCK
    bw, bh = w // n, h // n
    scale = OW // bw           # overlay pixels per block side
    out = bytearray(OW * OH * 4)
    mask = bytearray(OW * OH)
    for by in range(bh):
        band = [lit[(by * n + r) * w:(by * n + r + 1) * w] for r in range(n)]
        for bx in range(bw):
            count = sum(row[bx * n:(bx + 1) * n].count(1) for row in band)
            if count < FIRE_MIN:
                continue
            t = min(1.0, (count - FIRE_MIN) / 40.0)
            rgb = (255, int(110 + 120 * t), int(30 + 60 * t))
            cx, cy = bx * scale + scale // 2 - 1, by * scale + scale // 2 - 1
            for dy in (0, 1):
                for dx in (0, 1):
                    i = ((cy + dy) * OW + cx + dx) * 4
                    out[i:i + 4] = bytes((rgb[0], rgb[1], rgb[2], 240))
            if count >= FIRE_STRONG:
                for dy in range(scale):
                    start = (by * scale + dy) * OW + bx * scale
                    mask[start:start + scale] = b'\x01' * scale
    return raster.Raster(OW, OH, 4, out), bytes(mask)


def lightning_overlay(png_bytes):
    """NOAA nowCOAST lightning strike density (OW x OH, transparent where no strikes) ->
    (RGBA overlay, mask)."""
    img = raster.decode(png_bytes, want=4)
    mask = bytes(img.data[3::4])
    return raster.Raster(img.w, img.h, 4, _colored(mask, LIGHTNING_RGB, 230)), mask


# ---------------------------------------------------------------- the ISS

def _gmst(jd_ut1):
    """Greenwich mean sidereal time in radians (IAU-82)."""
    t = (jd_ut1 - 2451545.0) / 36525.0
    sec = 67310.54841 + (876600.0 * 3600 + 8640184.812866) * t + 0.093104 * t * t - 6.2e-6 * t ** 3
    return math.radians((sec % 86400) / 240.0)


class Orbit(object):
    """A satellite from two-line elements, propagated with the bundled sgp4."""

    def __init__(self, tle_text):
        from sgp4.api import Satrec
        lines = [l.rstrip() for l in tle_text.splitlines() if l.strip()]
        l1 = next(l for l in lines if l.startswith('1 '))
        l2 = next(l for l in lines if l.startswith('2 '))
        self.sat = Satrec.twoline2rv(l1, l2)

    def position(self, t=None):
        """-> (lat, lon) in degrees at Unix time t, or None if propagation fails."""
        from sgp4.api import jday
        now = datetime.utcfromtimestamp(time.time() if t is None else t)
        jd, fr = jday(now.year, now.month, now.day, now.hour, now.minute, now.second + now.microsecond / 1e6)
        err, r, _v = self.sat.sgp4(jd, fr)
        if err:
            return None
        g = _gmst(jd + fr)
        x = r[0] * math.cos(g) + r[1] * math.sin(g)
        y = -r[0] * math.sin(g) + r[1] * math.cos(g)
        lon = math.degrees(math.atan2(y, x))
        lat = math.degrees(math.atan2(r[2], math.hypot(x, y) * (1 - 0.00669437999014)))
        return lat, lon


# ---------------------------------------------------------------- map symbols

_SPRITES = {}


def _ring(radius, width, rgb, alpha):
    key = ('ring', radius, width, rgb, alpha)
    if key not in _SPRITES:
        px = []
        r = int(math.ceil(radius + width))
        for dy in range(-r, r + 1):
            for dx in range(-r, r + 1):
                d = math.hypot(dx, dy)
                edge = width / 2.0 - abs(d - radius)
                if edge > -0.5:
                    a = int(alpha * max(0.0, min(1.0, edge + 0.5)))
                    if a:
                        px.append((dx, dy, rgb[0], rgb[1], rgb[2], a))
        _SPRITES[key] = px
    return _SPRITES[key]


def _triangle(size, rgb, glow=None):
    key = ('tri', size, rgb, glow)
    if key not in _SPRITES:
        px = []
        h = size
        for dy in range(-h, 2):
            half = (dy + h) * 0.62
            for dx in range(-int(half) - 2, int(half) + 3):
                inside = abs(dx) <= half and dy <= 0
                rim = abs(dx) <= half + 1.5 and dy <= 1
                if inside:
                    px.append((dx, dy, rgb[0], rgb[1], rgb[2], 255))
                elif rim:
                    px.append((dx, dy, 20, 10, 5, 200))
        if glow:
            # a glowing plume above the crater
            for dy in range(-h - 7, -h + 1):
                for dx in range(-4, 5):
                    d = math.hypot(dx, (dy + h + 3) * 0.8)
                    if d < 4:
                        px.append((dx, dy, glow[0], glow[1], glow[2], int(230 * (1 - d / 4.0))))
        _SPRITES[key] = px
    return _SPRITES[key]


def quake_color(age_s):
    if age_s < 3600:
        return (255, 60, 40)
    if age_s < 6 * 3600:
        return (255, 140, 40)
    return (255, 210, 90)


def quake_radius(mag):
    return 3.0 + max(0.0, mag - 2.5) * 3.2


class Canvas(object):
    """A transparent RGBA image the symbols are stamped into."""

    def __init__(self, w, h):
        self.w, self.h = w, h
        self.data = bytearray(w * h * 4)
        self.empty = True

    def stamp(self, x, y, sprite):
        w, h, data = self.w, self.h, self.data
        x, y = int(round(x)), int(round(y))
        for dx, dy, r, g, b, a in sprite:
            px, py = x + dx, y + dy
            if 0 <= px < w and 0 <= py < h:
                i = (py * w + px) * 4
                if a > data[i + 3]:
                    data[i:i + 4] = bytes((r, g, b, a))
        self.empty = False

    def png(self):
        return raster.encode_rgba(self.w, self.h, bytes(self.data), level=1)


def draw_symbols(canvas_a, canvas_b, scale, quakes, volcanoes, to_xy, now):
    """Stamp quakes and volcanoes into two phases that Kodi alternates: quake rings throb
    outwards, volcanoes glow."""
    s = max(0.5, scale)
    for v in volcanoes:
        p = to_xy(v['lon'], v['lat'])
        if p is None:
            continue
        size = max(6, int(11 * s))
        canvas_a.stamp(p[0], p[1], _triangle(size, (230, 60, 30)))
        canvas_b.stamp(p[0], p[1], _triangle(size, (255, 150, 40), glow=(255, 220, 120)))
    for q in quakes:
        p = to_xy(q['lon'], q['lat'])
        if p is None:
            continue
        r = quake_radius(q['mag']) * s
        rgb = quake_color(now - q['time'])
        width = max(1.5, 2.2 * s)
        canvas_a.stamp(p[0], p[1], _ring(round(r, 1), round(width, 1), rgb, 240))
        canvas_b.stamp(p[0], p[1], _ring(round(r * 1.7, 1), round(width * 0.8, 1), rgb, 120))
