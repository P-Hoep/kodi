"""The screensaver window and its display loop: Kodi glue only.

Every control is created from Python, bottom to top: a black backdrop, two image controls so one
can crossfade into the other, a bottom shade, the three label sizes and the status line. The
display loop runs on its own thread; any input or the screensaver being woken stops it and the
window closes straight away.
"""

import collections
import os
import threading
import time
import traceback

import xbmc
import xbmcaddon
import xbmcgui
import xbmcvfs

from . import config, downloader, hf_client, labels, layout, net

W, H = 1920, 1080
CROSSFADE_MS = 1000
LABEL_FADE_MS = 800
# The image control is moved by Python, so the tick has to be at least as fast as the display
# refresh or the pan visibly steps. 120 Hz keeps a fresh position ready for every rendered frame
# on 50, 60 and 120 Hz screens; the loop does almost nothing per tick.
TICK = 1.0 / 120.0
RETRY_SECONDS = 10
RECENT = 200
SHADE_HEIGHT = 460

LABEL_BOXES = ((60, 946, 1500, 90),      # font28
               (60, 930, 1500, 110),     # font37
               (60, 912, 1500, 140))     # font45

FADE_IN_OUT = [('visible', 'effect=fade start=0 end=100 time=%d' % CROSSFADE_MS),
               ('hidden', 'effect=fade start=100 end=0 time=%d' % CROSSFADE_MS)]
LABEL_ANIMS = [('visible', 'effect=fade start=0 end=100 time=%d' % LABEL_FADE_MS),
               ('hidden', 'effect=fade start=100 end=0 time=%d' % LABEL_FADE_MS)]


def log(message, level=xbmc.LOGINFO):
    xbmc.log('[%s] %s' % (config.ADDON_ID, message), level)


def debug(message):
    log(message, xbmc.LOGDEBUG)


class ExitMonitor(xbmc.Monitor):
    """Kodi waking the screensaver is a stop signal even when Python gets no action."""

    def __init__(self, on_wake):
        xbmc.Monitor.__init__(self)
        self.on_wake = on_wake

    def onScreensaverDeactivated(self):
        self.on_wake()


class SaverWindow(xbmcgui.WindowXMLDialog):
    def __init__(self, *args, **kwargs):
        self.app = kwargs['app']

    def onInit(self):
        self.app.attach(self)

    def onAction(self, action):
        self.app.on_action(action)


class Saver(object):
    def __init__(self):
        self.addon = xbmcaddon.Addon(config.ADDON_ID)
        self.path = self.addon.getAddonInfo('path')
        self.settings = config.read(self.addon)
        self.reveal, self.show_for = config.timing(self.settings)
        self.batch_size = config.batch_size(self.settings)
        self.pan_enabled = bool(self.settings.get('pan_enabled', True))
        self.show_country = bool(self.settings.get('show_country_name', True))
        self.label_index = max(0, min(2, int(self.settings.get('label_size', 1))))
        self.stop = threading.Event()
        self.monitor = ExitMonitor(self.wake)
        self.window = None
        self.thread = None
        self.started = time.time()
        self.controls = None
        self.images = []
        self.label = None
        self.status_label = None
        self.active = 0
        self.recent = collections.deque(maxlen=RECENT)
        self.candidates = []
        self.prefetch = None
        self.store = None
        self.client = None
        self._in_flight = False

    # ------------------------------------------------------------ lifecycle

    def run(self):
        """show() rather than doModal(): when Kodi itself wakes the screensaver it closes the
        window without telling Python, and doModal() then never returns."""
        window = SaverWindow('screensaver-geoguess.xml', self.path, 'Default', '1080i', app=self)
        self.window = window
        try:
            window.show()
            started = time.time()
            while not self.stopped():
                if time.time() - started > 2.0 and not xbmc.getCondVisibility('System.ScreenSaverActive'):
                    break
                self.monitor.waitForAbort(0.2)
        finally:
            self.shutdown()

    def wake(self):
        self.stop.set()

    def on_action(self, _action):
        """Any key, click, touch or mouse move closes the screensaver."""
        self.wake()
        return True

    def stopped(self):
        return self.stop.is_set() or self.monitor.abortRequested()

    def shutdown(self):
        self.stop.set()
        if self.prefetch is not None:
            self.prefetch.close()
        if self.thread is not None:
            self.thread.join(1.5)
        if self.store is not None:
            self.store.clear()
        window, self.window = self.window, None
        if window is not None:
            try:
                window.close()
            except Exception:
                pass
        debug('screensaver closed after %.1f s' % (time.time() - self.started))

    # ------------------------------------------------------------ controls

    def media(self, name):
        return os.path.join(self.path, 'resources', 'skins', 'Default', 'media', name)

    def attach(self, window):
        if self.controls is not None or self.stopped():
            return
        backdrop = xbmcgui.ControlImage(-20, -20, W + 40, H + 40, self.media('white.png'),
                                        colorDiffuse='FF000000')
        self.images = [xbmcgui.ControlImage(0, 0, W, H, ''), xbmcgui.ControlImage(0, 0, W, H, '')]
        for image in self.images:
            image.setAnimations(FADE_IN_OUT)
            image.setVisible(False)
        shade = xbmcgui.ControlImage(0, H - SHADE_HEIGHT, W, SHADE_HEIGHT, self.media('shade.png'))
        self.label_boxes = []
        for font, (x, y, width, height) in zip(config.LABEL_FONTS, LABEL_BOXES):
            box = xbmcgui.ControlTextBox(x, y, width, height, font=font, textColor='FFFFFFFF')
            box.setAnimations(LABEL_ANIMS)
            box.setVisible(False)
            self.label_boxes.append(box)
        self.label = self.label_boxes[self.label_index]
        self.status_label = xbmcgui.ControlLabel(0, 480, W, 100, '', font='font37',
                                                 textColor='CCFFFFFF', alignment=2)
        self.controls = ([backdrop] + self.images + [shade] + self.label_boxes + [self.status_label])
        window.addControls(self.controls)
        debug('attached: reveal %.1f s, show_for %d s, label %s'
              % (self.reveal, self.show_for, config.LABEL_FONTS[self.label_index]))
        self.show_status(self.tr(32000))
        self.thread = threading.Thread(target=self.display_loop, name='geoguess-display')
        self.thread.daemon = True
        self.thread.start()

    def tr(self, sid):
        try:
            text = self.addon.getLocalizedString(sid)
        except Exception:
            text = ''
        return text or config.STRINGS.get(sid, '')

    def show_status(self, text):
        if self.status_label is None:
            return
        self.status_label.setLabel(text)
        self.status_label.setVisible(True)

    def hide_status(self):
        if self.status_label is not None:
            self.status_label.setVisible(False)

    def _show_label(self, text):
        self.label.setText(text)
        self.label.setVisible(True)

    def _hide_label(self):
        self.label.setVisible(False)

    # ------------------------------------------------------------ display

    def display_loop(self):
        try:
            self._display()
        except hf_client.Aborted:
            pass
        except Exception:
            log(traceback.format_exc(), xbmc.LOGERROR)

    def _display(self):
        temp = xbmcvfs.translatePath('special://temp/geoguess/')
        self.store = downloader.TempStore(temp)
        self.client = hf_client.Client(monitor=self.monitor, on_retry=self._on_retry)
        self.prefetch = downloader.Prefetcher(downloader.Downloader(self.client, self.store))
        while not self.stopped():
            downloaded = self._next_ready()
            if downloaded is None:
                break
            self.hide_status()
            self._cycle(downloaded)

    def _on_retry(self, _error, _delay):
        """Called by the client before each wait between failed metadata requests."""
        if self.stopped():
            return
        self.show_status(self.tr(32001) or self.tr(32000))

    def _pause(self, seconds):
        end = time.time() + seconds
        while time.time() < end:
            if self.stopped():
                return False
            if self.monitor.waitForAbort(min(0.2, max(0.0, end - time.time()))):
                return False
        return not self.stopped()

    def _next_item(self):
        """Pop a row from the last batch, fetching a new batch when it runs out."""
        while not self.candidates:
            if self.stopped():
                return None
            if not self.recent:
                self.show_status(self.tr(32000))
            try:
                self.candidates = self.client.batch(self.batch_size, self.recent)
            except hf_client.Aborted:
                return None
            except net.HttpError as error:
                log('batch failed: %s' % error)
                self.show_status(self.tr(32001))
                if not self._pause(RETRY_SECONDS):
                    return None
        return self.candidates.pop(0)

    def _next_ready(self):
        """A downloaded image for the next slide, or None when the screensaver is closing."""
        while not self.stopped():
            if not self._in_flight:
                item = self._next_item()
                if item is None:
                    return None
                self.prefetch.submit(item)
                self._in_flight = True
            got = self.prefetch.result(timeout=0.1)
            if got is None:
                continue
            item, result = got
            self._in_flight = False
            if isinstance(result, Exception):
                log('row %s failed: %s' % (getattr(item, 'row_idx', '?'), result))
                if isinstance(result, net.HttpError) and not result.retryable:
                    continue          # skip the row and go on
                if not self._pause(1):
                    return None
                continue
            return result
        return None

    def _cycle(self, downloaded):
        width, height = layout.display_size(downloaded.width or W, downloaded.height or H, W, H)
        if downloaded.width <= 0 or downloaded.height <= 0:
            width, height = W, H
        slot = 1 - self.active
        coming = self.images[slot]
        going = self.images[self.active]
        start_x = layout.centre_offset(width, W) if width <= W else 0
        coming.setImage(downloaded.path, False)
        coming.setWidth(int(width))
        coming.setHeight(int(height))
        coming.setPosition(start_x, 0)
        coming.setVisible(True)
        going.setVisible(False)
        debug('cycle row %d, %dx%d' % (downloaded.item.row_idx, width, height))
        self.active = slot
        self.recent.append(downloaded.item.row_idx)
        self._hide_label()
        started = time.time()

        # Start the next download right away so it is ready when this cycle ends.
        if not self._in_flight:
            item = self._next_item()
            if item is not None:
                self.prefetch.submit(item)
                self._in_flight = True
        self.hide_status()

        text = labels.display_label(downloaded.item.address, downloaded.item.country,
                                    self.show_country)
        revealed = False
        x = start_x
        while not self.stopped():
            elapsed = time.time() - started
            if elapsed >= self.show_for:
                break
            # Kodi's slide animation does not move a control created from Python, so the pan is
            # stepped here. The tick is faster than the display refresh and the position comes
            # from the clock rather than the tick count, so every rendered frame gets a fresh,
            # evenly spaced position and a late wake-up never makes the pan drift.
            moved = start_x + layout.pan_offset(width, W, elapsed, self.show_for, self.pan_enabled)
            if moved != x:
                coming.setPosition(moved, 0)
                x = moved
            if not revealed and elapsed >= self.reveal:
                self._show_label(text)
                debug('label: %s' % text)
                revealed = True
            if self.monitor.waitForAbort(TICK):
                break
        self._hide_label()


def main(args):
    try:
        Saver().run()
    except Exception:
        log(traceback.format_exc(), xbmc.LOGERROR)
