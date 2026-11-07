"""The tile board: binds a Layout's tiles to the window's slots and makes them live.

- Slots are pooled per size (tiles/geometry.py). Only tiles near the visible part of the hub
  are bound; scrolling rebinds (virtualisation), so a hub of any length fits the pools.
- Faces are double-buffered: new content goes into the hidden face, then rt.<slot>.face
  switches and the XML's Hidden / Visible animations (picked by rt.<slot>.fx) play.
- A timeline of (time, step) runs the multi-step animations without blocking input.
- Window properties are cached, so unchanged values are never sent to Kodi twice.
"""

import heapq
import itertools
import random

from .. import theme
from ..tiles import faces, geometry as g, styles
from ..tiles.scheduler import Scheduler

FX_MS = {'flip': 2 * g.FLIP_MS, 'cycle': g.CYCLE_MS, 'fade': g.FADE_MS}
BIND_MARGIN = 700


class Slot(object):
    def __init__(self, size, index):
        self.size = size
        self.name = g.slot_names(size)[index]
        self.cid = g.slot_id(size, index)
        self.tile = None
        self.face = 'a'
        self.control = None
        self.pos = None


class Board(object):
    def __init__(self, screen, settings, palette, ctx_strings, ss=False, rng=None):
        self.screen = screen
        self.settings = settings
        self.palette = palette
        self.style = settings.get('style', 'classic')
        self.ss = ss
        self.rng = rng or random.Random()
        self.strings = ctx_strings
        self.reduced = bool(settings.get('reduced_motion'))
        self.scheduler = Scheduler(settings.get('liveliness', 1), settings.get('max_active', 2), self.rng)
        self.slots = dict((size, [Slot(size, i) for i in range(g.POOLS[size])]) for size in g.POOLS)
        self.layout = None
        self.scroll = 0
        self.left = g.MARGIN_X
        self.focused = None
        self.timeline = []
        self.seq = itertools.count()
        self.cache = {}
        self.preload_n = 0
        self.strip = screen.control(g.STRIP)
        self.headers = [screen.control(g.HEADER_ID + i + 1) for i in range(g.HEADERS)]
        self.now = 0.0
        self.prop('rm', '1' if self.reduced else '')

    # ------------------------------------------------------------ properties

    def prop(self, key, value):
        value = '' if value is None else str(value)
        if self.cache.get(key) != value:
            self.cache[key] = value
            self.screen.setProperty(key, value)

    def face_ctx(self):
        return {'style': self.style, 'palette': self.palette, 'now': self.now, 'strings': self.strings,
                'show_images': self.settings.get('show_images', True)}

    def write_face(self, slot, face_name, face):
        base = 'rt.%s.%s.' % (slot.name, face_name)
        for key in faces.KEYS:
            self.prop(base + key, face.get(key, ''))

    def apply_palette(self, palette):
        self.palette = palette
        for key in theme.PROPERTIES:
            self.prop(key, palette.get(key, ''))
        self.prop('d.accent_text', palette['accent'])
        for slot in self.bound_slots():
            self.refresh_slot(slot)

    # ------------------------------------------------------------ layout and binding

    def bound_slots(self):
        return [s for pool in self.slots.values() for s in pool if s.tile is not None]

    def set_layout(self, layout, now, entrance=True, focus_id=None, left=None):
        self.now = now
        for slot in self.bound_slots():
            self.unbind(slot)
        self.timeline = []
        self.scheduler.busy.clear()
        self.layout = layout
        self.left = left if left is not None else g.MARGIN_X
        self.scroll = 0
        if self.strip is not None:
            self.strip.setAnimations([])
            self.strip.setPosition(0, 0)
        for i, header in enumerate(self.headers):
            if i < len(layout.headers) and not self.ss:
                x, title = layout.headers[i]
                if header is not None:
                    header.setPosition(int(x), g.HEADER_Y)
                self.prop('hdr.%d' % (i + 1), title)
            else:
                self.prop('hdr.%d' % (i + 1), '')
        self.focused = None
        target = layout.find(focus_id) if focus_id else None
        if not self.ss and layout.tiles:
            self.focused = target or self.first_tile()
            self.scroll = self.scroll_for(self.focused)
            if self.strip is not None:
                self.strip.setPosition(-self.scroll, 0)
        self.rebind(entrance=entrance)
        self.show_focus()
        self.scheduler.start(now)

    def first_tile(self):
        tiles = sorted(self.layout.tiles, key=lambda t: (t.x, t.y))
        return tiles[0] if tiles else None

    def in_range(self, tile, lo, hi):
        return tile.x + tile.w >= lo and tile.x <= hi

    def rebind(self, extra=None, entrance=False):
        """Bind tiles near the viewport, unbind the rest. extra: another (lo, hi) range to
        keep bound (the scroll target while sliding)."""
        if self.layout is None:
            return
        lo, hi = self.scroll - BIND_MARGIN, self.scroll + g.SCREEN_W + BIND_MARGIN
        if extra:
            lo, hi = min(lo, extra[0]), max(hi, extra[1])
        want = [t for t in self.layout.tiles if self.in_range(t, lo, hi)]
        centre = self.scroll + g.SCREEN_W / 2.0
        want.sort(key=lambda t: abs(t.x + t.w / 2.0 - centre))
        wanted = set(id(t) for t in want)
        for slot in self.bound_slots():
            if id(slot.tile) not in wanted:
                self.unbind(slot)
        for tile in want:
            if tile.slot is None:
                slot = self.free_slot(tile.size)
                if slot is None:
                    continue
                self.bind(tile, slot, entrance)

    def free_slot(self, size):
        for slot in self.slots[size]:
            if slot.tile is None:
                return slot
        return None

    def bind(self, tile, slot, entrance=False):
        slot.tile = tile
        tile.slot = slot
        if tile.shown_at == 0:
            tile.shown_at = self.now
        control = self.slot_control(slot)
        if control is not None:
            if entrance:
                col = max(0, int((tile.x - self.scroll - self.left) // g.STEP))
                delay = min(14, col) * g.ENTRANCE_STAGGER
                control.setAnimations([
                    ('visible', 'effect=zoom start=100,70 end=100,100 center=auto time=%d delay=%d tween=cubic '
                     'easing=out' % (g.ENTRANCE_MS, delay)),
                    ('visible', 'effect=fade start=0 end=100 time=%d delay=%d' % (g.ENTRANCE_MS, delay))])
                self.after(g.ENTRANCE_MS + delay + 100, lambda c=control, s=slot, t=tile: self._clear_anims(c, s, t))
            if slot.pos != (tile.x, tile.y):
                control.setPosition(int(tile.x), int(tile.y))
                slot.pos = (tile.x, tile.y)
        self.prop('rt.%s.fx' % slot.name, '')
        self.prop('rt.%s.peek' % slot.name, '')
        self.prop('rt.%s.pulse' % slot.name, '')
        self.refresh_slot(slot)
        self.prop('rt.%s.face' % slot.name, slot.face)
        self.prop('rt.%s.on' % slot.name, '1')

    def _clear_anims(self, control, slot, tile):
        if slot.tile is tile:
            control.setAnimations([])

    def unbind(self, slot):
        if slot.tile is not None:
            slot.tile.slot = None
        slot.tile = None
        self.prop('rt.%s.on' % slot.name, '')
        self.prop('rt.%s.peek' % slot.name, '')

    def slot_control(self, slot):
        if slot.control is None:
            slot.control = self.screen.control(slot.cid)
        return slot.control

    def refresh_slot(self, slot):
        """Rewrite the slot's visible face from its tile (content, colours, warning)."""
        tile = slot.tile
        if tile is None:
            return
        ctx = self.face_ctx()
        self.write_face(slot, slot.face, faces.front(tile, ctx))
        c = styles.colours(self.style, tile.colour, self.palette)
        self.prop('rt.%s.edge' % slot.name, c['edge'])
        self.prop('rt.%s.fc' % slot.name, c['focus'])
        warn = tile.kind in ('feed', 'count') and tile.source is not None and bool(tile.source.error)
        self.prop('rt.%s.warn' % slot.name, '1' if warn else '')

    def refresh_times(self, now):
        """Relative times move on: rewrite each bound face's label row."""
        self.now = now
        ctx = self.face_ctx()
        for slot in self.bound_slots():
            face = faces.front(slot.tile, ctx)
            self.prop('rt.%s.%s.meta' % (slot.name, slot.face), face.get('meta', ''))

    # ------------------------------------------------------------ timeline

    def after(self, ms, fn):
        heapq.heappush(self.timeline, (self.now + ms / 1000.0, next(self.seq), fn))

    def tick(self, now):
        self.now = now
        while self.timeline and self.timeline[0][0] <= now:
            _t, _n, fn = heapq.heappop(self.timeline)
            fn()
        if self.layout is not None and self.scheduler.due(now):
            visible = self.visible_ids()
            tiles = [s.tile for s in self.bound_slots()]
            focused = self.focused.id if self.focused is not None else None
            tile = self.scheduler.pick(tiles, now, focused, visible)
            if tile is not None:
                self.animate(tile)

    def visible_ids(self):
        lo, hi = self.scroll, self.scroll + g.SCREEN_W
        return set(s.tile.id for s in self.bound_slots() if self.in_range(s.tile, lo + 40, hi - 40))

    # ------------------------------------------------------------ live animations

    def preload(self, url):
        if url:
            self.preload_n = self.preload_n % 3 + 1
            self.prop('pre%d' % self.preload_n, url)

    def swap(self, tile, face, fx):
        """Show face on tile with a flip / cycle / fade. Returns the busy time in seconds."""
        slot = tile.slot
        if slot is None:
            return 0
        if self.reduced:
            fx = 'fade'
        nf = 'b' if slot.face == 'a' else 'a'
        self.write_face(slot, nf, face)
        self.prop('rt.%s.fx' % slot.name, fx)
        delay = 60
        if face.get('img'):
            self.preload(face['img'])
            delay = 900

        def flip():
            if slot.tile is tile:
                slot.face = nf
                self.prop('rt.%s.face' % slot.name, nf)
        self.after(delay, flip)
        return (delay + FX_MS[fx]) / 1000.0 + 0.2

    def animate(self, tile):
        ctx = self.face_ctx()
        busy = 0
        if tile.kind == 'feed':
            tile.cursor = (tile.cursor + 1) % max(1, len(tile.items))
            tile.shown_at = self.now
            fx = self.rng.choice(('flip', 'cycle')) if tile.size != 'small' else 'flip'
            busy = self.swap(tile, faces.front(tile, ctx), fx)
        elif tile.kind == 'item':
            item = tile.item
            if item.images and self.settings.get('show_images', True) and tile.size != 'small':
                busy = self.peek(tile)
            else:
                tile.side = 'back' if tile.side == 'front' else 'front'
                busy = self.swap(tile, faces.front(tile, ctx), 'flip')
        elif tile.kind == 'count':
            tile.side = 'back' if tile.side == 'front' else 'front'
            busy = self.swap(tile, faces.front(tile, ctx), 'flip')
        if busy:
            self.scheduler.mark(tile.id, self.now + busy)

    def peek(self, tile):
        slot = tile.slot
        hold = self.rng.uniform(3.0, 4.0)
        self.prop('rt.%s.peek' % slot.name, '1')

        def back():
            if slot.tile is tile:
                self.prop('rt.%s.peek' % slot.name, '')
        self.after(int((g.PEEK_MS / 1000.0 + hold) * 1000), back)
        return 2 * g.PEEK_MS / 1000.0 + hold + 0.2

    def pulse(self, tile):
        slot = tile.slot
        if slot is None:
            return
        self.prop('rt.%s.pulse' % slot.name, '1')
        self.after(g.PULSE_MS + 20, lambda: self.prop('rt.%s.pulse' % slot.name, ''))

    def replace_content(self, tile, items, fx='flip'):
        """Screensaver rotation: give a tile new items and flip to them."""
        tile.items = list(items)
        tile.cursor = 0
        tile.side = 'front'
        tile.shown_at = self.now
        if tile.slot is not None:
            busy = self.swap(tile, faces.front(tile, self.face_ctx()), fx)
            self.scheduler.mark(tile.id, self.now + busy)

    # ------------------------------------------------------------ focus and scrolling

    def show_focus(self):
        slot = self.focused.slot if self.focused is not None else None
        self.prop('focus', slot.name if slot is not None else '')

    def set_focus(self, tile):
        if tile is None:
            return
        self.focused = tile
        target = self.scroll_for(tile)
        if target != self.scroll:
            self.scroll_to(target)
        if tile.slot is None:
            self.rebind()
        self.show_focus()

    def max_scroll(self):
        if self.layout is None:
            return 0
        return max(0, self.left + self.layout.width + g.MARGIN_X - g.SCREEN_W)

    def scroll_for(self, tile):
        if tile is None:
            return self.scroll
        if self.layout.pages:
            page = max([p for p in self.layout.pages if p <= tile.x] or [self.layout.pages[0]])
            return max(0, page - g.SS_LEFT)
        x = self.scroll
        if tile.x - x < g.MARGIN_X:
            x = tile.x - g.MARGIN_X
        elif tile.x + tile.w - x > g.SCREEN_W - g.MARGIN_X:
            x = tile.x + tile.w - (g.SCREEN_W - g.MARGIN_X)
        return int(max(0, min(self.max_scroll(), x)))

    def scroll_to(self, x, ms=g.SCROLL_MS):
        old = self.scroll
        if x == old:
            return
        self.rebind(extra=(x - BIND_MARGIN, x + g.SCREEN_W + BIND_MARGIN))
        self.scroll = x
        if self.strip is not None:
            self.strip.setAnimations([('conditional', 'effect=slide start=%d,0 end=0,0 time=%d tween=cubic '
                                                      'easing=out condition=true' % (x - old, ms))])
            self.strip.setPosition(-x, 0)
        self.after(ms + 80, self.rebind)

    def move(self, direction):
        """Focus the nearest tile in a direction ('left', 'right', 'up', 'down')."""
        cur = self.focused
        if cur is None or self.layout is None:
            return False
        best, best_score = None, None
        for t in self.layout.tiles:
            if t is cur:
                continue
            if direction in ('left', 'right'):
                gap = (t.x - (cur.x + cur.w)) if direction == 'right' else (cur.x - (t.x + t.w))
                if gap < -5:
                    continue
                side = max(0, max(t.y, cur.y) - min(t.y + t.h, cur.y + cur.h))
                centre = abs((t.y + t.h / 2.0) - (cur.y + cur.h / 2.0))
            else:
                gap = (t.y - (cur.y + cur.h)) if direction == 'down' else (cur.y - (t.y + t.h))
                if gap < -5:
                    continue
                side = max(0, max(t.x, cur.x) - min(t.x + t.w, cur.x + cur.w))
                centre = abs((t.x + t.w / 2.0) - (cur.x + cur.w / 2.0))
            score = gap + 3 * side + 0.15 * centre
            if best_score is None or score < best_score:
                best, best_score = t, score
        if best is None:
            return False
        self.set_focus(best)
        return True

    def screen_rect(self, tile):
        return tile.x - self.scroll, tile.y, tile.w, tile.h

    # ------------------------------------------------------------ data updates

    def update_source(self, source):
        """A feed refreshed: feed tiles cycle through the new items, count tiles pulse."""
        if self.layout is None:
            return
        for tile in self.layout.tiles:
            if tile.source is None or tile.source.id != source.id:
                continue
            tile.source = source
            if tile.kind == 'feed':
                tile.items = list(source.items)
                if tile.slot is not None and not self.scheduler.is_busy(tile.id, self.now):
                    tile.cursor = 0
                    self.refresh_slot(tile.slot)
            elif tile.kind == 'count':
                changed = tile.count != source.new_count
                tile.count = source.new_count
                if tile.slot is not None:
                    self.refresh_slot(tile.slot)
                    if changed:
                        self.pulse(tile)
            elif tile.slot is not None:
                self.refresh_slot(tile.slot)
