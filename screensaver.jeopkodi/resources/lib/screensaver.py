"""The screensaver window: clue slides built from pre-rendered glyph images.

Python adds two pools of image controls once (one for the category and dollar value, one for the
clue and then the response) and for each slide only moves, resizes and re-textures the ones it
needs. The pools fade in and out through Home window properties, so Kodi does the fading and
Python just flips a property, like the Word Clock does. A thread works through the clues:
header and clue in, wait, clue out, response in, wait, everything out, next clue.
"""

import os
import threading
import time

import xbmc
import xbmcaddon
import xbmcgui

from . import clues, config, layout

ADDON_ID = config.ADDON_ID
PROP = 'jeopkodi.'
FADE_MS = 350
HEADER_POOL = 70
MAIN_POOL = 250
SCREEN_W, SCREEN_H = 1920, 1080
YELLOW_NAME, WHITE_NAME = 'y', 'w'


def log(message, level=xbmc.LOGINFO):
    xbmc.log('[%s] %s' % (ADDON_ID, message), level)


def read_settings(addon):
    try:
        st = addon.getSettings()   # Kodi 20+
        getters = {'boolean': st.getBool, 'integer': st.getInt}
    except AttributeError:
        getters = {'boolean': addon.getSettingBool, 'integer': addon.getSettingInt}
    return config.read(getters)


class ExitMonitor(xbmc.Monitor):
    def __init__(self, on_exit):
        xbmc.Monitor.__init__(self)
        self.on_exit = on_exit

    def onScreensaverDeactivated(self):
        self.on_exit()


class SaverWindow(xbmcgui.WindowXMLDialog):
    def __init__(self, *args, **kwargs):
        self.app = kwargs['app']
        self.built = False

    def onInit(self):
        if not self.built:
            self.built = True
            self.app.dialog_id = xbmcgui.getCurrentWindowDialogId()
            self.app.attach(self)

    def onAction(self, action):
        self.app.exit()


class Pool(object):
    """A fixed set of image controls that show glyphs for one piece of text at a time."""

    def __init__(self, count, prop, glyph_dir):
        self.prop = prop
        self.dir = glyph_dir
        blank = os.path.join(glyph_dir, '..', 'white.png')
        self.controls = [xbmcgui.ControlImage(-200, -200, 1, 1, blank, aspectRatio=0) for _ in range(count)]
        self.used = 0

    def attach(self, window):
        window.addControls(self.controls)
        cond = 'String.IsEqual(Window(Home).Property(%s%s),1)' % (PROP, self.prop)
        for c in self.controls:
            c.setVisibleCondition(cond)
            c.setAnimations([('Visible', 'effect=fade start=0 end=100 time=%d' % FADE_MS),
                             ('Hidden', 'effect=fade start=100 end=0 time=%d' % FADE_MS)])
            c.setVisible(False)

    def show(self, rects, colour):
        """rects: [(code, x, y, w, h)] from layout.place"""
        self.show_two(rects, colour, [], colour)

    def show_two(self, rects_a, colour_a, rects_b, colour_b):
        """Two batches of glyphs, each in its own colour."""
        rects = [(colour_a,) + r for r in rects_a] + [(colour_b,) + r for r in rects_b]
        n = min(len(rects), len(self.controls))
        for i in range(n):
            colour, code, x, y, w, h = rects[i]
            c = self.controls[i]
            c.setImage(os.path.join(self.dir, colour, '%04x.png' % code), False)
            c.setPosition(int(round(x)), int(round(y)))
            c.setWidth(max(1, int(round(w))))
            c.setHeight(max(1, int(round(h))))
            if i >= self.used:
                c.setVisible(True)
        for i in range(n, self.used):
            self.controls[i].setVisible(False)
        self.used = n


class Screensaver(object):
    def __init__(self):
        addon = xbmcaddon.Addon(ADDON_ID)
        self.path = addon.getAddonInfo('path')
        self.media = os.path.join(self.path, 'resources', 'media')
        self.s = read_settings(addon)
        self.home = xbmcgui.Window(10000)
        self.stop = threading.Event()
        self.monitor = ExitMonitor(self.exit)
        self.window = None
        self.dialog_id = 0
        self.thread = None
        self.props = {}
        self.font = layout.Font(os.path.join(self.media, 'glyphs', 'metrics.json'))

    # ------------------------------------------------------------ lifecycle

    def run(self):
        """show() and wait here rather than doModal(): when Kodi itself wakes the screensaver
        (a RunScript, a screenshot, a notification) it closes the window without telling
        Python, and doModal() then never returns, so Kodi kills the script. Waiting in a loop
        that also watches System.ScreenSaverActive always ends."""
        self.window = SaverWindow('screensaver-jeopkodi.xml', self.path, 'Default', '1080i', app=self)
        try:
            self.window.show()
            started = time.time()
            while not self.stopped():
                if time.time() - started > 2.0 and not xbmc.getCondVisibility('System.ScreenSaverActive'):
                    break
                self.monitor.waitForAbort(0.2)
        finally:
            self.stop.set()
            self.close_window()
            if self.thread:
                self.thread.join(2.0)
            for key in list(self.props):
                self.home.clearProperty(PROP + key)
            log('closed')
            del self.window
            del self.monitor

    def attach(self, window):
        glyphs = os.path.join(self.media, 'glyphs')
        self.header = Pool(HEADER_POOL, 'header', glyphs)
        self.main = Pool(MAIN_POOL, 'main', glyphs)
        self.header.attach(window)
        self.main.attach(window)
        dim = int(round(self.s['dim'] * 2.55))
        self.set_prop('dim', '%02X000000' % dim)
        self.thread = threading.Thread(target=self.loop, name='jeopkodi')
        self.thread.daemon = True
        self.thread.start()

    def exit(self):
        """Called from Kodi callbacks (a key, or the screensaver being woken)."""
        self.stop.set()      # run() notices and closes the window

    def close_window(self):
        """Close without waiting for Kodi's main thread: Window.close() holds Python's lock
        while it waits, and that deadlocks if Kodi restarts the screensaver at that moment.
        Dialog.Close is only posted to the main thread (and does nothing if Kodi already
        closed the window)."""
        if self.dialog_id:
            xbmc.executebuiltin('Dialog.Close(%d,true)' % self.dialog_id)
            self.monitor.waitForAbort(0.3)
        elif self.window:
            self.window.close()

    def stopped(self):
        return self.stop.is_set() or self.monitor.abortRequested()

    def wait(self, seconds):
        end = time.time() + seconds
        while not self.stopped():
            left = end - time.time()
            if left <= 0:
                return True
            self.stop.wait(min(left, 0.1))
        return False

    def set_prop(self, key, value):
        if self.props.get(key) != value:
            self.props[key] = value
            self.home.setProperty(PROP + key, value)

    # ------------------------------------------------------------ the show

    def loop(self):
        try:
            self._loop()
        except Exception:
            import traceback
            log('failed:\n' + traceback.format_exc(), xbmc.LOGERROR)

    def _loop(self):
        s = self.s
        db = os.path.join(self.path, 'resources', 'data', 'clues.db')
        source = clues.Clues(db, config.levels(s), s['daily'])
        log('started: levels %s, %d clues' % (config.levels(s), source.count))
        try:
            while not self.stopped():
                level, value, daily, category, clue, response = source.next()
                self.slide(level, value, daily, category, clue, response)
        finally:
            source.close()

    def slide(self, level, value, daily, category, clue, response):
        s = self.s
        scale = s['text_size'] / 100.0
        top = 0
        if s['show_header']:
            top = self.show_header(level, value, daily, category, scale)
        self.main.show(*self.clue_rects(clue, top, scale))
        self.set_prop('header', '1' if s['show_header'] else '')
        self.set_prop('main', '1')
        seconds = s['clue_seconds']
        if s['read_time']:
            seconds += max(0, len(clue) - 80) * 0.04
        if not self.wait(seconds):
            return
        self.set_prop('main', '')
        if not self.wait(FADE_MS / 1000.0 + 0.1):
            return
        text = clues.response_form(clue, response) if s['form'] else response
        self.main.show(*self.clue_rects(text, top, scale, colour=WHITE_NAME))
        self.set_prop('main', '1')
        if not self.wait(s['response_seconds']):
            return
        self.set_prop('main', '')
        self.set_prop('header', '')
        self.wait(FADE_MS / 1000.0 + 0.25)

    def clue_rects(self, text, top, scale, colour=WHITE_NAME):
        """The glyph rectangles for text centred in the area below the header, and the colour."""
        f = self.font
        area_top = top + 40 if top else 90
        box_w, box_h = 1320, SCREEN_H - area_top - 110
        max_px = 96 * scale
        px, lines = layout.fit(f, text, box_w * 1.0, box_h, max_px, 36 * scale)
        height = layout.block_height(lines, px)
        y = area_top + (box_h - height) / 2.0
        return layout.place(f, lines, px, SCREEN_W / 2.0, y), colour

    def show_header(self, level, value, daily, category, scale):
        """Category in white and the value in yellow, centred at the top; returns the bottom y."""
        f = self.font
        px_cat = 62 * scale
        px, lines = layout.fit(f, category, 1500, px_cat * 1.2, px_cat, 36 * scale)
        rects = layout.place(f, lines, px, SCREEN_W / 2.0, 60)
        bottom = 60 + layout.block_height(lines, px)
        if level == 6:
            label = 'FINAL JEOPARDY!'
        elif daily:
            label = 'DAILY DOUBLE'
        else:
            label = '$%d' % value
        px_val = 84 * scale
        vpx, vlines = layout.fit(f, label, 1500, px_val * 1.3, px_val, 40 * scale)
        vrects = layout.place(f, vlines, vpx, SCREEN_W / 2.0, bottom + 6)
        # Both colours share one pool: white glyphs first, then yellow, drawn as two batches.
        self.header.show_two(rects, WHITE_NAME, vrects, YELLOW_NAME)
        return bottom + 6 + layout.block_height(vlines, vpx)


def run():
    Screensaver().run()
