"""What the overlay says and when and where it shows. Pure logic, no Kodi imports.

Modes: 0 off, 1 on change (shown for ON_CHANGE seconds when a camera starts), 2 always.
With burn-in protection the overlay moves to a new offset, up to DRIFT pixels from home,
at every camera change and every DRIFT_PERIOD seconds while it stays up; the clock card
(fallback and clock-only modes) wanders across a wider area every CARD_PERIOD seconds.
"""

import random

from . import catalog, sun

OFF, ON_CHANGE_MODE, ALWAYS = 0, 1, 2
ON_CHANGE = 8.0
DRIFT = 24
DRIFT_PERIOD = 180.0
CARD_RANGE = (360, 200)     # the clock card's centre moves within +/- these (1920x1080 space)
CARD_PERIOD = 60.0


def texts(cam, now, sources=None, local_time=True, twenty_four=True, translate=lambda sid, text: text):
    """{'title', 'place', 'detail'} for a camera: its name; town and country; source and
    local time at the camera."""
    country = catalog.country_name(cam.cc)
    place = ', '.join(p for p in (cam.place, country) if p and p.lower() not in cam.title.lower()) or country
    detail = [catalog.source_name(cam.family, sources)]
    if local_time and cam.lat is not None and cam.cq != 'country_centroid':
        detail.append('%s %s' % (sun.local_time(cam.cc, cam.lat, cam.lon, now, twenty_four),
                                 translate(32001, 'local time')))
    return {'title': cam.title, 'place': place, 'detail': '  ·  '.join(detail)}


class Overlay(object):
    def __init__(self, mode=ON_CHANGE_MODE, burnin=True, rng=None):
        self.mode = mode
        self.burnin = burnin
        self.random = rng or random.Random()
        self.until = 0.0
        self.offset = (0, 0)
        self.moved = 0.0
        self.card = (0, 0)
        self.card_moved = -CARD_PERIOD

    def changed(self, now):
        """A new camera is on screen."""
        if self.mode == ON_CHANGE_MODE:
            self.until = now + ON_CHANGE
        self._drift(now)

    def hide(self):
        self.until = 0.0

    def visible(self, now):
        if self.mode == ALWAYS:
            return True
        return self.mode == ON_CHANGE_MODE and now < self.until

    def tick(self, now):
        """True when the overlay should move (always-on overlay, burn-in protection)."""
        if self.burnin and self.mode == ALWAYS and now - self.moved >= DRIFT_PERIOD:
            self._drift(now)
            return True
        return False

    def _drift(self, now):
        self.moved = now
        if self.burnin:
            self.offset = (self.random.randint(-DRIFT, DRIFT), self.random.randint(-DRIFT, DRIFT))

    def card_position(self, now):
        """(dx, dy) of the clock card from the centre; moves every CARD_PERIOD with burn-in on."""
        if self.burnin and now - self.card_moved >= CARD_PERIOD:
            self.card_moved = now
            self.card = (self.random.randint(-CARD_RANGE[0], CARD_RANGE[0]),
                         self.random.randint(-CARD_RANGE[1], CARD_RANGE[1]))
        return self.card
