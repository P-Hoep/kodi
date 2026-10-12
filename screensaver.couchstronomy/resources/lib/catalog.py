"""The bundled catalogues: stars, constellations, boundaries, deep-sky objects. No Kodi
imports.

Stars are float32 columns sorted brightest first, so "every star down to magnitude m" is a
prefix. Proper motion is applied once at load, and culling to the field of view is a few
C-level map() passes over the columns, so neither costs much even on a Fire TV Stick.
"""

import bisect
import json
import math
import os
import sys
from array import array
from itertools import compress, repeat
from operator import add, gt, mul

from . import astro

DATA = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'data')


def _path(name):
    return os.path.join(DATA, name)


class Stars(object):
    def __init__(self, year):
        with open(_path('stars.json'), encoding='utf-8') as handle:
            meta = json.load(handle)
        n = meta['count']
        with open(_path('stars.bin'), 'rb') as handle:
            blob = handle.read()
        cols = []
        for k in range(8):
            a = array('f')
            a.frombytes(blob[k * 4 * n:(k + 1) * 4 * n])
            if sys.byteorder != 'little':
                a.byteswap()
            cols.append(a)
        dt = year - meta['epoch']
        # Linear proper motion; the vectors stay unit length to ~1e-9 over centuries.
        self.x = array('d', map(add, cols[0], map(mul, cols[3], repeat(dt))))
        self.y = array('d', map(add, cols[1], map(mul, cols[4], repeat(dt))))
        self.z = array('d', map(add, cols[2], map(mul, cols[5], repeat(dt))))
        self.mag = cols[6]
        self.bv = cols[7]
        self.count = n
        self.year = year
        self.names = {}
        for i, proper, desig, con, dist_ly, hip, spect, var in meta['names']:
            self.names[i] = StarName(proper, desig, con, dist_ly, hip, spect, var)
        self.limit = meta['limit']

    def count_brighter(self, mag_limit):
        return bisect.bisect_right(self.mag, mag_limit)

    def in_cone(self, axis, cos_radius, mag_limit):
        """Indices of stars brighter than mag_limit within the cone (J2000 axis)."""
        n = self.count_brighter(mag_limit)
        ax, ay, az = axis
        xs, ys, zs = self.x[:n], self.y[:n], self.z[:n]
        dots = map(add, map(add, map(mul, xs, repeat(ax)), map(mul, ys, repeat(ay))), map(mul, zs, repeat(az)))
        return list(compress(range(n), map(gt, dots, repeat(cos_radius))))

    def vector(self, i):
        return (self.x[i], self.y[i], self.z[i])

    def find(self, name):
        for i, info in self.names.items():
            if info.proper == name:
                return i
        return None


class StarName(object):
    __slots__ = ('proper', 'desig', 'con', 'dist_ly', 'hip', 'spect', 'var')

    def __init__(self, proper, desig, con, dist_ly, hip, spect, var):
        self.proper, self.desig, self.con = proper, desig, con
        self.dist_ly, self.hip, self.spect, self.var = dist_ly, hip, spect, var

    def label(self):
        return self.proper or self.desig


def radec_vec(ra_deg, dec_deg):
    return astro.vec(ra_deg * astro.DEG, dec_deg * astro.DEG)


class Constellation(object):
    __slots__ = ('id', 'name', 'gen', 'rank', 'label', 'lines', 'center', 'cos_extent')

    def __init__(self, d):
        self.id, self.name, self.gen, self.rank = d['id'], d['name'], d['gen'], d['rank']
        self.label = radec_vec(*d['label'])
        self.lines = [[radec_vec(*p) for p in line] for line in d['lines']]
        pts = [p for line in self.lines for p in line] or [self.label]
        c = astro.norm(tuple(sum(p[k] for p in pts) for k in range(3)))
        self.center = c
        self.cos_extent = min(astro.dot(c, p) for p in pts)


class DeepSky(object):
    __slots__ = ('name', 'desig', 'alt', 'type', 'mag', 'major', 'minor', 'vec')

    TYPE_NAMES = {'gg': 'galaxy cluster', 'g': 'galaxy', 's': 'spiral galaxy', 's0': 'lenticular galaxy',
                  'sd': 'dwarf galaxy', 'i': 'irregular galaxy', 'e': 'elliptical galaxy',
                  'oc': 'open cluster', 'gc': 'globular cluster', 'dn': 'dark nebula', 'bn': 'bright nebula',
                  'sfr': 'star-forming region', 'rn': 'reflection nebula', 'en': 'emission nebula',
                  'pn': 'planetary nebula', 'snr': 'supernova remnant', 'ds': 'double star',
                  'as': 'asterism'}

    def __init__(self, d):
        self.name, self.desig, self.alt, self.type = d['name'], d['desig'], d['alt'], d['type']
        self.mag = d['mag']
        self.major, self.minor = d['size']
        self.vec = radec_vec(d['ra'], d['dec'])

    def type_name(self):
        return self.TYPE_NAMES.get(self.type, 'deep-sky object')

    def is_galaxy(self):
        return self.type in ('g', 's', 's0', 'sd', 'i', 'e', 'gg')

    def is_cluster(self):
        return self.type in ('oc', 'gc', 'as')


class Sky(object):
    def __init__(self):
        with open(_path('sky.json'), encoding='utf-8') as handle:
            d = json.load(handle)
        self.constellations = [Constellation(c) for c in d['constellations']]
        self.by_id = {c.id: c for c in self.constellations}
        self.borders = [[radec_vec(*p) for p in line] for line in d['borders']]
        self.dsos = [DeepSky(x) for x in d['dsos']]


def year_of(unix):
    return 1970.0 + unix / (365.25 * 86400.0)


def bv_to_rgb(bv):
    """B-V colour index -> an sRGB colour (Ballesteros' temperature, then a blackbody fit)."""
    bv = max(-0.4, min(2.0, bv))
    t = 4600.0 * (1.0 / (0.92 * bv + 1.7) + 1.0 / (0.92 * bv + 0.62))
    t /= 100.0
    if t <= 66:
        r = 255.0
        g = 99.4708025861 * math.log(t) - 161.1195681661
        b = 0.0 if t <= 19 else 138.5177312231 * math.log(t - 10) - 305.0447927307
    else:
        r = 329.698727446 * (t - 60) ** -0.1332047592
        g = 288.1221695283 * (t - 60) ** -0.0755148492
        b = 255.0
    return tuple(int(max(0, min(255, c))) for c in (r, g, b))
