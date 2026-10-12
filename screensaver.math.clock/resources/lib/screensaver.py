"""The screensaver window: a pool of image controls that show typeset glyphs.

Every second the clock thread works out which rows changed, typesets their new puzzles
(texmath), turns them into screen rectangles (clockface) and points pooled image controls
at the glyph PNGs. Kodi does the fading. Nothing is drawn in Python, so a Fire TV Stick
keeps up easily.
"""

import datetime
import os
import random
import threading
import time

import xbmc
import xbmcaddon
import xbmcgui

from . import clockface, config, splash, texmath

ADDON_ID = config.ADDON_ID
FADE_MS = 450           # rows that change once a minute
FADE_SECONDS_MS = 200   # the seconds row: Kodi redraws every frame while anything fades
POOL_START = 320
POOL_GROW = 80
REFRESH_SECONDS = [60, 30, 10]
SPLASH_MAX_SECONDS = 15.0


def log(message, level=xbmc.LOGINFO):
    xbmc.log('[%s] %s' % (ADDON_ID, message), level)


def read_settings(addon):
    try:
        st = addon.getSettings()   # Kodi 20+
        getters = {'boolean': st.getBool, 'integer': st.getInt}
    except AttributeError:
        getters = {'boolean': addon.getSettingBool, 'integer': addon.getSettingInt}
    return config.read(getters)


def anim_fade(start, end, ms):
    return [('conditional', 'effect=fade start=%d end=%d time=%d condition=true' % (start, end, ms))]


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
            self.app.attach(self)

    def onAction(self, action):
        self.app.exit()


class Screensaver(object):
    def __init__(self):
        addon = xbmcaddon.Addon(ADDON_ID)
        self.path = addon.getAddonInfo('path')
        self.media = os.path.join(self.path, 'resources', 'media')
        self.white = os.path.join(self.media, 'white.png')
        self.s = read_settings(addon)
        self.rng = random.Random()
        self.stop = threading.Event()
        self.monitor = ExitMonitor(self.exit)
        self.window = None
        self.thread = None
        self.splash = None
        self.free = []
        self.shown = {}         # slot -> controls on screen
        self.fading = []        # controls fading out, released on the next tick
        self.settling = []      # controls fading in; their animation is cleared next tick
        self.decor_key = None
        self.colour_key = None
        self.background = None

    # ------------------------------------------------------------ lifecycle

    def run(self):
        self.window = SaverWindow('screensaver-mathclock.xml', self.path, 'Default', '1080i', app=self)
        try:
            self.window.doModal()
        finally:
            self.stop.set()
            if self.splash:
                self.splash.close()
            if self.thread:
                self.thread.join(2.0)
            del self.window
            del self.monitor

    def attach(self, window):
        self.background = xbmcgui.ControlImage(0, 0, clockface.W, clockface.H, self.white, aspectRatio=0)
        window.addControl(self.background)
        self.grow(POOL_START)
        self.splash = splash.Splash(window, self.media, 'FFFF8A65', SPLASH_MAX_SECONDS, log)
        self.thread = threading.Thread(target=self.clock_loop, name='mathclock')
        self.thread.daemon = True
        self.thread.start()

    def exit(self):
        if not self.stop.is_set():
            self.stop.set()
            if self.window:
                self.window.close()

    def stopped(self):
        return self.stop.is_set() or self.monitor.abortRequested()

    # ------------------------------------------------------------ control pool

    def grow(self, n):
        controls = [xbmcgui.ControlImage(0, 0, 1, 1, self.white, aspectRatio=0) for _ in range(n)]
        self.window.addControls(controls)
        for c in controls:
            c.setVisible(False)
        self.free.extend(controls)

    def acquire(self, n):
        if len(self.free) < n:
            self.grow(max(POOL_GROW, n - len(self.free)))
        taken, self.free = self.free[:n], self.free[n:]
        return taken

    def show(self, slot, rects, colour, fade):
        """Replace what slot shows with rects [(glyph or None, x, y, w, h)]; fade is a
        cross-fade time in ms, or 0 to cut."""
        controls = self.acquire(len(rects))
        for c, (name, x, y, w, h) in zip(controls, rects):
            c.setImage(os.path.join(self.media, 'glyphs', name + '.png') if name else self.white)
            c.setPosition(x, y)
            c.setWidth(w)
            c.setHeight(h)
            c.setColorDiffuse(colour)
            c.setAnimations(anim_fade(0, 100, fade) if fade else [])
            c.setVisible(True)
        if fade:
            self.settling.extend(controls)
        old = self.shown.get(slot, [])
        self.shown[slot] = controls
        if fade:
            for c in old:
                c.setAnimations(anim_fade(100, 0, fade))
            self.fading.extend(old)
        else:
            self.release(old)

    def release(self, controls):
        for c in controls:
            c.setVisible(False)
            c.setAnimations([])
        self.free.extend(controls)

    # ------------------------------------------------------------ the clock

    def clock_loop(self):
        try:
            self._clock_loop()
        except Exception:
            import traceback
            log('clock thread failed:\n' + traceback.format_exc(), xbmc.LOGERROR)

    def _clock_loop(self):
        s = self.s
        kinds = clockface.rows(s)
        refresh = REFRESH_SECONDS[s['refresh']]
        fade = s['transition'] == 0
        log('started: rows %s, equations %d, colours %d' % (','.join(kinds), s['equation_set'], s['colours']))
        last_minute = None
        start = time.time()
        while not self.stopped():
            now = datetime.datetime.now()
            minute = now.replace(second=0, microsecond=0)
            # A finished conditional animation stays attached and keeps Kodi redrawing
            # every frame (about 40 % CPU instead of 3 % on a Mac), so detach them.
            self.release(self.fading)
            for c in self.settling:
                c.setAnimations([])
            self.fading, self.settling = [], []
            pal = clockface.palette(s, now)
            if pal['bg'] != self.colour_key:
                self.colour_key = pal['bg']
                self.background.setColorDiffuse(pal['bg'])
            if minute != last_minute:
                self.geo = clockface.Geometry(len(kinds), s['text_size'], clockface.drift(s, time.time() - start))
                self.decor(kinds, pal)
            new_minute = minute != last_minute
            for i, kind in enumerate(kinds):
                if kind == 'seconds' or new_minute or now.second % refresh == 0:
                    latex = clockface.puzzle(kind, now, s, self.rng)
                    ms = (FADE_SECONDS_MS if kind == 'seconds' else FADE_MS) if fade and last_minute else 0
                    self.show(kind, self.geo.rects(texmath.typeset(latex), i), pal['text'], ms)
            last_minute = minute
            self.splash.done()
            # Wake just after the next whole second.
            self.stop.wait(1.02 - (time.time() % 1.0))

    def decor(self, kinds, pal):
        """Labels, separators and the 24h badge: redrawn only when they move or recolour."""
        s, geo = self.s, self.geo
        key = (geo.dx, geo.dy, pal['label'], pal['rule'], pal['badge'])
        if key == self.decor_key:
            return
        self.decor_key = key
        labels = []
        if s['labels']:
            for i, kind in enumerate(kinds):
                labels += geo.label(clockface.ROWS[kind][0], i)
        self.show('labels', labels, pal['label'], 0)
        self.show('rules', [(None,) + r for r in geo.separators()] if s['separators'] else [], pal['rule'], 0)
        self.show('badge', geo.badge() if s['military'] and s['military_badge'] else [], pal['badge'], 0)


def run():
    Screensaver().run()
