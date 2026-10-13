"""Scenes 14 and 15: air quality and pollen; marine and tides."""

import math

from .. import charts
from ..layout import DIM, SOFT, WHITE
from .common import BOTTOM, MARGIN, TOP, W, header, no_data, place_chart

AQI = [(50, 'Good', 'FF00E400'), (100, 'Moderate', 'FFFFFF00'), (150, 'Unhealthy for sensitive groups', 'FFFF7E00'),
       (200, 'Unhealthy', 'FFFF0000'), (300, 'Very unhealthy', 'FF8F3F97'), (500, 'Hazardous', 'FF7E0023')]
POLLUTANTS = [('us_aqi_pm2_5', 'PM2.5'), ('us_aqi_pm10', 'PM10'), ('us_aqi_ozone', 'Ozone'),
              ('us_aqi_nitrogen_dioxide', 'NO2'), ('us_aqi_sulphur_dioxide', 'SO2'),
              ('us_aqi_carbon_monoxide', 'CO')]
POLLEN = [('alder_pollen', 'Alder'), ('birch_pollen', 'Birch'), ('grass_pollen', 'Grass'),
          ('mugwort_pollen', 'Mugwort'), ('olive_pollen', 'Olive'), ('ragweed_pollen', 'Ragweed')]


def category(aqi):
    for limit, name, color in AQI:
        if aqi <= limit:
            return name, color
    return AQI[-1][1], AQI[-1][2]


def pollen_level(grains):
    for limit, word in ((1, 'None'), (20, 'Low'), (100, 'Moderate'), (500, 'High')):
        if grains < limit:
            return word
    return 'Very high'


def air(ctx):
    lay = header('Air quality', ctx.place)
    data = ctx.hub.get('air') if ctx.hub else None
    cur = (data or {}).get('current') or {}
    aqi = cur.get('us_aqi')
    if aqi is None:
        return no_data(lay)
    name, color = category(aqi)
    # The dial: a 240° arc in category colours with a marker at the current value.
    size = 620
    c = charts.Chart(size, size - 60, (0, 1), (0, 1), pad=(0, 0, 0, 0))
    cx, cy, r = size / 2.0, size / 2.0, 250
    start, sweep = 210.0, -240.0
    prev = 0
    for limit, _n, col in AQI:
        a0 = start + sweep * prev / 300.0
        a1 = start + sweep * min(limit, 300) / 300.0
        c.canvas.arc(cx, cy, r, a0, a1 + 0.8, col.replace('FF', 'C0', 1), 34)
        prev = min(limit, 300)
        if limit >= 300:
            break
    a = math.radians(start + sweep * min(aqi, 300) / 300.0)
    c.canvas.disk(cx + r * math.cos(a), cy - r * math.sin(a), 30, 'FFFFFFFF')
    c.canvas.disk(cx + r * math.cos(a), cy - r * math.sin(a), 20, color)
    place_chart(lay, ctx, 'aqi_dial', c, MARGIN, TOP)
    lay.big('%d' % aqi, MARGIN + size // 2, TOP + 180, 190, 'center', WHITE, 'medium')
    lay.label(MARGIN, TOP + 380, size, 40, 'US AQI', 'sm', 'center', DIM)
    lay.label(MARGIN + size + 60, TOP + 20, 1000, 70, name, 'xl', color=color)
    subs = [(cur.get(k), label) for k, label in POLLUTANTS if cur.get(k) is not None]
    if subs:
        top = max(subs)
        lay.label(MARGIN + size + 60, TOP + 100, 1000, 44, 'Main pollutant: %s' % top[1], 'md', color=SOFT)
    y = TOP + 180
    for k, (value, label) in enumerate(sorted(subs, reverse=True)[:5]):
        lay.label(MARGIN + size + 60, y + k * 56, 200, 44, label, 'sm', color=SOFT)
        lay.image(MARGIN + size + 260, y + k * 56 + 14, 560, 18, 'pill.png', '30FFFFFF')
        lay.image(MARGIN + size + 260, y + k * 56 + 14, max(18, int(560 * min(value, 300) / 300.0)), 18,
                  'pill.png', category(value)[1])
        lay.label(MARGIN + size + 840, y + k * 56, 200, 44, '%d' % value, 'sm', color=WHITE)
    # Pollen where it's modelled (Europe); elsewhere say so.
    py = BOTTOM - 230
    pollen = [(label, cur.get(k)) for k, label in POLLEN if cur.get(k) is not None]
    lay.label(MARGIN, py, 800, 40, 'POLLEN', 'sm', color=DIM)
    if not pollen:
        lay.label(MARGIN, py + 50, 1600, 44, "Pollen isn't modelled for this area (Open-Meteo covers Europe).",
                  'md', color=SOFT)
    else:
        cw = (W - 2 * MARGIN) // max(1, len(pollen))
        for k, (label, grains) in enumerate(pollen):
            x = MARGIN + k * cw
            lay.card(x, py + 50, cw - 20, 150)
            lay.label(x, py + 66, cw - 20, 40, label, 'sm', 'center', SOFT)
            lay.label(x, py + 110, cw - 20, 50, pollen_level(grains), 'lg', 'center', WHITE)
            lay.label(x, py + 160, cw - 20, 30, '%d grains/m³' % grains, 'xs', 'center', DIM)
    return lay


def marine(ctx):
    tides = ctx.hub.get('tides') if ctx.hub else None
    station = (tides or {}).get('name') or ''
    lay = header('Marine and tides', '%s · %s' % (ctx.place, station.title()) if station else ctx.place)
    if not tides or not tides.get('curve'):
        return no_data(lay)
    u = ctx.u
    curve = tides['curve']
    day0 = math.floor((ctx.now + ctx.offset) / 86400.0) * 86400 - ctx.offset
    pts = [(t, v) for t, v in curve if day0 - 1800 <= t <= day0 + 86400 + 1800]
    if len(pts) < 4:
        return no_data(lay)
    metres = u.distance == 'km'
    conv = (lambda m: m) if metres else (lambda m: m * 3.28084)
    unit = 'm' if metres else 'ft'
    vals = [conv(v) for _t, v in pts]
    vmin, vmax = min(vals), max(vals)
    pad = max(0.2, (vmax - vmin) * 0.2)
    cw, ch = W - 2 * MARGIN, 520
    c = charts.Chart(cw, ch, (day0, day0 + 86400), (vmin - pad, vmax + pad * 1.6), pad=(90, 20, 20, 50))
    c.y_grid(fmt=lambda v: '%.1f %s' % (v, unit) if abs(vmax - vmin) < 4 else '%d %s' % (round(v), unit))
    xs = [t for t, _v in pts]
    c.band(xs, [vmin - pad] * len(xs), vals, '5029B6F6')
    c.line(xs, vals, 'FF4FC3F7', 5)
    if day0 <= ctx.now <= day0 + 86400:
        c.vline(ctx.now, 'C0FFFFFF', 3)
    for t, v, kind in tides.get('hilo') or []:
        if day0 <= t <= day0 + 86400:
            c.dot(t, conv(v), 'FFFFFFFF', 9)
            c.label(c.X(t), c.Y(conv(v)) - (64 if kind == 'H' else -16), '%s %s' % (
                'High' if kind == 'H' else 'Low', ctx.clock(t)), 'center', 'sm', WHITE)
    c.x_ticks([(day0 + h * 3600, ctx.hour(day0 + h * 3600)) for h in range(0, 25, 3)])
    place_chart(lay, ctx, 'tides', c, MARGIN, TOP)
    # Conditions row.
    sea = ((ctx.hub.get('marine') or {}).get('current') or {}) if ctx.hub else {}
    water = (tides.get('water') or {}).get('now')
    if water is None:
        water = sea.get('sea_surface_temperature')
    row = []
    if sea.get('wave_height') is not None:
        row.append(('Waves', '%.1f %s' % (conv(sea['wave_height']), unit)))
    if sea.get('wave_period') is not None:
        row.append(('Wave period', '%d s' % round(sea['wave_period'])))
    if sea.get('swell_wave_height') is not None:
        row.append(('Swell', '%.1f %s' % (conv(sea['swell_wave_height']), unit)))
    if water is not None:
        row.append(('Water temperature', u.temp(water, True)))
    nxt = [h for h in tides.get('hilo') or [] if h[0] > ctx.now][:2]
    for t, v, kind in nxt:
        row.append(('Next %s tide' % ('high' if kind == 'H' else 'low'), '%s  ·  %.1f %s' % (ctx.clock(t), conv(v),
                                                                                          unit)))
    y = TOP + ch + 50
    cw2 = (W - 2 * MARGIN) // max(1, len(row))
    for k, (cap, value) in enumerate(row):
        x = MARGIN + k * cw2
        lay.card(x, y, cw2 - 20, 170)
        lay.label(x + 28, y + 24, cw2 - 60, 34, cap.upper(), 'xs', color=DIM)
        lay.label(x + 28, y + 64, cw2 - 60, 60, value, 'lg', color=WHITE)
    lay.label(MARGIN, BOTTOM + 2, 1400, 30, 'Tide predictions: NOAA CO-OPS station %s (%s away)'
              % (tides.get('station'), u.distance_text(tides.get('distance_km') or 0)), 'xs', color='80FFFFFF')
    return lay
