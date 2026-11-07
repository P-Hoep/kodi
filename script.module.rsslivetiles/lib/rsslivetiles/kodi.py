"""Kodi glue shared by both front-ends: logging, settings, strings, paths, the store."""

import datetime
import os
import time

import xbmc
import xbmcaddon
import xbmcvfs

from . import APP_ID, LIBRARY_ID, SCREENSAVER_ID, config
from .feeds.store import Store
from .tiles import text

_debug = [False]
_store = []


def log(message, level=xbmc.LOGINFO):
    xbmc.log('[rsslivetiles] %s' % message, level)


def debug(message):
    if _debug[0]:
        log(message)


def has_addon(addon_id):
    return bool(xbmc.getCondVisibility('System.HasAddon(%s)' % addon_id))


def library():
    return xbmcaddon.Addon(LIBRARY_ID)


def library_path():
    return library().getAddonInfo('path')


def profile_root():
    path = xbmcvfs.translatePath('special://profile/addon_data/%s/' % LIBRARY_ID)
    if not os.path.isdir(path):
        os.makedirs(path, exist_ok=True)
    return path


def store():
    if not _store:
        _store.append(Store(profile_root()))
    return _store[0]


_strings = {}


def tr(sid):
    """On-screen text from the library's strings.po, with the English table as a fallback
    (Kodi reads a new add-on's strings only after a restart)."""
    if sid not in _strings:
        value = ''
        try:
            value = library().getLocalizedString(sid)
        except Exception:
            pass
        _strings[sid] = value or config.STRINGS.get(sid, '')
    return _strings[sid]


def relative_strings():
    return {'now': tr(32004), 'min': tr(32005), 'hours': tr(32006), 'yesterday': tr(32007), 'days': tr(32008),
            'new': tr(32009), 'up_to_date': tr(32010), 'offline': tr(32011), 'offline_body': tr(32012),
            'empty': tr(32013)}


def _getters(addon):
    return {'boolean': addon.getSettingBool, 'integer': addon.getSettingInt, 'string': addon.getSettingString}


def app_settings():
    """The program's settings, or its defaults when it is not installed."""
    if has_addon(APP_ID):
        try:
            return config.read(_getters(xbmcaddon.Addon(APP_ID)), 'app')
        except RuntimeError:
            pass
    return config.defaults('app')


def read_settings(addon_id):
    """Effective settings for one front-end (see config.effective)."""
    app = app_settings()
    if addon_id == SCREENSAVER_ID:
        ss = config.read(_getters(xbmcaddon.Addon(SCREENSAVER_ID)), 'ss')
        settings = config.effective(app, ss)
        settings['screensaver'] = True
    else:
        settings = config.effective(app)
        settings['screensaver'] = False
    _debug[0] = bool(settings.get('debug_log'))
    return settings


def fetch_options(settings):
    return {'refresh_min': settings.get('refresh_min', 30), 'max_items': settings.get('max_items', 30),
            'max_age_days': settings.get('max_age_days', 7), 'timeout': settings.get('timeout', 10),
            'og_image': settings.get('og_image', False)}


def now():
    return datetime.datetime.now()


def epoch():
    return time.time()


def notify(message, addon_id=APP_ID, ms=3000):
    import xbmcgui
    icon = xbmcgui.NOTIFICATION_INFO
    try:
        icon = os.path.join(xbmcaddon.Addon(addon_id).getAddonInfo('path'), 'icon.png')
    except Exception:
        pass
    xbmcgui.Dialog().notification('RSS Live Tiles', message, icon, ms)


__all__ = ['log', 'debug', 'tr', 'read_settings', 'store', 'library_path', 'has_addon', 'notify', 'text']
