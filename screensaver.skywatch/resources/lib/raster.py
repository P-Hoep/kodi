"""A small pure-Python RGBA canvas for charts, written out as PNG. No Kodi imports.

Kodi on Android and Fire TV has no imaging library, so this stands in for Pillow's ImageDraw:
fills use bytearray slice assignment (fast), and only antialiased lines and dots touch single
pixels. Fills *replace* pixels rather than blend, so draw back to front; lines and dots blend.
Text is not drawn here: chart labels are Kodi labels placed over the image.
"""

import math
import struct
import zlib

SIGNATURE = b'\x89PNG\r\n\x1a\n'


def rgba(color):
    """'AARRGGBB' hex (Kodi's colour order) or an (r, g, b, a) tuple -> (r, g, b, a)."""
    if isinstance(color, tuple):
        return color if len(color) == 4 else color + (255,)
    v = int(color, 16)
    if len(color) <= 6:
        return (v >> 16) & 255, (v >> 8) & 255, v & 255, 255
    return (v >> 16) & 255, (v >> 8) & 255, v & 255, (v >> 24) & 255


class Canvas(object):
    def __init__(self, width, height, background=(0, 0, 0, 0)):
        self.w = int(width)
        self.h = int(height)
        self.stride = self.w * 4
        self.buf = bytearray(bytes(rgba(background)) * (self.w * self.h))

    # ------------------------------------------------------------ fills (replace)

    def fill_rect(self, x0, y0, x1, y1, color):
        x0, x1 = sorted((int(round(x0)), int(round(x1))))
        y0, y1 = sorted((int(round(y0)), int(round(y1))))
        x0, y0 = max(0, x0), max(0, y0)
        x1, y1 = min(self.w, x1), min(self.h, y1)
        if x1 <= x0 or y1 <= y0:
            return
        row = bytes(rgba(color)) * (x1 - x0)
        for y in range(y0, y1):
            start = y * self.stride + x0 * 4
            self.buf[start:start + len(row)] = row

    def fill_rounded(self, x0, y0, x1, y1, radius, color):
        r = max(0, min(radius, (x1 - x0) / 2.0, (y1 - y0) / 2.0))
        c = rgba(color)
        for y in range(int(math.floor(y0)), int(math.ceil(y1))):
            yc = y + 0.5
            inset = 0.0
            if yc < y0 + r:
                dy = y0 + r - yc
                inset = r - math.sqrt(max(0.0, r * r - dy * dy))
            elif yc > y1 - r:
                dy = yc - (y1 - r)
                inset = r - math.sqrt(max(0.0, r * r - dy * dy))
            self.fill_rect(x0 + inset, y, x1 - inset, y + 1, c)

    def fill_polygon(self, points, color):
        """Even-odd scanline fill of a closed polygon [(x, y), ...]."""
        if len(points) < 3:
            return
        row_color = bytes(rgba(color))
        ys = [p[1] for p in points]
        top, bottom = max(0, int(math.floor(min(ys)))), min(self.h - 1, int(math.ceil(max(ys))))
        n = len(points)
        for y in range(top, bottom + 1):
            yc = y + 0.5
            xs = []
            for i in range(n):
                xa, ya = points[i]
                xb, yb = points[(i + 1) % n]
                if (ya <= yc < yb) or (yb <= yc < ya):
                    xs.append(xa + (yc - ya) * (xb - xa) / (yb - ya))
            xs.sort()
            for i in range(0, len(xs) - 1, 2):
                xa, xb = max(0, int(round(xs[i]))), min(self.w, int(round(xs[i + 1])))
                if xb > xa:
                    start = y * self.stride + xa * 4
                    self.buf[start:start + (xb - xa) * 4] = row_color * (xb - xa)

    def fill_between(self, xs, lows, highs, color):
        """Fill the band between two series sampled at the same x positions."""
        pts = list(zip(xs, highs)) + list(zip(reversed(xs), reversed(lows)))
        self.fill_polygon(pts, color)

    # ------------------------------------------------------------ strokes (blend)

    def blend(self, x, y, color, coverage):
        if not (0 <= x < self.w and 0 <= y < self.h) or coverage <= 0:
            return
        r, g, b, a = color
        a = a * min(1.0, coverage) / 255.0
        i = y * self.stride + x * 4
        buf = self.buf
        da = buf[i + 3] / 255.0
        oa = a + da * (1 - a)
        if oa <= 0:
            return
        buf[i] = int((r * a + buf[i] * da * (1 - a)) / oa)
        buf[i + 1] = int((g * a + buf[i + 1] * da * (1 - a)) / oa)
        buf[i + 2] = int((b * a + buf[i + 2] * da * (1 - a)) / oa)
        buf[i + 3] = int(oa * 255)

    def line(self, x0, y0, x1, y1, color, width=2.0):
        """Antialiased line with round caps: coverage from each pixel's distance to the segment."""
        c = rgba(color)
        half = width / 2.0
        dx, dy = x1 - x0, y1 - y0
        length2 = dx * dx + dy * dy
        reach = half + 1.5
        steep = abs(dy) > abs(dx)
        # Walk the major axis; on each step only a narrow band across the line is tested.
        if steep:
            a0, a1 = sorted((y0, y1))
        else:
            a0, a1 = sorted((x0, x1))
        lo = int(math.floor(a0 - reach))
        hi = int(math.ceil(a1 + reach))
        limit = self.h if steep else self.w
        for major in range(max(0, lo), min(limit - 1, hi) + 1):
            m = major + 0.5
            if steep:
                centre = x0 + (dx * (m - y0) / dy if dy else 0.0)
            else:
                centre = y0 + (dy * (m - x0) / dx if dx else 0.0)
            # Clamp the band centre to the segment so caps are covered.
            if steep:
                centre = min(max(centre, min(x0, x1)), max(x0, x1))
            else:
                centre = min(max(centre, min(y0, y1)), max(y0, y1))
            span = reach * (math.sqrt(length2) / max(abs(dx if steep else dy), 1e-9) if length2 and
                            (dx if steep else dy) else 1.0)
            span = min(span, reach * 4)
            for minor in range(int(math.floor(centre - span)), int(math.ceil(centre + span)) + 1):
                px, py = (minor + 0.5, m) if steep else (m, minor + 0.5)
                if length2 == 0:
                    t = 0.0
                else:
                    t = max(0.0, min(1.0, ((px - x0) * dx + (py - y0) * dy) / length2))
                ex, ey = px - (x0 + t * dx), py - (y0 + t * dy)
                cov = half + 0.5 - math.sqrt(ex * ex + ey * ey)
                if cov > 0:
                    if steep:
                        self.blend(minor, major, c, cov)
                    else:
                        self.blend(major, minor, c, cov)

    def polyline(self, points, color, width=2.0):
        pts = [p for p in points if p is not None and p[1] is not None]
        for a, b in zip(pts, pts[1:]):
            self.line(a[0], a[1], b[0], b[1], color, width)

    def dashed(self, x0, y0, x1, y1, color, width=1.5, dash=10, gap=8):
        length = math.hypot(x1 - x0, y1 - y0)
        if length == 0:
            return
        ux, uy = (x1 - x0) / length, (y1 - y0) / length
        pos = 0.0
        while pos < length:
            end = min(length, pos + dash)
            self.line(x0 + ux * pos, y0 + uy * pos, x0 + ux * end, y0 + uy * end, color, width)
            pos = end + gap

    def disk(self, cx, cy, radius, color):
        c = rgba(color)
        for y in range(int(cy - radius - 1), int(cy + radius + 2)):
            for x in range(int(cx - radius - 1), int(cx + radius + 2)):
                d = math.hypot(x + 0.5 - cx, y + 0.5 - cy)
                cov = radius + 0.5 - d
                if cov > 0:
                    self.blend(x, y, c, cov)

    def ring(self, cx, cy, radius, color, width=2.0):
        c = rgba(color)
        half = width / 2.0
        for y in range(int(cy - radius - half - 1), int(cy + radius + half + 2)):
            for x in range(int(cx - radius - half - 1), int(cx + radius + half + 2)):
                d = abs(math.hypot(x + 0.5 - cx, y + 0.5 - cy) - radius)
                cov = half + 0.5 - d
                if cov > 0:
                    self.blend(x, y, c, cov)

    def arc(self, cx, cy, radius, start_deg, end_deg, color, width=2.0, steps=None):
        """Arc from start to end degrees (0 = right, counter-clockwise, y up on screen)."""
        steps = steps or max(8, int(abs(end_deg - start_deg) / 3))
        pts = []
        for i in range(steps + 1):
            a = math.radians(start_deg + (end_deg - start_deg) * i / float(steps))
            pts.append((cx + radius * math.cos(a), cy - radius * math.sin(a)))
        self.polyline(pts, color, width)

    # ------------------------------------------------------------ output

    def png(self, level=6):
        stride = self.stride
        raw = b''.join(b'\x00' + bytes(self.buf[y * stride:(y + 1) * stride]) for y in range(self.h))

        def chunk(kind, body):
            return struct.pack('>I4s', len(body), kind) + body + struct.pack('>I', zlib.crc32(kind + body) & 0xFFFFFFFF)
        return (SIGNATURE + chunk(b'IHDR', struct.pack('>IIBBBBB', self.w, self.h, 8, 6, 0, 0, 0))
                + chunk(b'IDAT', zlib.compress(raw, level)) + chunk(b'IEND', b''))

    def pixel(self, x, y):
        i = y * self.stride + x * 4
        return tuple(self.buf[i:i + 4])


def png_size(data):
    """(width, height) from PNG bytes."""
    if not data.startswith(SIGNATURE):
        raise ValueError('not a PNG')
    return struct.unpack('>II', data[16:24])
