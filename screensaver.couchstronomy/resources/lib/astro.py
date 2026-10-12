"""Time scales, reference frames and the small corrections between them. No Kodi imports.

Conventions used throughout the add-on:
  - Directions are 3-vectors (tuples). Equatorial frames: x towards the equinox, z towards
    the celestial pole. The local horizon frame is ENU: x east, y north, z up.
  - "J2000" is the mean equator and equinox of J2000.0 (FK5, which is ICRS to well under
    an arcsecond). "Of date" is the true equator and equinox of date.
  - Times are Unix seconds (UTC). Julian dates are split into UT (Earth rotation, UT1 is
    taken as UTC: under 0.9 s, 0.004 degrees) and TT (ephemerides).

Accuracy target: a few arcseconds, well under one pixel at any field of view the
screensaver offers. Precession is IAU 1976 (Lieske), nutation the leading IAU 1980 terms
(about 0.5"), annual aberration from the Earth's VSOP87 velocity.
"""

import math

DEG = math.pi / 180.0
ARCSEC = DEG / 3600.0
TAU = 2.0 * math.pi
J2000 = 2451545.0
UNIX_EPOCH_JD = 2440587.5
C_AU_PER_DAY = 173.1446326846693
AU_KM = 149597870.7
EARTH_RADIUS_KM = 6378.137
EARTH_FLATTENING = 1.0 / 298.257223563
OBLIQUITY_J2000 = 84381.406 * ARCSEC   # IAU 2006 value; VSOP87 uses 23 26' 21.412"

# TAI - UTC after each leap second (only the recent ones matter here); TT = TAI + 32.184 s.
LEAP_SECONDS = (
    (1483228800, 37), (1435708800, 36), (1341100800, 35), (1230768000, 34),
    (1136073600, 33), (915148800, 32), (867715200, 31), (820454400, 30),
)


def tt_minus_utc(unix):
    for start, leap in LEAP_SECONDS:
        if unix >= start:
            return 32.184 + leap
    return 32.184 + 29


def jd_ut(unix):
    return unix / 86400.0 + UNIX_EPOCH_JD


def jd_tt(unix):
    return (unix + tt_minus_utc(unix)) / 86400.0 + UNIX_EPOCH_JD


def centuries(jd):
    return (jd - J2000) / 36525.0


# ---------------------------------------------------------------- vectors

def vec(lon, lat, r=1.0):
    """Spherical (radians) -> rectangular."""
    cl = math.cos(lat)
    return (r * cl * math.cos(lon), r * cl * math.sin(lon), r * math.sin(lat))


def radec(v):
    """Rectangular -> (lon in [0, 2pi), lat, length)."""
    x, y, z = v
    r = math.sqrt(x * x + y * y + z * z)
    lon = math.atan2(y, x) % TAU
    return lon, math.asin(max(-1.0, min(1.0, z / r))), r


def norm(v):
    x, y, z = v
    r = math.sqrt(x * x + y * y + z * z)
    return (x / r, y / r, z / r)


def dot(a, b):
    return a[0] * b[0] + a[1] * b[1] + a[2] * b[2]


def cross(a, b):
    return (a[1] * b[2] - a[2] * b[1], a[2] * b[0] - a[0] * b[2], a[0] * b[1] - a[1] * b[0])


def sub(a, b):
    return (a[0] - b[0], a[1] - b[1], a[2] - b[2])


def add(a, b):
    return (a[0] + b[0], a[1] + b[1], a[2] + b[2])


def scale(a, k):
    return (a[0] * k, a[1] * k, a[2] * k)


def length(v):
    return math.sqrt(v[0] * v[0] + v[1] * v[1] + v[2] * v[2])


def angle(a, b):
    """Angle between two vectors (radians), stable for small angles."""
    return math.atan2(length(cross(a, b)), dot(a, b))


def mxv(m, v):
    return (m[0][0] * v[0] + m[0][1] * v[1] + m[0][2] * v[2],
            m[1][0] * v[0] + m[1][1] * v[1] + m[1][2] * v[2],
            m[2][0] * v[0] + m[2][1] * v[1] + m[2][2] * v[2])


def mxm(a, b):
    return tuple(tuple(sum(a[i][k] * b[k][j] for k in range(3)) for j in range(3)) for i in range(3))


def transpose(m):
    return tuple(tuple(m[j][i] for j in range(3)) for i in range(3))


def rot_x(a):
    """Rotation of the frame about x by a (a vector's coordinates in the rotated frame)."""
    c, s = math.cos(a), math.sin(a)
    return ((1.0, 0.0, 0.0), (0.0, c, s), (0.0, -s, c))


def rot_y(a):
    c, s = math.cos(a), math.sin(a)
    return ((c, 0.0, -s), (0.0, 1.0, 0.0), (s, 0.0, c))


def rot_z(a):
    c, s = math.cos(a), math.sin(a)
    return ((c, s, 0.0), (-s, c, 0.0), (0.0, 0.0, 1.0))


# ---------------------------------------------------------------- precession and nutation

def precession_matrix(jd_tt_value):
    """Mean J2000 -> mean of date (IAU 1976; Meeus 21.2)."""
    t = centuries(jd_tt_value)
    zeta = (2306.2181 * t + 0.30188 * t * t + 0.017998 * t ** 3) * ARCSEC
    z = (2306.2181 * t + 1.09468 * t * t + 0.018203 * t ** 3) * ARCSEC
    theta = (2004.3109 * t - 0.42665 * t * t - 0.041833 * t ** 3) * ARCSEC
    return mxm(rot_z(-z), mxm(rot_y(theta), rot_z(-zeta)))


def mean_obliquity(jd_tt_value):
    t = centuries(jd_tt_value)
    return (84381.448 - 46.8150 * t - 0.00059 * t * t + 0.001813 * t ** 3) * ARCSEC


# Leading IAU 1980 nutation terms: multipliers of (D, M, M', F, Omega), then
# (psi, psi*T, eps, eps*T) in 0.0001".
NUTATION_TERMS = (
    (0, 0, 0, 0, 1, -171996, -174.2, 92025, 8.9),
    (-2, 0, 0, 2, 2, -13187, -1.6, 5736, -3.1),
    (0, 0, 0, 2, 2, -2274, -0.2, 977, -0.5),
    (0, 0, 0, 0, 2, 2062, 0.2, -895, 0.5),
    (0, 1, 0, 0, 0, 1426, -3.4, 54, -0.1),
    (0, 0, 1, 0, 0, 712, 0.1, -7, 0.0),
    (-2, 1, 0, 2, 2, -517, 1.2, 224, -0.6),
    (0, 0, 0, 2, 1, -386, -0.4, 200, 0.0),
    (0, 0, 1, 2, 2, -301, 0.0, 129, -0.1),
    (-2, -1, 0, 2, 2, 217, -0.5, -95, 0.3),
    (-2, 0, 1, 0, 0, -158, 0.0, 0, 0.0),
    (-2, 0, 0, 2, 1, 129, 0.1, -70, 0.0),
    (0, 0, -1, 2, 2, 123, 0.0, -53, 0.0),
    (2, 0, 0, 0, 0, 63, 0.0, 0, 0.0),
    (0, 0, 1, 0, 1, 63, 0.1, -33, 0.0),
    (2, 0, -1, 2, 2, -59, 0.0, 26, 0.0),
    (0, 0, -1, 0, 1, -58, -0.1, 32, 0.0),
    (0, 0, 1, 2, 1, -51, 0.0, 27, 0.0),
    (-2, 0, 2, 0, 0, 48, 0.0, 0, 0.0),
    (0, 0, -2, 2, 1, 46, 0.0, -24, 0.0),
    (2, 0, 0, 2, 2, -38, 0.0, 16, 0.0),
    (0, 0, 2, 2, 2, -31, 0.0, 13, 0.0),
    (0, 0, 2, 0, 0, 29, 0.0, 0, 0.0),
    (-2, 0, 1, 2, 2, 29, 0.0, -12, 0.0),
    (0, 0, 0, 2, 0, 26, 0.0, 0, 0.0),
    (-2, 0, 0, 2, 0, -22, 0.0, 0, 0.0),
    (0, 0, -1, 2, 1, 21, 0.0, -10, 0.0),
    (0, 2, 0, 0, 0, 17, -0.1, 0, 0.0),
    (2, 0, -1, 0, 1, 16, 0.0, -8, 0.0),
    (-2, 2, 0, 2, 2, -16, 0.1, 7, 0.0),
)


def nutation(jd_tt_value):
    """(dpsi, deps) in radians."""
    t = centuries(jd_tt_value)
    d = (297.85036 + 445267.111480 * t - 0.0019142 * t * t + t ** 3 / 189474.0) * DEG
    m = (357.52772 + 35999.050340 * t - 0.0001603 * t * t - t ** 3 / 300000.0) * DEG
    mp = (134.96298 + 477198.867398 * t + 0.0086972 * t * t + t ** 3 / 56250.0) * DEG
    f = (93.27191 + 483202.017538 * t - 0.0036825 * t * t + t ** 3 / 327270.0) * DEG
    om = (125.04452 - 1934.136261 * t + 0.0020708 * t * t + t ** 3 / 450000.0) * DEG
    dpsi = deps = 0.0
    for a, b, c, e, g, s0, s1, c0, c1 in NUTATION_TERMS:
        arg = a * d + b * m + c * mp + e * f + g * om
        dpsi += (s0 + s1 * t) * math.sin(arg)
        deps += (c0 + c1 * t) * math.cos(arg)
    return dpsi * 1e-4 * ARCSEC, deps * 1e-4 * ARCSEC


def nutation_matrix(eps0, dpsi, deps):
    """Mean of date -> true of date."""
    return mxm(rot_x(-(eps0 + deps)), mxm(rot_z(-dpsi), rot_x(eps0)))


# ---------------------------------------------------------------- sidereal time

def gmst(jd_ut_value):
    """Greenwich mean sidereal time, radians (Meeus 12.4)."""
    t = centuries(jd_ut_value)
    deg = (280.46061837 + 360.98564736629 * (jd_ut_value - J2000)
           + 0.000387933 * t * t - t ** 3 / 38710000.0)
    return (deg % 360.0) * DEG


# ---------------------------------------------------------------- ecliptic

def ecliptic_to_equatorial(v, eps):
    """Rotate an ecliptic vector into the equator with obliquity eps."""
    return mxv(rot_x(-eps), v)


ECL_TO_EQ_J2000 = rot_x(-OBLIQUITY_J2000)
EQ_TO_ECL_J2000 = rot_x(OBLIQUITY_J2000)


# ---------------------------------------------------------------- observer

def geodetic_to_ecef(lat, lon, height_m=0.0):
    """WGS84 geodetic -> Earth-fixed rectangular, km."""
    e2 = EARTH_FLATTENING * (2.0 - EARTH_FLATTENING)
    s = math.sin(lat)
    n = EARTH_RADIUS_KM / math.sqrt(1.0 - e2 * s * s)
    h = height_m / 1000.0
    return ((n + h) * math.cos(lat) * math.cos(lon),
            (n + h) * math.cos(lat) * math.sin(lon),
            (n * (1.0 - e2) + h) * s)


def equatorial_to_horizon_matrix(lst, lat):
    """True equator of date -> local ENU for local sidereal time lst and geodetic latitude
    lat. (The astronomical vertical is taken as the geodetic one.)"""
    c, s = math.cos(lst), math.sin(lst)
    cp, sp = math.cos(lat), math.sin(lat)
    # First rotate about the pole by lst: x' = cos(dec)cos(H), y' = -cos(dec)sin(H).
    return ((-s, c, 0.0),
            (-sp * c, -sp * s, cp),
            (cp * c, cp * s, sp))


def enu(az, alt):
    """Azimuth (clockwise from north) and altitude -> ENU unit vector."""
    ca = math.cos(alt)
    return (ca * math.sin(az), ca * math.cos(az), math.sin(alt))


def az_alt(v):
    x, y, z = v
    r = math.sqrt(x * x + y * y + z * z)
    return math.atan2(x, y) % TAU, math.asin(max(-1.0, min(1.0, z / r)))


# ---------------------------------------------------------------- atmosphere

def refraction(alt, pressure_mbar=1010.0, temp_c=10.0):
    """Refraction (radians) to add to a geometric (true) altitude: Saemundsson's formula,
    good to about 4" above 15 degrees and a fraction of an arcminute near the horizon."""
    h = alt / DEG
    if h < -1.9:
        return 0.0
    r = 1.02 / math.tan((h + 10.3 / (h + 5.11)) * DEG)   # arcminutes
    r *= (pressure_mbar / 1010.0) * (283.0 / (273.0 + temp_c))
    return max(0.0, r) / 60.0 * DEG


def refract_enu(v, pressure_mbar=1010.0, temp_c=10.0):
    """Apparent direction of a true ENU unit vector."""
    x, y, z = v
    h = math.asin(max(-1.0, min(1.0, z)))
    dh = refraction(h, pressure_mbar, temp_c)
    if dh == 0.0:
        return v
    hz = math.sqrt(x * x + y * y)
    if hz < 1e-12:
        return v
    h2 = h + dh
    k = math.cos(h2) / hz
    return (x * k, y * k, math.sin(h2))


def airmass(alt):
    """Pickering (2002), valid down to the horizon; alt in radians (apparent)."""
    h = max(alt / DEG, -0.5)
    return 1.0 / math.sin((h + 244.0 / (165.0 + 47.0 * max(h, 0.0) ** 1.1)) * DEG)


def extinction_mag(alt, k=0.2):
    """Extra magnitudes of atmospheric extinction relative to the zenith."""
    return k * (airmass(alt) - 1.0)


# ---------------------------------------------------------------- the per-instant frame

class Frame(object):
    """Everything about one instant and one observer that the rest of the add-on needs:
    the matrices from J2000 and from true-of-date coordinates to the local horizon, the
    Earth's velocity for aberration, and the observer's position."""

    def __init__(self, unix, lat, lon, height_m=0.0, earth_state=None):
        self.unix = unix
        self.lat, self.lon, self.height_m = lat, lon, height_m
        self.jd_ut = jd_ut(unix)
        self.jd_tt = jd_tt(unix)
        self.eps0 = mean_obliquity(self.jd_tt)
        self.dpsi, self.deps = nutation(self.jd_tt)
        self.eps = self.eps0 + self.deps
        self.gmst = gmst(self.jd_ut)
        self.gast = (self.gmst + self.dpsi * math.cos(self.eps)) % TAU
        self.lst = (self.gast + lon) % TAU
        p = precession_matrix(self.jd_tt)
        n = nutation_matrix(self.eps0, self.dpsi, self.deps)
        self.np = mxm(n, p)                                   # J2000 -> true of date
        self.date_to_hor = equatorial_to_horizon_matrix(self.lst, lat)
        self.j2000_to_hor = mxm(self.date_to_hor, self.np)
        # Earth's heliocentric position and velocity (J2000 equatorial, AU and AU/day).
        if earth_state is None:
            from . import vsop87
            earth_state = vsop87.earth_state(self.jd_tt)
        self.earth_pos, self.earth_vel = earth_state
        self.beta = scale(self.earth_vel, 1.0 / C_AU_PER_DAY)  # v/c, J2000 frame
        # Observer, geocentric, true equator of date (km).
        ecef = geodetic_to_ecef(lat, lon, height_m)
        self.observer_km = mxv(transpose(rot_z(self.gast)), ecef)

    def aberrate(self, u):
        """Annual aberration of a J2000 unit vector (first order; error < 0.001")."""
        b = self.beta
        x, y, z = u[0] + b[0], u[1] + b[1], u[2] + b[2]
        r = math.sqrt(x * x + y * y + z * z)
        return (x / r, y / r, z / r)

    def star_to_hor(self, u):
        """Apparent topocentric ENU direction (unrefracted) of a J2000 star direction."""
        return mxv(self.j2000_to_hor, self.aberrate(u))

    def date_vector_to_hor(self, v_km):
        """A geocentric true-of-date vector (km) -> topocentric ENU unit vector and distance."""
        t = sub(v_km, self.observer_km)
        d = length(t)
        return norm(mxv(self.date_to_hor, t)), d
