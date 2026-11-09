"""The four phosphor palettes, shared with the native screensaver's theme table."""

THEMES = [
    # primary, dim, faint, bright, alert, military, ground, fill
    ((0.46, 1.00, 0.55), (0.21, 0.56, 0.29), (0.05, 0.17, 0.09), (0.86, 1.00, 0.88),
     (1.00, 0.34, 0.22), (1.00, 0.78, 0.32), (0.40, 0.56, 0.42), (0.010, 0.032, 0.018)),
    ((1.00, 0.72, 0.28), (0.56, 0.36, 0.12), (0.17, 0.10, 0.03), (1.00, 0.94, 0.76),
     (1.00, 0.32, 0.20), (1.00, 0.56, 0.20), (0.62, 0.46, 0.20), (0.030, 0.018, 0.006)),
    ((0.58, 0.84, 1.00), (0.25, 0.42, 0.60), (0.06, 0.12, 0.20), (0.88, 0.97, 1.00),
     (1.00, 0.42, 0.42), (1.00, 0.80, 0.42), (0.42, 0.54, 0.64), (0.010, 0.020, 0.034)),
    ((0.90, 0.96, 0.92), (0.45, 0.53, 0.47), (0.12, 0.16, 0.13), (1.00, 1.00, 1.00),
     (1.00, 0.36, 0.30), (1.00, 0.80, 0.50), (0.54, 0.58, 0.54), (0.022, 0.026, 0.023)),
]

NAMES = ('P1 green', 'P3 amber', 'P11 ice blue', 'White')


def _rgb(value):
    return tuple(int(round(max(0.0, min(1.0, channel)) * 255.0)) for channel in value)


class Palette(object):
    __slots__ = ('primary', 'dim', 'faint', 'bright', 'alert', 'military', 'ground', 'fill')

    def __init__(self, index):
        values = THEMES[index % len(THEMES)]
        (self.primary, self.dim, self.faint, self.bright, self.alert, self.military,
         self.ground, self.fill) = [_rgb(value) for value in values]


def palette(index):
    return Palette(index)


def argb(color, alpha=255):
    return '%02X%02X%02X%02X' % (int(alpha), color[0], color[1], color[2])
