"""Lookup tables from output pixels to source pixels, and where a map sits on screen.
No Kodi imports.

A lookup table (LUT) is an array('I') with one entry per output pixel: the index of the
equirectangular source pixel it shows, or sw * sh (the transparent sentinel) outside the
map. Building one is slow in Python (seconds), so tables are cached on disk; using one is
a single C-level map() per frame. Spinning the globe or moving a central meridian never
needs a new table: the sources are rolled east-west instead (raster.roll_words).
"""

import hashlib
import math
import os
import zlib
from array import array

from . import projections

VERSION = 4  # bump when the rasteriser or a projection changes, to drop old cached tables
MARGIN = 0.94  # flat maps fill at most this share of the screen at zoom 1
GLOBE_FILL = 0.86


class Layout(object):
    """How a projection's plane maps to display pixels.

    The displayed map is disp_w x disp_h screen pixels; plane point (x, y) is shown at
    ((x - xmin) * k, (ymax - y) * k) inside it."""

    def __init__(self, proj, screen_w, screen_h, zoom=1.0, tilt=0.0):
        self.proj = proj
        self.tilt = tilt
        xmin, ymin, xmax, ymax = proj.bounds()
        bw, bh = xmax - xmin, ymax - ymin
        if proj.kind == 'cylindrical':
            k = screen_h * zoom / bh
        elif proj.kind == 'globe':
            k = screen_h * GLOBE_FILL * zoom / bh
        else:
            k = min(screen_w * MARGIN / bw, screen_h * MARGIN / bh) * zoom
        self.k = k
        self.xmin, self.ymax = xmin, ymax
        self.disp_w = int(round(bw * k))
        self.disp_h = int(round(bh * k))

    def plane_to_display(self, x, y):
        return (x - self.xmin) * self.k, (self.ymax - y) * self.k


# ---------------------------------------------------------------- building tables

def _fill_triangle(lut, out_w, out_h, a, b, c, sw, sh):
    """Rasterise one triangle; a, b, c = (x, y, u, v) in output and source pixels."""
    ax, ay, ua, va = a
    bx, by, ub, vb = b
    cx, cy, uc, vc = c
    det = (bx - ax) * (cy - ay) - (by - ay) * (cx - ax)
    if abs(det) < 1e-12:
        return
    au = ((ub - ua) * (cy - ay) - (by - ay) * (uc - ua)) / det
    bu = ((bx - ax) * (uc - ua) - (ub - ua) * (cx - ax)) / det
    av = ((vb - va) * (cy - ay) - (by - ay) * (vc - va)) / det
    bv = ((bx - ax) * (vc - va) - (vb - va) * (cx - ax)) / det
    ylo = max(0, int(math.ceil(min(ay, by, cy) - 0.5)))
    yhi = min(out_h - 1, int(math.ceil(max(ay, by, cy) - 0.5)) - 1)
    if yhi < ylo:
        return
    # Edges in a canonical direction (top to bottom, then left to right) so that the two
    # triangles sharing an edge compute exactly the same crossing: no gaps, no overlaps.
    edges = []
    for p, q in ((a, b), (b, c), (c, a)):
        if (p[1], p[0]) > (q[1], q[0]):
            p, q = q, p
        if q[1] != p[1]:
            edges.append((p[1], q[1], p[0], (q[0] - p[0]) / (q[1] - p[1])))
    vmax = sh - 1
    for py in range(ylo, yhi + 1):
        yc = py + 0.5
        xs = [x0 + (yc - y0) * slope for y0, y1, x0, slope in edges if y0 <= yc < y1]
        if len(xs) < 2:
            continue
        xl, xr = min(xs), max(xs)
        x0 = max(0, int(math.ceil(xl - 0.5)))
        x1 = min(out_w - 1, int(math.ceil(xr - 0.5)) - 1)
        n = x1 - x0 + 1
        if n <= 0:
            continue
        u0 = ua + au * (x0 + 0.5 - ax) + bu * (yc - ay) + sw   # + sw keeps int() a floor
        v0 = va + av * (x0 + 0.5 - ax) + bv * (yc - ay)
        v_end = v0 + av * (n - 1)
        if 0 <= v0 < sh and 0 <= v_end < sh:
            vals = [int(v0 + i * av) * sw + int(u0 + i * au) % sw for i in range(n)]
        else:
            vals = [min(vmax, max(0, int(v0 + i * av))) * sw + int(u0 + i * au) % sw for i in range(n)]
        start = py * out_w + x0
        lut[start:start + n] = array('I', vals)


def mesh_lut(proj, out_w, out_h, kx, ky, sw, sh, stop=None):
    """Table for a meshed projection; image pixel = ((x - xmin) * kx, (ymax - y) * ky)."""
    xmin, _ymin, _xmax, ymax = proj.bounds()
    verts, tris = proj.mesh()
    pts = [((x - xmin) * kx, (ymax - y) * ky, (lon + 180.0) / 360.0 * sw, (90.0 - lat) / 180.0 * sh, lat)
           for x, y, lon, lat in verts]
    lut = array('I', [sw * sh]) * (out_w * out_h)
    for n, (i, j, k) in enumerate(tris):
        if stop is not None and n % 1500 == 0 and stop():
            return None
        a, b, c = pts[i], pts[j], pts[k]
        u = [a[2], b[2], c[2]]
        # Keep the three longitudes within half a world of each other (antimeridian).
        for m in (1, 2):
            u[m] += sw * round((u[0] - u[m]) / float(sw))
        # A pole has no longitude of its own: borrow the others' so the texture doesn't smear.
        poles = [m for m, p in enumerate((a, b, c)) if abs(p[4]) > 89.999]
        if poles and len(poles) < 3:
            others = [u[m] for m in range(3) if m not in poles]
            for m in poles:
                u[m] = sum(others) / len(others)
        _fill_triangle(lut, out_w, out_h, (a[0], a[1], u[0], a[3]), (b[0], b[1], u[1], b[3]),
                       (c[0], c[1], u[2], c[3]), sw, sh)
    return lut


def globe_lut(out_w, out_h, tilt, sw, sh, stop=None):
    """Orthographic table for a globe filling out_w x out_h (an ellipse if they differ),
    centred on longitude 0 and latitude `tilt`. Exact per-pixel inverse."""
    lut = array('I', [sw * sh]) * (out_w * out_h)
    rx, ry = out_w / 2.0, out_h / 2.0
    p0 = tilt * projections.D2R
    sp0, cp0 = math.sin(p0), math.cos(p0)
    to_u = sw / (2 * math.pi)
    to_v = sh / math.pi
    asin, atan2, sqrt = math.asin, math.atan2, math.sqrt
    for py in range(out_h):
        if stop is not None and py % 64 == 0 and stop():
            return None
        y = -((py + 0.5) - ry) / ry
        if abs(y) >= 1:
            continue
        half = sqrt(1 - y * y)
        x_lo = max(0, int(math.ceil(rx - half * rx - 0.5)))
        x_hi = min(out_w - 1, int(math.ceil(rx + half * rx - 0.5)) - 1)
        row = []
        for px in range(x_lo, x_hi + 1):
            x = ((px + 0.5) - rx) / rx
            rho2 = x * x + y * y
            if rho2 >= 1:
                row.append(sw * sh)
                continue
            rho = sqrt(rho2)
            if rho < 1e-12:
                lat, lon = p0, 0.0
            else:
                sc = rho
                cc = sqrt(1 - rho2)
                lat = asin(max(-1.0, min(1.0, cc * sp0 + y * sc * cp0 / rho)))
                lon = atan2(x * sc, rho * cc * cp0 - y * sc * sp0)
            u = int((lon + math.pi) * to_u) % sw
            v = min(sh - 1, int((math.pi / 2 - lat) * to_v))
            row.append(v * sw + u)
        if row:
            start = py * out_w + x_lo
            lut[start:start + len(row)] = array('I', row)
    return lut


class LutCache(object):
    """Tables on disk under `folder`, at most `keep` of them (least recently used go)."""

    def __init__(self, folder, keep=40):
        self.folder = folder
        self.keep = keep
        if not os.path.isdir(folder):
            os.makedirs(folder)

    def path(self, key):
        return os.path.join(self.folder, hashlib.md5(repr((VERSION,) + key).encode()).hexdigest()[:20] + '.lut')

    def get(self, key, n):
        path = self.path(key)
        try:
            with open(path, 'rb') as handle:
                data = zlib.decompress(handle.read())
            lut = array('I')
            lut.frombytes(data)
            if len(lut) != n:
                return None
            os.utime(path, None)
            return lut
        except (OSError, IOError, zlib.error, ValueError):
            return None

    def put(self, key, lut):
        path = self.path(key)
        tmp = path + '.tmp'
        with open(tmp, 'wb') as handle:
            handle.write(zlib.compress(lut.tobytes(), 1))
        os.replace(tmp, path)
        self.prune()

    def prune(self):
        try:
            files = [os.path.join(self.folder, f) for f in os.listdir(self.folder) if f.endswith('.lut')]
            files.sort(key=os.path.getmtime, reverse=True)
            for path in files[self.keep:]:
                os.remove(path)
        except OSError:
            pass


def build(proj, out_w, out_h, kx, ky, sw, sh, tilt=0.0, cache=None, stop=None):
    """Cached table for proj at this output size and scale. None if stopped."""
    key = (proj.id, out_w, out_h, round(kx, 5), round(ky, 5), sw, sh, round(tilt, 3))
    if cache is not None:
        lut = cache.get(key, out_w * out_h)
        if lut is not None:
            return lut
    if proj.kind == 'globe':
        lut = globe_lut(out_w, out_h, tilt, sw, sh, stop)
    else:
        lut = mesh_lut(proj, out_w, out_h, kx, ky, sw, sh, stop)
        if lut is not None and proj.kind == 'cylindrical':
            _close_edges(lut, out_w, out_h, sw * sh)
    if lut is not None and cache is not None:
        cache.put(key, lut)
    return lut


def _close_edges(lut, out_w, out_h, sentinel):
    """A wrapping map's copies sit edge to edge, so its first and last columns must be
    filled; the rasteriser's fill rule can leave them empty."""
    for y in range(out_h):
        row = y * out_w
        for x, nx in ((0, 1), (out_w - 1, out_w - 2)):
            if lut[row + x] == sentinel:
                lut[row + x] = lut[row + nx]


def apply(lut, words):
    """Source words (array('I'), sentinel last) through a table -> output words."""
    return array('I', map(words.__getitem__, lut))


def apply_bytes(lut, data):
    """Same for a one-byte-per-pixel source (bytes/bytearray with the sentinel byte last)."""
    return bytes(map(data.__getitem__, lut))
