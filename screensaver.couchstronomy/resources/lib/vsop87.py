"""Planet positions from VSOP87B (Bretagnon & Francou 1988), truncated by
tools/make_couch_data.py to about an arcsecond over 1900-2100. No Kodi imports.

VSOP87B gives heliocentric spherical coordinates (L, B, R) in the ecliptic and equinox of
J2000. Each coordinate is sum over a of tau^a * sum A cos(B + C tau), with tau in Julian
millennia of TT from J2000.
"""

import json
import math
import os

from . import astro

DATA = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'data', 'vsop87.json')
PLANETS = ('mercury', 'venus', 'earth', 'mars', 'jupiter', 'saturn', 'uranus', 'neptune')
_series = None


def _load():
    global _series
    if _series is None:
        with open(DATA) as handle:
            _series = json.load(handle)
    return _series


def _evaluate(powers, tau):
    """(value, derivative per millennium) of one coordinate."""
    value = rate = 0.0
    tp = 1.0           # tau ** a
    for a, terms in enumerate(powers):
        s = ds = 0.0
        for amp, phase, freq in terms:
            arg = phase + freq * tau
            s += amp * math.cos(arg)
            ds -= amp * freq * math.sin(arg)
        if a:
            rate += a * tau ** (a - 1) * s
        rate += tp * ds
        value += tp * s
        tp *= tau
    return value, rate


def _spherical(planet, jd_tt, velocity=False):
    data = _load()[planet]
    tau = (jd_tt - astro.J2000) / 365250.0
    lon, dlon = _evaluate(data['L'], tau)
    lat, dlat = _evaluate(data['B'], tau)
    r, dr = _evaluate(data['R'], tau)
    return lon, lat, r, dlon, dlat, dr


def helio(planet, jd_tt):
    """Heliocentric position, J2000 equatorial, AU."""
    lon, lat, r = _spherical(planet, jd_tt)[:3]
    return astro.mxv(astro.ECL_TO_EQ_J2000, astro.vec(lon, lat, r))


def helio_state(planet, jd_tt):
    """Heliocentric position (AU) and velocity (AU/day), J2000 equatorial."""
    lon, lat, r, dlon, dlat, dr = _spherical(planet, jd_tt)
    cl, sl, cb, sb = math.cos(lon), math.sin(lon), math.cos(lat), math.sin(lat)
    pos = (r * cb * cl, r * cb * sl, r * sb)
    k = 1.0 / 365250.0   # per millennium -> per day
    vel = ((dr * cb * cl - r * sb * cl * dlat - r * cb * sl * dlon) * k,
           (dr * cb * sl - r * sb * sl * dlat + r * cb * cl * dlon) * k,
           (dr * sb + r * cb * dlat) * k)
    m = astro.ECL_TO_EQ_J2000
    return astro.mxv(m, pos), astro.mxv(m, vel)


def earth_state(jd_tt):
    return helio_state('earth', jd_tt)
