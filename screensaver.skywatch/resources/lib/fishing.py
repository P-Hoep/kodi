"""The fishing score: a transparent weighted sum of six factors, each 0..1, shown with its
parts on screen. No Kodi imports.

Factor          Best when
solunar         a major period overlaps the hour, more when it overlaps dawn or dusk
pressure        falling slowly before a front; poor right after a sharp rise
moon            within 2 days of new or full
wind            5-15 mph; poor above 20 mph
cloud           overcast or low light
water           stable or warming in spring, stable in autumn (needs a gauge or tide station)
"""

from . import astro

FACTORS = ('solunar', 'pressure', 'moon', 'wind', 'cloud', 'water')
NAMES = {'solunar': 'Solunar', 'pressure': 'Pressure', 'moon': 'Moon', 'wind': 'Wind', 'cloud': 'Cloud',
         'water': 'Water temp'}
# Species presets scale the user's weights.
PRESETS = {
    'General': {},
    'Bass': {'pressure': 1.3, 'water': 1.5},
    'Walleye': {'cloud': 2.0, 'wind': 1.3},
    'Trout': {'water': 3.0, 'cloud': 1.4, 'pressure': 0.8},
    'Panfish': {'solunar': 1.2, 'wind': 0.7},
    'Saltwater': {'solunar': 1.3, 'moon': 1.5, 'water': 0.5},
}
KMH_PER_MPH = 1.609344


def weights(settings, species='General'):
    raw = dict((f, float(settings.get('w_' + f, 0))) for f in FACTORS)
    for f, m in PRESETS.get(species, {}).items():
        raw[f] *= m
    return raw


def hour_solunar(t, periods, sun):
    """0.2 outside any period, 0.6 in a minor, 1.0 in a major; +0.3 within an hour of
    sunrise or sunset when a period is active (capped at 1)."""
    score = 0.2
    if any(a <= t <= b for a, b, _c in periods['major']):
        score = 1.0
    elif any(a <= t <= b for a, b, _c in periods['minor']):
        score = 0.6
    if score > 0.2:
        for edge in (sun.get('sunrise'), sun.get('sunset')):
            if edge and abs(t - edge) <= 3600:
                score = min(1.0, score + 0.3)
    return score


def solunar_factor(day_start, periods, sun):
    """Mean of the three best hours of the day."""
    hours = sorted((hour_solunar(day_start + h * 3600 + 1800, periods, sun) for h in range(24)), reverse=True)
    return sum(hours[:3]) / 3.0


def pressure_factor(trend_hpa_3h):
    """trend: change over 3 hours, hPa."""
    if trend_hpa_3h is None:
        return None
    d = trend_hpa_3h
    if -2.0 <= d < -0.5:
        return 1.0       # falling slowly: fish feed ahead of a front
    if d < -2.0:
        return 0.6       # falling fast: storm arriving
    if -0.5 <= d <= 0.5:
        return 0.7       # steady
    if d <= 2.0:
        return 0.45      # rising slowly
    return 0.2           # sharp rise behind a front


def moon_factor(days_to_new_or_full):
    if days_to_new_or_full is None:
        return None
    if days_to_new_or_full <= 2:
        return 1.0
    if days_to_new_or_full <= 4:
        return 0.6
    return 0.3


def wind_factor(kmh):
    if kmh is None:
        return None
    mph = kmh / KMH_PER_MPH
    if 5 <= mph <= 15:
        return 1.0
    if mph < 5:
        return 0.6
    if mph <= 20:
        return 0.6
    return 0.2


def cloud_factor(percent):
    if percent is None:
        return None
    if percent >= 70:
        return 1.0
    if percent >= 40:
        return 0.7
    return 0.4


def water_factor(change_c, month, hemisphere_north=True):
    """change_c: water temperature change over the last 2-3 days."""
    if change_c is None:
        return None
    spring = month in (3, 4, 5, 6) if hemisphere_north else month in (9, 10, 11, 12)
    if spring:
        if change_c > 0.5:
            return 1.0
        if change_c >= -0.5:
            return 0.8
        return 0.3
    if abs(change_c) <= 0.7:
        return 1.0
    return 0.6 if change_c > 0 else 0.4


def score(factors, w):
    """0..100 from {factor: value or None} and weights; missing factors drop out and the rest
    are renormalised. Returns (score, {factor: points contributed})."""
    total_w = sum(w[f] for f in FACTORS if factors.get(f) is not None)
    if total_w <= 0:
        return None, {}
    parts = {}
    for f in FACTORS:
        if factors.get(f) is not None:
            parts[f] = 100.0 * w[f] * factors[f] / total_w
    return int(round(sum(parts.values()))), parts


def rating(value):
    if value is None:
        return ''
    if value >= 80:
        return 'Excellent'
    if value >= 65:
        return 'Good'
    if value >= 45:
        return 'Fair'
    return 'Poor'


def day_inputs(day_start, hourly, lat, lon, offset):
    """Daytime means for one local day from the forecast's hourly arrays (5 am to 9 pm)."""
    times = hourly.get('time') or []
    lo, hi = day_start + 5 * 3600, day_start + 21 * 3600
    idx = [i for i, t in enumerate(times) if lo <= t < hi]

    def mean(key):
        vals = [hourly[key][i] for i in idx if hourly.get(key) and hourly[key][i] is not None]
        return sum(vals) / len(vals) if vals else None

    trend = None
    pressures = hourly.get('pressure_msl') or []
    deltas = []
    for i in idx:
        j = i - 3
        if j >= 0 and pressures[i] is not None and pressures[j] is not None:
            deltas.append(pressures[i] - pressures[j])
    if deltas:
        trend = sum(deltas) / len(deltas)
    return {'wind': mean('wind_speed_10m'), 'cloud': mean('cloud_cover'), 'trend': trend}


def forecast_days(fc, lat, lon, settings, water_change=None, days=4, species='General', now=None):
    """[{'start', 'score', 'parts', 'factors', 'periods', 'sun'}] for today and the next days."""
    import time
    now = time.time() if now is None else now
    offset = fc.get('offset', 0)
    hourly = fc.get('hourly') or {}
    w = weights(settings, species)
    month = int(time.strftime('%m', time.gmtime(now + offset)))
    out = []
    today = astro.local_midnight(now, offset)
    for k in range(days):
        start = today + k * 86400
        noon = start + 12 * 3600
        periods = astro.solunar(noon, lat, lon, offset)
        sun = astro.sun_day(noon, lat, lon, offset)
        inp = day_inputs(start, hourly, lat, lon, offset)
        factors = {
            'solunar': solunar_factor(start, periods, sun),
            'pressure': pressure_factor(inp['trend']),
            'moon': moon_factor(astro.days_from_new_or_full(noon)),
            'wind': wind_factor(inp['wind']),
            'cloud': cloud_factor(inp['cloud']),
            'water': water_factor(water_change, month, lat >= 0) if k == 0 else None,
        }
        value, parts = score(factors, w)
        out.append({'start': start, 'score': value, 'parts': parts, 'factors': factors, 'periods': periods,
                    'sun': sun, 'inputs': inp})
    return out
