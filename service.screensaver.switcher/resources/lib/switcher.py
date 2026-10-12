"""The Kodi side: read settings, set Kodi's screensaver, and restart a running one."""

import json
import time

import xbmc
import xbmcaddon

from . import config, schedule

ADDON_ID = config.ADDON_ID


def log(message, level=xbmc.LOGINFO):
    xbmc.log('[%s] %s' % (ADDON_ID, message), level)


def rpc(method, params=None):
    msg = {'jsonrpc': '2.0', 'id': 1, 'method': method}
    if params is not None:
        msg['params'] = params
    reply = json.loads(xbmc.executeJSONRPC(json.dumps(msg)))
    if 'error' in reply:
        raise RuntimeError('%s: %s' % (method, reply['error']))
    return reply.get('result')


def settings():
    addon = xbmcaddon.Addon(ADDON_ID)
    return config.read({'boolean': addon.getSettingBool, 'integer': addon.getSettingInt,
                        'string': addon.getSettingString})


def installed():
    """{addon id: name} of the enabled screensavers."""
    result = rpc('Addons.GetAddons', {'type': config.SCREENSAVER, 'enabled': True, 'properties': ['name']})
    return dict((a['addonid'], a['name']) for a in result.get('addons', []))


def current():
    return rpc('Settings.GetSettingValue', {'setting': 'screensaver.mode'}).get('value', '')


def now_minutes():
    t = time.localtime()
    return t.tm_hour * 60 + t.tm_min


def running():
    return xbmc.getCondVisibility('System.ScreenSaverActive')


def restart(monitor):
    """Wake the running screensaver and start it again, so the new one shows."""
    rpc('Input.ExecuteAction', {'action': 'noop'})  # Kodi spends input on waking the screensaver
    for _ in range(50):
        if not running():
            break
        if monitor.waitForAbort(0.1):
            return
    # Give a Python screensaver a moment to close its window before the next one starts.
    if monitor.waitForAbort(1.0):
        return
    xbmc.executebuiltin('ActivateScreensaver')


def apply(target, monitor, reload_running):
    """Make `target` Kodi's screensaver. Returns True if the setting changed."""
    if not target:
        return False
    names = installed()
    if target not in names:
        log('scheduled screensaver %s is not installed or is disabled; leaving %s'
            % (target, current()), xbmc.LOGWARNING)
        return False
    before = current()
    if before == target:
        return False
    rpc('Settings.SetSettingValue', {'setting': 'screensaver.mode', 'value': target})
    log('screensaver %s -> %s' % (before, target))
    if reload_running and running():
        log('restarting the running screensaver')
        restart(monitor)
    return True
