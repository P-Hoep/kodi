"""Scene 13: sun and moon. Everything is computed locally."""

import math

from .. import astro, charts
from ..layout import DIM, SOFT, WARM, WHITE
from .common import MARGIN, TOP, header


def _hm(seconds):
    seconds = int(round(seconds))
    return '%d h %02d min' % (seconds // 3600, (seconds % 3600) // 60)


def _delta(seconds):
    sign = '+' if seconds >= 0 else '−'
    seconds = abs(int(round(seconds)))
    if seconds >= 60:
        return '%s%d min %02d s' % (sign, seconds // 60, seconds % 60)
    return '%s%d s' % (sign, seconds)


def build(ctx):
    lay = header('Sun and moon', '%s · %s' % (ctx.place, ctx.date_text(ctx.now)))
    lat, lon, off = ctx.lat, ctx.lon, ctx.offset
    sun = astro.sun_day(ctx.now, lat, lon, off)
    yesterday = astro.sun_day(ctx.now - 86400, lat, lon, off)
    # Day-length arc: the sun's path from sunrise to sunset, with where it is now.
    aw, ah = 960, 560
    c = charts.Chart(aw, ah, (0, 1), (0, 1), pad=(0, 0, 0, 0))
    cx, cy, r = aw / 2.0, ah - 90, 380
    c.canvas.fill_rect(30, cy, aw - 30, cy + 2, '60FFFFFF')
    c.canvas.arc(cx, cy, r, 180, 0, '50FFE082', 4)
    if sun['sunrise'] and sun['sunset']:
        length = sun['sunset'] - sun['sunrise']
        frac = (ctx.now - sun['sunrise']) / length if length else 0
        if 0 <= frac <= 1:
            c.canvas.arc(cx, cy, r, 180, 180 - 180 * frac, 'FFFFD54F', 8)
            a = math.radians(180 - 180 * frac)
            c.canvas.disk(cx + r * math.cos(a), cy - r * math.sin(a), 34, 'FFFFD54F')
            c.canvas.disk(cx + r * math.cos(a), cy - r * math.sin(a), 60, '30FFD54F')
        c.label(cx - r, cy + 14, ctx.clock(sun['sunrise']), 'center', 'md', WHITE)
        c.label(cx + r, cy + 14, ctx.clock(sun['sunset']), 'center', 'md', WHITE)
        c.label(cx - r, cy + 58, 'Sunrise', 'center', 'xs', DIM)
        c.label(cx + r, cy + 58, 'Sunset', 'center', 'xs', DIM)
    from .common import place_chart
    place_chart(lay, ctx, 'sunarc', c, MARGIN - 20, TOP + 10)
    lx = MARGIN + 210
    lay.label(lx, TOP + 250, 560, 40, 'DAY LENGTH', 'xs', 'center', DIM)
    lay.label(lx, TOP + 284, 560, 70, _hm(sun['day_length']), 'xl', 'center', WHITE)
    change = sun['day_length'] - yesterday['day_length']
    lay.label(lx, TOP + 360, 560, 44, '%s vs yesterday' % _delta(change), 'sm', 'center',
              'FF69F0AE' if change >= 0 else 'FFFF8A65')
    # Sun details.
    y = TOP + 640
    rows = [('Solar noon', ctx.clock(sun['noon'])),
            ('Golden hour', '%s – %s' % (ctx.clock(sun['golden_evening'][0]), ctx.clock(sun['golden_evening'][1]))
             if sun['golden_evening'] else '--'),
            ('Morning golden hour', '%s – %s' % (ctx.clock(sun['golden_morning'][0]),
                                                 ctx.clock(sun['golden_morning'][1])) if sun['golden_morning'] else '--'),
            ('First light / last light', '%s / %s' % (ctx.clock(sun['dawn']), ctx.clock(sun['dusk'])))]
    for k, (cap, value) in enumerate(rows):
        lay.label(MARGIN, y + k * 52, 420, 44, cap, 'sm', color=SOFT)
        lay.label(MARGIN + 430, y + k * 52, 500, 44, value, 'sm', color=WARM if 'Golden' in cap else WHITE)
    # Moon.
    mx = 1120
    phase = astro.moon_phase(ctx.now)
    lay.image(mx, TOP + 20, 300, 300, 'moon/moon_%02d.png' % phase['frame'])
    lay.label(mx + 330, TOP + 66, 600, 60, phase['name'], 'lg', color=WHITE)
    lay.label(mx + 340, TOP + 130, 560, 44, '%d%% illuminated' % round(phase['illumination'] * 100), 'md',
              color=SOFT)
    lay.label(mx + 340, TOP + 180, 560, 44, 'Moon age %.1f days' % phase['age'], 'sm', color=DIM)
    moon = astro.moon_day(ctx.now, lat, lon, off)
    rows = [('Moonrise', ', '.join(ctx.clock(t) for t in moon['rise']) or 'none today'),
            ('Moonset', ', '.join(ctx.clock(t) for t in moon['set']) or 'none today')]
    nfull = astro.next_phase(ctx.now, 180)
    nnew = astro.next_phase(ctx.now, 0)
    for label, t in sorted((('Full moon', nfull), ('New moon', nnew)), key=lambda e: e[1] or 0):
        if t:
            days = (t - ctx.now) / 86400.0
            rows.append(('Next %s' % label.lower(), '%s  ·  in %d day%s' % (ctx.date_text(t), round(days),
                                                                         '' if round(days) == 1 else 's')))
    for k, (cap, value) in enumerate(rows):
        lay.label(mx, TOP + 380 + k * 62, 300, 50, cap, 'md', color=SOFT)
        lay.label(mx + 300, TOP + 380 + k * 62, 520, 50, value, 'md', color=WHITE)
    return lay
