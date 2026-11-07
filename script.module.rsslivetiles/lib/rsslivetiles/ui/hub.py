"""The program: a horizontally scrolling hub of live tiles (spec 4, 5).

Remote: arrows move the focus (the hub scrolls to keep it on screen), Select expands a tile
into the detail view, Menu opens the tile's context menu, Back leaves. Everything renders
from the cache at once; the feed worker refreshes in the background and the board takes
the new items as they arrive.
"""

import time

import xbmc
import xbmcaddon
import xbmcgui

from .. import APP_ID, config, kodi, sources, theme
from ..tiles import geometry as g, layouts, styles
from . import manager
from . import screen as sc
from .board import Board
from .detail import Detail
from .worker import FeedWorker

tr = kodi.tr
MINUTE = 60.0
IDLE_RELAYOUT = 20.0


def layout_ctx(settings, ss=False):
    name = settings.get('layout', 'feed_groups')
    ctx = {'rows': g.SS_ROWS if ss else g.HUB_ROWS, 'top': g.SS_TOP if ss else g.HUB_TOP,
           'left': g.SS_LEFT if (ss or name == 'spotlight') else g.MARGIN_X,
           'max_bands': g.SS_BANDS if ss else None, 'show_images': settings.get('show_images', True),
           'clock': ss and settings.get('show_clock', True), 'shade': settings.get('shade_variation', True),
           'limit': 48, 'group_items': 3}
    return ctx


class Hub(object):
    def __init__(self):
        self.next = None
        self.reload()

    def reload(self):
        self.settings = kodi.read_settings(APP_ID)
        self.store = kodi.store()

    def run(self):
        while True:
            self.next = None
            style = self.settings.get('style', 'classic')
            sc.AppScreen.open(styles.window_xml(style), self.logic, props=self.static_props())
            if self.next == 'settings':
                xbmcaddon.Addon(APP_ID).openSettings()
                self.reload()
                continue
            break

    def static_props(self):
        return {'t.title': tr(32000), 't.scan': tr(32020), 't.hints': tr(32022), 't.play': tr(32023)}

    # ------------------------------------------------------------ window logic

    def logic(self, screen):
        self.screen = screen
        s = self.settings
        self.palette = theme.resolve(s, kodi.now())
        self.board = Board(screen, s, self.palette, kodi.relative_strings(), ss=False)
        self.board.apply_palette(self.palette)
        if theme.custom_accent_warning(s):
            kodi.notify(tr(32069))
        self.feeds = self.store.feeds()
        self.worker = FeedWorker(self.store, self.feeds, kodi.fetch_options(s), screen.post)
        self.dirty = False
        self.last_input = time.time()
        self.touched = False
        started = time.time()
        self.relayout(entrance=True)
        kodi.debug('hub on screen in %.2f s (%d tiles)' % (time.time() - started, len(self.board.layout.tiles)))
        self.worker.start()
        self.detail = Detail(screen, self.board, s, on_other=self.handle_other)
        next_minute = time.time() + MINUTE
        try:
            while True:
                event = screen.wait(0.05)
                now = time.time()
                if event is not None:
                    if self.handle(event) == 'quit':
                        return None
                if now >= next_minute:
                    next_minute = now + MINUTE
                    self.minute(now)
                if self.dirty and now - self.last_input > IDLE_RELAYOUT:
                    self.relayout(entrance=True, keep_focus=True)
                self.board.tick(now)
        finally:
            self.worker.stop()
            self.store.mark_read([f.id for f in self.feeds])

    def build_layout(self):
        s = self.settings
        self.sources = sources.build(self.store, self.feeds, s, self.palette['accent_hex'])
        ctx = layout_ctx(s)
        return layouts.build(s.get('layout', 'feed_groups'), self.sources, ctx), ctx['left']

    def relayout(self, entrance=True, keep_focus=False):
        focus_id = self.board.focused.id if keep_focus and self.board.focused is not None else None
        layout, left = self.build_layout()
        if self.board.layout is not None and self.board.layout.tiles:
            self.board.prop('relayout', '1')
            self.screen.sleep(g.THEME_FADE_MS / 1000.0)
            for slot in self.board.bound_slots():
                self.board.unbind(slot)
            self.screen.sleep(0.08)
        self.board.set_layout(layout, time.time(), entrance=entrance, focus_id=focus_id, left=left)
        self.board.prop('relayout', '')
        self.dirty = False
        if layout.tiles:
            self.board.prop('msg.title', '')
            self.board.prop('msg.body', '')
        elif not self.feeds:
            self.board.prop('msg.title', tr(32002))
            self.board.prop('msg.body', tr(32003))
        else:
            self.board.prop('msg.title', tr(32001))
            self.board.prop('msg.body', '')

    def minute(self, now):
        self.board.refresh_times(now)
        palette = theme.resolve(self.settings, kodi.now())
        if palette['name'] != self.palette['name']:
            self.palette = palette
            self.board.prop('themefade', '1')
            self.screen.sleep(g.THEME_FADE_MS / 1000.0)
            self.board.apply_palette(palette)
            self.board.prop('themefade', '')

    # ------------------------------------------------------------ events

    def handle_other(self, event):
        kind = event[0]
        if kind == 'feed':
            feed_id = event[1]
            feed = next((f for f in self.feeds if f.id == feed_id), None)
            if feed is None:
                return
            state = self.store.state()
            src = sources.make(self.store, feed, self.settings, self.palette['accent_hex'],
                               set(state.get('hidden', [])), state.get('last_view', {}))
            mine = [t for t in self.board.layout.tiles if t.source is not None and t.source.id == feed_id]
            had_items = any(t.source.items for t in mine)
            if src.items and not had_items:
                # First items for this feed: its group needs real tiles. Re-lay out now if the
                # user has not started moving around (or is idle), else when they are idle.
                self.board.update_source(src)
                if not self.touched or time.time() - self.last_input > IDLE_RELAYOUT:
                    self.relayout(entrance=True, keep_focus=True)
                else:
                    self.dirty = True
                return
            self.board.update_source(src)
        elif kind == 'status':
            self.board.prop('status', tr(32014) if event[1] == 'updating' else tr(32015) if event[1] else '')

    def handle(self, event):
        kind, value = event[0], event[1] if len(event) > 1 else None
        if kind not in ('action', 'click'):
            self.handle_other(event)
            return None
        self.last_input = time.time()
        self.touched = True
        if kind == 'click':
            self.open_detail(self.board.focused)
            return None
        if value in sc.BACK_ACTIONS:
            return 'quit'
        moves = {sc.ACTION_LEFT: 'left', sc.ACTION_RIGHT: 'right', sc.ACTION_UP: 'up', sc.ACTION_DOWN: 'down'}
        if value in moves:
            self.board.move(moves[value])
        elif value == sc.ACTION_SELECT:
            self.open_detail(self.board.focused)
        elif value in sc.MENU_ACTIONS:
            return self.context_menu(self.board.focused)
        elif value in (sc.ACTION_PAGE_DOWN, sc.ACTION_SCROLL_DOWN):
            self.page(1)
        elif value in (sc.ACTION_PAGE_UP, sc.ACTION_SCROLL_UP):
            self.page(-1)
        return None

    def page(self, direction):
        board = self.board
        if board.layout is None or board.focused is None:
            return
        target_x = board.focused.x + direction * (g.SCREEN_W - 2 * g.MARGIN_X)
        tiles = sorted(board.layout.tiles, key=lambda t: (abs(t.x - target_x), abs(t.y - board.focused.y)))
        if tiles:
            board.set_focus(tiles[0])

    # ------------------------------------------------------------ detail

    def items_for(self, tile):
        if tile is None or tile.source is None:
            return [], 0
        items = tile.source.items
        if not items:
            return [], 0
        current = tile.item
        if current is not None:
            for i, item in enumerate(items):
                if item.id == current.id:
                    return items, i
        return items, 0

    def open_detail(self, tile):
        items, index = self.items_for(tile)
        if not items:
            return
        action = self.detail.open(tile, items, index, tile.source)
        self.last_input = time.time()
        if action == 'menu':
            self.context_menu(tile, item=self.detail.current)

    # ------------------------------------------------------------ context menu

    def context_menu(self, tile, item=None):
        entries = []
        if tile is not None and tile.source is not None:
            if tile.source.items:
                entries.append(('open', tr(32030)))
            entries += [('read', tr(32031)), ('refresh', tr(32032)), ('edit', tr(32033))]
            if tile.kind in ('item', 'thumb') or item is not None:
                entries.append(('hide', tr(32034)))
        entries += [('layout', tr(32039)), ('refresh_all', tr(32037)), ('read_all', tr(32038)),
                    ('manage', tr(32035)), ('settings', tr(32036))]
        pick = xbmcgui.Dialog().contextmenu([e[1] for e in entries])
        if pick < 0:
            return None
        what = entries[pick][0]
        if what == 'open':
            self.open_detail(tile)
        elif what == 'read':
            self.mark_read([tile.source.id])
        elif what == 'read_all':
            self.mark_read([f.id for f in self.feeds])
        elif what == 'refresh':
            self.worker.refresh_now([tile.source.id])
        elif what == 'refresh_all':
            self.worker.refresh_now()
        elif what == 'edit':
            index = next((i for i, f in enumerate(self.store.feeds()) if f.id == tile.source.id), -1)
            if index >= 0 and manager.edit_feed(self.store, index):
                self.feeds_changed()
        elif what == 'hide':
            target = item or tile.item
            if target is not None:
                self.store.hide(target.id)
                self.relayout(entrance=False, keep_focus=False)
        elif what == 'layout':
            self.choose_layout()
        elif what == 'manage':
            if manager.run(self.store):
                self.feeds_changed()
        elif what == 'settings':
            self.next = 'settings'
            return 'quit'
        return None

    def mark_read(self, feed_ids):
        self.store.mark_read(feed_ids)
        state = self.store.state()
        for feed in self.feeds:
            if feed.id in feed_ids:
                src = sources.make(self.store, feed, self.settings, self.palette['accent_hex'],
                                   set(state.get('hidden', [])), state.get('last_view', {}))
                self.board.update_source(src)

    def feeds_changed(self):
        self.feeds = self.store.feeds()
        self.worker.set_feeds(self.feeds)
        self.relayout(entrance=True, keep_focus=True)

    def choose_layout(self):
        names = config.APP_LAYOUTS
        current = names.index(self.settings.get('layout', 'feed_groups'))
        pick = xbmcgui.Dialog().select(tr(32039), [config.LAYOUT_LABELS[n] for n in names], preselect=current)
        if pick < 0 or pick == current:
            return
        self.settings['layout'] = names[pick]
        try:
            xbmcaddon.Addon(APP_ID).setSettingInt('layout', pick)
        except RuntimeError:
            pass
        self.relayout(entrance=True)


def main(args):
    if args:
        from .. import actions
        actions.run(APP_ID, args[0])
        return
    try:
        Hub().run()
    except sc.Closed:
        pass
    except Exception:
        import traceback
        kodi.log(traceback.format_exc(), xbmc.LOGERROR)
        raise
