"""Artificial satellites: CelesTrak orbital elements, cached on disk, propagated with SGP4
on the device. No Kodi imports.

Elements   Downloaded per CelesTrak GP group when online, kept in the profile folder, and
           used until they are older than the user's limit; then those satellites are
           hidden, never shown at a position the data can no longer support.
Keyframes  A worker propagates every satellite at instants `step` seconds apart and keeps
           the ones above the horizon at either end of the interval. Between keyframes
           the engine interpolates along the orbit (great-circle slerp, radius linear),
           which is accurate to well under a kilometre for these intervals, so moving dots
           cost almost nothing per frame.
Brightness Standard magnitudes (1000 km range, half lit) are approximate: known values for
           a few objects, typical ones for rocket bodies and Starlink, a default otherwise;
           a diffuse-sphere phase law and the Earth's cylindrical shadow do the rest.
"""

import math
import os
import time

from . import astro, net
from .sgp4.api import Satrec

CELESTRAK = 'https://celestrak.org/NORAD/elements/gp.php?GROUP=%s&FORMAT=tle'
STD_MAG = {25544: -1.8, 48274: -0.8, 20580: 2.2}   # ISS, Tiangong (Tianhe), Hubble
EARTH_RADIUS_KM = 6371.0
MAX_TRACKED = 60


class Satellite(object):
    __slots__ = ('name', 'number', 'rec', 'epoch_unix', 'std_mag', 'group')

    def __init__(self, name, rec, group):
        self.name = name.strip()
        self.rec = rec
        self.number = rec.satnum
        self.group = group
        self.epoch_unix = (rec.jdsatepoch + rec.jdsatepochF - astro.UNIX_EPOCH_JD) * 86400.0
        if self.number in STD_MAG:
            self.std_mag = STD_MAG[self.number]
        elif self.name.startswith('STARLINK'):
            self.std_mag = 5.0
        elif 'R/B' in self.name:
            self.std_mag = 3.0
        else:
            self.std_mag = 4.5

    def age_days(self, unix):
        return (unix - self.epoch_unix) / 86400.0

    def short_name(self):
        n = self.name
        if n.startswith('ISS'):
            return 'ISS'
        if n.startswith('CSS'):
            return 'Tiangong'
        if n.startswith('HST'):
            return 'Hubble'
        return n.title() if n.isupper() and not n.startswith('STARLINK') else n


def parse_tle(text, group):
    """Two- or three-line element sets -> [Satellite]; malformed sets are skipped."""
    lines = [l.rstrip() for l in text.splitlines() if l.strip()]
    out = []
    i = 0
    while i < len(lines):
        if lines[i].startswith('1 ') and i + 1 < len(lines) and lines[i + 1].startswith('2 '):
            name, l1, l2 = 'NORAD %s' % lines[i][2:7].strip(), lines[i], lines[i + 1]
            i += 2
        elif i + 2 < len(lines) and lines[i + 1].startswith('1 ') and lines[i + 2].startswith('2 '):
            name, l1, l2 = lines[i], lines[i + 1], lines[i + 2]
            i += 3
        else:
            i += 1
            continue
        try:
            out.append(Satellite(name, Satrec.twoline2rv(l1, l2), group))
        except Exception:
            continue
    return out


class ElementStore(object):
    """Orbital elements per CelesTrak group, on disk in `folder`."""

    def __init__(self, folder):
        self.folder = folder
        if not os.path.isdir(folder):
            os.makedirs(folder)

    def path(self, group):
        return os.path.join(self.folder, 'tle-%s.txt' % group)

    def fetched(self, group):
        p = self.path(group)
        return os.path.getmtime(p) if os.path.exists(p) else None

    def download(self, group):
        try:
            text = net.fetch(CELESTRAK % group, timeout=30).decode('ascii', 'replace')
        except net.HttpError as error:
            # CelesTrak answers 404 "No GP data found" for a group that is empty right now
            # (for example no launches in the last 30 days): that is data, not a failure.
            if 'HTTP Error 404' not in str(error):
                raise
            text = ''
        if text and not parse_tle(text, group):
            raise net.HttpError('CelesTrak %s: no elements in the reply' % group)
        tmp = self.path(group) + '.tmp'
        with open(tmp, 'w') as handle:
            handle.write(text)
        os.replace(tmp, self.path(group))

    def load(self, groups):
        """All satellites in the cached groups, de-duplicated by catalogue number."""
        seen = {}
        for group in groups:
            p = self.path(group)
            if not os.path.exists(p):
                continue
            try:
                with open(p) as handle:
                    sats = parse_tle(handle.read(), group)
            except (IOError, OSError, ValueError):
                continue
            for s in sats:
                seen.setdefault(s.number, s)
        return list(seen.values())

    def clear(self):
        for name in os.listdir(self.folder):
            if name.startswith('tle-'):
                try:
                    os.remove(os.path.join(self.folder, name))
                except OSError:
                    pass


# ---------------------------------------------------------------- geometry

def teme_to_ecef_matrix(unix):
    """TEME -> pseudo Earth-fixed: a rotation by Greenwich mean sidereal time (polar motion
    is ignored: a few metres)."""
    return astro.rot_z(astro.gmst(astro.jd_ut(unix)))


class Observer(object):
    def __init__(self, lat, lon, elevation_m):
        self.lat, self.lon = lat, lon
        self.ecef = astro.geodetic_to_ecef(lat, lon, elevation_m)
        sl, cl = math.sin(lon), math.cos(lon)
        sp, cp = math.sin(lat), math.cos(lat)
        # ECEF -> ENU
        self.enu = ((-sl, cl, 0.0), (-sp * cl, -sp * sl, cp), (cp * cl, cp * sl, sp))

    def topocentric(self, r_ecef):
        d = astro.sub(r_ecef, self.ecef)
        return astro.mxv(self.enu, d)


def sun_teme(unix):
    """Unit vector to the Sun, mean equator of date (good to a few arcminutes here)."""
    jd = astro.jd_tt(unix)
    t = astro.centuries(jd)
    l0 = (280.46646 + 36000.76983 * t) % 360.0
    m = math.radians((357.52911 + 35999.05029 * t) % 360.0)
    c = (1.914602 - 0.004817 * t) * math.sin(m) + 0.019993 * math.sin(2 * m) + 0.000289 * math.sin(3 * m)
    lon = math.radians(l0 + c)
    eps = astro.mean_obliquity(jd)
    return astro.ecliptic_to_equatorial(astro.vec(lon, 0.0), eps)


def in_shadow(r_teme, sun_u):
    """Cylindrical Earth shadow."""
    d = astro.dot(r_teme, sun_u)
    if d > 0:
        return False
    perp = astro.sub(r_teme, astro.scale(sun_u, d))
    return astro.length(perp) < EARTH_RADIUS_KM


def magnitude(std_mag, range_km, phase):
    """Diffuse sphere: standard magnitude is at 1000 km and a 90 degree phase angle."""
    f = math.sin(phase) + (math.pi - phase) * math.cos(phase)
    if f <= 1e-6:
        return 99.0
    return std_mag + 5.0 * math.log10(range_km / 1000.0) - 2.5 * math.log10(f)


def slerp(a, b, t):
    ra, rb = astro.length(a), astro.length(b)
    ua, ub = astro.scale(a, 1.0 / ra), astro.scale(b, 1.0 / rb)
    c = max(-1.0, min(1.0, astro.dot(ua, ub)))
    om = math.acos(c)
    r = ra + (rb - ra) * t
    if om < 1e-9:
        return astro.scale(ua, r)
    so = math.sin(om)
    ka, kb = math.sin((1 - t) * om) / so, math.sin(t * om) / so
    return (r * (ka * ua[0] + kb * ub[0]), r * (ka * ua[1] + kb * ub[1]), r * (ka * ua[2] + kb * ub[2]))


class Fix(object):
    """One satellite's state at one instant, for the screen."""
    __slots__ = ('sat', 'hor', 'range_km', 'lit', 'mag')

    def __init__(self, sat, hor, range_km, lit, mag):
        self.sat, self.hor, self.range_km, self.lit, self.mag = sat, hor, range_km, lit, mag


class Tracker(object):
    """Keyframes for every satellite, refreshed by a worker; interpolated by the engine."""

    def __init__(self, sats, observer, max_age_days):
        self.observer = observer
        self.max_age = max_age_days
        self.all = sats
        self.sats = []
        self.stale = 0
        self.step = 20.0 if len(sats) < 2000 else 40.0
        self.window = None      # (t0, t1, [(sat, r0, r1)])
        self.cost = 0.0
        self.oldest_days = self.newest_days = None
        self.select(time.time())

    def select(self, unix):
        fresh = [s for s in self.all if abs(s.age_days(unix)) <= self.max_age]
        self.stale = len(self.all) - len(fresh)
        self.sats = fresh
        ages = [s.age_days(unix) for s in fresh]
        self.oldest_days = max(ages) if ages else None
        self.newest_days = min(ages) if ages else None

    def _propagate(self, sat, unix):
        jd = unix / 86400.0 + astro.UNIX_EPOCH_JD
        whole = math.floor(jd - 0.5) + 0.5
        err, r, _v = sat.rec.sgp4(whole, jd - whole)
        if err:
            return None
        return r

    def build(self, t0, stop=None):
        """Keyframes for [t0, t0 + step]. Returns the new window (also stored)."""
        started = time.time()
        t1 = t0 + self.step
        m0, m1 = teme_to_ecef_matrix(t0), teme_to_ecef_matrix(t1)
        obs = self.observer
        keep = []
        # Cheap rejection: above the horizon means within about this angle of the zenith,
        # as seen from the Earth's centre.
        up = astro.norm(obs.ecef)
        for i, sat in enumerate(self.sats):
            if stop is not None and i % 500 == 0 and stop():
                return None
            r0 = self._propagate(sat, t0)
            r1 = self._propagate(sat, t1)
            if r0 is None or r1 is None:
                continue
            e0, e1 = astro.mxv(m0, r0), astro.mxv(m1, r1)
            rmin = min(astro.length(e0), astro.length(e1))
            horizon = EARTH_RADIUS_KM / rmin
            if astro.dot(up, e0) / astro.length(e0) < horizon - 0.1 and \
                    astro.dot(up, e1) / astro.length(e1) < horizon - 0.1:
                continue
            if obs.topocentric(e0)[2] < 0 and obs.topocentric(e1)[2] < 0:
                continue
            keep.append((sat, r0, r1))
        self.window = (t0, t1, keep)
        self.cost = time.time() - started
        # Keep the worker under about a sixth of a core: lengthen the interval if needed.
        self.step = min(90.0, max(self.step, self.cost * 6.0))
        return self.window

    def fixes(self, unix, shadowed=False):
        """Positions at `unix` of every satellite above the horizon in the current window."""
        w = self.window
        if w is None or not (w[0] - 1 <= unix <= w[1] + 1):
            return []
        t0, t1, keep = w
        t = (unix - t0) / (t1 - t0)
        m = teme_to_ecef_matrix(unix)
        sun = sun_teme(unix)
        obs = self.observer
        out = []
        for sat, r0, r1 in keep:
            r = slerp(r0, r1, t)
            top = obs.topocentric(astro.mxv(m, r))
            if top[2] <= 0:
                continue
            rng = astro.length(top)
            hor = astro.scale(top, 1.0 / rng)
            lit = not in_shadow(r, sun)
            if not lit and not shadowed:
                continue
            # Phase angle at the satellite between the Sun and the observer.
            to_obs = astro.mxv(astro.transpose(m), astro.sub(obs.ecef, astro.mxv(m, r)))
            phase = astro.angle(sun, to_obs)
            mag = magnitude(sat.std_mag, rng, phase) if lit else 99.0
            out.append(Fix(sat, hor, rng, lit, mag))
        return out
