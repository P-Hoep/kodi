"""The screensaver window: a grid of glyph images that Kodi fades on and off.

Each cell has an unlit glyph, an optional glow and a lit glyph, created once. The lit ones are
visible when the Home window property wordclock.c<n> is set and the unlit one when it is not,
and each has Visible/Hidden fade animations, so when the time changes Python only flips a few
properties and Kodi does the fading. A thread wakes every second to work out the phrase and
the colours (day/night blend, rainbow cycle, dimming) and to move the clock as it drifts.
"""

import datetime
import os
import threading
import time

import xbmc
import xbmcaddon
import xbmcgui

from . import config, grid, look

ADDON_ID = config.ADDON_ID
PROP = 'wordclock.'
FADE_MS = 800
RIPPLE_MS = 12          # per cell, in reading order
CELLS = grid.SIZE * grid.SIZE
CARD_IDS = (11, 12)


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


def fades(transition, index):
    if transition == 2:
        return []
    delay = ' delay=%d' % (index * RIPPLE_MS) if transition == 1 else ''
    return [('Visible', 'effect=fade start=0 end=100 time=%d%s' % (FADE_MS, delay)),
            ('Hidden', 'effect=fade start=100 end=0 time=%d%s' % (FADE_MS, delay))]


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
        self.s = read_settings(addon)
        self.home = xbmcgui.Window(10000)
        self.stop = threading.Event()
        self.monitor = ExitMonitor(self.exit)
        self.window = None
        self.thread = None
        self.props = {}
        self.diffuse = {}
        self.offset = None

    # ------------------------------------------------------------ lifecycle

    def run(self):
        self.window = SaverWindow('screensaver-wordclock.xml', self.path, 'Default', '1080i', app=self)
        try:
            self.window.doModal()
        finally:
            self.stop.set()
            if self.thread:
                self.thread.join(2.0)
            for key in list(self.props):
                self.home.clearProperty(PROP + key)
            del self.window
            del self.monitor

    def attach(self, window):
        s = self.s
        self.set_prop('frame', str(s['frame']))
        font = os.path.join(self.media, 'fonts', config.FONTS[s['font']][1])
        lit_weight = 'b' if s['weight'] == 0 else 'r'
        lay = look.Layout(s)
        self.unlit, self.glow, self.lit = [], [], []
        for i in range(CELLS):
            letter = grid.ROWS[i // grid.SIZE][i % grid.SIZE]
            self.unlit.append(self.image(os.path.join(font, letter + 'r.png'), lay.letter_rect(i)))
            if s['glow']:
                self.glow.append(self.image(os.path.join(font, letter + 'g' + lit_weight + '.png'), lay.glow_rect(i)))
            self.lit.append(self.image(os.path.join(font, letter + lit_weight + '.png'), lay.letter_rect(i)))
        self.dots_off, self.dots_on = [], []
        if s['dots']:
            dot = os.path.join(self.media, 'dot.png')
            self.dots_off = [self.image(dot, r) for r in lay.dot_rects()]
            self.dots_on = [self.image(dot, r) for r in lay.dot_rects()]
        controls = self.unlit + self.glow + self.lit + self.dots_off + self.dots_on
        window.addControls(controls)
        cond = 'String.IsEmpty(Window(Home).Property(%s%%s))' % PROP
        for i in range(CELLS):
            anims = fades(s['transition'], i)
            key = 'c%d' % i
            self.unlit[i].setVisibleCondition(cond % key)
            self.unlit[i].setAnimations(anims)
            for c in ([self.glow[i]] if self.glow else []) + [self.lit[i]]:
                c.setVisibleCondition('!' + cond % key)
                c.setAnimations(anims)
        for k in range(len(self.dots_on)):
            self.dots_off[k].setVisibleCondition(cond % ('d%d' % k))
            self.dots_on[k].setVisibleCondition('!' + cond % ('d%d' % k))
            for c in (self.dots_off[k], self.dots_on[k]):
                c.setAnimations(fades(s['transition'], 0))
        self.thread = threading.Thread(target=self.clock_loop, name='wordclock')
        self.thread.daemon = True
        self.thread.start()

    def image(self, path, rect):
        x, y, w, h = rect
        return xbmcgui.ControlImage(x, y, w, h, path, aspectRatio=0)

    def exit(self):
        if not self.stop.is_set():
            self.stop.set()
            if self.window:
                self.window.close()

    def stopped(self):
        return self.stop.is_set() or self.monitor.abortRequested()

    # ------------------------------------------------------------ helpers

    def set_prop(self, key, value):
        if self.props.get(key) != value:
            self.props[key] = value
            self.home.setProperty(PROP + key, value)

    def colour(self, control, value):
        if self.diffuse.get(id(control)) != value:
            self.diffuse[id(control)] = value
            control.setColorDiffuse(value)

    def now(self):
        """The real time, or the test hook's (Home property wordclock.demo = HH:MM[:SS])."""
        demo = self.home.getProperty(PROP + 'demo')
        now = datetime.datetime.now()
        if demo:
            try:
                parts = [int(p) for p in demo.split(':')] + [0]
                return now.replace(hour=parts[0], minute=parts[1], second=parts[2], microsecond=0)
            except (ValueError, IndexError):
                pass
        return now

    # ------------------------------------------------------------ the clock

    def clock_loop(self):
        try:
            self._clock_loop()
        except Exception:
            import traceback
            log('clock thread failed:\n' + traceback.format_exc(), xbmc.LOGERROR)

    def _clock_loop(self):
        s = self.s
        options = config.clock_options(s)
        start = time.time()
        phase, blend_from, blend_start = None, None, 0.0
        last_text = None
        log('started: font %s, palettes %d/%d, mode %d' % (config.FONTS[s['font']][1], s['night_palette'],
                                                           s['day_palette'], s['mode']))
        while not self.stopped():
            now = self.now()
            # Colours: blend toward the new palette when day turns to night or back.
            target_phase = look.phase(s, now)
            target = look.palette(s, target_phase)
            if phase is None:
                phase, current = target_phase, target
            elif target_phase != phase:
                blend_from, blend_start, phase = current, time.time(), target_phase
            if blend_from is not None:
                t = min(1.0, (time.time() - blend_start) / look.BLEND_SECONDS)
                current = look.mix(blend_from, target, t)
                if t >= 1.0:
                    blend_from = None
            else:
                current = target
            c = look.finish(s, current, look.dim_factor(s, now))
            words, dots = grid.phrase(now.hour, now.minute, now.second, options)
            self.move(look.drift(s, time.time() - start))
            self.paint(c, words, now.hour * 3600 + now.minute * 60 + now.second)
            lit = grid.lit_cells(words)
            for i in range(CELLS):
                self.set_prop('c%d' % i, '1' if i in lit else '')
            for k in range(len(self.dots_on)):
                self.set_prop('d%d' % k, '1' if k < dots else '')
            text = grid.text(words)
            if text != last_text:
                log('%s -> %s' % (now.strftime('%H:%M:%S'), text), xbmc.LOGDEBUG)
                last_text = text
            # Wake just after the next whole second.
            self.stop.wait(1.02 - (time.time() % 1.0))

    def paint(self, c, words, seconds):
        self.set_prop('bg', c['bg'])
        self.set_prop('card', c['card'])
        for ctl in self.unlit + self.dots_off:
            self.colour(ctl, c['unlit'])
        for ctl in self.dots_on:
            self.colour(ctl, c['lit'])
        if self.s['lit_effect'] == 0:
            cell_colour = dict((i, c['lit']) for i in range(CELLS))
        else:
            # Only cells in the current phrase change colour; the ones fading out keep theirs.
            cell_colour = {}
            for w in words:
                for i in grid.cells(w):
                    cell_colour[i] = look.word_colour(self.s, w, c['lit'], seconds)
        glow_alpha = look.GLOW_ALPHA[self.s['glow']]
        for i, value in cell_colour.items():
            self.colour(self.lit[i], value)
            if self.glow:
                self.colour(self.glow[i], look.with_alpha(value, glow_alpha))

    def move(self, offset):
        if offset == self.offset:
            return
        self.offset = offset
        lay = look.Layout(self.s, offset)
        x, y, w, h = lay.card
        for cid in CARD_IDS:
            card = self.window.getControl(cid)
            card.setPosition(x, y)
            card.setWidth(w)
            card.setHeight(h)
        for i in range(CELLS):
            for ctl, rect in ((self.unlit[i], lay.letter_rect(i)), (self.lit[i], lay.letter_rect(i))) + \
                    (((self.glow[i], lay.glow_rect(i)),) if self.glow else ()):
                ctl.setPosition(rect[0], rect[1])
        for k, rect in enumerate(lay.dot_rects() if self.dots_on else []):
            self.dots_off[k].setPosition(rect[0], rect[1])
            self.dots_on[k].setPosition(rect[0], rect[1])


def run():
    Screensaver().run()
