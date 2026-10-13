"""The scene playlist: order, durations, alert promotion and shuffle. Pure logic,
no Kodi imports, so it is unit-tested directly."""

import random

from . import config


class Playlist(object):
    def __init__(self, settings, seed=None):
        self.s = settings
        self.random = random.Random(seed)
        self.order = []
        self.pos = -1
        self.current = None

    def duration(self, sid):
        if sid == 'alert':
            return 40
        return self.s.get('dur_' + sid, 20)

    def base_order(self):
        """Enabled scenes sorted by their position setting."""
        s = self.s
        ids = []
        for i, sid in enumerate(config.SCENE_IDS):
            if s.get('scene_' + sid, 0) == 0:
                continue
            pos = s.get('pos_' + sid, i + 1)
            # On a tie, a scene the user moved goes before one still at its default position.
            ids.append((pos, 0 if pos != i + 1 else 1, i, sid))
        ids.sort()
        order = [entry[-1] for entry in ids]
        if s.get('shuffle'):
            maps = [sid for sid in order if sid in config.MAP_SCENES]
            rest = [sid for sid in order if sid not in config.MAP_SCENES]
            self.random.shuffle(rest)
            order = maps + rest
        return order

    def next(self, available, alerts=False):
        """The next scene id to show, skipping unavailable ones; None when nothing can show.
        available: f(scene id) -> bool. alerts: a warning is active (promoted to the front)."""
        if not self.order:
            self.order = self.base_order()
            self.pos = -1
        promote = alerts and self.s.get('alert_promote', True)
        if promote and self.current != 'alert' and (self.pos == -1 or self.pos >= len(self.order) - 1) \
                and available('alert'):
            self.pos = -1 if self.pos >= len(self.order) - 1 else self.pos
            self.current = 'alert'
            return 'alert'
        for _ in range(len(self.order)):
            self.pos += 1
            if self.pos >= len(self.order):
                self.pos = 0
                if self.s.get('shuffle'):
                    self.order = self.base_order()
                if promote and available('alert') and self.current != 'alert':
                    self.pos = -1
                    self.current = 'alert'
                    return 'alert'
            sid = self.order[self.pos]
            if available(sid):
                self.current = sid
                return sid
        self.current = None
        return None

    def skip(self, available, step, alerts=False):
        """Interactive mode: step +1 / -1 scenes."""
        if step > 0:
            return self.next(available, alerts)
        for _ in range(len(self.order)):
            self.pos = (self.pos - 1) % max(1, len(self.order))
            sid = self.order[self.pos]
            if available(sid):
                self.current = sid
                return sid
        return self.current
