"""Choosing the next camera: filter the catalogue by the settings and the health list, weight
what is left toward daylit, high-quality, unseen scenes, and draw one. No Kodi imports.

When the filters leave nothing, they are relaxed in this order: daylight, then minimum
resolution, then unverified streams allowed. If the pool is still empty, draw() returns
None and the session shows the fallback card.
"""

import random
import time

from . import config, sun

QUALITY_WEIGHT = {'premium': 1.5, 'high': 1.2, 'standard': 1.0, 'low': 0.5}
DAYLIGHT_WEIGHT = {sun.DAY: 1.0, sun.TWILIGHT: 0.6, sun.NIGHT: 0.05, sun.UNKNOWN: 1.0}
FAVOURITE = 3.0
RECENT = 0.1
SAME_PLACE = 0.5            # same source or country as the camera on screen
FRESH = 1.1                 # verified in the last FRESH_DAYS: a tiebreak
FRESH_DAYS = 14
RELAX_STEPS = ('daylight', 'resolution', 'unverified')


class Filters(object):
    """The settings that decide which cameras may show, at one relaxation level."""

    def __init__(self, s, favourites=(), relax=0):
        envs = set(config.ENVIRONMENTS[i] for i in s.get('environments', []) if 0 <= i < len(config.ENVIRONMENTS))
        if s.get('traffic'):
            envs.add('traffic')
        self.environments = envs
        self.country_mode = s.get('country_mode', 0)
        self.countries = config.country_codes(s.get('countries', ''))
        self.kinds = ('hls', 'youtube') if s.get('youtube') else ('hls',)
        self.favourites = set(favourites)
        self.favourites_only = bool(s.get('favourites_only')) and bool(self.favourites)
        self.relax = relax
        self.daylight = bool(s.get('daylight', True)) and relax < 1
        self.night = bool(s.get('night'))
        self.min_height = config.MIN_RES_PX[s.get('min_res', 2)] if relax < 2 else 0
        self.unverified = bool(s.get('unverified')) or relax >= 3

    def static_ok(self, cam):
        """Every test that doesn't depend on the time or the health list."""
        if cam.kind not in self.kinds or cam.env not in self.environments:
            return False
        if not self.unverified and cam.status != 'active':
            return False
        if self.country_mode == 1 and cam.cc not in self.countries:
            return False
        if self.country_mode == 2 and cam.cc in self.countries:
            return False
        if self.favourites_only and cam.id not in self.favourites:
            return False
        return True


def light_of(cam, now):
    return sun.daylight(cam.lat, cam.lon, now, cam.cq)


def candidates(cams, s, health=None, history=None, now=None, exclude=(), relax=0):
    """[(camera, light)] that pass the filters at one relaxation level."""
    now = time.time() if now is None else now
    f = Filters(s, history.favourites if history else (), relax)
    blocked_ids = health.blocked_ids(now) if health else set()
    blocked_sources = health.blocked_sources(now) if health else set()
    exclude = set(exclude)
    out = []
    for cam in cams:
        if cam.id in exclude or cam.id in blocked_ids or cam.family in blocked_sources:
            continue
        if not f.static_ok(cam):
            continue
        if f.min_height:
            height = cam.height or (health.known_height(cam.id, now) if health else 0)
            if height and height < f.min_height:
                continue
        light = light_of(cam, now)
        if f.daylight:
            # Daylight on: night cameras only with "Allow night cameras"; cameras placed at a
            # country's centroid (unknown light) only once the daylight filter is relaxed.
            if light == sun.UNKNOWN or (light == sun.NIGHT and not f.night):
                continue
        out.append((cam, light))
    return out


def weight(cam, light, s, favourites, recent, current=None):
    w = QUALITY_WEIGHT.get(cam.quality, 1.0)
    if s.get('daylight', True):
        w *= 1.0 if (light == sun.NIGHT and s.get('night')) else DAYLIGHT_WEIGHT[light]
    if cam.id in favourites:
        w *= FAVOURITE
    if cam.id in recent:
        w *= RECENT
    if current is not None and (cam.family == current.family or (cam.cc and cam.cc == current.cc)):
        w *= SAME_PLACE
    return w


class Selector(object):
    def __init__(self, settings, health=None, history=None, rng=None, log=lambda msg: None):
        self.s = settings
        self.health = health
        self.history = history
        self.random = rng or random.Random()
        self.log = log
        self.relaxed = 0

    def pool(self, cams, now=None, exclude=()):
        """(candidates, relaxation level) for the first level that leaves any camera."""
        now = time.time() if now is None else now
        for relax in range(len(RELAX_STEPS) + 1):
            found = candidates(cams, self.s, self.health, self.history, now, exclude, relax)
            if found:
                if relax != self.relaxed:
                    self.log('filters relaxed: %s' % (', '.join(RELAX_STEPS[:relax]) or 'none'))
                self.relaxed = relax
                return found, relax
        self.relaxed = len(RELAX_STEPS) + 1
        return [], self.relaxed

    def draw(self, cams, current=None, now=None, exclude=()):
        """One camera, or None if nothing can show."""
        now = time.time() if now is None else now
        exclude = set(exclude)
        if current is not None:
            exclude.add(current.id)
        found, _relax = self.pool(cams, now, exclude)
        if not found and current is not None:
            found, _relax = self.pool(cams, now, exclude - set([current.id]))
        if not found:
            return None
        favourites = set(self.history.favourites) if self.history else set()
        recent = self.history.recent(now) if self.history else set()
        weights = []
        for cam, light in found:
            w = weight(cam, light, self.s, favourites, recent, current)
            if cam.verified and now - cam.verified < FRESH_DAYS * 86400:
                w *= FRESH
            weights.append(w)
        total = sum(weights)
        pick = self.random.random() * total
        for (cam, _light), w in zip(found, weights):
            pick -= w
            if pick <= 0:
                return cam
        return found[-1][0]
