"""Kodi glue shared by the plugin and the service: settings, the API client, logging
that never prints the key, list items that work on Kodi 19 and 20+, and the window
properties the plugin uses to hand a playback session to the service."""

import json
import os
import uuid

import xbmc
import xbmcaddon
import xbmcgui
import xbmcvfs

from . import api, auth, config
from .cache import Cache

ADDON = xbmcaddon.Addon(config.ADDON_ID)
HOME = xbmcgui.Window(10000)
SESSION_PROP = 'audioshelf.session'
SEEK_PROP = 'audioshelf.seek'
_secrets = []


def log(message, level=xbmc.LOGINFO):
    message = str(message)
    for secret in _secrets:
        if secret:
            message = message.replace(secret, '***')
    xbmc.log('[%s] %s' % (config.ADDON_ID, message), level)


def addon():
    return xbmcaddon.Addon(config.ADDON_ID)  # fresh, so changed settings are seen


def settings():
    a = addon()
    s = config.read({'boolean': a.getSettingBool, 'integer': a.getSettingInt, 'string': a.getSettingString})
    for secret in (s['api_key'], s['password']):
        if secret and secret not in _secrets:
            _secrets.append(secret)
    return s


def profile():
    path = xbmcvfs.translatePath(ADDON.getAddonInfo('profile'))
    os.makedirs(path, exist_ok=True)
    return path


def addon_path():
    return ADDON.getAddonInfo('path')


def client(s=None):
    s = s or settings()
    if s['use_api_key']:
        method = auth.ApiKey(s['api_key'])
    else:
        method = auth.Login(s['username'], s['password'], os.path.join(profile(), 'tokens.json'))
    for secret in method.secrets():
        if secret and secret not in _secrets:
            _secrets.append(secret)
    return api.Client(s['server_url'], method, s['timeout'])


def cache(s=None):
    s = s or settings()
    return Cache(os.path.join(profile(), 'cache'), s['cache_minutes'] * 60, s['server_url'])


def device_info():
    """A stable per-installation id, so the server's sessions list shows this Kodi."""
    path = os.path.join(profile(), 'device_id')
    try:
        device_id = open(path).read().strip()
    except OSError:
        device_id = ''
    if not device_id:
        device_id = 'kodi-' + uuid.uuid4().hex
        with open(path, 'w') as handle:
            handle.write(device_id)
    build = xbmc.getInfoLabel('System.BuildVersion').split(' ')[0]
    return {'deviceId': device_id, 'clientName': 'Kodi Audioshelf',
            'clientVersion': ADDON.getAddonInfo('version'), 'manufacturer': 'Kodi', 'model': build or 'Kodi'}


# -- user-facing errors ------------------------------------------------------------

def explain(error):
    """A short, useful message for an API error (no secrets, no tracebacks)."""
    if isinstance(error, api.NotConfigured):
        return 'Enter the server address and your username and password in the add-on settings.'
    if isinstance(error, api.AuthError):
        if 'password' in str(error).lower() or 'signed out' in str(error).lower():
            return str(error).split(': ', 1)[-1] + '.'
        return 'The server rejected the sign-in. Check the username and password (or API key) in the settings.'
    if isinstance(error, api.Unreachable):
        return "Can't reach the server. Check the address and that the server is running."
    if isinstance(error, api.NotFound):
        return 'Not found on the server. It may have been removed; try refreshing.'
    return 'The server gave an unexpected answer. See the Kodi log for details.'


def notify(message, icon=xbmcgui.NOTIFICATION_INFO, ms=4000):
    xbmcgui.Dialog().notification(config.ADDON_NAME, message, icon, ms)


def error_dialog(error):
    log('error: %s' % error, xbmc.LOGWARNING)
    message = explain(error)
    if isinstance(error, (api.NotConfigured, api.AuthError, api.Unreachable)):
        if xbmcgui.Dialog().yesno(config.ADDON_NAME, message, nolabel='Close', yeslabel='Settings'):
            addon().openSettings()
    else:
        xbmcgui.Dialog().ok(config.ADDON_NAME, message)


# -- list items ----------------------------------------------------------------------

def list_item(label, label2='', art=None, info=None, properties=None, playable=False):
    """info: title, artist, album, comment, duration, genre, year, mediatype, playcount."""
    li = xbmcgui.ListItem(label, label2, offscreen=True)
    if art:
        li.setArt(art)
    if info:
        set_music_info(li, info)
    for key, value in (properties or {}).items():
        li.setProperty(key, str(value))
    if playable:
        li.setProperty('IsPlayable', 'true')
    return li


def set_music_info(li, info):
    if hasattr(li, 'getMusicInfoTag'):  # Kodi 20+
        tag = li.getMusicInfoTag()
        if info.get('title'):
            tag.setTitle(info['title'])
        if info.get('artist'):
            artist = info['artist']
            tag.setArtist(', '.join(artist) if isinstance(artist, list) else artist)
        if info.get('album'):
            tag.setAlbum(info['album'])
        if info.get('comment'):
            tag.setComment(info['comment'])
        if info.get('duration'):
            tag.setDuration(int(info['duration']))
        if info.get('genre'):
            tag.setGenres(info['genre'])
        if info.get('year'):
            try:
                tag.setYear(int(info['year']))
            except ValueError:
                pass
        if info.get('mediatype'):
            tag.setMediaType(info['mediatype'])
        if info.get('playcount'):
            tag.setPlayCount(info['playcount'])
        if info.get('tracknumber'):
            tag.setTrack(info['tracknumber'])
    else:
        legacy = dict((k, v) for k, v in info.items() if v and k != 'mediatype')
        if 'genre' in legacy:
            legacy['genre'] = ' / '.join(legacy['genre'])
        li.setInfo('music', legacy)


# -- plugin -> service hand-over -------------------------------------------------------

def set_json_prop(name, value):
    HOME.setProperty(name, json.dumps(value) if value is not None else '')


def get_json_prop(name):
    raw = HOME.getProperty(name)
    if not raw:
        return None
    try:
        return json.loads(raw)
    except ValueError:
        return None
