"""Apparent topocentric positions, sizes, phases and magnitudes of the Sun, Moon and
planets. No Kodi imports.

Planets: VSOP87 heliocentric positions with light-time iteration, annual aberration,
precession and nutation, then topocentric parallax. Magnitudes from Meeus chapter 41
(Astronomical Almanac formulae). Each body comes back as a Body whose `hor` is an
unrefracted ENU unit vector; the scene refracts and projects it.
"""

import math

from . import astro, moon, vsop87

PLANETS = (
    # name, VSOP id, equatorial radius km, display colour
    ('Mercury', 'mercury', 2439.7, (214, 204, 190)),
    ('Venus', 'venus', 6051.8, (255, 249, 228)),
    ('Mars', 'mars', 3396.2, (255, 176, 128)),
    ('Jupiter', 'jupiter', 71492.0, (255, 236, 212)),
    ('Saturn', 'saturn', 60268.0, (255, 228, 176)),
    ('Uranus', 'uranus', 25559.0, (196, 232, 238)),
    ('Neptune', 'neptune', 24764.0, (168, 188, 255)),
)
SUN_RADIUS_KM = 696000.0
MOON_RADIUS_KM = 1737.4
SATURN_POLE = astro.vec(40.589 * astro.DEG, 83.537 * astro.DEG)   # J2000, IAU


class Body(object):
    __slots__ = ('name', 'kind', 'hor', 'dist_km', 'mag', 'radius', 'phase_angle', 'illum',
                 'sun_dir', 'color', 'helio_au', 'ring_tilt', 'pole_hor')

    def __init__(self, name, kind, color):
        self.name, self.kind, self.color = name, kind, color
        self.ring_tilt = None
        self.pole_hor = None
        self.sun_dir = None
        self.helio_au = None
        self.phase_angle = 0.0
        self.illum = 1.0

    @property
    def distance_au(self):
        return self.dist_km / astro.AU_KM

    def __repr__(self):
        az, alt = astro.az_alt(self.hor)
        return '<%s az %.3f alt %.3f mag %.1f>' % (self.name, az / astro.DEG, alt / astro.DEG, self.mag)


def _magnitude(name, r, delta, i_deg, ring_b=0.0):
    five = 5.0 * math.log10(r * delta)
    i = i_deg
    if name == 'Mercury':
        return -0.42 + five + 0.0380 * i - 0.000273 * i * i + 0.000002 * i ** 3
    if name == 'Venus':
        return -4.40 + five + 0.0009 * i + 0.000239 * i * i - 0.00000065 * i ** 3
    if name == 'Mars':
        return -1.52 + five + 0.016 * i
    if name == 'Jupiter':
        return -9.40 + five + 0.005 * i
    if name == 'Saturn':
        sb = abs(math.sin(ring_b))
        return -8.88 + five - 2.60 * sb + 1.25 * sb * sb
    if name == 'Uranus':
        return -7.19 + five
    return -6.87 + five


def _to_hor(frame, g_j2000_au):
    """Geocentric astrometric J2000 vector (AU) -> topocentric ENU unit vector, distance km
    and the true-of-date geocentric vector (km)."""
    d_au = astro.length(g_j2000_au)
    u = frame.aberrate(astro.scale(g_j2000_au, 1.0 / d_au))
    g_date = astro.scale(astro.mxv(frame.np, u), d_au * astro.AU_KM)
    hor, dist = frame.date_vector_to_hor(g_date)
    return hor, dist, g_date


def compute(frame, which=None):
    """All bodies (or the names in `which`) for one Frame. Returns {name: Body}."""
    out = {}
    jd = frame.jd_tt
    earth = frame.earth_pos
    # Sun: the geocentric direction is minus the Earth's heliocentric position.
    sun = Body('Sun', 'sun', (255, 250, 240))
    sun.hor, sun.dist_km, sun_date = _to_hor(frame, astro.scale(earth, -1.0))
    sun.radius = math.asin(SUN_RADIUS_KM / sun.dist_km)
    sun.mag = -26.74
    sun_top = astro.scale(sun.hor, sun.dist_km)
    out['Sun'] = sun

    if which is None or 'Moon' in which:
        m = Body('Moon', 'moon', (242, 240, 232))
        g = moon.geocentric_of_date(frame)
        m.hor, m.dist_km = frame.date_vector_to_hor(g)
        m.radius = math.asin(MOON_RADIUS_KM / m.dist_km)
        moon_top = astro.scale(m.hor, m.dist_km)
        to_sun = astro.sub(sun_top, moon_top)
        m.sun_dir = astro.norm(to_sun)
        i = astro.angle(to_sun, astro.scale(moon_top, -1.0))
        m.phase_angle = i
        m.illum = (1.0 + math.cos(i)) / 2.0
        i_deg = i / astro.DEG
        m.mag = -12.73 + 0.026 * abs(i_deg) + 4e-9 * i_deg ** 4
        # Lunar north is within a few degrees of the celestial pole; good enough to orient
        # the texture (libration is not modelled).
        m.pole_hor = astro.mxv(frame.date_to_hor, (0.0, 0.0, 1.0))
        out['Moon'] = m

    for name, vid, radius_km, color in PLANETS:
        if which is not None and name not in which:
            continue
        tau = 0.0
        for _ in range(3):
            p = vsop87.helio(vid, jd - tau)
            g = astro.sub(p, earth)
            tau = astro.length(g) / astro.C_AU_PER_DAY
        b = Body(name, 'planet', color)
        b.helio_au = p
        b.hor, b.dist_km, _g_date = _to_hor(frame, g)
        r = astro.length(p)
        delta = astro.length(g)
        i = math.acos(max(-1.0, min(1.0, astro.dot(p, g) / (r * delta))))
        b.phase_angle = i
        b.illum = (1.0 + math.cos(i)) / 2.0
        b.radius = math.asin(radius_km / b.dist_km)
        top = astro.scale(b.hor, b.dist_km)
        b.sun_dir = astro.norm(astro.sub(sun_top, top))
        ring_b = 0.0
        if name == 'Saturn':
            ring_b = math.asin(max(-1.0, min(1.0, -astro.dot(SATURN_POLE, astro.norm(g)))))
            b.ring_tilt = ring_b
            b.pole_hor = astro.mxv(frame.j2000_to_hor, SATURN_POLE)
        b.mag = _magnitude(name, r, delta, i / astro.DEG, ring_b)
        out[name] = b
    return out


def sun_hor(frame):
    """Just the Sun's apparent ENU direction (cheap; used for the sky colour)."""
    return _to_hor(frame, astro.scale(frame.earth_pos, -1.0))[0]
