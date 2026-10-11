"""Infrared cloud overlay: one small image for the whole view, clouds only. No Kodi imports.

Infrared satellite pixels are 2-4 km across, so map tiles from NOAA's WMS break down when
zoomed in (blocky bins from about zoom 8, empty tiles from zoom 12). Instead, one GetMap
covers the screen at roughly the satellite's own resolution, warm (clear) pixels are made
transparent so only cold cloud tops remain, and Kodi stretches the result smoothly."""

import math

from . import net, png
from .geo import world_size

BASE = 'https://nowcoast.noaa.gov/geoserver/observations/satellite/ows'
# layer, style, km per pixel, (clear below, opaque above): infrared brightness 0-255, brighter
# = colder. The products use different scales; thresholds were measured on clear ground and
# cloud bands in each (GOES clear land 73-92, global clear land 11-47).
GOES = ('goes_longwave_imagery', 'goes-lir', 2.0, (100, 190))
GLOBAL = ('global_longwave_imagery_mosaic', 'reflectance', 4.0, (60, 180))
GOES_MIN_ZOOM = 6  # zoomed further out, the view is wider than GOES's regional coverage
HALF = math.pi * 6378137.0                                     # EPSG:3857 half extent (m)
MARGIN_PX = 96                                                 # overscan so drift never shows an edge


def in_goes_coverage(lat, lon):
    """GOES East/West regional imagery covers roughly the Americas north of the equator."""
    return 0.0 <= lat <= 70.0 and -170.0 <= lon <= -40.0


def product(view):
    if view.zoom >= GOES_MIN_ZOOM and in_goes_coverage(view.lat, view.lon):
        return GOES
    return GLOBAL


def request(view):
    """(url, screen rectangle (x, y, w, h), thresholds) for the cloud image covering view."""
    ox, oy = view.origin
    size = float(world_size(view.zoom))
    x0, y0 = ox - MARGIN_PX, max(0.0, oy - MARGIN_PX)
    x1, y1 = ox + view.width + MARGIN_PX, min(size, oy + view.height + MARGIN_PX)
    metres_per_px = 2 * HALF / size

    def mx(px):
        return px * metres_per_px - HALF

    def my(py):
        return HALF - py * metres_per_px

    layer, style, km, thresholds = product(view)
    width_km = (x1 - x0) * metres_per_px * math.cos(math.radians(view.lat)) / 1000.0
    w = int(max(24, min(384, round(width_km / km))))
    h = int(max(16, round(w * (y1 - y0) / (x1 - x0))))
    url = (BASE + '?service=WMS&version=1.1.1&request=GetMap&layers=%s&styles=%s&srs=EPSG:3857'
           '&bbox=%.1f,%.1f,%.1f,%.1f&width=%d&height=%d&format=image/png&transparent=true'
           % (layer, style, mx(x0), my(y1), mx(x1), my(y0), w, h))
    rect = (int(round(x0 - ox)), int(round(y0 - oy)), int(round(x1 - x0)), int(round(y1 - y0)))
    return url, rect, thresholds


def clouds_only(width, height, pixels, thresholds):
    """Keep the cold (bright) pixels as white cloud with matching opacity."""
    clear_below, opaque_above = thresholds
    span = float(opaque_above - clear_below)
    out = []
    for r, g, b, a in pixels:
        if not a:
            out.append((255, 255, 255, 0))
            continue
        v = (r * 299 + g * 587 + b * 114) // 1000
        f = (v - clear_below) / span
        f = 0.0 if f <= 0 else (1.0 if f >= 1 else f)
        out.append((255, 255, 255, int(f * 230 * a / 255)))
    return png.encode_rgba(width, height, out)


def fetch(view):
    """-> (png bytes of white clouds on transparent, screen rectangle)."""
    url, rect, thresholds = request(view)
    w, h, pixels = png.decode(net.fetch(url, timeout=20))
    return clouds_only(w, h, pixels, thresholds), rect


