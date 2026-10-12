"""The star layer: a transparent RGBA image of stars, planets, the Moon and Sun, deep-sky
glows and constellation lines, drawn in pure Python. No Kodi imports.

Kodi blends the layer over the sky-colour layers. Every mark is written with a per-byte
max() over whole sprite rows (one C-level map per row), so overlapping glows merge rather
than add, and a layer of a thousand stars takes a few tens of milliseconds on a Mac.

Brightness: a star's peak alpha follows its flux through a display gamma, so six
magnitudes (a factor of 250 in light) become about a factor of ten on screen, as the eye
sees them. Stars brighter than about first magnitude saturate and grow a restrained halo.
"""

import math
import struct
import zlib

from . import astro

SIGNATURE = b'\x89PNG\r\n\x1a\n'
SUBPIXEL = 4          # sprite positions are quantised to 1/4 pixel
MAX_SPRITES = 40000


def _chunk(kind, body):
    return struct.pack('>I4s', len(body), kind) + body + struct.pack('>I', zlib.crc32(kind + body) & 0xFFFFFFFF)


def encode_png(w, h, raw, channels=4, level=1):
    """RGBA (channels 4), RGB (3) or grey (1) bytes -> PNG bytes, unfiltered rows."""
    ctype = {1: 0, 3: 2, 4: 6}[channels]
    stride = w * channels
    rows = b''.join(b'\x00' + raw[y * stride:(y + 1) * stride] for y in range(h))
    return (SIGNATURE + _chunk(b'IHDR', struct.pack('>IIBBBBB', w, h, 8, ctype, 0, 0, 0))
            + _chunk(b'IDAT', zlib.compress(rows, level)) + _chunk(b'IEND', b''))


class Appearance(object):
    """Magnitude -> (core alpha, sigma px, halo alpha, halo radius px)."""

    def __init__(self, enhance=0, brightness=1.0, scale=1.0):
        self.gamma = (2.3, 2.7, 3.1)[enhance]
        self.gain = brightness * (1.0, 1.25, 1.45)[enhance]
        self.size = scale * (1.0, 1.12, 1.25)[enhance]
        self.floor = (0.16, 0.20, 0.24)[enhance]
        self.scale = scale

    def __call__(self, mag):
        flux = 10.0 ** (-0.4 * (mag - 2.2))
        core = flux ** (1.0 / self.gamma) * self.gain
        core = min(1.0, self.floor + (1.0 - self.floor) * core) if core > 0.002 else 0.0
        # A TV pixel seen from the sofa is far smaller than the eye's blur, so even the
        # faintest stars get a few pixels; bright ones grow and take a soft halo.
        sigma = min(2.4, 0.9 + 0.25 * max(0.0, 4.5 - mag)) * self.size * self.scale
        halo_a = halo_r = 0.0
        if mag < 2.5:
            halo_a = min(0.3, 0.075 * (2.5 - mag)) * min(1.0, self.gain)
            halo_r = (4.0 + 3.0 * (2.5 - mag)) * self.size * self.scale
        return core, sigma, halo_a, halo_r


class StarLayer(object):
    def __init__(self, width, height, appearance, line_rgb=(96, 130, 196), line_alpha=0.26):
        self.w, self.h = width, height
        self.look = appearance
        self.sprites = {}
        self.line_rgb = line_rgb
        self.line_alpha = line_alpha
        self.moon_mips = None
        self.buf = None

    # ------------------------------------------------------------ primitives

    def clear(self):
        self.buf = bytearray(self.w * self.h * 4)

    def _sprite(self, mag_q, fx, fy, rgb):
        key = (mag_q, fx, fy, rgb)
        sp = self.sprites.get(key)
        if sp is not None:
            return sp
        if len(self.sprites) > MAX_SPRITES:
            self.sprites.clear()
        core, sigma, halo_a, halo_r = self.look(mag_q / 10.0)
        ox, oy = fx / float(SUBPIXEL), fy / float(SUBPIXEL)
        rad = int(math.ceil(max(2.5 * sigma, halo_r)))
        inv2s = 1.0 / (2.0 * sigma * sigma)
        rows = []
        r, g, b = rgb
        for dy in range(-rad, rad + 1):
            row = bytearray()
            first = None
            for dx in range(-rad, rad + 1):
                ddx, ddy = dx - ox, dy - oy
                d2 = ddx * ddx + ddy * ddy
                a = core * math.exp(-d2 * inv2s)
                if halo_r:
                    d = math.sqrt(d2)
                    if d < halo_r:
                        t = d / halo_r
                        a = max(a, halo_a * (1.0 - t) ** 2 / (1.0 + 6.0 * t * t))
                ai = int(a * 255 + 0.5)
                if ai > 255:
                    ai = 255
                if ai <= 1 and first is None:
                    continue
                if first is None:
                    first = dx
                row += bytes((r, g, b, ai)) if ai > 1 else b'\x00\x00\x00\x00'
            if first is None:
                continue
            while row and row[-1] <= 1 and len(row) >= 4 and row[-4:] == b'\x00\x00\x00\x00':
                del row[-4:]
            if row:
                rows.append((dy, first, bytes(row)))
        self.sprites[key] = rows
        return rows

    def _blit(self, rows, x0, y0):
        buf, w, h = self.buf, self.w, self.h
        for dy, dx, data in rows:
            y = y0 + dy
            if y < 0 or y >= h:
                continue
            x = x0 + dx
            n = len(data) // 4
            if x < 0:
                cut = -x
                if cut >= n:
                    continue
                data = data[cut * 4:]
                n -= cut
                x = 0
            if x + n > w:
                n = w - x
                if n <= 0:
                    continue
                data = data[:n * 4]
            off = (y * w + x) * 4
            end = off + n * 4
            buf[off:end] = bytes(map(max, buf[off:end], data))

    def star(self, x, y, mag, rgb, fade=1.0):
        if fade < 1.0:
            if fade <= 0.02:
                return
            mag -= 2.5 * math.log10(fade)
        mag_q = int(round(mag * 10))
        ix, iy = int(math.floor(x)), int(math.floor(y))
        fx = int((x - ix) * SUBPIXEL)
        fy = int((y - iy) * SUBPIXEL)
        self._blit(self._sprite(mag_q, fx, fy, rgb), ix, iy)

    def pixel(self, x, y, rgb, a):
        if 0 <= x < self.w and 0 <= y < self.h and a > 0:
            off = (y * self.w + x) * 4
            ai = int(a * 255)
            buf = self.buf
            if ai > buf[off + 3]:
                buf[off] = max(buf[off], rgb[0])
                buf[off + 1] = max(buf[off + 1], rgb[1])
                buf[off + 2] = max(buf[off + 2], rgb[2])
                buf[off + 3] = ai

    def line(self, x0, y0, x1, y1, rgb, alpha, dash=0):
        """Xiaolin Wu's antialiased line, clipped to the image."""
        c = _clip(x0, y0, x1, y1, -1, -1, self.w, self.h)
        if c is None:
            return
        x0, y0, x1, y1 = c
        steep = abs(y1 - y0) > abs(x1 - x0)
        if steep:
            x0, y0, x1, y1 = y0, x0, y1, x1
        if x0 > x1:
            x0, x1, y0, y1 = x1, x0, y1, y0
        dx = x1 - x0
        grad = (y1 - y0) / dx if dx else 0.0
        y = y0 + grad * (round(x0) - x0)
        plot = self.pixel
        i = 0
        for x in range(int(round(x0)), int(round(x1)) + 1):
            if dash and (i // dash) % 2:
                i += 1
                y += grad
                continue
            i += 1
            fy = math.floor(y)
            f = y - fy
            if steep:
                plot(int(fy), x, rgb, alpha * (1 - f))
                plot(int(fy) + 1, x, rgb, alpha * f)
            else:
                plot(x, int(fy), rgb, alpha * (1 - f))
                plot(x, int(fy) + 1, rgb, alpha * f)
            y += grad

    def ring(self, x, y, rx, ry, rgb, alpha):
        """A thin ellipse outline (deep-sky symbols)."""
        n = max(16, int((rx + ry) * 1.6))
        prev = None
        for i in range(n + 1):
            t = 2 * math.pi * i / n
            p = (x + rx * math.cos(t), y + ry * math.sin(t))
            if prev:
                self.line(prev[0], prev[1], p[0], p[1], rgb, alpha)
            prev = p

    def glow(self, x, y, r, rgb, peak):
        """A soft round glow (deep-sky objects)."""
        if peak < 0.01 or r < 0.5:
            return
        rad = int(r * 2.2) + 1
        ix, iy = int(x), int(y)
        sig2 = 2.0 * (r * 0.8) ** 2
        texel = bytes(rgb)
        rows = []
        for dy in range(-rad, rad + 1):
            row = bytearray()
            for dx in range(-rad, rad + 1):
                d2 = (ix + dx - x) ** 2 + (iy + dy - y) ** 2
                a = int(255 * peak * math.exp(-d2 / sig2))
                row += texel + bytes((a,)) if a > 1 else b'\x00\x00\x00\x00'
            rows.append((dy, -rad, bytes(row)))
        self._blit(rows, ix, iy)

    # ------------------------------------------------------------ resolved bodies

    def disk(self, d, moon_texture=None, daylight=0.0):
        """Draw a Disk from scene.py: the Moon (textured), the Sun, or a planet with its
        phase. Lighting is per pixel: a surface normal facing the viewer is lit when it
        faces the Sun, so phases and the tilt of the terminator come out right."""
        b = d.body
        r = d.r
        if r < 0.5:
            return
        sx, sy, sz = d.sun
        rad = int(math.ceil(r + 1.5))
        if d.ring is not None:
            rad = int(math.ceil(r * 2.4 + 1.5))
        ix, iy = int(round(d.x)), int(round(d.y))
        fx, fy = d.x - ix, d.y - iy
        tex = None
        if b.kind == 'moon' and moon_texture is not None:
            tex = moon_texture.level(2 * r)
        cn, sn = math.cos(d.north), math.sin(d.north)
        base = b.color
        alpha_scale = d.fade
        ring = d.ring
        if ring is not None:
            tilt, ring_angle = ring
            sb = abs(math.sin(tilt)) or 1e-3
            cr, sr = math.cos(ring_angle), math.sin(ring_angle)
            near_sign = 1.0 if tilt > 0 else -1.0
        rows = []
        inv_r = 1.0 / r
        for dy in range(-rad, rad + 1):
            row = bytearray()
            for dx in range(-rad, rad + 1):
                px = (dx - fx) * inv_r
                py = -(dy - fy) * inv_r
                rr = px * px + py * py
                a = 0.0
                rgb = base
                in_disk = rr <= 1.0
                cover = max(0.0, min(1.0, (1.0 - math.sqrt(rr)) * r + 0.5))
                if cover > 0:
                    pz = math.sqrt(max(0.0, 1.0 - rr))
                    mu = sx * px + sy * py + sz * pz
                    if b.kind == 'sun':
                        limb = 0.55 + 0.45 * pz
                        rgb = (255, int(250 * limb + 5 * (1 - limb)), int(232 * limb))
                        a = cover
                    else:
                        lit = _smooth(-0.03, 0.07, mu)
                        if tex is not None:
                            # Texture: rotate the screen offset so the Moon's north is up.
                            tx = px * cn - py * sn
                            ty = px * sn + py * cn
                            g = tex.sample(tx, ty) / 255.0
                            shade = lit * (0.25 + 0.75 * min(1.0, mu * 4.0 + 0.6) if lit < 1 else 1.0)
                            earthshine = 0.07 * (1.0 - b.illum)
                            k = max(shade, earthshine) * g
                            v = 0.32 + 0.68 * g if shade > earthshine else g
                            rgb = (int(base[0] * v), int(base[1] * v), int(base[2] * v))
                            a = cover * min(1.0, k * 1.15 + (0.12 if shade > 0.02 else 0.0))
                            a = max(a, cover * earthshine * 0.6)
                        else:
                            limb = 0.62 + 0.38 * pz
                            a = cover * lit * limb
                            if b.name == 'Jupiter':
                                band = 0.88 + 0.12 * math.cos(py * 9.0 * cn + px * 9.0 * sn)
                                a *= band
                    a *= alpha_scale
                if ring is not None:
                    # Coordinates along the ring's major axis (u) and the projected pole (v).
                    u = px * cr - py * sr
                    vv = px * sr + py * cr
                    rho = math.sqrt(u * u + (vv / sb) ** 2)
                    ring_a = 0.0
                    if 1.24 <= rho <= 2.27:
                        ring_a = 0.25 if rho < 1.53 else (0.85 if rho < 1.95 else (0.15 if rho < 2.03 else 0.6))
                    if ring_a and (not in_disk or vv * near_sign < 0):
                        ring_a *= 0.85
                        if ring_a * alpha_scale > a:
                            a = ring_a * alpha_scale
                            rgb = (232, 214, 170)
                ai = int(min(1.0, a) * 255)
                row += bytes((rgb[0], rgb[1], rgb[2], ai)) if ai > 0 else b'\x00\x00\x00\x00'
            rows.append((dy, -rad, bytes(row)))
        self._blit(rows, ix, iy)

    # ------------------------------------------------------------ whole layer

    def render(self, scene, moon_texture=None, show_icons=False):
        self.clear()
        for x0, y0, x1, y1 in scene.borders:
            self.line(x0, y0, x1, y1, (150, 120, 70), 0.22, dash=5)
        for x0, y0, x1, y1 in scene.lines:
            self.line(x0, y0, x1, y1, self.line_rgb, self.line_alpha)
        for x, y, rx, ry, intensity, d in scene.dsos:
            r = math.sqrt(rx * ry)
            if intensity > 0.01:
                tint = (225, 228, 255) if d.is_galaxy() else ((255, 215, 225) if d.type in ('en', 'snr', 'sfr', 'bn') else (232, 240, 255))
                self.glow(x, y, r, tint, intensity)
            if show_icons:
                rr = max(5.0, r)
                if d.is_galaxy():
                    self.ring(x, y, max(5.0, rx), max(3.0, ry), (200, 150, 120), 0.45)
                elif d.type == 'gc':
                    self.ring(x, y, rr, rr, (200, 190, 120), 0.45)
                    self.line(x - rr, y, x + rr, y, (200, 190, 120), 0.35)
                    self.line(x, y - rr, x, y + rr, (200, 190, 120), 0.35)
                elif d.is_cluster():
                    self.ring(x, y, rr, rr, (200, 190, 120), 0.4)
                else:
                    self.line(x - rr, y - rr, x + rr, y - rr, (130, 190, 140), 0.45)
                    self.line(x + rr, y - rr, x + rr, y + rr, (130, 190, 140), 0.45)
                    self.line(x + rr, y + rr, x - rr, y + rr, (130, 190, 140), 0.45)
                    self.line(x - rr, y + rr, x - rr, y - rr, (130, 190, 140), 0.45)
        for p in scene.points:
            self.star(p.x, p.y, p.mag, p.rgb, p.fade)
        for d in sorted(scene.disks, key=lambda d: -d.body.dist_km):
            if d.body.kind == 'planet':
                self.star(d.x, d.y, d.mag, d.body.color, d.fade)   # its glow
            elif d.body.kind == 'sun':
                self.star(d.x, d.y, -3.0, (255, 248, 230), 1.0)
            self.disk(d, moon_texture)
        return self.buf


def load_raw(path):
    """A texture written by tools/make_couch_data.py: (width, height, channels, bytes)."""
    with open(path, 'rb') as handle:
        blob = handle.read()
    if blob[:4] != b'CSKY':
        raise ValueError('%s: not a Couchstronomy texture' % path)
    w, h, channels = struct.unpack('<HHH', blob[4:10])
    data = zlib.decompress(blob[10:])
    if len(data) != w * h * channels:
        raise ValueError('%s: truncated texture' % path)
    return w, h, channels, data


def _smooth(e0, e1, x):
    t = (x - e0) / (e1 - e0)
    if t <= 0:
        return 0.0
    if t >= 1:
        return 1.0
    return t * t * (3 - 2 * t)


def _clip(x0, y0, x1, y1, xmin, ymin, xmax, ymax):
    """Liang-Barsky."""
    dx, dy = x1 - x0, y1 - y0
    t0, t1 = 0.0, 1.0
    for p, q in ((-dx, x0 - xmin), (dx, xmax - x0), (-dy, y0 - ymin), (dy, ymax - y0)):
        if p == 0:
            if q < 0:
                return None
            continue
        t = q / p
        if p < 0:
            if t > t1:
                return None
            t0 = max(t0, t)
        else:
            if t < t0:
                return None
            t1 = min(t1, t)
    return x0 + t0 * dx, y0 + t0 * dy, x0 + t1 * dx, y0 + t1 * dy


class MoonTexture(object):
    """The bundled 256 x 256 near-side image with box-filtered smaller levels."""

    def __init__(self, path):
        w, _h, channels, data = load_raw(path)
        img = (w, bytes(data[0::channels]))
        self.levels = [img]
        while img[0] > 8:
            img = _half(img)
            self.levels.append(img)

    def level(self, diameter_px):
        best = self.levels[0]
        for lv in self.levels:
            if lv[0] >= diameter_px:
                best = lv
        return _Level(best)


class _Level(object):
    __slots__ = ('size', 'grey')

    def __init__(self, lv):
        self.size, self.grey = lv[0], lv[1]

    def sample(self, x, y):
        """x, y in [-1, 1] with y up."""
        n = self.size
        i = int((x + 1.0) * 0.5 * n)
        j = int((1.0 - y) * 0.5 * n)
        if i < 0 or j < 0 or i >= n or j >= n:
            return 0
        return self.grey[j * n + i]


def _half(lv):
    n, g = lv
    m = n // 2
    out = bytearray(m * m)
    for j in range(m):
        r0 = (2 * j) * n
        r1 = r0 + n
        for i in range(m):
            k = 2 * i
            out[j * m + i] = (g[r0 + k] + g[r0 + k + 1] + g[r1 + k] + g[r1 + k + 1]) // 4
    return (m, bytes(out))
