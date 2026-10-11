"""Local weather (Open-Meteo, keyless) and the moon's phase (computed). No Kodi imports."""

import math
import time

from . import net

# WMO weather interpretation codes, as used by Open-Meteo.
WMO = {
    0: 'Clear', 1: 'Mostly clear', 2: 'Partly cloudy', 3: 'Overcast',
    45: 'Fog', 48: 'Freezing fog',
    51: 'Light drizzle', 53: 'Drizzle', 55: 'Heavy drizzle',
    56: 'Freezing drizzle', 57: 'Freezing drizzle',
    61: 'Light rain', 63: 'Rain', 65: 'Heavy rain',
    66: 'Freezing rain', 67: 'Freezing rain',
    71: 'Light snow', 73: 'Snow', 75: 'Heavy snow', 77: 'Snow grains',
    80: 'Light showers', 81: 'Showers', 82: 'Violent showers',
    85: 'Snow showers', 86: 'Heavy snow showers',
    95: 'Thunderstorm', 96: 'Thunderstorm with hail', 99: 'Thunderstorm with hail',
}
COMPASS = ['N', 'NNE', 'NE', 'ENE', 'E', 'ESE', 'SE', 'SSE', 'S', 'SSW', 'SW', 'WSW', 'W', 'WNW', 'NW', 'NNW']


def compass(degrees):
    return COMPASS[int((degrees % 360) / 22.5 + 0.5) % 16]


def _clock(iso):
    """'2026-10-10T07:21' -> '7:21'"""
    try:
        hh, mm = iso.split('T')[1][:5].split(':')
        return '%d:%s' % (int(hh), mm)
    except (AttributeError, IndexError, ValueError):
        return '--'


def fetch(lat, lon, imperial=True):
    """Current conditions for lat/lon as display strings."""
    url = ('https://api.open-meteo.com/v1/forecast?latitude=%.4f&longitude=%.4f'
           '&current=temperature_2m,apparent_temperature,relative_humidity_2m,weather_code,'
           'wind_speed_10m,wind_direction_10m,is_day'
           '&daily=temperature_2m_max,temperature_2m_min,sunrise,sunset'
           '&timezone=auto&forecast_days=1' % (lat, lon))
    if imperial:
        url += '&temperature_unit=fahrenheit&wind_speed_unit=mph'
    return parse(net.fetch_json(url, timeout=15), imperial)


def parse(data, imperial=True):
    cur = data.get('current') or {}
    daily = data.get('daily') or {}

    def first(key):
        values = daily.get(key) or []
        return values[0] if values else None

    def deg(value):
        return '--' if value is None else '%d°' % int(round(value))

    unit = 'mph' if imperial else 'km/h'
    wind = cur.get('wind_speed_10m')
    direction = cur.get('wind_direction_10m')
    wind_text = 'Calm' if wind is not None and wind < 1 else (
        'Wind %d %s %s' % (int(round(wind)), unit, compass(direction or 0)) if wind is not None else 'Wind --')
    humidity = cur.get('relative_humidity_2m')
    return {
        'temp': deg(cur.get('temperature_2m')) + ('F' if imperial else 'C'),
        'condition': WMO.get(cur.get('weather_code'), 'Weather'),
        'feels_hi_lo': 'Feels %s   ·   H %s  L %s' % (deg(cur.get('apparent_temperature')),
                                                   deg(first('temperature_2m_max')),
                                                   deg(first('temperature_2m_min'))),
        'wind_humidity': '%s   ·   Humidity %s' % (wind_text, '--' if humidity is None else '%d%%' % humidity),
        'sun': 'Sunrise %s   ·   Sunset %s' % (_clock(first('sunrise')), _clock(first('sunset'))),
        'fetched': time.time(),
    }


# ---------------------------------------------------------------- moon

SYNODIC_MONTH = 29.530588853           # days, new moon to new moon
REFERENCE_NEW_MOON_JD = 2451550.09765  # 2000-01-06 18:14 UTC (Meeus)
MOON_FRAMES = 30                        # pre-drawn images media/moon/moon_00..29.png
PHASES = [  # (age in days up to which the name applies, name)
    (1.84566, 'New moon'), (5.53699, 'Waxing crescent'), (9.22831, 'First quarter'),
    (12.91963, 'Waxing gibbous'), (16.61096, 'Full moon'), (20.30228, 'Waning gibbous'),
    (23.99361, 'Last quarter'), (27.68493, 'Waning crescent'), (99.0, 'New moon'),
]


def julian_day(epoch):
    return epoch / 86400.0 + 2440587.5


def moon(epoch=None):
    """The moon's phase at epoch (default now). Mean-phase model: phase times within about 0.6 days of USNO."""
    epoch = time.time() if epoch is None else epoch
    age = (julian_day(epoch) - REFERENCE_NEW_MOON_JD) % SYNODIC_MONTH
    angle = 2 * math.pi * age / SYNODIC_MONTH
    lit = (1 - math.cos(angle)) / 2
    name = next(n for limit, n in PHASES if age < limit)
    half = SYNODIC_MONTH / 2
    to_full = (half - age) % SYNODIC_MONTH
    to_new = SYNODIC_MONTH - age
    if name == 'Full moon':
        upcoming = 'New moon in %s' % _days(to_new)
    elif name == 'New moon':
        upcoming = 'Full moon in %s' % _days(to_full)
    elif age < half:
        upcoming = 'Full moon in %s' % _days(to_full)
    else:
        upcoming = 'New moon in %s' % _days(to_new)
    return {
        'age': age,
        'illumination': lit,
        'name': name,
        'frame': int(round(age / SYNODIC_MONTH * MOON_FRAMES)) % MOON_FRAMES,
        'text': '%s   ·   %d%% lit' % (name, int(round(lit * 100))),
        'upcoming': upcoming,
    }


def _days(d):
    d = int(round(d))
    return 'today' if d == 0 else ('1 day' if d == 1 else '%d days' % d)
