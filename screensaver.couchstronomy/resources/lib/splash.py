"""Loading splash: the add-on's art (media/splash.png, from tools/make_splash.py) centred on
black, with pulsing dots, until the screensaver has something to show.

Kodi draws controls in the order they were added, so the screensaver adds its own controls
first and then makes the Splash, which goes on top. Call done() once the first real frame is
up; the splash then fades out, but never before MIN_SECONDS (so a fast start doesn't flash it)
and never later than max_seconds (so a feed that never answers doesn't leave it up). Call
close() when the screensaver ends: Kodi waits for every thread, daemon or not, before it lets
a script finish, so a pending timer would hold the script open until Kodi kills it.
The same file is in every screensaver add-on; keep the copies identical.
"""

import os
import threading
import time

import xbmcgui

W, H = 1920, 1080
ART_W, ART_H = 960, 760
DOTS_W, DOTS_H = 120, 24
MIN_SECONDS = 2.5   # Kodi loads the art asynchronously; on a Fire TV Stick it takes about a second
FADE_IN_MS = 400
FADE_OUT_MS = 700


def _fade(start, end, ms, extra=''):
    return [('conditional', 'effect=fade start=%d end=%d time=%d %scondition=true' % (start, end, ms, extra))]


class Splash(object):
    def __init__(self, window, media, accent='FFFFFFFF', max_seconds=30.0, log=lambda msg: None):
        self.started = time.time()
        self.log = log
        self.lock = threading.Lock()
        self.state = 'shown'   # -> 'leaving' -> 'gone'
        self.timers = []
        x, y = (W - ART_W) // 2, (H - ART_H) // 2 - 30
        self.black = xbmcgui.ControlImage(-50, -50, W + 100, H + 100, os.path.join(media, 'white.png'),
                                          aspectRatio=0, colorDiffuse='FF000000')
        self.art = xbmcgui.ControlImage(x, y, ART_W, ART_H, os.path.join(media, 'splash.png'), aspectRatio=0)
        self.dots = xbmcgui.ControlImage((W - DOTS_W) // 2, y + ART_H + 4, DOTS_W, DOTS_H,
                                         os.path.join(media, 'splash_dots.png'), aspectRatio=0,
                                         colorDiffuse=accent)
        self.controls = [self.black, self.art, self.dots]
        window.addControls(self.controls)
        self.art.setAnimations(_fade(0, 100, FADE_IN_MS))
        self.dots.setAnimations(_fade(100, 20, 900, 'pulse=true '))
        self.timeout = self._timer(max_seconds, self._timeout)

    def _timer(self, seconds, fn):
        t = threading.Timer(seconds, fn)
        t.daemon = True
        t.start()
        self.timers.append(t)
        return t

    def close(self):
        for t in self.timers:
            t.cancel()

    def _timeout(self):
        if self.state == 'shown':
            self.log('splash: still loading after %.0f s, showing the screensaver anyway'
                     % (time.time() - self.started))
            self.done()

    def done(self):
        """The first frame is up: fade the splash out (after MIN_SECONDS). Safe to call often."""
        with self.lock:
            if self.state != 'shown':
                return
            self.state = 'leaving'
        self.timeout.cancel()
        wait = MIN_SECONDS - (time.time() - self.started)
        if wait > 0:
            self._timer(wait, self._leave)
        else:
            self._leave()

    def _leave(self):
        self.log('splash: shown for %.1f s' % (time.time() - self.started))
        try:
            for c in self.controls:
                c.setAnimations(_fade(100, 0, FADE_OUT_MS))
        except Exception:
            return   # the window has closed
        self._timer(FADE_OUT_MS / 1000.0 + 0.1, self._remove)

    def _remove(self):
        # A finished conditional animation keeps Kodi redrawing every frame; hiding the
        # controls and dropping their animations stops that.
        self.state = 'gone'
        try:
            for c in self.controls:
                c.setVisible(False)
                c.setAnimations([])
        except Exception:
            pass
