"""The settings table, the data source and the on-screen strings. No Kodi imports.

tools/make_settings_geoguess.py turns CATEGORIES and STRINGS into resources/settings.xml and
strings.po; read() loads the values from an xbmcaddon.Addon in the glue layer.
"""

ADDON_ID = 'screensaver.geoguess'
ADDON_NAME = 'GeoGuess Screensaver'
VERSION = '0.1.0'

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


def B(sid, label, default, **kw):
    return dict(id=sid, type='boolean', label=label, default=default, **kw)


def S(sid, label, default, lo, hi, step=1, **kw):
    return dict(id=sid, type='slider', label=label, default=default, min=lo, max=hi, step=step, **kw)


def O(sid, label, default, options, **kw):
    return dict(id=sid, type='options', label=label, default=default, options=options, **kw)


CATEGORIES = [
    ('Playback', [
        S('reveal_after', 'Reveal the location after (seconds)', 8, 1, 60),
        S('show_for', 'Time per location (seconds)', 25, 5, 120),
        S('batch_size', 'Locations fetched per request', 40, 10, 100, step=10),
    ]),
    ('Display', [
        B('show_country_name', 'Append the full country name', True),
        B('pan_enabled', 'Pan slowly across each panorama', True),
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
    """(reveal, show_for) in seconds, clamped so the label always gets a moment on screen."""
    show_for = max(5, min(120, int(settings.get('show_for', 25))))
    reveal = float(settings.get('reveal_after', 8))
    reveal = max(0.5, min(reveal, show_for - 1.0))
    return reveal, show_for


def batch_size(settings):
    return max(10, min(100, int(settings.get('batch_size', 40))))
