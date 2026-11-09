"""Kodi glue shared by both front-ends: logging, settings, strings and paths."""

import datetime
import os

import xbmc
import xbmcaddon

from . import LIBRARY_ID, config

_debug = [False]
_strings = {}


def log(message, level=xbmc.LOGINFO):
    xbmc.log('[opentrivia] %s' % message, level)


def debug(message):
    if _debug[0]:
        log(message)


def set_debug(on):
    _debug[0] = bool(on)


def library():
    return xbmcaddon.Addon(LIBRARY_ID)


def library_path():
    return library().getAddonInfo('path')


def db_path():
    return os.path.join(library_path(), 'resources', 'data', 'trivia.db')


def _getters(addon):
    try:
        settings = addon.getSettings()      # Kodi 20+
    except (AttributeError, RuntimeError):
        return {'boolean': addon.getSettingBool, 'integer': addon.getSettingInt,
                'string': addon.getSettingString}
    return {'boolean': settings.getBool, 'integer': settings.getInt, 'string': settings.getString}


def read_settings(addon_id):
    who = config.ADDONS[addon_id]
    settings = config.read(_getters(xbmcaddon.Addon(addon_id)), who)
    settings['source_addon'] = addon_id
    set_debug(settings.get('debug_log'))
    return settings


def open_settings(addon_id):
    xbmcaddon.Addon(addon_id).openSettings()


def tr(sid):
    """On-screen text from the library's strings.po, with the English table as a fallback (Kodi
    reads a new add-on's strings only after a restart)."""
    if sid not in _strings:
        text = ''
        try:
            text = library().getLocalizedString(sid)
        except Exception:
            pass
        _strings[sid] = text or config.STRINGS.get(sid, '')
    return _strings[sid]


def now():
    return datetime.datetime.now()
