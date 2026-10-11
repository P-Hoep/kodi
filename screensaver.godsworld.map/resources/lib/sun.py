"""Where the Sun is overhead, and how high it stands anywhere. No Kodi imports.

Low-precision solar coordinates (the Astronomical Almanac's approximation, good to about
0.01 degrees from 1950 to 2050), far finer than a pixel on a world map."""

import math

J2000 = 946728000.0  # 2000-01-01 12:00 UTC as a Unix time


def subsolar(t):
    """Unix time -> (lat, lon) in degrees of the point with the Sun at the zenith."""
    d = (t - J2000) / 86400.0
    g = math.radians((357.529 + 0.98560028 * d) % 360.0)
    q = (280.459 + 0.98564736 * d) % 360.0
    ecl_lon = math.radians(q + 1.915 * math.sin(g) + 0.020 * math.sin(2 * g))
    obliquity = math.radians(23.439 - 0.00000036 * d)
    dec = math.asin(math.sin(obliquity) * math.sin(ecl_lon))
    ra = math.degrees(math.atan2(math.cos(obliquity) * math.sin(ecl_lon), math.cos(ecl_lon)))
    gmst = (280.46061837 + 360.98564736629 * d) % 360.0
    lon = (ra - gmst + 540.0) % 360.0 - 180.0
    return math.degrees(dec), lon


class Sun(object):
    """Solar altitude for one moment, cheap to evaluate at many points."""

    def __init__(self, t):
        self.lat, self.lon = subsolar(t)
        self.sin_dec = math.sin(math.radians(self.lat))
        self.cos_dec = math.cos(math.radians(self.lat))

    def sin_altitude(self, lat, lon):
        p = math.radians(lat)
        return (math.sin(p) * self.sin_dec
                + math.cos(p) * self.cos_dec * math.cos(math.radians(lon - self.lon)))

    def row(self, lat):
        """For a parallel: (A, B) with sin(altitude) = A + B * cos(lon - sun lon)."""
        p = math.radians(lat)
        return math.sin(p) * self.sin_dec, math.cos(p) * self.cos_dec


# Twilight blend: full night below NIGHT_ALT, full day above DAY_ALT (degrees of altitude).
NIGHT_ALT = -9.0
DAY_ALT = 3.0
SIN_NIGHT = math.sin(math.radians(NIGHT_ALT))
SIN_DAY = math.sin(math.radians(DAY_ALT))


def daylight(sin_alt):
    """0 (night) .. 1 (day) for a sine of solar altitude, with a smooth twilight."""
    f = (sin_alt - SIN_NIGHT) / (SIN_DAY - SIN_NIGHT)
    if f <= 0:
        return 0.0
    if f >= 1:
        return 1.0
    return f * f * (3 - 2 * f)
