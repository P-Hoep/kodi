"""The Vintage Radar screensaver: the app's scope, hands-off.

This is the same window, model and feed as the app (script.vintageradar) - both run
vintageradar.session.App and vintageradar.ui.Scene - but the session is not interactive: no
clicks, no contact sheet, no settings menu. Any key, click or the screensaver being deactivated
closes the window.
"""

import threading
import time

import xbmc
import xbmcaddon
import xbmcgui

from vintageradar import SCREENSAVER_ID, SKIN, config, fontdraw, session, ui


class ExitMonitor(xbmc.Monitor):
    def __init__(self, on_exit):
        xbmc.Monitor.__init__(self)
        self.on_exit = on_exit

    def onScreensaverDeactivated(self):
        self.on_exit()


class SaverWindow(xbmcgui.WindowXMLDialog):
    """The dialog the scope lives in; every control is added by the shared Scene."""

    def __init__(self, *args, **kwargs):
        # Kodi's window type takes the XML arguments itself; the saver arrives by keyword.
        self.controller = kwargs['controller']
        self.builder = None
        self.scene = None

    def onInit(self):
        if self.scene is None and self.builder is not None:
            self.scene = self.builder(self)
            self.setFocusId(self.scene.anchor_id)
            self.controller.attach(self)
            self.controller.start()

    def onAction(self, action):
        # In a screensaver any input means the user is back; Kodi also sends
        # onScreensaverDeactivated.
        self.controller.exit()


class Screensaver(object):
    def __init__(self):
        self.addon = xbmcaddon.Addon(SCREENSAVER_ID)
        self.settings = config.read(SCREENSAVER_ID, self.addon)
        self.media, self.library_path = session.media_path()
        self.renderer = fontdraw.Renderer(self.media, session.temp_dir())
        self.window = None
        self.dialog_id = None
        self.app = None
        self.thread = None
        self.stop = threading.Event()
        self.monitor = ExitMonitor(self.exit)

    def build(self, window):
        return ui.Scene(window, self.media, self.renderer, self.app.model, self.settings)

    def attach(self, window):
        self.dialog_id = xbmcgui.getCurrentWindowDialogId()

    def start(self):
        # The session waits on the model and feed; the window callbacks never touch controls.
        self.thread = threading.Thread(target=self.app.run, name='vintageradar-saver')
        self.thread.daemon = True
        self.thread.start()

    def run(self):
        """show() and wait here rather than doModal(): when Kodi itself wakes the screensaver
        (a RunScript, a screenshot, a notification) it closes the window without telling Python,
        and doModal() then never returns, so Kodi kills the script. Waiting in a loop that also
        watches System.ScreenSaverActive always ends."""
        self.window = SaverWindow(SKIN, self.library_path, 'Default', '1080i', controller=self)
        self.app = session.App(self.addon, self.settings, self.renderer, self.window,
                               addon_id=SCREENSAVER_ID, interactive=False)
        self.window.builder = self.build
        try:
            self.window.show()
            started = time.time()
            while not self.stopped():
                if time.time() - started > 2.0 and \
                        not xbmc.getCondVisibility('System.ScreenSaverActive'):
                    break
                self.monitor.waitForAbort(0.2)
        finally:
            self.close()

    def exit(self):
        """Called from Kodi callbacks (a key, or the screensaver being woken)."""
        self.stop.set()

    def stopped(self):
        return self.stop.is_set() or self.monitor.abortRequested()

    def close(self):
        if self.app is not None:
            self.app.close()
        if self.thread is not None and self.thread.is_alive():
            self.thread.join(3.0)
        self.thread = None
        self.close_window()
        self.app = None
        try:
            del self.window
        except Exception:
            pass
        self.window = None

    def close_window(self):
        """Close without waiting on Kodi's main thread: Dialog.Close is only posted, and does
        nothing if Kodi has already closed the window."""
        if self.dialog_id:
            xbmc.executebuiltin('Dialog.Close(%d,true)' % self.dialog_id)
            self.monitor.waitForAbort(0.3)
        elif self.window is not None:
            self.window.close()      # before onInit: nothing is running yet


def main():
    Screensaver().run()
