"""Reads the add-on's settings.xml values into radar_core.Settings.

The apps and the screensaver share one settings table (tools/make_settings_vintageradar.py), so
the ids here — including the coordinate ids latitude/longitude — must match that generator.
Missing or blank values fall back to the generated defaults, which also keeps the app usable in
offline tests and on a fresh install before Kodi has written settings.xml.
"""

import xbmcaddon

from . import defaults
from .radar_core import Settings

ADDON_ID = 'script.vintageradar'


def _as_bool(raw, fallback):
    if isinstance(raw, str) and raw.strip().lower() in ('true', '1', 'yes', 'on'):
        return True
    if isinstance(raw, str) and raw.strip().lower() in ('false', '0', 'no', 'off'):
        return False
    return fallback


def _as_int(raw, fallback):
    try:
        return int(float(raw))
    except (TypeError, ValueError):
        return fallback


def _as_float(raw, fallback):
    try:
        return float(raw)
    except (TypeError, ValueError):
        return fallback


def read(addon_id=ADDON_ID, addon=None):
    if addon is None:
        addon = xbmcaddon.Addon(addon_id)
    values = {}
    for key, fallback in defaults.DEFAULTS.items():
        try:
            raw = addon.getSetting(key)
        except Exception:
            raw = ''
        if raw is None or raw == '':
            raw = fallback
        if isinstance(fallback, bool):
            values[key] = _as_bool(raw, fallback)
        elif isinstance(fallback, int):
            values[key] = _as_int(raw, fallback)
        else:
            values[key] = raw
    values['lat'] = _as_float(values.pop('latitude'), 44.9031331)
    values['lon'] = _as_float(values.pop('longitude'), -93.3096136)
    return Settings(**values)
