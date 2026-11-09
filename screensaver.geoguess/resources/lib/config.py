"""The settings table, the data source, the answer map and the on-screen strings. No Kodi imports.

tools/make_settings_geoguess.py turns CATEGORIES and STRINGS into resources/settings.xml and
strings.po; read() loads the values from an xbmcaddon.Addon in the glue layer.
"""

import math
from urllib.parse import urlencode

ADDON_ID = 'screensaver.geoguess'
ADDON_NAME = 'GeoGuess Screensaver'
VERSION = '0.4.0'

# Both Hugging Face datasets hold the same 11,054 rows with the same five columns and the same
# row order. The first one's /rows endpoint works; the second's parquet row groups are larger
# than the datasets server's 300 MB scan limit, so its /rows answers HTTP 500 ("Scan size limit
# exceeded") and the client stays on the first. Keep the working one first.
SOURCES = ('yunusserhat/random_streetview_images',
           'stochastic/random_streetview_images_pano_v0.0.2')

API = 'https://datasets-server.huggingface.co'
USER_AGENT = '%s/%s (Kodi screensaver; +https://github.com/P-Hoep/kodi)' % (ADDON_ID, VERSION)

TIMEOUT = 15                 # seconds, every request
BACKOFF = (10, 20, 40, 60)   # seconds between failed metadata requests, then 60 forever

# The answer map is a NASA Blue Marble image rendered on demand by the GIBS WMS, so it is centred
# on the row and zoomed in to a region rather than the whole world. The latitude span is fixed;
# the longitude span grows with 1/cos(latitude) so the plate carree image is not stretched at high
# latitudes, which keeps the view roughly 670 km wide and 335 km tall anywhere on Earth.
GIBS = 'https://gibs.earthdata.nasa.gov/wms/epsg4326/best/wms.cgi'
MAP_LAYER = 'BlueMarble_ShadedRelief_Bathymetry'
MAP_WIDTH, MAP_HEIGHT = 720, 360
MAP_LAT_SPAN = 3.0
MAP_MIN_COS = 0.25           # near the poles the half-width is capped at 12 degrees


def B(sid, label, default, **kw):
    return dict(id=sid, type='boolean', label=label, default=default, **kw)


def S(sid, label, default, lo, hi, step=1, **kw):
    return dict(id=sid, type='slider', label=label, default=default, min=lo, max=hi, step=step, **kw)


def O(sid, label, default, options, **kw):
    return dict(id=sid, type='options', label=label, default=default, options=options, **kw)


CATEGORIES = [
    ('Playback', [
        S('reveal_after', 'Reveal the location (seconds into the last pass)', 8, 1, 60),
        S('show_for', 'Seconds per panorama pass', 25, 5, 120),
        S('batch_size', 'Locations fetched per request', 40, 10, 100, step=10),
    ]),
    ('Display', [
        B('show_country_name', 'Append the full country name', True),
        B('pan_enabled', 'Pan slowly across each panorama', True),
        S('pan_passes', 'Passes across each panorama', 1, 1, 10, visible='pan_enabled'),
        B('show_clock', 'Show a clock in the top right corner', False),
        B('show_map', 'Show a zoomed map of the location instead of its name', False),
        O('label_size', 'Location label size', 1, ['Small', 'Medium', 'Large']),
    ]),
]

# On-screen text. Settings labels start at 30100; these start at 32000 so the generator can
# append them after the settings strings without renumbering.
STRINGS = {
    32000: 'Loading a street view…',
    32001: 'No connection. Retrying…',
}

LABEL_FONTS = ('font28', 'font37', 'font45')


def all_settings():
    for _title, settings in CATEGORIES:
        for s in settings:
            yield s


def defaults():
    return dict((s['id'], s['default']) for s in all_settings())


def read(addon):
    """Read every setting from an xbmcaddon.Addon into a plain dict."""
    values = defaults()
    for s in all_settings():
        sid = s['id']
        try:
            raw = addon.getSetting(sid)
            if raw == '' and s['type'] != 'string':
                continue      # not written yet: keep the table's default
            if s['type'] == 'boolean':
                values[sid] = addon.getSettingBool(sid)
            elif s['type'] in ('integer', 'options', 'slider'):
                values[sid] = addon.getSettingInt(sid)
            else:
                values[sid] = raw
        except Exception:
            pass              # a missing setting keeps its default
    return values


def timing(settings):
    """(reveal, show_for) in seconds, clamped so the answer always gets a moment on screen.

    reveal is measured into the final pass, not the start of the cycle: see reveal_time().
    """
    show_for = max(5, min(120, int(settings.get('show_for', 25))))
    reveal = float(settings.get('reveal_after', 8))
    reveal = max(0.5, min(reveal, show_for - 1.0))
    return reveal, show_for


def reveal_time(reveal, show_for, passes):
    """When the answer appears, in seconds from the start of the cycle.

    The delay is counted into the final pass, so every earlier pass is played without the
    answer: with three passes the name appears after two full sweeps, not a few seconds into
    the first. A single pass keeps the plain "reveal after N seconds" behaviour.
    """
    return float(show_for) * (max(1, int(passes)) - 1) + float(reveal)


def pan_passes(settings):
    """How many times the pan sweeps across a panorama before the next location."""
    return max(1, min(10, int(settings.get('pan_passes', 1))))


def map_bbox(latitude, longitude):
    """(left, bottom, right, top) in degrees of the answer map around a point.

    The window is centred on the point when it can be and slid inward when the point is too
    close to the antimeridian or a pole, so every edge stays inside the world. The caller places
    the pin from the returned bounds, so a slid window still points at the right spot.
    """
    lat = max(-90.0, min(90.0, float(latitude)))
    lon = max(-180.0, min(180.0, float(longitude)))
    half_lat = MAP_LAT_SPAN / 2.0
    half_lon = MAP_LAT_SPAN / max(MAP_MIN_COS, math.cos(math.radians(lat)))
    centre_lat = max(-90.0 + half_lat, min(90.0 - half_lat, lat))
    centre_lon = max(-180.0 + half_lon, min(180.0 - half_lon, lon))
    return (centre_lon - half_lon, centre_lat - half_lat,
            centre_lon + half_lon, centre_lat + half_lat)


def map_url(bbox):
    """The GIBS WMS request for one answer map. JPEG keeps the download around 50 KB."""
    query = [('SERVICE', 'WMS'), ('REQUEST', 'GetMap'), ('VERSION', '1.1.1'),
             ('SRS', 'EPSG:4326'), ('FORMAT', 'image/jpeg'), ('LAYERS', MAP_LAYER),
             ('WIDTH', MAP_WIDTH), ('HEIGHT', MAP_HEIGHT),
             ('BBOX', '%.4f,%.4f,%.4f,%.4f' % tuple(bbox))]
    return GIBS + '?' + urlencode(query)


def batch_size(settings):
    return max(10, min(100, int(settings.get('batch_size', 40))))
