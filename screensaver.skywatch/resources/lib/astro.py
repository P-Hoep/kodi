"""Sun, moon and solunar times, computed locally. No network, no Kodi imports.

Sun: the NOAA solar-position equations (about 1 minute for rise/set). Moon: Paul Schlyter's
low-precision lunar theory with the main perturbation terms (a few arcminutes), with
topocentric parallax handled through the standard rise/set altitude of +0.125 degrees.
Times are epoch seconds (UTC); callers format them with the location's UTC offset.

Solunar periods follow John Alden Knight's tables: majors are about two hours centred on
the moon's upper transit (overhead) and lower transit (underfoot); minors are about one
hour centred on moonrise and moonset.
"""

import math

DEG = math.pi / 180.0
SYNODIC = 29.530588853
SUN_ALTITUDE = -0.833      # rise/set: refraction + the sun's radius
MOON_ALTITUDE = 0.125      # rise/set: refraction + radius - horizontal parallax (about 0.95°)
MAJOR_HALF = 3600.0        # a major period is 2 h, centred on the transit
MINOR_HALF = 1800.0        # a minor period is 1 h, centred on rise or set


def jd(epoch):
    return epoch / 86400.0 + 2440587.5


def rev(x):
    return x - math.floor(x / 360.0) * 360.0


def gmst_deg(epoch):
    d = jd(epoch) - 2451545.0
    return rev(280.46061837 + 360.98564736629 * d)


# ---------------------------------------------------------------- sun

def sun_radec(epoch):
    """Apparent right ascension and declination of the sun, degrees."""
    t = (jd(epoch) - 2451545.0) / 36525.0
    l0 = rev(280.46646 + t * (36000.76983 + t * 0.0003032))
    m = 357.52911 + t * (35999.05029 - 0.0001537 * t)
    c = (math.sin(m * DEG) * (1.914602 - t * (0.004817 + 0.000014 * t))
         + math.sin(2 * m * DEG) * (0.019993 - 0.000101 * t) + math.sin(3 * m * DEG) * 0.000289)
    true_long = l0 + c
    omega = 125.04 - 1934.136 * t
    lam = true_long - 0.00569 - 0.00478 * math.sin(omega * DEG)
    eps0 = 23 + (26 + (21.448 - t * (46.815 + t * (0.00059 - t * 0.001813))) / 60.0) / 60.0
    eps = eps0 + 0.00256 * math.cos(omega * DEG)
    ra = math.atan2(math.cos(eps * DEG) * math.sin(lam * DEG), math.cos(lam * DEG)) / DEG
    dec = math.asin(math.sin(eps * DEG) * math.sin(lam * DEG)) / DEG
    return rev(ra), dec, rev(lam)


def altitude(ra, dec, epoch, lat, lon):
    ha = rev(gmst_deg(epoch) + lon - ra)
    s = (math.sin(lat * DEG) * math.sin(dec * DEG)
         + math.cos(lat * DEG) * math.cos(dec * DEG) * math.cos(ha * DEG))
    return math.asin(max(-1.0, min(1.0, s))) / DEG


def hour_angle(ra, epoch, lon):
    """Local hour angle in degrees, -180..180 (0 = on the meridian)."""
    return rev(gmst_deg(epoch) + lon - ra + 180.0) - 180.0


def sun_altitude(epoch, lat, lon):
    ra, dec, _ = sun_radec(epoch)
    return altitude(ra, dec, epoch, lat, lon)


# ---------------------------------------------------------------- moon

def moon_ecliptic(epoch):
    """Geocentric ecliptic longitude and latitude of the moon (degrees) and distance (Earth radii)."""
    d = jd(epoch) - 2451543.5
    n = rev(125.1228 - 0.0529538083 * d)
    i = 5.1454
    w = rev(318.0634 + 0.1643573223 * d)
    a = 60.2666
    e = 0.054900
    m = rev(115.3654 + 13.0649929509 * d)
    ecc = m + e / DEG * math.sin(m * DEG) * (1.0 + e * math.cos(m * DEG))
    for _ in range(3):
        ecc = ecc - (ecc - e / DEG * math.sin(ecc * DEG) - m) / (1 - e * math.cos(ecc * DEG))
    xv = a * (math.cos(ecc * DEG) - e)
    yv = a * math.sqrt(1 - e * e) * math.sin(ecc * DEG)
    v = math.atan2(yv, xv) / DEG
    r = math.hypot(xv, yv)
    xh = r * (math.cos(n * DEG) * math.cos((v + w) * DEG) - math.sin(n * DEG) * math.sin((v + w) * DEG) * math.cos(i * DEG))
    yh = r * (math.sin(n * DEG) * math.cos((v + w) * DEG) + math.cos(n * DEG) * math.sin((v + w) * DEG) * math.cos(i * DEG))
    zh = r * math.sin((v + w) * DEG) * math.sin(i * DEG)
    lon = rev(math.atan2(yh, xh) / DEG)
    lat = math.atan2(zh, math.hypot(xh, yh)) / DEG
    # Perturbations.
    ms = rev(356.0470 + 0.9856002585 * d)        # sun's mean anomaly
    ws = 282.9404 + 4.70935e-5 * d
    ls = rev(ms + ws)                            # sun's mean longitude
    lm = rev(n + w + m)                          # moon's mean longitude
    dd = lm - ls                                 # mean elongation
    f = lm - n                                   # argument of latitude
    lon += (-1.274 * math.sin((m - 2 * dd) * DEG) + 0.658 * math.sin(2 * dd * DEG)
            - 0.186 * math.sin(ms * DEG) - 0.059 * math.sin((2 * m - 2 * dd) * DEG)
            - 0.057 * math.sin((m - 2 * dd + ms) * DEG) + 0.053 * math.sin((m + 2 * dd) * DEG)
            + 0.046 * math.sin((2 * dd - ms) * DEG) + 0.041 * math.sin((m - ms) * DEG)
            - 0.035 * math.sin(dd * DEG) - 0.031 * math.sin((m + ms) * DEG)
            - 0.015 * math.sin((2 * f - 2 * dd) * DEG) + 0.011 * math.sin((m - 4 * dd) * DEG))
    lat += (-0.173 * math.sin((f - 2 * dd) * DEG) - 0.055 * math.sin((m - f - 2 * dd) * DEG)
            - 0.046 * math.sin((m + f - 2 * dd) * DEG) + 0.033 * math.sin((f + 2 * dd) * DEG)
            + 0.017 * math.sin((2 * m + f) * DEG))
    r += -0.58 * math.cos((m - 2 * dd) * DEG) - 0.46 * math.cos(2 * dd * DEG)
    return rev(lon), lat, r


def moon_radec(epoch):
    lon, lat, _r = moon_ecliptic(epoch)
    d = jd(epoch) - 2451543.5
    eps = (23.4393 - 3.563e-7 * d) * DEG
    x = math.cos(lon * DEG) * math.cos(lat * DEG)
    y = math.sin(lon * DEG) * math.cos(lat * DEG)
    z = math.sin(lat * DEG)
    ye = y * math.cos(eps) - z * math.sin(eps)
    ze = y * math.sin(eps) + z * math.cos(eps)
    ra = rev(math.atan2(ye, x) / DEG)
    dec = math.atan2(ze, math.hypot(x, ye)) / DEG
    return ra, dec


def moon_altitude(epoch, lat, lon):
    ra, dec = moon_radec(epoch)
    return altitude(ra, dec, epoch, lat, lon)


def phase_angle(epoch):
    """Moon-sun elongation in ecliptic longitude, 0..360 (0 new, 180 full)."""
    _ra, _dec, sun_lon = sun_radec(epoch)
    moon_lon = moon_ecliptic(epoch)[0]
    return rev(moon_lon - sun_lon)


PHASE_NAMES = [(22.5, 'New moon'), (67.5, 'Waxing crescent'), (112.5, 'First quarter'),
               (157.5, 'Waxing gibbous'), (202.5, 'Full moon'), (247.5, 'Waning gibbous'),
               (292.5, 'Last quarter'), (337.5, 'Waning crescent'), (360.1, 'New moon')]
MOON_FRAMES = 30   # media/moon/moon_00..29.png, frame 0 = new


def moon_phase(epoch):
    angle = phase_angle(epoch)
    illum = (1 - math.cos(angle * DEG)) / 2.0
    name = next(n for limit, n in PHASE_NAMES if angle < limit)
    age = angle / 360.0 * SYNODIC
    return {'angle': angle, 'illumination': illum, 'name': name, 'age': age,
            'frame': int(round(angle / 360.0 * MOON_FRAMES)) % MOON_FRAMES}


def next_phase(epoch, target_deg):
    """Epoch of the next time the elongation reaches target_deg (0 new, 180 full)."""
    def diff(t):
        return (phase_angle(t) - target_deg + 180.0) % 360.0 - 180.0
    step = 6 * 3600.0
    t = epoch
    prev = diff(t)
    for _ in range(int(31 * 86400 / step) + 2):
        t2 = t + step
        cur = diff(t2)
        if prev < 0 <= cur and cur - prev < 90:
            lo, hi = t, t2
            for _ in range(30):
                mid = (lo + hi) / 2.0
                if diff(mid) < 0:
                    lo = mid
                else:
                    hi = mid
            return (lo + hi) / 2.0
        t, prev = t2, cur
    return None


def days_from_new_or_full(epoch):
    """Days to the nearest new or full moon (past or future)."""
    angle = phase_angle(epoch)
    to_event = min(angle % 180.0, 180.0 - angle % 180.0)
    return to_event / 360.0 * SYNODIC


# ---------------------------------------------------------------- events in a day

def _crossings(f, start, end, step, level):
    """Times where f(t) - level changes sign in [start, end): [(t, rising)]."""
    out = []
    t0, v0 = start, f(start) - level
    t = start
    while t < end:
        t1 = min(end, t + step)
        v1 = f(t1) - level
        if (v0 < 0) != (v1 < 0):
            lo, hi, vlo = t0, t1, v0
            for _ in range(18):
                mid = (lo + hi) / 2.0
                vm = f(mid) - level
                if (vm < 0) == (vlo < 0):
                    lo, vlo = mid, vm
                else:
                    hi = mid
            out.append(((lo + hi) / 2.0, v1 > v0))
        t0, v0, t = t1, v1, t1
    return out


def _meridian(radec, start, end, lon, lower=False, step=1200.0):
    """Upper (or lower) transit times in [start, end)."""
    def ha(t):
        h = hour_angle(radec(t)[0], t, lon)
        if lower:
            h = rev(h) - 180.0
        return h
    out = []
    t = start
    h0 = ha(t)
    while t < end:
        t1 = min(end, t + step)
        h1 = ha(t1)
        if h0 < 0 <= h1 and h1 - h0 < 90:
            lo, hi = t, t1
            for _ in range(18):
                mid = (lo + hi) / 2.0
                if ha(mid) < 0:
                    lo = mid
                else:
                    hi = mid
            out.append((lo + hi) / 2.0)
        t, h0 = t1, h1
    return out


def local_midnight(epoch, offset):
    """Epoch of the location's midnight starting the day that contains epoch."""
    return math.floor((epoch + offset) / 86400.0) * 86400.0 - offset


def sun_day(epoch, lat, lon, offset):
    """Sunrise, sunset, solar noon, day length and golden hours for the local day of epoch."""
    start = local_midnight(epoch, offset)
    end = start + 86400.0

    def f(t):
        return sun_altitude(t, lat, lon)
    events = _crossings(f, start, end, 1800.0, SUN_ALTITUDE)
    rise = next((t for t, up in events if up), None)
    sset = next((t for t, up in events if not up), None)
    golden = _crossings(f, start, end, 1800.0, 6.0)
    morning_gold_end = next((t for t, up in golden if up), None)
    evening_gold_start = next((t for t, up in golden if not up), None)
    noon = (_meridian(lambda t: sun_radec(t)[:2], start, end, lon) or [None])[0]
    if rise and sset and sset > rise:
        length = sset - rise
    else:
        length = 86400.0 if noon and f(noon) > 0 else 0.0
    dawn = _crossings(f, start, end, 1800.0, -6.0)
    return {
        'sunrise': rise, 'sunset': sset, 'noon': noon, 'day_length': length,
        'golden_morning': (rise, morning_gold_end) if rise and morning_gold_end else None,
        'golden_evening': (evening_gold_start, sset) if sset and evening_gold_start else None,
        'dawn': next((t for t, up in dawn if up), None),
        'dusk': next((t for t, up in dawn if not up), None),
        'noon_altitude': f(noon) if noon else None,
    }


def moon_day(epoch, lat, lon, offset):
    """Moonrise, moonset, overhead and underfoot transits for the local day of epoch."""
    start = local_midnight(epoch, offset)
    end = start + 86400.0
    events = _crossings(lambda t: moon_altitude(t, lat, lon), start, end, 1200.0, MOON_ALTITUDE)
    return {
        'rise': [t for t, up in events if up],
        'set': [t for t, up in events if not up],
        'overhead': _meridian(moon_radec, start, end, lon),
        'underfoot': _meridian(moon_radec, start, end, lon, lower=True),
    }


def solunar(epoch, lat, lon, offset):
    """Solunar periods for the local day: {'major': [(start, end, centre)], 'minor': [...]}."""
    m = moon_day(epoch, lat, lon, offset)
    majors = sorted(m['overhead'] + m['underfoot'])
    minors = sorted(m['rise'] + m['set'])
    return {
        'major': [(t - MAJOR_HALF, t + MAJOR_HALF, t) for t in majors],
        'minor': [(t - MINOR_HALF, t + MINOR_HALF, t) for t in minors],
        'moon': m,
    }
