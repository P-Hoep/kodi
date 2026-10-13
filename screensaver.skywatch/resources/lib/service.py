"""The background service: keeps data and radar frames warm so the screensaver starts
instantly, without fetching all day.

Refresh modes (Data > Refresh while the screensaver is off):
  Never   the service does nothing; the screensaver fetches when it starts.
  Hourly  refresh everything once an hour.
  Smart   refresh only in the 30 minutes before Kodi's screensaver timeout would fire
          (idle time from xbmc.getGlobalIdleTime()), so the loop is ready the moment it starts.
It sleeps entirely during playback and while the screensaver itself is running.
"""

import json
import os
import time

import xbmc
import xbmcaddon
import xbmcgui
import xbmcvfs

from . import budget as budget_mod
from . import cache, config, hub as hub_mod, net, radar, scenes
from .workers import Workers

ADDON_ID = config.ADDON_ID
WARM_WINDOW = 30 * 60


def log(message, level=xbmc.LOGDEBUG):
    xbmc.log('[%s service] %s' % (ADDON_ID, message), level)


def screensaver_timeout():
    """Kodi's screensaver timeout in seconds, or None when no screensaver is set."""
    try:
        reply = json.loads(xbmc.executeJSONRPC(json.dumps({
            'jsonrpc': '2.0', 'id': 1, 'method': 'Settings.GetSettingValue', 'params': {'setting': 'screensaver.time'}})))
        minutes = reply['result']['value']
        mode = json.loads(xbmc.executeJSONRPC(json.dumps({
            'jsonrpc': '2.0', 'id': 1, 'method': 'Settings.GetSettingValue',
            'params': {'setting': 'screensaver.mode'}})))['result']['value']
        if mode != ADDON_ID:
            return None
        return int(minutes) * 60
    except Exception:
        return None


class Service(object):
    def __init__(self):
        self.monitor = xbmc.Monitor()
        self.last_run = 0.0

    def settings(self):
        addon = xbmcaddon.Addon(ADDON_ID)
        return addon, config.read({'boolean': addon.getSettingBool, 'integer': addon.getSettingInt,
                                   'number': addon.getSettingNumber, 'string': addon.getSetting})

    def should_refresh(self, mode, now):
        if mode == 0:
            return False
        if xbmc.Player().isPlaying() or xbmcgui.Window(10000).getProperty('skywatch.active') == 'true':
            return False
        if mode == 1:
            return now - self.last_run >= 3600
        timeout = screensaver_timeout()
        if timeout is None:
            return False
        idle = xbmc.getGlobalIdleTime()
        # Warm up in the half hour before the screensaver would start, at most every 5 minutes.
        if timeout - WARM_WINDOW <= idle < timeout and now - self.last_run >= 300:
            return True
        return False

    def refresh(self, addon, s):
        if not (s['lat'] or s['lon']):
            return
        profile = xbmcvfs.translatePath(addon.getAddonInfo('profile'))
        store = cache.JsonCache(os.path.join(profile, 'data.db'))
        budget = budget_mod.Budget(store)
        net.set_contact(s.get('nws_email'))
        hub = hub_mod.Hub(s, store, budget, log)
        pool = Workers(2, 'skywatch-service')
        try:
            hub.run_due(pool.submit)
            fc = hub.get('forecast')
            wind = ((fc or {}).get('current') or {}).get('wind_direction_10m')
            chains = radar.Chains(s)
            perf = ['balanced', 'low', 'balanced', 'high'][s.get('profile', 0)]
            seen = set()
            # Only the first map scenes: enough for an instant start, not the whole playlist.
            # Rainbow is skipped here: its tiles are budgeted for the screensaver only.
            for sid, spec in list(scenes.map_specs(s, wind).items())[:2]:
                if spec.view.key() in seen:
                    continue
                seen.add(spec.view.key())
                feed = radar.Feed(sid, spec.view, chains, os.path.join(profile, 'frames'), radar.RESOLUTION[perf],
                                  budget, log, spec.past, spec.future, radar.MAX_FRAMES[perf], spec.past_step,
                                  spec.future_step, allow_rainbow=False)
                feed.update(pool.submit)
            deadline = time.time() + 90
            while time.time() < deadline and not self.monitor.abortRequested():
                if self.monitor.waitForAbort(3):
                    break
                if xbmc.Player().isPlaying():
                    break
            budget.save()
        finally:
            pool.shutdown()
            store.close()

    def run(self):
        log('started', xbmc.LOGINFO)
        while not self.monitor.waitForAbort(30):
            try:
                addon, s = self.settings()
                now = time.time()
                if self.should_refresh(s.get('refresh', 2), now):
                    self.last_run = now
                    log('warming data and radar frames')
                    self.refresh(addon, s)
            except Exception as error:
                log('refresh failed: %s' % error, xbmc.LOGWARNING)


def run():
    Service().run()
