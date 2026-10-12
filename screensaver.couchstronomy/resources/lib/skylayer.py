"""The two low-resolution layers under the stars. No Kodi imports.

Background  a coarse RGB image of the sky's own light: airglow, light pollution, twilight,
            daylight, the Sun's glare and moonlight. Kodi stretches it smoothly to full
            screen. Recomputed only while the Sun or Moon changes it.
Milky Way   an RGBA image of the Milky Way plus the ground (or a black fade) below the
            horizon. The camera never moves, so each pixel's hour angle and declination
            are fixed: a new frame is the bundled RA/Dec map shifted by the sidereal time,
            which is a handful of C-level map() passes over precomputed index arrays.
"""

import math
import os
import random
from array import array
from itertools import repeat
from operator import add, mod

from . import astro, draw

DEG = astro.DEG
DATA = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'data')
MW_RGB = (200, 208, 232)
GROUND, FADE, SEE_THROUGH = 0, 1, 2



def _clamp(x, lo=0.0, hi=1.0):
    return lo if x < lo else (hi if x > hi else x)


class SkyLight(object):
    """The sky's colour at a direction, given the Sun and Moon (all angles in degrees)."""

    def __init__(self, sun_alt, sun_hor, moon_alt, moon_hor, moon_illum, light_pollution, keep_dark):
        self.sun_hor, self.moon_hor = sun_hor, moon_hor
        self.lp = light_pollution
        s = -90.0 if keep_dark else sun_alt
        self.twilight = _clamp((s + 18.0) / 16.0) ** 2.4
        self.day = _clamp((s + 3.0) / 9.0) ** 1.3
        self.sun_below = _clamp(-s / 6.0)
        m = 0.0
        if moon_alt > -2:
            m = moon_illum ** 1.5 * _clamp((moon_alt + 2.0) / 20.0)
        self.moon = m * (0.35 if keep_dark else 1.0)

    def rgb(self, v):
        alt = math.degrees(math.asin(_clamp(v[2], -1.0, 1.0)))
        a = max(alt, 0.0)
        hz = math.exp(-a / 12.0)
        hz2 = math.exp(-a / 7.0)
        r = 1.2 + 3.0 * hz
        g = 2.0 + 4.0 * hz
        b = 6.0 + 7.0 * hz
        lp = self.lp
        if lp:
            r += lp * (60.0 * hz2 + 5.0)
            g += lp * (44.0 * hz2 + 5.0)
            b += lp * (30.0 * hz2 + 6.0)
        tw, day = self.twilight, self.day
        if tw > 0.001:
            cs = astro.dot(v, self.sun_hor)
            k = tw * (1.0 - day)
            sun_side = ((1.0 + cs) / 2.0) ** 3
            anti = ((1.0 - cs) / 2.0) ** 2
            low = math.exp(-a / 6.0)
            r += k * (14.0 + 240.0 * low * (0.3 + 0.7 * sun_side) * self.sun_below + 55.0 * anti * hz)
            g += k * (26.0 + 115.0 * low * (0.3 + 0.7 * sun_side) * self.sun_below + 35.0 * anti * hz)
            b += k * (62.0 + 45.0 * low * (0.3 + 0.7 * sun_side) * self.sun_below + 65.0 * anti * hz)
            if day > 0.001:
                mix = (1.0 - a / 90.0) ** 3
                sep = math.degrees(math.acos(_clamp(cs, -1.0, 1.0)))
                glare = 150.0 * math.exp(-sep / 6.0) + 55.0 * math.exp(-sep / 30.0)
                r += day * (38.0 + 112.0 * mix + glare)
                g += day * (92.0 + 93.0 * mix + glare * 0.97)
                b += day * (190.0 + 35.0 * mix + glare * 0.88)
        if self.moon > 0.001:
            cm = astro.dot(v, self.moon_hor)
            sep = math.degrees(math.acos(_clamp(cm, -1.0, 1.0)))
            aureole = math.exp(-sep / 7.0)
            r += self.moon * (9.0 + 45.0 * aureole)
            g += self.moon * (15.0 + 45.0 * aureole)
            b += self.moon * (30.0 + 52.0 * aureole)
        return r, g, b

    def ground(self):
        d, t = self.day, self.twilight * (1.0 - self.day)
        return (int(3 + 26 * d + 6 * t + 6 * self.moon), int(3 + 28 * d + 5 * t + 6 * self.moon),
                int(5 + 22 * d + 8 * t + 8 * self.moon))


class Background(object):
    """The coarse sky-colour image."""

    def __init__(self, camera, w=256, h=144):
        self.w, self.h = w, h
        self.dirs = []
        # Fixed per-pixel noise (one value per channel) to dither dark gradients: without
        # it, 8-bit steps show as bands; a regular pattern would show as a grid.
        rng = random.Random(7)
        self.noise = [rng.random() for _ in range(w * h * 3)]
        for j in range(h):
            for i in range(w):
                sx = (i + 0.5) * camera.width / float(w)
                sy = (j + 0.5) * camera.height / float(h)
                self.dirs.append(camera.unproject(sx, sy))

    def render(self, light):
        out = bytearray(self.w * self.h * 3)
        k = 0
        noise = self.noise
        for v in self.dirs:
            r, g, b = light.rgb(v)
            out[k] = min(255, int(r + noise[k]))
            out[k + 1] = min(255, int(g + noise[k + 1]))
            out[k + 2] = min(255, int(b + noise[k + 2]))
            k += 3
        return draw.encode_png(self.w, self.h, bytes(out), channels=3, level=6)


class MilkyWay(object):
    """Lookup tables from screen pixels to the bundled Milky Way map, and the ground mask."""

    def __init__(self, camera, lat, horizon_mode, extinction, w=480, h=270):
        self.w, self.h = w, h
        tw, th, _c, tex = draw.load_raw(os.path.join(DATA, 'milkyway.bin'))
        self.tex = tex
        self.tw = tw
        hor_to_eq0 = astro.transpose(astro.equatorial_to_horizon_matrix(0.0, lat))
        self.col0 = array('d')
        self.rowbase = array('l')
        fade = bytearray(w * h)
        ground_runs = []
        for j in range(h):
            run_start = None
            for i in range(w):
                sx = (i + 0.5) * camera.width / float(w)
                sy = (j + 0.5) * camera.height / float(h)
                v = camera.unproject(sx, sy)
                e = astro.mxv(hor_to_eq0, v)
                ra0 = math.atan2(e[1], e[0])
                dec = math.asin(_clamp(e[2], -1.0, 1.0))
                row = min(th - 1, int((0.5 - dec / math.pi) * th))
                self.col0.append((ra0 / (2 * math.pi)) % 1.0 * tw)
                self.rowbase.append(row * tw)
                alt = math.degrees(math.asin(_clamp(v[2], -1.0, 1.0)))
                f = 1.0
                if extinction and alt > -1:
                    f = 10 ** (-0.4 * 0.2 * (astro.airmass(max(alt, 0.0) * DEG) - 1.0))
                if horizon_mode == FADE:
                    f *= _clamp(alt / 12.0)
                elif horizon_mode == GROUND:
                    f *= _clamp(alt / 1.5)
                fade[j * w + i] = int(255 * f)
                below = alt < 0 and horizon_mode != SEE_THROUGH
                if below and run_start is None:
                    run_start = i
                elif not below and run_start is not None:
                    ground_runs.append((j, run_start, i))
                    run_start = None
            if run_start is not None:
                ground_runs.append((j, run_start, w))
        self.fade = bytes(fade)
        self.ground_runs = ground_runs
        self.horizon_mode = horizon_mode
        self.has_ground = bool(ground_runs)
        self._table_key = None
        self._table = None

    def _pair_table(self, gain):
        """65536-entry table: (Milky Way value, fade) -> alpha."""
        if self._table_key == gain:
            return self._table
        out = bytearray(65536)
        for f in range(256):
            base = f << 8
            ff = f / 255.0 * gain
            for m in range(256):
                a = (m / 255.0) ** 1.25 * ff * 255.0
                out[base | m] = 255 if a > 255 else int(a)
        self._table_key, self._table = gain, bytes(out)
        return self._table

    def render(self, lst, gain, ground_rgb, show_milky_way=True):
        """RGBA PNG bytes for local sidereal time lst (radians). gain scales the Milky Way's
        alpha (0 hides it)."""
        n = self.w * self.h
        out = bytearray(n * 4)
        if show_milky_way and gain > 0.003:
            shift = (lst / (2 * math.pi)) % 1.0 * self.tw
            cols = map(mod, map(int, map(add, self.col0, repeat(shift))), repeat(self.tw))
            idx = map(add, self.rowbase, cols)
            mw = bytes(map(self.tex.__getitem__, idx))
            pairs = bytearray(n * 2)
            pairs[0::2] = mw
            pairs[1::2] = self.fade
            keys = array('H')
            keys.frombytes(bytes(pairs))
            if keys.itemsize == 2 and array('H', [1]).tobytes() != b'\x01\x00':
                keys.byteswap()
            alpha = bytes(map(self._pair_table(gain).__getitem__, keys))
            out[0::4] = bytes((MW_RGB[0],)) * n
            out[1::4] = bytes((MW_RGB[1],)) * n
            out[2::4] = bytes((MW_RGB[2],)) * n
            out[3::4] = alpha
        if self.ground_runs:
            px = bytes(ground_rgb if self.horizon_mode == GROUND else (0, 0, 0)) + b'\xff'
            w = self.w
            for j, i0, i1 in self.ground_runs:
                out[(j * w + i0) * 4:(j * w + i1) * 4] = px * (i1 - i0)
        return draw.encode_png(self.w, self.h, bytes(out), channels=4, level=3)
