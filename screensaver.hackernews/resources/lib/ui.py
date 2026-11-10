"""The screensaver window and the show.

A worker thread owns the show: it loads the cache (or fetches), builds the slide queue and
sets window properties that the skin reads. Kodi's UI thread only runs onInit and onAction;
any input sets the stop flag and run() closes the window. Two content layers, A and B, let
Kodi cross-fade between slides while Python fills the hidden one. The window is shown with
show() and watched here rather than with doModal(), because Kodi can close a screensaver
itself (a notification, a screenshot, waking it) without telling Python, and doModal() then
never returns.
"""

import random
import threading
import time
import traceback

import xbmc
import xbmcaddon
import xbmcgui
import xbmcvfs

from . import cache as cache_module
from . import config, hn_client, playlist

ADDON_ID = config.ADDON_ID
PROP = 'hn.'
SCREEN_W, SCREEN_H = 1920, 1080
BAR_WIDTH = 1728
DRIFT_SECONDS = 60.0
DRIFT_POINTS = [(0, 0), (4, 2), (-3, 3), (2, -2), (-4, -3), (3, -4), (5, 3), (-2, 4), (0, 0)]
RETRY_FIRST, RETRY_MAX = 60.0, 300.0


def log(message, level=xbmc.LOGINFO):
    xbmc.log('[%s] %s' % (ADDON_ID, message), level)


def read_settings(addon):
    try:
        settings = addon.getSettings()          # Kodi 20+
        getters = {'boolean': settings.getBool, 'integer': settings.getInt}
    except AttributeError:                       # Kodi 19
        getters = {'boolean': addon.getSettingBool, 'integer': addon.getSettingInt}
    return config.read(getters)


def profile_path(addon):
    try:
        return xbmcvfs.translatePath(addon.getAddonInfo('profile'))
    except AttributeError:                       # very old Kodi
        return xbmc.translatePath(addon.getAddonInfo('profile'))


class ExitMonitor(xbmc.Monitor):
    def __init__(self, on_exit):
        xbmc.Monitor.__init__(self)
        self.on_exit = on_exit

    def onScreensaverDeactivated(self):
        self.on_exit()


class SaverWindow(xbmcgui.WindowXMLDialog):
    def __init__(self, *args, **kwargs):
        self.saver = kwargs.get('saver')
        self.built = False

    def onInit(self):
        if not self.built:
            self.built = True
            self.saver.attach(self)

    def onAction(self, _action):
        self.saver.exit()

    def onClick(self, _control_id):
        self.saver.exit()


class FetchJob(threading.Thread):
    """One refresh in the background; the show keeps playing until it finishes."""

    def __init__(self, saver, kind):
        threading.Thread.__init__(self, name='hackernews-fetch')
        self.saver = saver
        self.kind = kind
        self.data = None
        self.error = None
        self.done = threading.Event()
        self.daemon = True

    def run(self):
        try:
            self.data = self.saver.fetch(self.kind)
        except Exception as error:      # never let a fetch take the screensaver down
            self.error = error
            log('refresh failed: %s' % error, xbmc.LOGWARNING)
        finally:
            self.done.set()


class Saver(object):
    def __init__(self):
        self.addon = xbmcaddon.Addon(ADDON_ID)
        self.path = self.addon.getAddonInfo('path')
        self.profile = profile_path(self.addon)
        self.settings = read_settings(self.addon)
        self.cache = cache_module.Cache(self.profile)
        self.rng = random.Random()
        self.stop = threading.Event()
        self.monitor = ExitMonitor(self.exit)
        self.window = None
        self.dialog_id = 0
        self.thread = None
        self.front = ''
        self.kind = config.list_key(self.settings)
        self.refresh = config.refresh_seconds(self.settings)
        self.data = None
        self.slides = []
        self.index = 0
        self.next_fetch = 0.0
        self.next_drift = 0.0
        self.backoff = RETRY_FIRST
        self.fetch_job = None
        self.drift_points = list(DRIFT_POINTS)

    # ------------------------------------------------------------ lifecycle

    def run(self):
        self.window = SaverWindow('screensaver-hackernews.xml', self.path, 'Default', '1080i',
                                  saver=self)
        try:
            self.window.show()
            started = time.time()
            while not self.stopped():
                if time.time() - started > 2.0 and \
                        not xbmc.getCondVisibility('System.ScreenSaverActive'):
                    break
                self.monitor.waitForAbort(0.2)
        finally:
            self.stop.set()
            self.close_window()
            if self.thread:
                self.thread.join(2.0)
            log('closed')
            del self.window
            del self.monitor

    def attach(self, window):
        """Kodi's UI thread calls this from onInit."""
        self.dialog_id = xbmcgui.getCurrentWindowDialogId()
        self.apply_look()
        self.thread = threading.Thread(target=self.loop, name='hackernews')
        self.thread.daemon = True
        self.thread.start()

    def exit(self):
        """Any key, click or the screensaver being woken."""
        self.stop.set()

    def close_window(self):
        """Dialog.Close is posted to Kodi's main thread, so it cannot deadlock the way
        Window.close() can when Kodi is already restarting the screensaver."""
        if self.dialog_id:
            xbmc.executebuiltin('Dialog.Close(%d,true)' % self.dialog_id)
            self.monitor.waitForAbort(0.3)
        elif self.window:
            try:
                self.window.close()
            except RuntimeError:
                pass

    def stopped(self):
        return self.stop.is_set() or self.monitor.abortRequested()

    def wait(self, seconds):
        """Sleep, returning True when the show should end."""
        end = time.time() + seconds
        while not self.stopped():
            left = end - time.time()
            if left <= 0:
                return False
            self.stop.wait(min(left, 0.1))
        return True

    # ------------------------------------------------------------ properties

    def set(self, name, value):
        if not self.window:
            return
        try:
            self.window.setProperty(PROP + name, '' if value is None else str(value))
        except RuntimeError:
            pass

    def set_layer(self, layer, name, value):
        self.set(layer + '.' + name, value)

    def set_front(self, layer):
        self.front = layer
        self.set('front', layer)

    def set_bar(self, fraction):
        if not self.window:
            return
        try:
            control = self.window.getControl(501)
            control.setWidth(max(1, int(round(BAR_WIDTH * max(0.0, min(1.0, fraction))))))
        except RuntimeError:
            pass

    def set_status(self, text):
        self.set('status', text)

    def show_message(self, text):
        self.set_front('')
        self.set('message', text)
        self.set('counter', '')
        self.set_bar(0.0)

    def clear_message(self):
        self.set('message', '')

    def apply_look(self):
        colours = config.theme_colours(self.settings)
        for key in ('bg', 'text', 'dim', 'accent', 'track'):
            self.set(key, colours[key])
        self.set('scale', str(self.settings.get('font_scale', 100)))
        self.set('clock', '1' if self.settings.get('clock', True) else '0')
        self.set('wordmark', self.tr(32000))
        self.set('source', self.tr(config.source_label_id(self.settings)))
        self.set('message', '')

    def tr(self, string_id):
        return self.addon.getLocalizedString(string_id)

    def debug(self, message):
        if self.settings.get('debug'):
            log(message)

    # ------------------------------------------------------------ the show

    def loop(self):
        try:
            self.play()
        except Exception:
            log(traceback.format_exc(), xbmc.LOGERROR)

    def play(self):
        self.data = self.cache.load(self.kind)
        if self.data is None:
            self.data = self.fetch_blocking()
            if self.data is None:
                return
        self.slides = self.build(self.data)
        if not self.slides:
            self.show_message(self.tr(32009))
            return
        self.index = 0
        self.next_fetch = float(self.data.get('fetched_at') or 0) + self.refresh
        self.next_drift = time.time() + DRIFT_SECONDS
        while not self.stopped():
            slide = self.slides[self.index]
            self.show_slide(slide, self.index, len(self.slides))
            if not self.wait_slide(slide['seconds']):
                return
            self.index = (self.index + 1) % len(self.slides)
            self.poll_fetch()
            if self.fetch_job is None and time.time() >= self.next_fetch:
                self.fetch_job = FetchJob(self, self.kind)
                self.fetch_job.start()

    def build(self, data):
        return playlist.build(data, self.settings, self.tr, rng=self.rng)

    def fetch(self, kind, save=False):
        settings = self.settings
        data = hn_client.load(kind,
                              limit=settings.get('stories', 15),
                              comments=settings.get('comments', 3),
                              include_reply=settings.get('include_reply', False),
                              use_algolia=settings.get('use_algolia', True),
                              debug=self.debug if settings.get('debug') else None)
        if save:
            self.cache.save(kind, data)
        return data

    def fetch_blocking(self):
        """No cache yet: keep trying, with a calm message, until there is data or the show ends."""
        while not self.stopped():
            self.show_message(self.tr(32001))
            try:
                return self.fetch(self.kind, save=True)
            except Exception as error:
                log('fetch failed: %s' % error, xbmc.LOGWARNING)
                self.show_message(self.tr(32002))
                if self.wait(self.backoff):
                    return None
                self.backoff = min(RETRY_MAX, self.backoff * 2)
        return None

    def poll_fetch(self):
        job = self.fetch_job
        if not job or not job.done.is_set():
            return
        self.fetch_job = None
        self.clear_message()
        if job.data and job.data.get('stories'):
            self.data = job.data
            self.cache.save(self.kind, job.data)
            self.slides = self.build(job.data)
            self.index = 0
            self.backoff = RETRY_FIRST
            self.set_status('')
            self.next_fetch = float(job.data.get('fetched_at') or 0) + self.refresh
        else:
            self.set_status(self.tr(32003))
            self.next_fetch = time.time() + self.backoff
            self.backoff = min(RETRY_MAX, self.backoff * 2)

    def show_slide(self, slide, index, total):
        layer = 'b' if self.front == 'a' else 'a'
        if slide['kind'] == playlist.STORY:
            self.set_layer(layer, 'mode', 'story')
            self.set_layer(layer, 'rank', slide['rank'])
            self.set_layer(layer, 'title', slide['title'])
            self.set_layer(layer, 'meta', slide['meta'])
            self.set_layer(layer, 'storytext', slide['body'])
        else:
            self.set_layer(layer, 'mode', 'comment')
            self.set_layer(layer, 'chead', slide['head'])
            self.set_layer(layer, 'cauthor', slide['author'])
            self.set_layer(layer, 'ctext', slide['text'])
        self.clear_message()
        self.set_front(layer)
        self.set('counter', self.tr(32004) % (index + 1, total))
        self.set_bar(0.0)

    def wait_slide(self, seconds):
        start = time.time()
        seconds = max(1.0, float(seconds))
        while not self.stopped():
            self.set_bar((time.time() - start) / seconds)
            if time.time() - start >= seconds:
                self.set_bar(1.0)
                return True
            if self.settings.get('drift', True) and time.time() >= self.next_drift:
                self.drift()
                self.next_drift = time.time() + DRIFT_SECONDS
            self.stop.wait(0.1)
        return False

    def drift(self):
        if not self.drift_points:
            return
        x, y = self.drift_points.pop(0)
        self.drift_points.append((x, y))
        if not self.window:
            return
        try:
            self.window.getControl(900).setPosition(x, y)
        except (RuntimeError, AttributeError):
            self.drift_points = []      # this Kodi cannot move a group; leave the layout still


def run():
    Saver().run()


def clear_cache():
    addon = xbmcaddon.Addon(ADDON_ID)
    removed = cache_module.Cache(profile_path(addon)).clear()
    log('cache cleared (%d files)' % removed)
    xbmcgui.Dialog().ok(addon.getAddonInfo('name'), addon.getLocalizedString(32010))
