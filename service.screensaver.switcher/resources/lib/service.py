"""The background service: at each minute, work out which window applies and, when that
changes, switch Kodi's screensaver.

The service only acts when the scheduled choice changes (and at start-up or after a
settings change), so a screensaver picked by hand in Kodi's settings stays until the
next window boundary.
"""

import time
import traceback

import xbmc

from . import schedule, switcher

log = switcher.log


class Monitor(xbmc.Monitor):
    def __init__(self):
        xbmc.Monitor.__init__(self)
        self.changed = True

    def onSettingsChanged(self):
        self.changed = True


def seconds_to_next_minute():
    return 61 - time.localtime().tm_sec


def run():
    monitor = Monitor()
    last = None
    log('service started')
    while not monitor.abortRequested():
        try:
            s = switcher.settings()
            if s['enabled']:
                slot, target = schedule.wanted(s, switcher.now_minutes())
                if monitor.changed or (slot, target) != last:
                    reason = 'window %d' % slot if slot else 'default'
                    if target:
                        log('%s wants %s' % (reason, target))
                    switcher.apply(target, monitor, s['reload'] and not monitor.changed)
                    last = (slot, target)
            else:
                last = None
            monitor.changed = False
        except Exception:
            log('check failed:\n' + traceback.format_exc(), xbmc.LOGERROR)
        # Wake at the next minute, or straight away when the settings change.
        deadline = time.time() + seconds_to_next_minute()
        while not monitor.changed and time.time() < deadline:
            if monitor.waitForAbort(1):
                break
    log('service stopped')
