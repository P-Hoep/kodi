"""Offline solar elevation (NOAA solar position formula) and the local time at a camera.
No Kodi imports, no network.

Local time comes from a small per-country table of standard offsets and daylight-saving
rules, with longitude bands for the countries that span several zones. Kodi's Python on
Android has no time zone database, and a clock on a TV only needs to be right to the hour.
"""

import calendar
import math
import time

DAY, TWILIGHT, NIGHT, UNKNOWN = 'day', 'twilight', 'night', 'unknown'


def julian_day(epoch):
    return epoch / 86400.0 + 2440587.5


def solar_elevation(lat, lon, epoch):
    """Sun's elevation in degrees above the horizon (refraction ignored) at lat/lon, Unix time."""
    jc = (julian_day(epoch) - 2451545.0) / 36525.0
    l0 = (280.46646 + jc * (36000.76983 + jc * 0.0003032)) % 360.0
    m = 357.52911 + jc * (35999.05029 - 0.0001537 * jc)
    e = 0.016708634 - jc * (0.000042037 + 0.0000001267 * jc)
    mr = math.radians(m)
    centre = (math.sin(mr) * (1.914602 - jc * (0.004817 + 0.000014 * jc)) + math.sin(2 * mr) * (0.019993 - 0.000101 * jc)
              + math.sin(3 * mr) * 0.000289)
    true_long = l0 + centre
    omega = 125.04 - 1934.136 * jc
    app_long = true_long - 0.00569 - 0.00478 * math.sin(math.radians(omega))
    obliq0 = 23 + (26 + (21.448 - jc * (46.815 + jc * (0.00059 - jc * 0.001813))) / 60.0) / 60.0
    obliq = obliq0 + 0.00256 * math.cos(math.radians(omega))
    decl = math.asin(math.sin(math.radians(obliq)) * math.sin(math.radians(app_long)))
    y = math.tan(math.radians(obliq / 2.0)) ** 2
    l0r = math.radians(l0)
    eq_time = 4 * math.degrees(y * math.sin(2 * l0r) - 2 * e * math.sin(mr) + 4 * e * y * math.sin(mr) * math.cos(2 * l0r)
                               - 0.5 * y * y * math.sin(4 * l0r) - 1.25 * e * e * math.sin(2 * mr))
    minutes = (epoch % 86400) / 60.0
    true_solar = (minutes + eq_time + 4 * lon) % 1440.0
    hour_angle = true_solar / 4.0 - 180.0
    latr = math.radians(lat)
    cos_zenith = (math.sin(latr) * math.sin(decl)
                  + math.cos(latr) * math.cos(decl) * math.cos(math.radians(hour_angle)))
    return 90.0 - math.degrees(math.acos(max(-1.0, min(1.0, cos_zenith))))


def classify(elevation):
    if elevation is None:
        return UNKNOWN
    if elevation > 0.0:
        return DAY
    if elevation >= -6.0:
        return TWILIGHT
    return NIGHT


def daylight(lat, lon, epoch, coordinates_quality=None):
    """'day', 'twilight', 'night', or 'unknown' for a camera placed at a country's centroid."""
    if coordinates_quality == 'country_centroid' or lat is None or lon is None:
        return UNKNOWN
    return classify(solar_elevation(lat, lon, epoch))


# ---------------------------------------------------------------- local time

def _nth_sunday(year, month, n):
    """Day of month of the n-th Sunday (n = -1 for the last)."""
    days = calendar.monthrange(year, month)[1]
    sundays = [d for d in range(1, days + 1) if calendar.weekday(year, month, d) == 6]
    return sundays[n if n < 0 else n - 1]


def _last_weekday(year, month, weekday):
    days = calendar.monthrange(year, month)[1]
    return max(d for d in range(1, days + 1) if calendar.weekday(year, month, d) == weekday)


def _utc(year, month, day, hour=0.0):
    return calendar.timegm((year, month, day, 0, 0, 0)) + hour * 3600


def _dst(rule, epoch, std):
    """True if daylight-saving time is in force. std: standard offset in hours."""
    if not rule:
        return False
    year = time.gmtime(epoch).tm_year
    if rule == 'eu':        # last Sunday of March to last Sunday of October, 01:00 UTC
        start = _utc(year, 3, _nth_sunday(year, 3, -1), 1)
        end = _utc(year, 10, _nth_sunday(year, 10, -1), 1)
        return start <= epoch < end
    if rule == 'us':        # second Sunday of March to first Sunday of November, 02:00 local
        start = _utc(year, 3, _nth_sunday(year, 3, 2), 2 - std)
        end = _utc(year, 11, _nth_sunday(year, 11, 1), 1 - std)
        return start <= epoch < end
    if rule == 'eg':        # last Friday of April to last Thursday of October
        start = _utc(year, 4, _last_weekday(year, 4, 4), -std)
        end = _utc(year, 10, _last_weekday(year, 10, 3), 24 - std)
        return start <= epoch < end
    # Southern hemisphere: on from spring (Sep/Oct) to autumn (April), across New Year.
    if rule == 'au':        # first Sunday of October to first Sunday of April, 02:00 standard
        start = _utc(year, 10, _nth_sunday(year, 10, 1), 2 - std)
        end = _utc(year, 4, _nth_sunday(year, 4, 1), 2 - std)
    elif rule == 'nz':      # last Sunday of September to first Sunday of April
        start = _utc(year, 9, _nth_sunday(year, 9, -1), 2 - std)
        end = _utc(year, 4, _nth_sunday(year, 4, 1), 2 - std)
    elif rule == 'cl':      # first Sunday of September to first Sunday of April
        start = _utc(year, 9, _nth_sunday(year, 9, 1), 4 - std)
        end = _utc(year, 4, _nth_sunday(year, 4, 1), 3 - std)
    else:
        return False
    return epoch >= start or epoch < end


# Country -> (standard UTC offset in hours, DST rule). Countries spanning several zones are
# worked out from the coordinates in _zone() instead.
ZONES = {
    'AL': (1, 'eu'), 'AR': (-3, None), 'AT': (1, 'eu'), 'AW': (-4, None), 'BA': (1, 'eu'), 'BB': (-4, None),
    'BE': (1, 'eu'), 'BG': (2, 'eu'), 'BL': (-4, None), 'BM': (-4, 'us'), 'BO': (-4, None), 'BQ': (-4, None),
    'BZ': (-6, None), 'CH': (1, 'eu'), 'CL': (-4, 'cl'), 'CN': (8, None), 'CR': (-6, None), 'CV': (-1, None),
    'CW': (-4, None), 'CY': (2, 'eu'), 'CZ': (1, 'eu'), 'DE': (1, 'eu'), 'DO': (-4, None), 'EC': (-5, None),
    'EE': (2, 'eu'), 'EG': (2, 'eg'), 'FI': (2, 'eu'), 'FO': (0, 'eu'), 'FR': (1, 'eu'), 'GB': (0, 'eu'),
    'GD': (-4, None), 'GP': (-4, None), 'GR': (2, 'eu'), 'GT': (-6, None), 'GY': (-4, None), 'HR': (1, 'eu'),
    'HU': (1, 'eu'), 'IE': (0, 'eu'), 'IL': (2, 'eu'), 'IN': (5.5, None), 'IR': (3.5, None), 'IS': (0, None),
    'IT': (1, 'eu'), 'JM': (-5, None), 'JO': (3, None), 'JP': (9, None), 'KE': (3, None), 'KG': (6, None),
    'KR': (9, None), 'KY': (-5, None), 'KZ': (5, None), 'LK': (5.5, None), 'LT': (2, 'eu'), 'LU': (1, 'eu'),
    'LV': (2, 'eu'), 'MA': (1, None), 'MQ': (-4, None), 'MT': (1, 'eu'), 'MV': (5, None), 'NA': (2, None),
    'NL': (1, 'eu'), 'NO': (1, 'eu'), 'NZ': (12, 'nz'), 'PE': (-5, None), 'PH': (8, None), 'PL': (1, 'eu'),
    'PR': (-4, None), 'RO': (2, 'eu'), 'SC': (4, None), 'SE': (1, 'eu'), 'SG': (8, None), 'SI': (1, 'eu'),
    'SK': (1, 'eu'), 'SM': (1, 'eu'), 'SX': (-4, None), 'TC': (-5, 'us'), 'TH': (7, None), 'TR': (3, None),
    'TT': (-4, None), 'TW': (8, None), 'TZ': (3, None), 'UY': (-3, None), 'VE': (-4, None), 'VG': (-4, None),
    'VI': (-4, None), 'VN': (7, None), 'XK': (1, 'eu'), 'ZA': (2, None), 'ZM': (2, None), 'DK': (1, 'eu'),
    'UA': (2, 'eu'), 'RS': (1, 'eu'), 'ME': (1, 'eu'), 'MK': (1, 'eu'), 'AE': (4, None), 'QA': (3, None),
    'HK': (8, None), 'MY': (8, None),
}


def _zone(cc, lat, lon):
    """(standard offset hours, DST rule) for a camera."""
    if cc == 'US':
        if lon < -154 and lat < 23:
            return -10, None                     # Hawaii
        if lon < -129.9 and lat > 51:
            return -9, 'us'                      # Alaska
        if 31.3 < lat < 37.0 and -114.8 < lon < -109.05:
            return -7, None                      # Arizona
        if lon > -86.5:
            return -5, 'us'
        if lon > -101.0:
            return -6, 'us'
        if lon > -114.5:
            return -7, 'us'
        return -8, 'us'
    if cc == 'CA':
        if lon > -59.5 and lat > 46.5:
            return -3.5, 'us'                    # Newfoundland
        if lon > -64.5:
            return -4, 'us'
        if lon > -90.0:
            return -5, 'us'
        if lon > -102.0:
            return -6, 'us'
        if lon > -120.0:
            return -7, 'us'
        return -8, 'us'
    if cc == 'AU':
        if lon < 129.0:
            return 8, None                       # Western Australia
        if lon < 141.0:
            return 9.5, 'au' if lat < -26.0 else None   # South Australia / Northern Territory
        return 10, 'au' if lat < -28.2 else None        # NSW, Victoria, Tasmania / Queensland
    if cc == 'BR':
        if lon > -54.5 or lat < -24.0:
            return -3, None
        if lon < -66.0 and lat > -11.5:
            return -5, None
        return -4, None
    if cc == 'MX':
        if lon < -114.5:
            return -8, 'us'                      # Baja California
        if lon < -105.5 and lat > 22.0:
            return -7, None                      # Sonora, Sinaloa
        if lon > -89.5 and lat < 22.0:
            return -5, None                      # Quintana Roo
        return -6, None
    if cc == 'RU':
        if lon < 23.0:
            return 2, None                       # Kaliningrad
        if lon < 45.0:
            return 3, None
        return int(round(lon / 15.0)) + 1, None
    if cc == 'ID':
        if lon < 115.0:
            return 7, None
        if lon < 127.0:
            return 8, None
        return 9, None
    if cc == 'ES' and lon < -13.0:
        return 0, 'eu'                           # Canary Islands
    if cc == 'PT':
        return (-1 if lon < -20.0 else 0), 'eu'  # Azores
    if cc in ZONES:
        return ZONES[cc]
    return int(round(lon / 15.0)), None


def utc_offset(cc, lat, lon, epoch):
    """The camera's UTC offset in seconds at Unix time epoch."""
    std, rule = _zone((cc or '').upper(), lat or 0.0, lon or 0.0)
    return int((std + (1 if _dst(rule, epoch, std) else 0)) * 3600)


def local_time(cc, lat, lon, epoch, twenty_four=True):
    """'14:05' (or '2:05 PM') at the camera."""
    tm = time.gmtime(epoch + utc_offset(cc, lat, lon, epoch))
    if twenty_four:
        return '%02d:%02d' % (tm.tm_hour, tm.tm_min)
    hour = tm.tm_hour % 12 or 12
    return '%d:%02d %s' % (hour, tm.tm_min, 'AM' if tm.tm_hour < 12 else 'PM')
