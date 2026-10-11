"""Web Mercator math for 256 px slippy-map tiles. No Kodi imports."""

import math

TILE = 256
MAX_LAT = 85.05112878
EARTH_RADIUS_KM = 6371.0088


def clamp(value, low, high):
    return max(low, min(high, value))


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


def mercator_bounds(x, y, zoom):
    """EPSG:3857 bbox (minx, miny, maxx, maxy) of tile x/y, for WMS GetMap."""
    half = math.pi * 6378137.0
    span = 2 * half / (1 << zoom)
    minx = -half + x * span
    maxy = half - y * span
    return minx, maxy - span, minx + span, maxy


def haversine_km(lat1, lon1, lat2, lon2):
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp = p2 - p1
    dl = math.radians(lon2 - lon1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * EARTH_RADIUS_KM * math.asin(math.sqrt(min(1.0, a)))


class Viewport(object):
    """What the screen shows: a center, a zoom and a screen size in pixels."""

    def __init__(self, lat, lon, zoom, width=1920, height=1080):
        self.lat = clamp(lat, -MAX_LAT, MAX_LAT)
        self.lon = wrap_lon(lon)
        self.zoom = zoom
        self.width = width
        self.height = height

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

    def contains(self, x, y, margin=0):
        return -margin <= x <= self.width + margin and -margin <= y <= self.height + margin

    def pan(self, dx, dy):
        """Move the center by dx/dy screen pixels."""
        cx, cy = to_pixel(self.lat, self.lon, self.zoom)
        size = world_size(self.zoom)
        half_h = self.height / 2.0
        cy = clamp(cy + dy, min(half_h, size / 2.0), max(size - half_h, size / 2.0))
        self.lat, self.lon = from_pixel(cx + dx, cy, self.zoom)

    def tiles(self):
        """(slot_x, slot_y, tile_x, tile_y, screen_x, screen_y) for every visible tile."""
        ox, oy = self.origin
        n = 1 << self.zoom
        first_x = int(math.floor(ox / TILE))
        first_y = int(math.floor(oy / TILE))
        last_x = int(math.floor((ox + self.width - 1) / TILE))
        last_y = int(math.floor((oy + self.height - 1) / TILE))
        out = []
        for j, ty in enumerate(range(first_y, last_y + 1)):
            for i, tx in enumerate(range(first_x, last_x + 1)):
                sx = int(round(tx * TILE - ox))
                sy = int(round(ty * TILE - oy))
                if 0 <= ty < n:
                    out.append((i, j, tx % n, ty, sx, sy))
        return out

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

    def bbox(self):
        """(south, west, north, east) of the screen; west may exceed east across the antimeridian."""
        ox, oy = self.origin
        north, west = from_pixel(ox, max(0, oy), self.zoom)
        size = world_size(self.zoom)
        south, east = from_pixel(ox + self.width, min(size, oy + self.height), self.zoom)
        if self.width >= size:
            west, east = -180.0, 180.0
        return south, west, north, east

    def radius_km(self):
        """Distance from the center to a screen corner."""
        if self.width >= world_size(self.zoom):
            return EARTH_RADIUS_KM * math.pi
        ox, oy = self.origin
        lat, lon = from_pixel(ox, max(0.0, oy), self.zoom)
        return haversine_km(self.lat, self.lon, lat, lon)

    def max_tiles(self):
        cols = int(math.ceil(self.width / float(TILE))) + 1
        rows = int(math.ceil(self.height / float(TILE))) + 1
        return cols * rows
