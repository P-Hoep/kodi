"""Camera movement and automatic cycling. No Kodi imports.

Motion is a pure function of time, so the window can ask "where should the map be at
time t" for any t and let Kodi animate between answers at the display's frame rate."""

import math
import random

STATIC, PAN, ROTATE, AUTO = range(4)
# Pan patterns
WANDER, SWEEP, ORBIT = range(3)
DRIFT_PX = 24.0   # minimum wander, so a map that fits the screen still moves (burn-in)


class Sequence(object):
    """Cycles through items in a fixed order, or shuffled without repeating an item until
    all have been shown (and never the same item twice in a row)."""

    def __init__(self, items, shuffle=False, seed=None, start=None):
        self.items = list(items)
        self.shuffle = shuffle
        self.rng = random.Random(seed)
        self.bag = []
        self.last = None
        self.pos = -1
        if start in self.items and not shuffle:
            self.pos = self.items.index(start)
            self.last = start

    def next(self):
        if not self.items:
            return None
        if len(self.items) == 1:
            self.last = self.items[0]
            return self.last
        if not self.shuffle:
            self.pos = (self.pos + 1) % len(self.items)
            self.last = self.items[self.pos]
            return self.last
        if not self.bag:
            self.bag = list(self.items)
            self.rng.shuffle(self.bag)
            if self.bag[-1] == self.last:  # popped from the end: avoid an immediate repeat
                self.bag[0], self.bag[-1] = self.bag[-1], self.bag[0]
        self.last = self.bag.pop()
        return self.last


class Motion(object):
    """How one scene moves.

    mode is resolved for the projection: 'spin' (re-rendered with a moving central
    meridian), 'scroll' (a cylindrical map sliding sideways and wrapping), 'pan' (the
    camera wandering over a map larger than the screen) or 'static'."""

    def __init__(self, kind, rotatable, setting, speed, eastward, pattern, disp_w, disp_h, screen_w, screen_h):
        self.disp_w, self.disp_h = disp_w, disp_h
        self.screen_w, self.screen_h = screen_w, screen_h
        self.speed = max(1, min(10, speed))
        self.sign = -1.0 if eastward else 1.0   # eastward: the surface moves east (to the right)
        self.pattern = pattern
        if setting == STATIC:
            mode = 'static'
        elif kind == 'globe':
            mode = 'spin'
        elif kind == 'cylindrical':
            mode = 'scroll' if setting in (ROTATE, AUTO, PAN) else 'static'
        elif setting == ROTATE and rotatable:
            mode = 'spin'
        else:
            mode = 'pan'   # pan, automatic, or rotate where the projection cannot rotate
        self.mode = mode
        self.deg_per_s = 0.35 * self.speed
        self.px_per_s = 5.0 * self.speed

    def rotation(self, t):
        """Central meridian in degrees (spin), for time t in seconds since the scene began."""
        if self.mode != 'spin':
            return 0.0
        return (self.sign * self.deg_per_s * t) % 360.0

    def offset(self, t):
        """Top-left screen position of the map image at time t (floats)."""
        cx = (self.screen_w - self.disp_w) / 2.0
        cy = (self.screen_h - self.disp_h) / 2.0
        if self.mode == 'scroll':
            # Content moves with the surface; wrapped into one map width by the window.
            x = -self.sign * self.disp_w / 360.0 * self.deg_per_s * t
            ay = max(0.0, (self.disp_h - self.screen_h) / 2.0)
            y = cy + ay * math.sin(t * self.px_per_s / max(ay, 200.0) * 0.5) if ay else cy
            return cx + x, y
        if self.mode != 'pan':
            return cx, cy
        ax = max(DRIFT_PX, (self.disp_w - self.screen_w) / 2.0)
        ay = max(DRIFT_PX, (self.disp_h - self.screen_h) / 2.0)
        # Angular speeds chosen so the camera's top speed is about px_per_s.
        wx = self.px_per_s / ax
        wy = self.px_per_s / ay
        if self.pattern == SWEEP:
            return cx + ax * math.sin(wx * t), cy + ay * math.sin(wy * 0.25 * t)
        if self.pattern == ORBIT:
            w = self.px_per_s / max(ax, ay)
            return cx + ax * math.cos(w * t), cy + ay * math.sin(w * t)
        # Wander: a slow Lissajous figure that never quite repeats.
        return cx + ax * math.sin(wx * 0.61 * t), cy + ay * math.sin(wy * 0.37 * t + 1.1)
