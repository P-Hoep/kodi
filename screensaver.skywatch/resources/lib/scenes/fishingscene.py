"""Scene 12: the fishing forecast, with the score's parts shown so it never feels like a black box."""

from .. import astro, charts, config, fishing
from ..layout import DIM, SOFT, WHITE
from .common import MARGIN, TOP, W, header, no_data, place_chart

SCORE_COLORS = [(80, 'FF69F0AE'), (65, 'FFB2FF59'), (45, 'FFFFD740'), (0, 'FFFF8A65')]


def score_color(v):
    for limit, color in SCORE_COLORS:
        if (v or 0) >= limit:
            return color
    return SOFT


def water_change(series, hours=60):
    """°C change over roughly the last 2.5 days of an hourly [(t, °C)] series."""
    if not series or len(series) < 6:
        return None
    end_t, end_v = series[-1]
    start = [v for t, v in series if t <= end_t - hours * 3600]
    base = start[-1] if start else series[0][1]
    return end_v - base


def build(ctx):
    s = ctx.s
    hub = ctx.hub
    spot_lat, spot_lon = hub.fish_spot() if hub else (ctx.lat, ctx.lon)
    fc = (hub.get('fish_forecast') if hub and (spot_lat, spot_lon) != (ctx.lat, ctx.lon) else None) or ctx.fc
    name = s.get('fish_name') or ''
    gauge = hub.get('gauge') if hub and s.get('fish_spot') == 2 else None
    tides = hub.get('tides') if hub else None
    if not name and s.get('fish_spot') in (2, 3):
        name = ((gauge or {}).get('name') or (tides or {}).get('name') or '').title()
    species = config.SPECIES[s.get('species', 0)]
    lay = header('Fishing forecast', '%s · %s' % (name or ctx.place, species))
    if not fc:
        return no_data(lay)
    series = (gauge or {}).get('water_series') or ((tides or {}).get('water') or {}).get('series')
    change = water_change(series)
    days = fishing.forecast_days(fc, spot_lat, spot_lon, s, change, 4, species, ctx.now)
    today = days[0]
    u = ctx.u
    # Today's score, big.
    x, y = MARGIN, TOP
    lay.card(x, y, 520, 420, '70183050')
    lay.label(x + 36, y + 24, 460, 40, 'TODAY', 'sm', color=DIM)
    if today['score'] is not None:
        lay.big('%d' % today['score'], x + 36, y + 70, 230, color=score_color(today['score']), weight='medium')
        lay.label(x + 40, y + 310, 460, 60, fishing.rating(today['score']), 'xl', color=score_color(today['score']))
    # Next three days.
    for k, d in enumerate(days[1:]):
        cx = x + 560 + k * 250
        lay.card(cx, y, 230, 200)
        lay.label(cx, y + 20, 230, 40, ctx.day_name(d['start'] + 43200), 'md', 'center', WHITE)
        if d['score'] is not None:
            lay.label(cx, y + 74, 230, 70, '%d' % d['score'], 'xl', 'center', score_color(d['score']))
            lay.label(cx, y + 146, 230, 34, fishing.rating(d['score']), 'xs', 'center', SOFT)
    # Factor breakdown: bar per factor, the points it contributes.
    bx, by = x + 560, y + 230
    lay.label(bx, by, 760, 34, "WHAT'S IN TODAY'S SCORE", 'xs', color=DIM)
    w = fishing.weights(s, species)
    total_w = sum(w[f] for f in fishing.FACTORS if today['factors'].get(f) is not None) or 1
    for k, f in enumerate(fishing.FACTORS):
        ry = by + 40 + k * 46
        lay.label(bx, ry, 200, 40, fishing.NAMES[f], 'sm', color=SOFT)
        val = today['factors'].get(f)
        lay.image(bx + 210, ry + 12, 420, 18, 'pill.png', '30FFFFFF')
        if val is None:
            lay.label(bx + 650, ry, 300, 40, 'no data', 'xs', color=DIM)
            continue
        lay.image(bx + 210, ry + 12, max(18, int(420 * val)), 18, 'pill.png', score_color(val * 100))
        lay.label(bx + 650, ry, 220, 40, '+%d of %d' % (round(today['parts'].get(f, 0)),
                                                        round(100.0 * w[f] / total_w)), 'sm', color=WHITE)
    # Solunar strip for today.
    periods, sun = today['periods'], today['sun']
    start = today['start']
    strip = charts.Chart(W - 2 * MARGIN, 150, (start, start + 86400), (0, 1), pad=(20, 46, 20, 40))
    if sun['sunrise'] and sun['sunset']:
        strip.shade(start, sun['sunrise'], '50000814')
        strip.shade(sun['sunset'], start + 86400, '50000814')
        strip.shade(sun['sunrise'], sun['sunset'], '18FFE082')
    for a, b, _c in periods['minor']:
        strip.canvas.fill_rounded(strip.X(a), strip.Y(0.55), strip.X(b), strip.Y(0.0), 8, 'B04FC3F7')
    for a, b, _c in periods['major']:
        strip.canvas.fill_rounded(strip.X(a), strip.Y(1.0), strip.X(b), strip.Y(0.0), 8, 'E069F0AE')
    if start <= ctx.now < start + 86400:
        strip.vline(ctx.now, 'FFFFFFFF', 3)
    ticks = [(start + h * 3600, ctx.hour(start + h * 3600)) for h in range(0, 25, 3)]
    strip.x_ticks(ticks)
    strip.label(strip.left, 4, 'Solunar periods today:  major (2 h, moon overhead/underfoot)  ·  minor (1 h, '
                'moonrise/moonset)', 'left', 'xs', SOFT)
    sy = by + 40 + 6 * 46 + 24
    place_chart(lay, ctx, 'fishing_strip', strip, MARGIN, sy)
    # Conditions row.
    inp = today['inputs']
    phase = astro.moon_phase(start + 43200)
    lay_row = [
        ('Moon', '%s, %d%%' % (phase['name'], round(phase['illumination'] * 100))),
        ('Pressure', ('%s over 3 h' % ('%+.2f %s' % (u.p(inp['trend']), u.pressure) if u.pressure == 'inHg'
                                     else '%+d %s' % (round(u.p(inp['trend'])), u.pressure)))
         if inp['trend'] is not None else '--'),
        ('Wind', u.wind_text(inp['wind'])),
        ('Cloud', '%d%%' % round(inp['cloud']) if inp['cloud'] is not None else '--'),
    ]
    water = None
    if gauge and gauge.get('water_c') is not None:
        water = gauge['water_c']
    elif tides and (tides.get('water') or {}).get('now') is not None:
        water = tides['water']['now']
    if water is not None:
        lay_row.append(('Water', '%s%s' % (u.temp(water), (' (%s)' % u.temp_delta(change)) if change is not None
                                          else '')))
    if gauge and gauge.get('flow_cfs') is not None:
        lay_row.append(('River flow', '{:,} ft³/s'.format(int(gauge['flow_cfs']))))
    elif tides and tides.get('hilo'):
        nxt = [h for h in tides['hilo'] if h[0] > ctx.now][:1]
        if nxt:
            lay_row.append(('Next tide', '%s %s' % ('High' if nxt[0][2] == 'H' else 'Low', ctx.clock(nxt[0][0]))))
    ry = sy + 160
    cw = (W - 2 * MARGIN) // len(lay_row)
    for k, (cap, value) in enumerate(lay_row):
        lay.label(MARGIN + k * cw, ry, cw - 20, 30, cap.upper(), 'xs', color=DIM)
        lay.label(MARGIN + k * cw, ry + 30, cw - 20, 44, value, 'sm', color=WHITE)
    return lay
