"""Which tile animates next (spec 4.3, scheduler rules):

- at most max_active tiles animate at once (1-4)
- a random tile animates every few seconds, by liveliness (Calm / Normal / Lively)
- no tile animates twice in a row; tiles on screen are preferred
- the focused tile never animates
"""

import random

CALM, NORMAL, LIVELY = 0, 1, 2
INTERVALS = {CALM: (6.0, 10.0), NORMAL: (2.0, 6.0), LIVELY: (1.0, 2.5)}


class Scheduler(object):
    def __init__(self, liveliness=NORMAL, max_active=2, rng=None):
        self.rng = rng or random.Random()
        self.low, self.high = INTERVALS.get(liveliness, INTERVALS[NORMAL])
        self.max_active = max(1, min(4, int(max_active)))
        self.busy = {}                  # tile id -> time it finishes
        self.last = None
        self.next_at = 0.0

    def delay(self):
        return self.rng.uniform(self.low, self.high)

    def start(self, now):
        self.next_at = now + self.rng.uniform(1.0, 2.5)

    def settle(self, now):
        for tid, until in list(self.busy.items()):
            if until <= now:
                del self.busy[tid]

    def active(self, now):
        self.settle(now)
        return len(self.busy)

    def due(self, now):
        return now >= self.next_at and self.active(now) < self.max_active

    def pick(self, tiles, now, focused=None, visible=None):
        """The next tile to animate, or None. tiles: candidates (Tile objects with .id and
        .live); visible: ids on screen."""
        self.settle(now)
        self.next_at = now + self.delay()
        if len(self.busy) >= self.max_active:
            return None
        pool = [t for t in tiles if t.live and t.id not in self.busy and t.id != focused]
        if len(pool) > 1:
            pool = [t for t in pool if t.id != self.last] or pool
        if visible is not None:
            on_screen = [t for t in pool if t.id in visible]
            if on_screen:
                pool = on_screen
        if not pool:
            return None
        tile = self.rng.choice(pool)
        self.last = tile.id
        return tile

    def mark(self, tile_id, until):
        self.busy[tile_id] = max(until, self.busy.get(tile_id, 0))

    def is_busy(self, tile_id, now):
        return self.busy.get(tile_id, 0) > now
