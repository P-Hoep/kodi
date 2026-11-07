"""The screensaver (spec 6): the tile grid fills the screen without scrolling, renders from
the cache at once and refreshes in the background. Every few minutes the tiles that have
shown the same story longest flip to fresh ones. The grid shifts a few pixels every two
minutes (burn-in protection), can drift slowly, and dims at night. Any input exits at once.
"""

import random
import threading
import time

import xbmc

from .. import SCREENSAVER_ID, kodi, sources, theme
from ..tiles import geometry as g, layouts, styles
from . import screen as sc
from .board import Board
from .hub import layout_ctx
from .worker import FeedWorker

MINUTE = 60.0
BURN_IN_SECONDS = 120.0
DRIFT_SECONDS = 40.0
SPOTLIGHT_SECONDS = 30.0


class ExitMonitor(xbmc.Monitor):
    def __init__(self, on_wake):
        xbmc.Monitor.__init__(self)
        self.on_wake = on_wake

    def onScreensaverDeactivated(self):
        self.on_wake()


class Saver(object):
    def __init__(self):
        self.settings = kodi.read_settings(SCREENSAVER_ID)
        self.store = kodi.store()
        self.rng = random.Random()
        self.lock = threading.Lock()
        self.woken = False
        self.screen = None
        self.monitor = ExitMonitor(self.wake)

    def wake(self):
        with self.lock:
            self.woken = True
            screen = self.screen
        if screen:
            screen.finish()

    def on_input(self, _action_id):
        """Any key, click, touch or mouse move: close now (on Kodi's UI thread)."""
        self.wake()
        return True

    def run(self):
        started = time.time()
        sc.SaverScreen.open(styles.window_xml(self.settings.get('style', 'classic')), self.logic,
                            on_input=self.on_input, props={'ss': '1'})
        kodi.debug('screensaver closed after %.1f s' % (time.time() - started))

    # ------------------------------------------------------------ logic

    def logic(self, screen):
        with self.lock:
            self.screen = screen
            if self.woken:
                return None
        s = self.settings
        started = time.time()
        self.palette = theme.resolve(s, kodi.now())
        self.board = Board(screen, s, self.palette, kodi.relative_strings(), ss=True, rng=self.rng)
        self.board.apply_palette(self.palette)
        self.apply_dim()
        self.feeds = self.store.feeds()
        self.relayout()
        kodi.debug('screensaver on screen in %.2f s (%d tiles)' % (time.time() - started,
                                                                  len(self.board.layout.tiles)))
        worker = FeedWorker(self.store, self.feeds, kodi.fetch_options(s), screen.post)
        worker.start()
        rotate_every = max(1, s.get('rotation_min', 3)) * MINUTE
        now = time.time()
        timers = {'minute': now + MINUTE, 'rotate': now + rotate_every, 'burn': now + BURN_IN_SECONDS,
                  'drift': now + DRIFT_SECONDS, 'page': now + SPOTLIGHT_SECONDS}
        self.dirty = False
        try:
            while True:
                event = screen.wait(0.05)
                now = time.time()
                if event is not None and event[0] == 'feed':
                    self.on_feed(event[1])
                if now >= timers['minute']:
                    timers['minute'] = now + MINUTE
                    self.minute(now)
                if now >= timers['rotate']:
                    timers['rotate'] = now + rotate_every
                    if self.dirty:
                        self.relayout()
                    else:
                        self.rotate()
                if s.get('burn_in', True) and now >= timers['burn']:
                    timers['burn'] = now + BURN_IN_SECONDS
                    self.shift(8, 2000)
                if s.get('drift') and now >= timers['drift']:
                    timers['drift'] = now + DRIFT_SECONDS
                    self.shift(28, int(DRIFT_SECONDS * 1000))
                if self.board.layout.pages and now >= timers['page']:
                    timers['page'] = now + SPOTLIGHT_SECONDS
                    self.next_page()
                self.board.tick(now)
        finally:
            worker.stop()

    def relayout(self):
        s = self.settings
        self.sources = sources.build(self.store, self.feeds, s, self.palette['accent_hex'])
        ctx = layout_ctx(s, ss=True)
        layout = layouts.build(s.get('layout', 'mixed_wall'), self.sources, ctx)
        if self.board.layout is not None and self.board.layout.tiles:
            self.board.prop('relayout', '1')
            self.screen.sleep(g.THEME_FADE_MS / 1000.0)
            for slot in self.board.bound_slots():
                self.board.unbind(slot)
            self.screen.sleep(0.08)
        self.board.set_layout(layout, time.time(), entrance=True, left=ctx['left'])
        self.board.prop('relayout', '')
        self.dirty = False
        self.board.prop('msg.title', '' if layout.tiles else kodi.tr(32001))

    def on_feed(self, feed_id):
        feed = next((f for f in self.feeds if f.id == feed_id), None)
        if feed is None:
            return
        state = self.store.state()
        src = sources.make(self.store, feed, self.settings, self.palette['accent_hex'],
                           set(state.get('hidden', [])), state.get('last_view', {}))
        mine = [t for t in self.board.layout.tiles if t.source is not None and t.source.id == feed_id]
        if src.items and not any(t.source.items for t in mine):
            self.board.update_source(src)
            if not any(t.item is not None for t in self.board.layout.tiles):
                self.relayout()          # first data ever: show it now
            else:
                self.dirty = True        # at the next rotation
            return
        self.board.update_source(src)

    # ------------------------------------------------------------ periodic

    def minute(self, now):
        self.board.refresh_times(now)
        palette = theme.resolve(self.settings, kodi.now())
        if palette['name'] != self.palette['name']:
            self.palette = palette
            self.board.prop('themefade', '1')
            self.screen.sleep(g.THEME_FADE_MS / 1000.0)
            self.board.apply_palette(palette)
            self.apply_dim()
            self.board.prop('themefade', '')

    def apply_dim(self):
        pct = int(self.settings.get('night_dim', 0) or 0)
        if pct and self.palette['name'] == 'night':
            self.board.prop('dim', '%02X000000' % int(round(255 * pct / 100.0)))
        else:
            self.board.prop('dim', '')

    def rotate(self):
        """The item tiles that have shown the same story longest flip to stories not on screen."""
        board = self.board
        tiles = [t for t in board.layout.tiles if t.kind in ('item', 'thumb') and t.slot is not None]
        if not tiles:
            return
        shown = set(t.item.id for t in board.layout.tiles if t.item is not None)
        need_image = self.settings.get('show_images', True)
        fresh = []
        for src in sorted(self.sources, key=lambda s: -len(s.items)):
            for item in src.items:
                if item.id not in shown:
                    fresh.append((item, src))
        fresh.sort(key=lambda p: p[0].published, reverse=True)
        tiles.sort(key=lambda t: t.shown_at)
        count = max(1, len(tiles) // 4)
        delay = 0
        for tile in tiles[:count]:
            pick = None
            for n, (item, src) in enumerate(fresh):
                if tile.kind == 'thumb' or tile.notitle or (tile.size == 'large' and need_image):
                    if not item.images:
                        continue
                pick = n
                break
            if pick is None:
                continue
            item, src = fresh.pop(pick)
            tile.source = src
            tile.colour = src.accent
            board.after(delay, lambda t=tile, i=item: board.replace_content(t, [i], 'flip'))
            delay += 700

    def shift(self, amount, ms):
        control = self.screen.control(g.BOARD)
        if control is None:
            return
        old = getattr(self, 'offset', (0, 0))
        new = (self.rng.randint(-amount, amount), self.rng.randint(-amount, amount))
        control.setAnimations([('conditional', 'effect=slide start=%d,%d end=0,0 time=%d tween=sine easing=inout '
                                               'condition=true' % (old[0] - new[0], old[1] - new[1], ms))])
        control.setPosition(new[0], new[1])
        self.offset = new

    def next_page(self):
        board = self.board
        pages = board.layout.pages
        if len(pages) < 2:
            return
        current = max([i for i, p in enumerate(pages) if p - g.SS_LEFT <= board.scroll] or [0])
        target = pages[(current + 1) % len(pages)] - g.SS_LEFT
        board.scroll_to(max(0, target), ms=900)


def main(args):
    if args:
        from .. import actions
        actions.run(SCREENSAVER_ID, args[0])
        return
    try:
        Saver().run()
    except sc.Closed:
        pass
