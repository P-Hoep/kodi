"""Scenes 8 and 9: the 48-hour graph and the daily forecast cards."""

import time

from .. import charts, units as units_mod
from ..layout import COOL, DIM, SOFT, WARM, WHITE
from .common import BOTTOM, MARGIN, TOP, W, header, icon, no_data, place_chart, wrap


def hourly(ctx):
    lay = header('Next 48 hours', ctx.place)
    fc = ctx.fc
    h = (fc or {}).get('hourly') or {}
    times = h.get('time') or []
    i0 = ctx.hourly_index()
    idx = list(range(i0, min(len(times), i0 + 49)))
    if len(idx) < 6:
        return no_data(lay)
    u = ctx.u
    ts = [times[i] for i in idx]
    temp = [u.t(h['temperature_2m'][i]) for i in idx]
    feels = [u.t(h['apparent_temperature'][i]) for i in idx]
    pop = [(h.get('precipitation_probability') or [0] * len(times))[i] or 0 for i in idx]
    wind = [u.w(h['wind_speed_10m'][i]) for i in idx]
    gust = [u.w((h.get('wind_gusts_10m') or [None] * len(times))[i]) for i in idx]
    is_day = [(h.get('is_day') or [1] * len(times))[i] for i in idx]
    vals = [v for v in temp + feels if v is not None]
    lo, hi = min(vals), max(vals)
    pad = max(3.0, (hi - lo) * 0.15)
    cw = W - 2 * MARGIN
    # Temperature with day/night shading and precipitation-probability bars behind.
    chart = charts.Chart(cw, 520, (ts[0], ts[-1]), (lo - pad, hi + pad), pad=(90, 20, 90, 50))
    k = 0
    while k < len(ts):
        if is_day[k]:
            k += 1
            continue
        j = k
        while j < len(ts) and not is_day[j]:
            j += 1
        chart.shade(ts[k] - 1800, ts[j - 1] + 1800, '40000814')
        k = j
    # Precipitation probability uses the full height: 0-100 % on the right axis.
    scale = (hi + pad - (lo - pad)) / 100.0
    chart.bars(ts, [lo - pad + p * scale for p in pop], 'FF2C6DB0', width_frac=0.75,
               base=lo - pad, colors=['%02X42A5F5' % (90 + int(p * 1.4)) for p in pop])
    chart.y_grid(fmt=lambda v: '%d°' % round(v))
    for p in (0, 50, 100):
        chart.label(chart.right + 14, chart.Y(lo - pad + p * scale) - 14, '%d%%' % p, 'left', color='B064B5F6')
    chart.line(ts, feels, 'A0FFE0B2', 3)
    chart.line(ts, temp, WARM, 6)
    ticks = []
    for t in ts:
        tm = ctx.local(t)
        if tm.tm_hour % 6 == 0:
            ticks.append((t, ctx.day_name(t) if tm.tm_hour == 0 else ctx.hour(t)))
    chart.x_ticks(ticks, tall=True, color='18FFFFFF')
    # Mark the high and low.
    for target, color in ((max(temp), WARM), (min(temp), 'FF81D4FA')):
        k = temp.index(target)
        chart.dot(ts[k], target, color, 9)
        chart.label(chart.X(ts[k]), chart.Y(target) + (-56 if color == WARM else 14), '%d°' % round(target),
                    'center', 'md', color)
    y0 = TOP - 10
    place_chart(lay, ctx, 'hourly', chart, MARGIN, y0)
    # Wind speed band under the temperature chart.
    wtop = max([10.0] + [g for g in gust if g is not None] + [w for w in wind if w is not None]) * 1.1
    wc = charts.Chart(cw, 190, (ts[0], ts[-1]), (0, wtop), pad=(90, 10, 90, 36))
    wc.band(ts, [0] * len(ts), gust, '3080CBC4')
    wc.band(ts, [0] * len(ts), wind, '9026A69A')
    wc.line(ts, wind, 'FF80CBC4', 3)
    wc.y_grid(step=charts.nice_step(wtop, 2), fmt=lambda v: '%d' % round(v))
    wc.x_ticks([(t, '') for t, _ in ticks], tall=True, color='18FFFFFF')
    place_chart(lay, ctx, 'hourly_wind', wc, MARGIN, y0 + 540)
    # Legend.
    ly = y0 + 540 + 196
    items = [(WARM, 'Temperature'), ('FFFFE0B2', 'Feels like'), ('FF42A5F5', 'Chance of precipitation'),
             ('FF26A69A', 'Wind (%s), shaded to gusts' % u.wind)]
    x = MARGIN + 90
    for color, text in items:
        lay.rect(x, ly + 14, 34, 8, color)
        lay.label(x + 46, ly, 520, 34, text, 'xs', color=SOFT)
        x += 46 + 22 * len(text) // 2 + 90
    return lay


def daily(ctx):
    n = 10 if ctx.s.get('daily_days', 0) == 1 else 7
    lay = header('%d-day forecast' % n, ctx.place)
    fc = ctx.fc
    d = (fc or {}).get('daily') or {}
    times = d.get('time') or []
    start = None
    for i, t in enumerate(times):
        if t <= ctx.now < t + 86400:
            start = i
            break
    if start is None:
        return no_data(lay)
    idx = list(range(start, min(len(times), start + n)))
    u = ctx.u
    his = [u.t(d['temperature_2m_max'][i]) for i in idx]
    los = [u.t(d['temperature_2m_min'][i]) for i in idx]
    top, bottom = max(his), min(los)
    span = max(1.0, top - bottom)
    nws_lines = _nws_by_date(ctx)
    gap = 18
    cw = (W - 2 * MARGIN - gap * (n - 1)) // n
    ch = BOTTOM - TOP
    bar_top, bar_h = TOP + 340, 210
    chars = max(10, cw // 13)
    for k, i in enumerate(idx):
        x = MARGIN + k * (cw + gap)
        lay.card(x, TOP, cw, ch, '55101C2C' if k else '80183050')
        cx = x + cw // 2
        lay.label(cx - cw // 2, TOP + 18, cw, 50, ctx.day_name(times[i]), 'md', 'center', WHITE)
        tm = ctx.local(times[i])
        lay.label(cx - cw // 2, TOP + 66, cw, 34, '%d/%d' % (tm.tm_mon, tm.tm_mday), 'xs', 'center', DIM)
        isz = min(150, cw - 20)
        lay.image(cx - isz // 2, TOP + 104, isz, isz, icon(d['weather_code'][i], True))
        # Range bar on the shared temperature scale.
        y_hi = bar_top + (top - his[k]) / span * bar_h
        y_lo = bar_top + (top - los[k]) / span * bar_h
        lay.label(cx - cw // 2, y_hi - 62, cw, 56, '%d°' % round(his[k]), 'lg', 'center', WARM)
        lay.image(cx - 9, y_hi, 18, max(18, y_lo - y_hi), 'pill.png', 'FF5E8FC4', aspect=0)
        lay.image(cx - 9, y_hi, 18, 18, 'dot.png', WARM)
        lay.image(cx - 9, max(y_hi, y_lo - 18), 18, 18, 'dot.png', 'FF81D4FA')
        lay.label(cx - cw // 2, y_lo + 8, cw, 56, '%d°' % round(los[k]), 'lg', 'center', 'FF81D4FA')
        y = bar_top + bar_h + 76
        pop = (d.get('precipitation_probability_max') or [None] * len(times))[i]
        if pop is not None:
            lay.image(cx - 70, y + 4, 34, 34, 'icons/raindrop.png')
            lay.label(cx - 30, y, 120, 40, '%d%%' % pop, 'sm', color=COOL if pop >= 30 else SOFT)
        wind = d.get('wind_speed_10m_max', [None] * len(times))[i]
        wdir = (d.get('wind_direction_10m_dominant') or [None] * len(times))[i]
        lay.label(cx - cw // 2, y + 44, cw, 34, '%s %s' % (units_mod.compass(wdir), u.wind_text(wind)),
                  'xs', 'center', SOFT)
        line = nws_lines.get(time.strftime('%Y-%m-%d', tm)) or (nws_lines.get('first') if k == 0 else None)
        if line:
            for j, text in enumerate(wrap(line, chars, 2)):
                lay.label(x + 8, y + 92 + j * 30, cw - 16, 30, text, 'xs', 'center', SOFT)
    return lay


def _nws_by_date(ctx):
    periods = ctx.hub.get('nws_forecast') if ctx.hub and ctx.hub.us else None
    out = {}
    if periods:
        out['first'] = periods[0].get('short') or ''
    for p in periods or []:
        if p.get('day') and p.get('date') and p['date'] not in out:
            out[p['date']] = p.get('short') or ''
    return out
