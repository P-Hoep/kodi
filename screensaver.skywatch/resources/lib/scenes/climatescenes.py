"""Scenes 10 and 11: today against the 1991-2020 normal, and the year in temperature."""

import time

from .. import charts, climate
from ..layout import DIM, SOFT, WARM, WHITE
from .common import BOTTOM, MARGIN, MONTHS, TOP, W, header, no_data, place_chart

RED = 'FFEF5350'
BLUE = 'FF42A5F5'


def _today(ctx):
    tm = ctx.local(ctx.now)
    return '%02d-%02d' % (tm.tm_mon, tm.tm_mday), tm


def today_vs_normal(ctx):
    lay = header('Today vs normal', '%s · 1991–2020 normals · ERA5 since 1940' % ctx.place)
    data = ctx.hub.climate() if ctx.hub else None
    fc = ctx.fc
    if not data or not fc:
        return no_data(lay, 'Building climate normals...')
    u = ctx.u
    mmdd, tm = _today(ctx)
    i = climate.INDEX.get(mmdd)
    normal = data['normals'][i] if i is not None else None
    record = data['records'][i] if i is not None else None
    daily = fc.get('daily') or {}
    hi = lo = None
    for k, t in enumerate(daily.get('time') or []):
        if t <= ctx.now < t + 86400:
            hi, lo = daily['temperature_2m_max'][k], daily['temperature_2m_min'][k]
    if normal is None or hi is None:
        return no_data(lay)
    # Left: today's numbers against normal and records.
    x = MARGIN
    y = TOP + 10
    lay.label(x, y, 600, 40, 'TODAY  ·  %s' % climate.day_label(mmdd).upper(), 'sm', color=DIM)
    lay.big('%d°' % round(u.t(hi)), x, y + 46, 200, color=WARM)
    lay.big('%d°' % round(u.t(lo)), x + 330, y + 46, 200, color='FF81D4FA')
    lay.label(x + 6, y + 252, 300, 40, 'High', 'sm', color=SOFT)
    lay.label(x + 336, y + 252, 300, 40, 'Low', 'sm', color=SOFT)
    rows = [
        ('Normal', '%s / %s' % (u.temp(normal['hi']), u.temp(normal['lo']))),
        ('Departure', '%s / %s' % (u.temp_delta(hi - normal['hi']), u.temp_delta(lo - normal['lo']))),
    ]
    if record:
        rows.append(('Record high', '%s  (%d)' % (u.temp(record['hi'][0]), record['hi'][1])))
        rows.append(('Record low', '%s  (%d)' % (u.temp(record['lo'][0]), record['lo'][1])))
    for k, (cap, value) in enumerate(rows):
        lay.label(x, y + 320 + k * 62, 260, 50, cap, 'md', color=SOFT)
        lay.label(x + 260, y + 320 + k * 62, 420, 50, value, 'md', color=WHITE)
    fact = climate.fact(mmdd, tm.tm_year, hi, lo, data['history'], normal, u)
    # Right: the band chart for this day (record range, p10-p90, normal, today).
    cx0, cw, ch = 720, 340, 600
    vals = [record['lo'][0], record['hi'][0]] if record else [normal['lo10'], normal['hi90']]
    vals += [hi, lo]
    vmin, vmax = u.t(min(vals)) - 3, u.t(max(vals)) + 3
    band = charts.Chart(cw, ch, (0, 1), (vmin, vmax), pad=(80, 20, 20, 20))
    band.y_grid(fmt=lambda v: '%d°' % round(v))
    if record:
        band.range_bar(0.5, u.t(record['lo'][0]), u.t(record['hi'][0]), '30FFFFFF', 120)
    band.range_bar(0.5, u.t(normal['lo10']), u.t(normal['lo90']), '6042A5F5', 90)
    band.range_bar(0.5, u.t(normal['hi10']), u.t(normal['hi90']), '60EF5350', 90)
    band.canvas.fill_rect(band.X(0.5) - 70, band.Y(u.t(normal['hi'])) - 2, band.X(0.5) + 70,
                          band.Y(u.t(normal['hi'])) + 2, 'C0FFFFFF')
    band.canvas.fill_rect(band.X(0.5) - 70, band.Y(u.t(normal['lo'])) - 2, band.X(0.5) + 70,
                          band.Y(u.t(normal['lo'])) + 2, 'C0FFFFFF')
    band.dot(0.5, u.t(hi), WARM, 16)
    band.dot(0.5, u.t(lo), 'FF81D4FA', 16)
    place_chart(lay, ctx, 'climate_band', band, cx0, TOP)
    legend = [('30FFFFFF', 'Record range'), ('60EF5350', 'Usual highs'),
              ('6042A5F5', 'Usual lows'), ('C0FFFFFF', 'Normal'), (WARM, 'Today')]
    lx = cx0 + cw + 30
    for k, (color, text) in enumerate(legend):
        col, row = k % 3, k // 3
        lay.rect(lx + col * 250, TOP + 20 + row * 44 + 12, 28, 14, color)
        lay.label(lx + col * 250 + 40, TOP + 20 + row * 44, 210, 34, text, 'xs', color=SOFT)
    # Month to date: daily mean anomaly bars.
    month_dates = ['%04d-%02d-%02d' % (tm.tm_year, tm.tm_mon, d) for d in range(1, tm.tm_mday + 1)]
    anoms = climate.anomalies(data['daily'], data['normals'], month_dates)
    if any(a is not None for a in anoms):
        vals = [abs(u.dt(a)) for a in anoms if a is not None]
        top = max(5.0, max(vals) * 1.2)
        mx, my = lx - 70, TOP + 130
        mw, mh = W - MARGIN - mx, 400
        mc = charts.Chart(mw, mh, (0.5, max(len(month_dates), 10) + 0.5), (-top, top), pad=(70, 50, 10, 46))
        mc.y_grid(step=charts.nice_step(top, 2), fmt=lambda v: '%+d°' % round(v) if v else '0')
        disp = [u.dt(a) if a is not None else None for a in anoms]
        mc.bars(list(range(1, len(month_dates) + 1)), disp, RED, base=0, width_frac=0.75,
                colors=[RED if (a or 0) >= 0 else BLUE for a in disp])
        mc.x_ticks([(d, str(d)) for d in range(1, len(month_dates) + 1) if d == 1 or d % 5 == 0])
        mc.label(mc.left, 4, '%s so far: daily departure from normal' % MONTHS[tm.tm_mon - 1], 'left', 'sm', SOFT)
        valid = [a for a in disp if a is not None]
        place_chart(lay, ctx, 'climate_month', mc, mx, my)
        if valid:
            mean = sum(valid) / len(valid)
            lay.label(mx + 70, my + mh + 6, mw, 40, 'Month to date: %+.1f° %s normal'
                      % (abs(mean), 'above' if mean >= 0 else 'below'), 'sm', color=RED if mean >= 0 else BLUE)
    if fact:
        lay.card(MARGIN, BOTTOM - 120, W - 2 * MARGIN, 110, '70183050')
        lay.label(MARGIN + 40, BOTTOM - 100, W - 2 * MARGIN - 80, 70, fact, 'xl', color=WHITE)
    return lay


def year(ctx):
    lay = header('A year in temperature', '%s · daily highs and lows over the 1991–2020 normal'
                 % ctx.place)
    data = ctx.hub.climate() if ctx.hub else None
    if not data:
        return no_data(lay, 'Building climate normals...')
    u = ctx.u
    daily = data['daily']
    end = time.strftime('%Y-%m-%d', ctx.local(ctx.now))
    rows = [(d, hi, lo) for d, hi, lo in zip(daily['time'], daily['max'], daily['min']) if d <= end][-365:]
    if len(rows) < 30:
        return no_data(lay)
    xs = list(range(len(rows)))
    norm = [data['normals'][climate.INDEX[d[5:]]] for d, _h, _l in rows]
    recs = [data['records'][climate.INDEX[d[5:]]] for d, _h, _l in rows]
    vals = [u.t(v) for _d, h, l in rows for v in (h, l)] + [u.t(n['lo10']) for n in norm if n] + \
           [u.t(n['hi90']) for n in norm if n]
    vmin, vmax = min(vals) - 4, max(vals) + 4
    cw, ch = W - 2 * MARGIN, BOTTOM - TOP - 70
    c = charts.Chart(cw, ch, (-0.5, len(rows) - 0.5), (vmin, vmax), pad=(80, 10, 20, 50))
    c.band(xs, [u.t(n['lo']) if n else None for n in norm], [u.t(n['hi']) if n else None for n in norm],
           '402A4A6A')
    c.y_grid(fmt=lambda v: '%d°' % round(v))
    rec_hi = rec_lo = 0
    for k, (d, hi, lo) in enumerate(rows):
        n = norm[k]
        if n is None:
            continue
        mean = (hi + lo) / 2.0 - (n['hi'] + n['lo']) / 2.0
        color = RED if mean > 1 else BLUE if mean < -1 else 'FFB0BEC5'
        x = c.X(k)
        c.canvas.fill_rect(x - 1.6, c.Y(u.t(hi)), x + 1.6, c.Y(u.t(lo)), color)
    for k, (d, hi, lo) in enumerate(rows):
        r = recs[k]
        if r and hi >= r['hi'][0] - 0.05:
            c.dot(k, u.t(hi) + (vmax - vmin) * 0.015, 'FFFFEB3B', 6)
            rec_hi += 1
        if r and lo <= r['lo'][0] + 0.05:
            c.dot(k, u.t(lo) - (vmax - vmin) * 0.015, 'FFE1F5FE', 6)
            rec_lo += 1
    ticks = []
    for k, (d, _h, _l) in enumerate(rows):
        if d.endswith('-01'):
            ticks.append((k, MONTHS[int(d[5:7]) - 1] + (' %s' % d[:4] if d[5:7] == '01' else '')))
    c.x_ticks(ticks, tall=True, color='14FFFFFF')
    place_chart(lay, ctx, 'year', c, MARGIN, TOP)
    ly = TOP + ch + 14
    items = [(RED, 'Warmer than normal'), (BLUE, 'Colder than normal'), ('FF2A4A6A', 'Normal range'),
             ('FFFFEB3B', 'Record high (%d)' % rec_hi), ('FFE1F5FE', 'Record low (%d)' % rec_lo)]
    x = MARGIN + 80
    for color, text in items:
        lay.rect(x, ly + 12, 28, 12, color)
        lay.label(x + 40, ly, 400, 34, text, 'xs', color=SOFT)
        x += 340
    return lay
