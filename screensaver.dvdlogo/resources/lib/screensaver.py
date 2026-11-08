"""The screensaver window: one image of the DVD logo, slid around by Kodi.

Python only plans; Kodi moves the logo. Each leg runs from one wall (or one tick of a
last-second swerve) to the next as a linear Kodi slide animation, so Python wakes a few times
a minute and the movement is smooth at the display's rate.

The motion lives in bounce.py, which treats the bouncing as a straight line folded back into
the screen; that is what makes an exact corner hit possible with only a few degrees of course
correction at a bounce.
"""

import colorsys
import os
import random
import threading
import time

import xbmc
import xbmcaddon
import xbmcgui

from . import bounce, config

ADDON_ID = config.ADDON_ID
PROP = 'dvdlogo.'
VEER_LEAD = 0.5               # seconds before the corner the near miss swerves


def log(message, level=xbmc.LOGINFO):
    xbmc.log('[%s] %s' % (ADDON_ID, message), level)


def read_settings(addon):
    try:
        st = addon.getSettings()   # Kodi 20+
        getters = {'boolean': st.getBool, 'integer': st.getInt, 'string': st.getString}
    except AttributeError:
        getters = {'boolean': addon.getSettingBool, 'integer': addon.getSettingInt,
                   'string': addon.getSetting}
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


class Screensaver(object):
    def __init__(self):
        addon = xbmcaddon.Addon(ADDON_ID)
        self.path = addon.getAddonInfo('path')
        self.media = os.path.join(self.path, 'resources', 'media')
        self.s = read_settings(addon)
        s = self.s
        self.logo_w, self.logo_h = config.logo_pixels(s)
        self.field_w = config.W - self.logo_w
        self.field_h = config.H - self.logo_h
        self.rng = random.Random()
        self.motion = bounce.Motion(self.field_w, self.field_h, config.speed_pixels(s), self.rng)
        self.home = xbmcgui.Window(10000)
        self.stop = threading.Event()
        self.monitor = ExitMonitor(self.exit)
        self.window = None
        self.dialog_id = 0
        self.logo = None
        self.thread = None
        self.colour = None
        self.corner_hits = 0
        self.attempt = None
        self.pending = False
        self.trick = s['trick']
        self.fake_next = self.trick == config.MISS
        self.next_try_at = 0.0

    # ------------------------------------------------------------ lifecycle

    def run(self):
        """show() and wait here rather than doModal(): when Kodi itself wakes the screensaver
        (a RunScript, a screenshot) it closes the window without telling Python, doModal()
        then never returns and Kodi kills the script after 5 seconds. Waiting in a loop that
        also watches System.ScreenSaverActive always ends."""
        self.window = SaverWindow('screensaver-dvdlogo.xml', self.path, 'Default', '1080i', app=self)
        try:
            self.window.show()
            started = time.time()
            next_rainbow = 0.0
            while not self.stopped():
                if time.time() - started > 2.0 and not xbmc.getCondVisibility('System.ScreenSaverActive'):
                    break
                if self.s['colour_mode'] == config.COLOUR_RAINBOW:
                    now = time.time()
                    if now >= next_rainbow:
                        next_rainbow = now + 0.25
                        self.set_colour(self.rainbow_colour(now))
                self.monitor.waitForAbort(0.2)
        finally:
            self.stop.set()
            self.close_window()
            if self.thread:
                self.thread.join(2.0)
            self.home.clearProperty(PROP + 'bg')
            log('closed after %d corner hit%s' % (self.corner_hits, '' if self.corner_hits == 1 else 's'))
            del self.window
            del self.monitor

    def attach(self, window):
        s = self.s
        self.next_try_at = time.time() + min(config.FIRST_TRY_SECONDS, s['trick_every'])
        x, y = self.rng.uniform(0, self.field_w), self.rng.uniform(0, self.field_h)
        self.motion.start(x, y)
        self.base = (int(round(x)), int(round(y)))   # the control never leaves this spot
        self.home.setProperty(PROP + 'bg', s['background'])
        white = os.path.join(self.media, 'white.png')
        self.background = xbmcgui.ControlImage(-60, -60, config.W + 120, config.H + 120, white,
                                               aspectRatio=0)
        self.background.setColorDiffuse(s['background'])
        self.logo = xbmcgui.ControlImage(self.base[0], self.base[1], self.logo_w, self.logo_h,
                                         os.path.join(self.media, 'dvd.png'), aspectRatio=0)
        self.set_colour(self.initial_colour())
        window.addControls([self.background, self.logo])
        log('logo %dx%d, field %dx%d, speed %.0f px/s, trick %d, start %.0f,%.0f' % (
            self.logo_w, self.logo_h, self.field_w, self.field_h, self.motion.speed,
            self.trick, x, y))
        self.thread = threading.Thread(target=self.animate, name='dvdlogo')
        self.thread.daemon = True
        self.thread.start()

    def close_window(self):
        """Close the window without waiting for Kodi's main thread. Window.close() waits for
        the main thread while holding Python's lock; if the main thread wants that lock at the
        same moment (it does when it stops this script because a screensaver is being started
        again), both wait forever and Kodi freezes. Dialog.Close is only posted to the main
        thread (and does nothing if Kodi already closed the window)."""
        if self.dialog_id:
            xbmc.executebuiltin('Dialog.Close(%d,true)' % self.dialog_id)
            self.monitor.waitForAbort(0.3)
        elif self.window:
            self.window.close()      # before onInit: nothing is running yet

    def stopped(self):
        return self.stop.is_set() or self.monitor.abortRequested()

    def exit(self):
        """Called from Kodi callbacks (a key, or the screensaver being woken)."""
        self.stop.set()      # run() notices and closes the window

    # ------------------------------------------------------------ colour

    def rainbow_colour(self, now):
        r, g, b = colorsys.hsv_to_rgb((now * 0.04) % 1.0, 0.65, 1.0)
        return 'FF%02X%02X%02X' % (int(r * 255), int(g * 255), int(b * 255))

    def random_colour(self):
        r, g, b = colorsys.hsv_to_rgb(self.rng.random(), 0.80, 1.0)
        return 'FF%02X%02X%02X' % (int(r * 255), int(g * 255), int(b * 255))

    def initial_colour(self):
        mode = self.s['colour_mode']
        if mode == config.COLOUR_WHITE:
            return 'FFFFFFFF'
        if mode == config.COLOUR_FIXED:
            return self.s['colour']
        if mode == config.COLOUR_RAINBOW:
            return self.rainbow_colour(time.time())
        if mode == config.COLOUR_BOUNCE:
            return self.random_colour()
        return 'FFFFFFFF'        # corner hits: start classic white, colour up when it lands one

    def set_colour(self, colour):
        if colour and colour != self.colour:
            self.colour = colour
            if self.logo is not None:
                self.logo.setColorDiffuse(colour)

    # ------------------------------------------------------------ the loop

    def animate(self):
        try:
            self.animate_loop()
        except Exception:
            import traceback
            log('animation thread failed:\n' + traceback.format_exc(), xbmc.LOGERROR)
        finally:
            # However the loop ended (a key, Kodi stopping the script, an error), the window
            # must close or Kodi waits for this script until it gives up on it.
            if not self.stop.is_set():
                self.stop.set()
            self.close_window()

    def animate_loop(self):
        while not self.stopped():
            dt, kind = self.motion.next_leg()
            dt = max(dt, 0.001)
            before = self.motion.point()
            self.motion.advance(dt, kind)
            after = self.motion.point()
            self.slide(before, after, dt)
            if not self.wait(dt):
                return
            self.event(kind)

    def slide(self, before, after, seconds):
        """Animate the logo from `before` to `after`; Kodi does the interpolation.

        The control itself stays where it was created. Kodi draws it at its position plus the
        slide's offset, so the offsets are the absolute screen positions relative to that
        base. One call starts each leg: moving the control and then animating it are two
        calls, and a frame rendered between them draws the logo at the far end of the new
        leg for a flash.
        """
        x0, y0, x1, y1 = bounce.slide_offsets(self.base, before, after)
        ms = max(1, int(round(seconds * 1000)))
        self.logo.setAnimations([
            ('conditional', 'effect=slide start=%d,%d end=%d,%d time=%d tween=linear condition=true'
             % (x0, y0, x1, y1, ms))])

    def wait(self, seconds):
        deadline = time.time() + seconds
        while not self.stopped():
            left = deadline - time.time()
            if left <= 0:
                return True
            self.stop.wait(min(left, 0.05))
        return False

    def event(self, kind):
        if kind == 'corner':
            self.corner_hit()
        elif kind == 'veer':
            self.near_miss()
        elif kind == 'wall':
            self.wall_bounce()
        elif kind == 'turn':
            if self.motion.turning == 0:
                self.finished_attempt()

    def wall_bounce(self):
        mode = self.s['colour_mode']
        if mode == config.COLOUR_BOUNCE:
            self.set_colour(self.random_colour())
        self.try_trick()

    def corner_hit(self):
        self.corner_hits += 1
        log('corner hit #%d' % self.corner_hits)
        if self.s['colour_mode'] in (config.COLOUR_BOUNCE, config.COLOUR_CORNER):
            self.set_colour(self.random_colour())
        if self.attempt is not None:
            self.finished_attempt()

    def near_miss(self):
        log('veer at the last second')
        if self.s['colour_mode'] == config.COLOUR_BOUNCE:
            self.set_colour(self.random_colour())
        if self.attempt is not None:
            self.finished_attempt()

    # ------------------------------------------------------------ corner tricks

    def try_trick(self):
        if self.trick == config.BOUNCE or self.attempt is not None or self.motion.turning:
            return
        if not self.pending and time.time() >= self.next_try_at:
            self.pending = True
        if not self.pending:
            return
        fake = self.trick == config.MISS or (self.trick == config.ALTERNATE and self.fake_next)
        target = (self.motion.aim_near_miss(VEER_LEAD) if fake else self.motion.aim())
        if target is None:
            return                      # try again at the next bounce
        self.pending = False
        self.attempt = {'fake': fake}
        log('aiming at corner (%s)' % ('near miss' if fake else 'hit'))

    def finished_attempt(self):
        attempt, self.attempt = self.attempt, None
        if attempt is None:
            return
        self.pending = False
        self.next_try_at = time.time() + self.s['trick_every']
        if self.trick == config.ALTERNATE:
            self.fake_next = not attempt['fake']


def run():
    Screensaver().run()
