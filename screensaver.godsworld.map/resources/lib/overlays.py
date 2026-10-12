"""Weather overlays in geographic space: equirectangular RGBA images and gridded fields.
No Kodi imports.

Everything here is in longitude/latitude, before any projection, so the same overlay
lines up on every projection, the globe and the ASCII grid."""

import math
import random
import re
from array import array

from . import raster

OW, OH = 1024, 512   # overlay image size (0.35 degree pixels)

# ---------------------------------------------------------------- temperature colours

TEMP_MIN, TEMP_MAX = -40.0, 45.0
TEMP_STOPS = [(-40, (120, 40, 160)), (-25, (60, 60, 200)), (-10, (40, 140, 230)), (0, (120, 220, 235)),
              (8, (90, 200, 120)), (16, (190, 220, 80)), (24, (250, 200, 50)), (32, (245, 120, 40)),
              (40, (210, 40, 40)), (45, (140, 10, 30))]


def temperature_color(t):
    if t <= TEMP_STOPS[0][0]:
        return TEMP_STOPS[0][1]
    for (t0, c0), (t1, c1) in zip(TEMP_STOPS, TEMP_STOPS[1:]):
        if t <= t1:
            f = (t - t0) / float(t1 - t0)
            return tuple(int(c0[i] + (c1[i] - c0[i]) * f + 0.5) for i in range(3))
    return TEMP_STOPS[-1][1]


# 256 temperature steps, so a whole row is coloured with bytes.translate.
_T_TABLES = [bytes(temperature_color(TEMP_MIN + (TEMP_MAX - TEMP_MIN) * i / 255.0)[c] for i in range(256))
             for c in range(3)]


# ---------------------------------------------------------------- gridded fields

class Grid(object):
    """Values on a regular lat/lon grid (lats descending, lons ascending and wrapping)."""

    def __init__(self, lats, lons, values):
        self.lats, self.lons, self.values = lats, lons, values  # values[j][i] (lat j, lon i)
        self.dlat = lats[0] - lats[1]
        self.dlon = lons[1] - lons[0]

    def _row_weights(self, lat):
        f = (self.lats[0] - lat) / self.dlat
        f = max(0.0, min(len(self.lats) - 1.0, f))
        j = min(int(f), len(self.lats) - 2)
        return j, f - j

    def row(self, lat):
        """The field along one parallel, at the grid's longitudes."""
        j, f = self._row_weights(lat)
        a, b = self.values[j], self.values[j + 1]
        return [x + (y - x) * f for x, y in zip(a, b)]

    def sample(self, lon, lat):
        j, f = self._row_weights(lat)
        x = ((lon - self.lons[0]) % 360.0) / self.dlon
        i = int(x) % len(self.lons)
        g = x - int(x)
        i2 = (i + 1) % len(self.lons)
        r0, r1 = self.values[j], self.values[j + 1]
        top = r0[i] + (r0[i2] - r0[i]) * g
        bottom = r1[i] + (r1[i2] - r1[i]) * g
        return top + (bottom - top) * f


class Weather(object):
    """Temperature (deg C) and wind (u, v in m/s, plus speed and direction) fields."""

    def __init__(self, temp, u, v, valid_time=None):
        self.temp, self.u, self.v = temp, u, v
        self.valid_time = valid_time

    def wind(self, lon, lat):
        return self.u.sample(lon, lat), self.v.sample(lon, lat)


def grid_points(lat_step=10, lon_step=15, lat_max=80):
    lats = list(range(lat_max, -lat_max - 1, -lat_step))
    lons = list(range(-180, 180, lon_step))
    return lats, lons


def parse_open_meteo(docs, lats, lons):
    """Open-Meteo multi-location JSON (a list, one entry per point, lat-major) -> Weather."""
    n = len(lons)
    temp, u, v = [], [], []
    valid = None
    for j in range(len(lats)):
        tr, ur, vr = [], [], []
        for i in range(n):
            cur = docs[j * n + i].get('current') or {}
            t = cur.get('temperature_2m')
            speed = (cur.get('wind_speed_10m') or 0.0) / 3.6     # km/h -> m/s
            direction = cur.get('wind_direction_10m') or 0.0     # degrees, wind FROM
            valid = valid or cur.get('time')
            rad = math.radians(direction)
            tr.append(t if t is not None else float('nan'))
            ur.append(-speed * math.sin(rad))   # towards east
            vr.append(-speed * math.cos(rad))   # towards north
        temp.append(tr)
        u.append(ur)
        v.append(vr)
    _fill_gaps(temp)
    return Weather(Grid(lats, lons, temp), Grid(lats, lons, u), Grid(lats, lons, v), valid)


def _fill_gaps(rows):
    """Replace missing values with the mean of their row (rare; keeps the field drawable)."""
    for row in rows:
        good = [x for x in row if x == x]
        mean = sum(good) / len(good) if good else 0.0
        for i, x in enumerate(row):
            if x != x:
                row[i] = mean


def temperature_image(weather, alpha=210):
    """RGBA OW x OH image of the temperature field (built at half size, then doubled)."""
    w, h = OW // 2, OH // 2
    grid = weather.temp
    lons = grid.lons
    nl = len(lons)
    out = bytearray(w * h * 4)
    span = TEMP_MAX - TEMP_MIN
    # Column positions on the grid, shared by every row.
    cols = []
    for x in range(w):
        lon = -180.0 + (x + 0.5) * 360.0 / w
        g = ((lon - lons[0]) % 360.0) / grid.dlon
        i = int(g) % nl
        cols.append((i, (i + 1) % nl, g - int(g)))
    for y in range(h):
        lat = 90.0 - (y + 0.5) * 180.0 / h
        row = grid.row(lat)
        q = bytes(max(0, min(255, int((row[i] + (row[i2] - row[i]) * f - TEMP_MIN) / span * 255)))
                  for i, i2, f in cols)
        start = y * w * 4
        for c in range(3):
            out[start + c:start + w * 4:4] = q.translate(_T_TABLES[c])
        out[start + 3:start + w * 4:4] = bytes((alpha,)) * w
    return raster.Raster(OW, OH, 4, raster.upsample2(out, w, h, 4))


# ---------------------------------------------------------------- satellite products

# Infrared brightness (brighter = colder cloud tops) -> cloud opacity, for NOAA nowCOAST's
# global longwave mosaic ('reflectance' style). Half the planet reads above 104, so only
# clearly cold tops count: clear below 125, opaque above 205.
CLOUD_CLEAR, CLOUD_OPAQUE = 125, 205
_CLOUD_ALPHA = bytes(0 if i <= CLOUD_CLEAR else (235 if i >= CLOUD_OPAQUE else
                     int(235 * ((i - CLOUD_CLEAR) / float(CLOUD_OPAQUE - CLOUD_CLEAR)) ** 1.2))
                     for i in range(256))
_CLOUD_GREY = bytes(int(200 + 55 * min(1.0, max(0.0, (i - CLOUD_CLEAR) / float(CLOUD_OPAQUE - CLOUD_CLEAR))))
                    for i in range(256))


def clouds_image(png_bytes):
    """nowCOAST infrared PNG (grey + alpha) -> RGBA white clouds, OW x OH."""
    img = raster.decode(png_bytes, want=4)
    grey = bytes(img.data[0::4])
    alpha_in = bytes(img.data[3::4])
    out = bytearray(len(img.data))
    shade = grey.translate(_CLOUD_GREY)
    out[0::4] = shade
    out[1::4] = shade
    out[2::4] = shade
    alpha = grey.translate(_CLOUD_ALPHA)
    # The mosaic fills some gaps between satellites with flat saturated blocks; real cloud
    # tops are never that uniform, so long runs of 255, and a 4-pixel rim around them
    # (the block's soft edge), are treated as missing data.
    mask = bytearray(len(grey))
    for m in re.finditer(b'\xff{6,}', grey):
        mask[m.start():m.end()] = b'\x01' * (m.end() - m.start())
    if any(mask):
        w = img.w
        rows = [int.from_bytes(bytes(mask[y * w:(y + 1) * w]), 'big') for y in range(img.h)]
        wide = [r | r << 8 | r << 16 | r << 24 | r << 32 | r >> 8 | r >> 16 | r >> 24 | r >> 32 for r in rows]
        full = (1 << (8 * w)) - 1
        grown = bytearray()
        for y in range(img.h):
            v = 0
            for k in range(max(0, y - 4), min(img.h, y + 5)):
                v |= wide[k]
            grown += (v & full).to_bytes(w, 'big')
        alpha = raster.pair_map(alpha, bytes(grown), _masked_table())
    # Where the source has no data, keep it transparent: min(alpha, source alpha).
    out[3::4] = raster.pair_map(bytes(alpha), alpha_in, _min_table())
    return raster.Raster(img.w, img.h, 4, out)


_TABLES = {}


def _masked_table():
    """pair_map table: the value where the mask byte is 0, else 0."""
    if 'masked' not in _TABLES:
        _TABLES['masked'] = raster.pair_table(lambda a, m: 0 if m else a)
    return _TABLES['masked']


def _min_table():
    if 'min' not in _TABLES:
        _TABLES['min'] = raster.pair_table(min)
    return _TABLES['min']


def precipitation_image(png_bytes):
    """NASA GIBS IMERG precipitation rate PNG, recoloured from its rainbow scale to a calmer
    blue-to-white one (lilac for snow) that leaves the map readable. The source uses a few
    dozen colours, so each distinct colour is mapped once and the image through a dict."""
    img = raster.decode(png_bytes, want=4)
    words = img.words()
    mapping = {}
    for word in set(words):
        r, g, b, a = word & 255, (word >> 8) & 255, (word >> 16) & 255, word >> 24
        mapping[word] = _rain_word(r, g, b, a)
    out = raster.Raster(img.w, img.h, 4, None)
    recoloured = array('I', map(mapping.__getitem__, words[:-1]))
    if not raster.LITTLE:
        recoloured.byteswap()
    out.data = bytearray(recoloured.tobytes())
    return out


RAIN_RAMP = [(70, 130, 230, 120), (60, 170, 250, 170), (120, 215, 255, 210), (235, 245, 255, 235)]
SNOW = (215, 190, 255, 190)


def _rain_word(r, g, b, a):
    if a < 20:
        return 0
    hi, lo = max(r, g, b), min(r, g, b)
    if hi == lo:
        hue = 0.0
    elif hi == r:
        hue = (60.0 * (g - b) / (hi - lo)) % 360
    elif hi == g:
        hue = 60.0 * (b - r) / (hi - lo) + 120
    else:
        hue = 60.0 * (r - g) / (hi - lo) + 240
    if 170 <= hue <= 300:     # IMERG draws snow in blues and purples
        c = SNOW
    else:                     # rain: green (light) .. yellow .. red (heavy)
        t = max(0.0, min(1.0, (130.0 - min(hue, 130.0)) / 130.0))
        c = RAIN_RAMP[min(3, int(t * 4))]
    alpha = c[3] * a // 255
    return c[0] | c[1] << 8 | c[2] << 16 | alpha << 24


def rain_intensity(r, g, b, a):
    """0 dry .. 3 heavy, from an IMERG colour (blue light, green/yellow moderate, red heavy)."""
    if a < 40:
        return 0
    if r > 180 and g < 140:
        return 3
    if r > 150 or g > 150:
        return 2
    return 1


# ---------------------------------------------------------------- wind particles

class Particles(object):
    """Points drifting with the wind, in lon/lat. Drawn by Kodi as small dots that slide
    between positions, so they move smoothly at the display frame rate."""

    def __init__(self, count, seed=3):
        self.rng = random.Random(seed)
        self.items = [self._spawn() for _ in range(count)]

    def _spawn(self):
        lat = math.degrees(math.asin(self.rng.uniform(-0.97, 0.97)))  # uniform over the sphere
        return [self.rng.uniform(-180, 180), lat, self.rng.randint(8, 40), True]  # lon, lat, life, new

    def step(self, weather, seconds, speedup=7000.0):
        """Advance by `seconds` of screen time. Real winds would barely move at world scale,
        so motion is sped up `speedup` times (a 10 m/s wind crosses ~6 degrees a second)."""
        out = []
        for p in self.items:
            lon, lat, life, _new = p
            if life <= 0:
                p[:] = self._spawn()
                out.append(p)
                continue
            u, v = weather.wind(lon, lat)
            k = seconds * speedup / 111320.0
            dlat = v * k
            dlon = u * k / max(0.15, math.cos(math.radians(lat)))
            lat = max(-85.0, min(85.0, lat + dlat))
            lon = (lon + dlon + 540.0) % 360.0 - 180.0
            p[:] = [lon, lat, life - 1, False]
            out.append(p)
        return out

    def speed(self, weather, p):
        u, v = weather.wind(p[0], p[1])
        return math.hypot(u, v)
