"""Web Mercator math for 256 px slippy-map tiles and WMS bounding boxes. No Kodi imports."""

import math

TILE = 256
MAX_LAT = 85.05112878
EARTH_RADIUS_KM = 6371.0088
HALF_WORLD_M = math.pi * 6378137.0   # EPSG:3857 half extent

# Rough coverage boxes (south, west, north, east).
CONUS = (24.0, -125.5, 50.0, -66.0)
IEM_NEXRAD = (23.0, -127.0, 51.0, -65.0)   # the IEM composite covers CONUS only
HRRR = (21.0, -134.0, 53.0, -60.0)


def clamp(value, low, high):
    return max(low, min(high, value))


def inside(lat, lon, box):
    s, w, n, e = box
    return s <= lat <= n and w <= lon <= e


def world_size(zoom):
    return TILE * (1 << zoom)


def to_pixel(lat, lon, zoom):
    """Global pixel coordinates of lat/lon at zoom (origin top-left, 180W 85N)."""
    size = world_size(zoom)
    lat = clamp(lat, -MAX_LAT, MAX_LAT)
    x = (lon + 180.0) / 360.0 * size
    s = math.sin(math.radians(lat))
    y = (0.5 - math.log((1 + s) / (1 - s)) / (4 * math.pi)) * size
    return x, y


def from_pixel(x, y, zoom):
    size = world_size(zoom)
    lon = x / size * 360.0 - 180.0
    n = math.pi - 2.0 * math.pi * y / size
    lat = math.degrees(math.atan(math.sinh(n)))
    return lat, wrap_lon(lon)


def wrap_lon(lon):
    return ((lon + 180.0) % 360.0) - 180.0


def pixel_to_mercator(x, y, zoom):
    """Global pixel -> EPSG:3857 metres."""
    span = 2 * HALF_WORLD_M / world_size(zoom)
    return -HALF_WORLD_M + x * span, HALF_WORLD_M - y * span


def haversine_km(lat1, lon1, lat2, lon2):
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp = p2 - p1
    dl = math.radians(lon2 - lon1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * EARTH_RADIUS_KM * math.asin(math.sqrt(min(1.0, a)))


def offset_point(lat, lon, bearing_deg, km):
    """The point km away from lat/lon along bearing (degrees from north)."""
    d = km / EARTH_RADIUS_KM
    b = math.radians(bearing_deg)
    p1, l1 = math.radians(lat), math.radians(lon)
    p2 = math.asin(math.sin(p1) * math.cos(d) + math.cos(p1) * math.sin(d) * math.cos(b))
    l2 = l1 + math.atan2(math.sin(b) * math.sin(d) * math.cos(p1), math.cos(d) - math.sin(p1) * math.sin(p2))
    return math.degrees(p2), wrap_lon(math.degrees(l2))


class Viewport(object):
    """What the screen shows: a centre, a zoom and a screen size in pixels."""

    def __init__(self, lat, lon, zoom, width=1920, height=1080):
        self.lat = clamp(lat, -MAX_LAT, MAX_LAT)
        self.lon = wrap_lon(lon)
        self.zoom = zoom
        self.width = width
        self.height = height

    def key(self):
        return '%.4f_%.4f_z%d_%dx%d' % (self.lat, self.lon, self.zoom, self.width, self.height)

    @property
    def origin(self):
        cx, cy = to_pixel(self.lat, self.lon, self.zoom)
        return cx - self.width / 2.0, cy - self.height / 2.0

    def screen_xy(self, lat, lon):
        """Screen position of lat/lon, choosing the world copy nearest the view."""
        ox, oy = self.origin
        x, y = to_pixel(lat, lon, self.zoom)
        size = world_size(self.zoom)
        x -= ox
        center = self.width / 2.0
        if x - center > size / 2.0:
            x -= size
        elif center - x > size / 2.0:
            x += size
        return x, y - oy

    def tiles_at(self, max_zoom):
        """[(z, tile_x, tile_y, screen_x, screen_y, size)] for a source limited to max_zoom.

        Above max_zoom the source's tiles are drawn enlarged (2x per extra level)."""
        z = min(self.zoom, max_zoom)
        size = TILE * (1 << (self.zoom - z))
        ox, oy = self.origin
        n = 1 << z
        out = []
        for ty in range(int(math.floor(oy / size)), int(math.floor((oy + self.height - 1) / size)) + 1):
            if not 0 <= ty < n:
                continue
            for tx in range(int(math.floor(ox / size)), int(math.floor((ox + self.width - 1) / size)) + 1):
                out.append((z, tx % n, ty, int(round(tx * size - ox)), int(round(ty * size - oy)), size))
        return out

    def max_tiles(self, max_zoom=99):
        size = TILE * (1 << max(0, self.zoom - max_zoom))
        cols = int(math.ceil(self.width / float(size))) + 1
        rows = int(math.ceil(self.height / float(size))) + 1
        return cols * rows

    def bbox3857(self):
        """(minx, miny, maxx, maxy) of the screen in EPSG:3857 metres, for WMS GetMap."""
        ox, oy = self.origin
        x0, y1 = pixel_to_mercator(ox, oy, self.zoom)
        x1, y0 = pixel_to_mercator(ox + self.width, oy + self.height, self.zoom)
        return x0, y0, x1, y1

    def bbox(self):
        """(south, west, north, east) of the screen."""
        ox, oy = self.origin
        north, west = from_pixel(ox, max(0, oy), self.zoom)
        size = world_size(self.zoom)
        south, east = from_pixel(ox + self.width, min(size, oy + self.height), self.zoom)
        if self.width >= size:
            west, east = -180.0, 180.0
        return south, west, north, east

    def lonlat_to_screen(self, lon, lat):
        return self.screen_xy(lat, lon)

    def km_per_pixel(self):
        return 2 * math.pi * EARTH_RADIUS_KM * math.cos(math.radians(self.lat)) / world_size(self.zoom)
