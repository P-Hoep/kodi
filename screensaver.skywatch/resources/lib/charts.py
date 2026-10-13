"""Chart primitives over raster.Canvas: an x/y mapping plus lines, bands, bars, shading and
gridlines. Text is collected as label specs [(x, y, text, align, size)] in chart pixel
coordinates for the Kodi layer to place over the image. No Kodi imports."""

import math

from .raster import Canvas

GRID = '30FFFFFF'
AXIS_TEXT = 'B0D8E0EA'


def nice_step(span, target=5):
    """A round tick step giving about target ticks over span."""
    if span <= 0:
        return 1.0
    raw = span / float(target)
    mag = 10 ** math.floor(math.log10(raw))
    for m in (1, 2, 2.5, 5, 10):
        if raw <= m * mag:
            return m * mag
    return 10 * mag


class Chart(object):
    """Plot area inside a canvas. x and y data ranges map to the area (y up)."""

    def __init__(self, width, height, x_range, y_range, pad=(70, 20, 20, 44)):
        self.canvas = Canvas(width, height)
        self.w, self.h = width, height
        self.left, self.top, self.right, self.bottom = pad[0], pad[1], width - pad[2], height - pad[3]
        self.x0, self.x1 = x_range
        self.y0, self.y1 = y_range
        if self.x1 == self.x0:
            self.x1 = self.x0 + 1
        if self.y1 == self.y0:
            self.y1 = self.y0 + 1
        self.labels = []

    def X(self, x):
        return self.left + (x - self.x0) * (self.right - self.left) / float(self.x1 - self.x0)

    def Y(self, y):
        return self.bottom - (y - self.y0) * (self.bottom - self.top) / float(self.y1 - self.y0)

    def label(self, x, y, text, align='center', size='xs', color=AXIS_TEXT):
        self.labels.append((int(round(x)), int(round(y)), text, align, size, color))

    # ------------------------------------------------------------ furniture

    def y_grid(self, step=None, fmt=lambda v: '%d' % round(v), side='left', color=GRID):
        step = step or nice_step(self.y1 - self.y0)
        v = math.ceil(self.y0 / step) * step
        while v <= self.y1 + 1e-9:
            y = self.Y(v)
            self.canvas.fill_rect(self.left, y, self.right, y + 1, color)
            if side == 'left':
                self.label(self.left - 12, y - 14, fmt(v), 'right')
            elif side == 'right':
                self.label(self.right + 12, y - 14, fmt(v), 'left')
            v += step

    def x_ticks(self, ticks, color=GRID, tall=False):
        """ticks: [(x value, text)]"""
        for xv, text in ticks:
            x = self.X(xv)
            if tall:
                self.canvas.fill_rect(x, self.top, x + 1, self.bottom, color)
            else:
                self.canvas.fill_rect(x, self.bottom, x + 1, self.bottom + 8, '60FFFFFF')
            if text:
                self.label(x, self.bottom + 10, text, 'center')

    def shade(self, xa, xb, color):
        self.canvas.fill_rect(self.X(xa), self.top, self.X(xb), self.bottom, color)

    def hline(self, yv, color, width=1.5, dashed=False):
        y = self.Y(yv)
        if dashed:
            self.canvas.dashed(self.left, y, self.right, y, color, width)
        else:
            self.canvas.line(self.left, y, self.right, y, color, width)

    def vline(self, xv, color, width=2.0, dashed=False):
        x = self.X(xv)
        if dashed:
            self.canvas.dashed(x, self.top, x, self.bottom, color, width)
        else:
            self.canvas.line(x, self.top, x, self.bottom, color, width)

    # ------------------------------------------------------------ data

    def line(self, xs, ys, color, width=4.0):
        pts = [(self.X(x), self.Y(y)) if y is not None else None for x, y in zip(xs, ys)]
        run = []
        for p in pts + [None]:
            if p is None:
                self.canvas.polyline(run, color, width)
                run = []
            else:
                run.append(p)

    def band(self, xs, lows, highs, color):
        good = [(x, lo, hi) for x, lo, hi in zip(xs, lows, highs) if lo is not None and hi is not None]
        if len(good) < 2:
            return
        self.canvas.fill_between([self.X(g[0]) for g in good], [self.Y(g[1]) for g in good],
                                 [self.Y(g[2]) for g in good], color)

    def bars(self, xs, ys, color, width_frac=0.7, base=None, colors=None, round_px=0):
        """Vertical bars centred on each x; width from the spacing of xs."""
        if not xs:
            return
        spacing = (self.right - self.left) / float(max(1, len(xs))) if len(xs) < 2 else \
            abs(self.X(xs[1]) - self.X(xs[0]))
        half = spacing * width_frac / 2.0
        base_y = self.Y(self.y0 if base is None else base)
        for i, (x, y) in enumerate(zip(xs, ys)):
            if y is None:
                continue
            c = colors[i] if colors else color
            top = self.Y(y)
            if abs(base_y - top) < 1:
                continue
            if round_px:
                self.canvas.fill_rounded(self.X(x) - half, min(top, base_y), self.X(x) + half, max(top, base_y),
                                         round_px, c)
            else:
                self.canvas.fill_rect(self.X(x) - half, top, self.X(x) + half, base_y, c)

    def range_bar(self, xv, lo, hi, color, width=14):
        x = self.X(xv)
        self.canvas.fill_rounded(x - width / 2.0, self.Y(hi), x + width / 2.0, self.Y(lo), width / 2.0, color)

    def dot(self, xv, yv, color, radius=6):
        self.canvas.disk(self.X(xv), self.Y(yv), radius, color)

    def png(self):
        return self.canvas.png()
