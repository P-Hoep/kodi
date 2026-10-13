"""Scenes 6 and 7: current conditions, and the next two hours of precipitation."""

from .. import astro, charts, units as units_mod
from ..layout import ACCENT, COOL, DIM, SOFT, WHITE
from .common import BOTTOM, MARGIN, TOP, W, header, icon, no_data, place_chart, tile, weather_text

RAIN_MM_15 = 0.1     # at least this much in 15 minutes counts as precipitation starting
                     # (about 20 dBZ, the "rain reaches you" threshold)


def pressure_trend(fc, now):
    """hPa change over the last 3 hours from the hourly series, or None."""
    hourly = (fc or {}).get('hourly') or {}
    times, values = hourly.get('time') or [], hourly.get('pressure_msl') or []
    past = [(t, v) for t, v in zip(times, values) if v is not None and t <= now]
    if len(past) < 4:
        return None
    return past[-1][1] - past[-4][1]


def trend_word(delta):
    if delta is None:
        return ''
    if delta > 1.0:
        return 'rising'
    if delta < -1.0:
        return 'falling'
    return 'steady'


def current(ctx):
    lay = header('Current conditions', ctx.place)
    fc = ctx.fc
    if not fc or not fc.get('current'):
        return no_data(lay)
    c = fc['current']
    u = ctx.u
    day = bool(c.get('is_day', 1))
    lay.image(MARGIN - 10, TOP + 10, 380, 380, icon(c.get('weather_code'), day))
    temp = u.t(c.get('temperature_2m'))
    text = '%d°' % int(round(temp)) if temp is not None else '--'
    lay.big(text, 520, TOP + 30, 300, color=WHITE)
    lay.label(530, TOP + 350, 900, 70, weather_text(c.get('weather_code')), 'xl', color=WHITE)
    lay.label(532, TOP + 425, 900, 50, 'Feels like %s' % u.temp(c.get('apparent_temperature')), 'md',
              color=SOFT)
    # Today's high and low beside the big number.
    daily = fc.get('daily') or {}
    idx = _today_index(daily, ctx)
    if idx is not None:
        hi = daily['temperature_2m_max'][idx]
        lo = daily['temperature_2m_min'][idx]
        lay.label(1220, TOP + 70, 400, 60, 'High  %s' % u.temp(hi), 'lg', color='FFFFB74D')
        lay.label(1220, TOP + 140, 400, 60, 'Low   %s' % u.temp(lo), 'lg', color='FF81D4FA')
        pop = (daily.get('precipitation_probability_max') or [None] * (idx + 1))[idx]
        if pop is not None:
            lay.label(1220, TOP + 210, 500, 60, 'Precip  %d%%' % pop, 'lg', color=SOFT)
    # Detail tiles: two rows of four.
    trend = pressure_trend(fc, ctx.now)
    sun = astro.sun_day(ctx.now, ctx.lat, ctx.lon, ctx.offset)
    wind_dir = c.get('wind_direction_10m')
    gust = c.get('wind_gusts_10m')
    vis = c.get('visibility')
    tiles = [
        ('Wind', '%s %s' % (units_mod.compass(wind_dir), u.wind_text(c.get('wind_speed_10m'))),
         'Gusts %s' % u.wind_text(gust) if gust is not None else '', 'icons/wind.png'),
        ('Humidity', '%d%%' % c['relative_humidity_2m'] if c.get('relative_humidity_2m') is not None else '--',
         'Dew point %s' % u.temp(c.get('dew_point_2m')), 'icons/humidity.png'),
        ('Pressure', u.pressure_text(c.get('pressure_msl')), trend_word(trend).capitalize() +
         (' %s over 3 h' % ('%+.2f' % u.p(trend) if u.pressure == 'inHg' else '%+d' % round(u.p(trend)))
          if trend is not None else ''), 'icons/barometer.png'),
        ('UV index', '%d' % round(c['uv_index']) if c.get('uv_index') is not None else '--',
         uv_word(c.get('uv_index')), 'icons/uv-index.png'),
        ('Visibility', u.distance_text(vis / 1000.0) if vis is not None else '--', '', 'icons/horizon.png'),
        ('Cloud cover', '%d%%' % c['cloud_cover'] if c.get('cloud_cover') is not None else '--', '',
         'icons/cloudy.png'),
        ('Sunrise', ctx.clock(sun['sunrise']), '', 'icons/sunrise.png'),
        ('Sunset', ctx.clock(sun['sunset']), '', 'icons/sunset.png'),
    ]
    tw, th, gap = (W - 2 * MARGIN - 3 * 24) // 4, 160, 24
    y0 = BOTTOM - 2 * th - gap
    for i, (cap, value, sub, ic) in enumerate(tiles):
        x = MARGIN + (i % 4) * (tw + gap)
        y = y0 + (i // 4) * (th + gap)
        tile(lay, x, y, tw, th, cap, value, sub, ic)
    # Compass arrow for the wind (points where the wind blows to).
    if wind_dir is not None:
        lay.image(MARGIN + tw - 70, y0 + 20, 48, 48, 'arrow.png', ACCENT, rotate=(wind_dir + 180) % 360)
    if trend is not None and abs(trend) > 1.0:
        lay.image(MARGIN + 2 * (tw + gap) + tw - 70, y0 + 20, 48, 48, 'arrow.png', 'FFFFB74D' if trend > 0 else COOL, rotate=0 if trend > 0 else 180)
    return lay


def uv_word(uv):
    if uv is None:
        return ''
    for limit, word in ((3, 'Low'), (6, 'Moderate'), (8, 'High'), (11, 'Very high')):
        if uv < limit:
            return word
    return 'Extreme'


def _today_index(daily, ctx):
    times = daily.get('time') or []
    for i, t in enumerate(times):
        if t <= ctx.now < t + 86400:
            return i
    return None


# ---------------------------------------------------------------- next 2 hours

def next_two_hours(fc, now):
    """[(t, mm per 15 min, snow cm)] for the 8 quarter hours from now."""
    m = (fc or {}).get('minutely') or {}
    times = m.get('time') or []
    precip = m.get('precipitation') or [None] * len(times)
    snow = m.get('snowfall') or [0] * len(times)
    out = []
    for t, p, s in zip(times, precip, snow):
        if t + 900 > now and len(out) < 8:
            out.append((t, p or 0.0, s or 0.0))
    return out


def precip_expected(fc, now):
    """True when the next 2 hours have precipitation, or the next 3 hourly probabilities reach 40%."""
    if any(p >= RAIN_MM_15 for _t, p, _s in next_two_hours(fc, now)):
        return True
    hourly = (fc or {}).get('hourly') or {}
    for t, pop in zip(hourly.get('time') or [], hourly.get('precipitation_probability') or []):
        if now - 3600 < t <= now + 2 * 3600 and (pop or 0) >= 40:
            return True
    return False


def first_rain(fc, now, horizon_hours=18):
    """Epoch of the first quarter hour with precipitation within the horizon, or None.
    Open-Meteo's 15-minute series comes from HRRR in the US, so this matches the future radar."""
    m = (fc or {}).get('minutely') or {}
    for t, p in zip(m.get('time') or [], m.get('precipitation') or []):
        if now - 900 < t <= now + horizon_hours * 3600 and (p or 0) >= RAIN_MM_15:
            return t
    return None


def rain_end(fc, start):
    m = (fc or {}).get('minutely') or {}
    raining = False
    for t, p in zip(m.get('time') or [], m.get('precipitation') or []):
        if t < start:
            continue
        if (p or 0) >= RAIN_MM_15:
            raining = True
        elif raining:
            return t
    return None


def headline(fc, now, ctx):
    slots = next_two_hours(fc, now)
    wet = [s for s in slots if s[1] >= RAIN_MM_15]
    kind = 'Snow' if any(s[2] > 0 for s in wet) else 'Rain'
    if not wet:
        return 'No precipitation expected in the next 2 hours'
    if slots[0][1] >= RAIN_MM_15:
        end = rain_end(fc, now)
        if end and end - now <= 2 * 3600:
            return '%s ending in about %d min' % (kind, max(5, round((end - now) / 300.0) * 5))
        return '%s continuing for the next 2 hours' % kind
    minutes = max(5, int(round((wet[0][0] - now) / 300.0)) * 5)
    return '%s starting in about %d min' % (kind, minutes)


def nexthours(ctx):
    lay = header('Next 2 hours', ctx.place)
    fc = ctx.fc
    slots = next_two_hours(fc, ctx.now)
    if not slots:
        return no_data(lay)
    lay.label(MARGIN, TOP + 10, W - 2 * MARGIN, 80, headline(fc, ctx.now, ctx), 'xl', color=WHITE)
    u = ctx.u
    rates = [u.mm(p * 4) for _t, p, _s in slots]   # per hour
    top = max([0.4 if u.precip == 'in' else 10.0] + [r for r in rates if r is not None])
    cw, ch = W - 2 * MARGIN, 600
    chart = charts.Chart(cw, ch, (-0.5, len(slots) - 0.5), (0, top * 1.15), pad=(110, 30, 20, 60))
    chart.y_grid(fmt=lambda v: ('%.2f' % v) if u.precip == 'in' else ('%.1f' % v))
    colors = [('FF90CAF9' if p < 2.5 / 4 else 'FF42A5F5' if p < 7.6 / 4 else 'FF1565C0') if not s else 'FFE1F5FE'
              for _t, p, s in slots]
    chart.bars(list(range(len(slots))), rates, COOL, width_frac=0.72, colors=colors, round_px=10)
    chart.x_ticks([(i, ctx.clock(t)) for i, (t, _p, _s) in enumerate(slots)])
    y0 = TOP + 130
    place_chart(lay, ctx, 'nexthours', chart, MARGIN, y0)
    lay.label(MARGIN, y0 + ch + 6, 900, 34, 'Precipitation rate (%s per hour), 15-minute steps'
              % u.precip, 'xs', color=DIM)
    return lay
