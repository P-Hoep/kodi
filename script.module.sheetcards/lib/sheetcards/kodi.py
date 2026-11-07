"""Kodi glue shared by both front-ends: logging, settings, strings, paths, the data loader."""

import datetime
import os
import time

import xbmc
import xbmcaddon
import xbmcvfs

from . import APP_ID, LIBRARY_ID, SCREENSAVER_ID, config, data, sheet
from .cache import Cache

_debug = [False]


def log(message, level=xbmc.LOGINFO):
    xbmc.log('[sheetcards] %s' % message, level)


def debug(message):
    if _debug[0]:
        log(message)


def set_debug(on):
    _debug[0] = bool(on)


def has_addon(addon_id):
    return bool(xbmc.getCondVisibility('System.HasAddon(%s)' % addon_id))


def library():
    return xbmcaddon.Addon(LIBRARY_ID)


def library_path():
    return library().getAddonInfo('path')


def profile_root():
    path = xbmcvfs.translatePath('special://profile/addon_data/%s/' % LIBRARY_ID)
    if not os.path.isdir(path):
        os.makedirs(path)
    return path


def cache():
    return Cache(profile_root())


_strings = {}


def tr(sid):
    """On-screen text from the library's strings.po, with the English table as a fallback
    (Kodi reads a new add-on's strings only after a restart)."""
    if sid not in _strings:
        text = ''
        try:
            text = library().getLocalizedString(sid)
        except Exception:
            pass
        _strings[sid] = text or config.STRINGS.get(sid, '')
    return _strings[sid]


def _getters(addon):
    return {'boolean': addon.getSettingBool, 'integer': addon.getSettingInt, 'string': addon.getSettingString}


def read_settings(addon_id):
    """Settings for one front-end. The screensaver takes the shared ones from the app when
    use_app_settings is on and the app is installed."""
    who = config.ADDONS[addon_id]
    settings = config.read(_getters(xbmcaddon.Addon(addon_id)), who)
    settings['source_addon'] = addon_id
    if who == 'ss' and settings.get('use_app_settings') and has_addon(APP_ID):
        app = config.read(_getters(xbmcaddon.Addon(APP_ID)), 'app')
        for key in config.shared_ids():
            settings[key] = app[key]
        settings['source_addon'] = APP_ID
    settings['sheet_id'] = sheet.extract_id(settings.get('sheet_id', ''))
    set_debug(settings.get('debug_log'))
    return settings


def settings_addon(addon_id):
    """The add-on whose settings hold the sheet ID and decks for this front-end."""
    return read_settings(addon_id)['source_addon']


def loader(settings):
    return data.Loader(cache(), settings['sheet_id'], settings.get('header_row', 0), settings.get('tab_names', ''),
                       settings.get('api_key', ''), log=log, debug=debug if _debug[0] else None)


def ago(timestamp, now=None):
    seconds = max(0, (now or time.time()) - timestamp)
    if seconds < 90:
        return tr(32054)
    if seconds < 3600:
        return tr(32055) % (seconds // 60)
    if seconds < 2 * 86400:
        return tr(32056) % (seconds // 3600)
    return tr(32057) % (seconds // 86400)


def error_text(err):
    """SheetError -> (title, body) for an error card."""
    kind = getattr(err, 'kind', 'bad_data')
    if kind == 'no_id':
        return tr(32000), tr(32001)
    if kind == 'not_public':
        return tr(32002), tr(32003)
    if kind == 'not_found':
        return tr(32004), tr(32005)
    if kind == 'network':
        return tr(32006), tr(32007)
    return tr(32011), tr(32012)


def now():
    return datetime.datetime.now()


def notify(message, icon_addon=APP_ID):
    import xbmcgui
    icon = ''
    try:
        icon = os.path.join(xbmcaddon.Addon(icon_addon).getAddonInfo('path'), 'icon.png')
    except Exception:
        pass
    xbmcgui.Dialog().notification('Sheetcards', message, icon or xbmcgui.NOTIFICATION_INFO, 3000)


__all__ = ['log', 'debug', 'tr', 'read_settings', 'loader', 'cache', 'library_path', 'has_addon', 'ago',
           'error_text', 'notify', 'APP_ID', 'SCREENSAVER_ID', 'LIBRARY_ID']
