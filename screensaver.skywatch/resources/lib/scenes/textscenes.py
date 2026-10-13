"""Scenes 16 and 17 plus the alert scene: forecast discussion, ambient clock, active warning."""

import time

from ..layout import DIM, SOFT, WHITE, Layout
from .common import BOTTOM, MARGIN, TOP, W, H, header, icon, no_data, weather_text


def discussion(ctx):
    afd = ctx.hub.get('afd') if ctx.hub else None
    office = (afd or {}).get('office') or ''
    issued = (afd or {}).get('issued')
    sub = 'NWS %s · issued %s' % (office, ctx.clock(issued)) if issued else 'National Weather Service'
    lay = header('Forecast discussion', sub)
    if not afd or not afd.get('points'):
        return no_data(lay)
    text = '\n\n'.join('•  ' + p for p in afd['points'])
    lay.card(MARGIN - 20, TOP - 10, W - 2 * MARGIN + 40, BOTTOM - TOP + 10, '50101C2C')
    lay.scroll(MARGIN + 20, TOP + 20, W - 2 * MARGIN - 40, BOTTOM - TOP - 50, text)
    return lay


def alert(ctx, alerts):
    lay = Layout('Weather alert', 'bg_night.jpg')
    if not alerts:
        return no_data(lay)
    a = alerts[0]
    lay.rect(0, 0, W, H, 'FF3A0A0A')
    lay.rect(0, 0, W, 16, a['color'])
    lay.image(MARGIN, 80, 150, 150, 'icons/tornado.png' if 'Tornado' in a['event'] else 'icons/thunderstorms-rain.png')
    lay.label(MARGIN + 190, 86, 1500, 80, a['event'].upper(), 'xl', color=a['color'])
    until = ('until %s' % ctx.clock(a['ends'])) if a.get('ends') else ''
    lay.label(MARGIN + 192, 168, 1500, 50, until, 'md', color=WHITE)
    lay.label(MARGIN, 260, W - 2 * MARGIN, 44, (a.get('area') or '')[:150], 'sm', color=SOFT)
    body = a.get('description') or a.get('headline') or ''
    if a.get('instruction'):
        body += '\n\n' + a['instruction']
    lay.scroll(MARGIN, 330, W - 2 * MARGIN, BOTTOM - 340, body.replace('\n\n', ' ').replace('\n', ' ')
               .replace(' ', '\n\n'))
    if len(alerts) > 1:
        lay.label(MARGIN, BOTTOM + 2, 1400, 30, 'Also in effect: ' + ', '.join(x['event'] for x in alerts[1:4]),
                  'xs', color=SOFT)
    return lay


def ambient(ctx):
    lay = Layout('Ambient clock', 'bg.jpg')
    clock = ctx.u.clock(ctx.now)
    am = ''
    if clock.endswith(('AM', 'PM')):
        clock, am = clock[:-3], clock[-2:]
    lay.big(clock + (' ' + am if am else ''), W // 2, 250, 340, 'center', WHITE, 'light')
    tm = time.localtime(ctx.now)
    lay.label(0, 620, W, 60, time.strftime('%A, %B ', tm) + str(tm.tm_mday), 'xl', 'center', DIM)
    fc = ctx.fc
    if fc and fc.get('current'):
        c = fc['current']
        lay.image(MARGIN, BOTTOM - 210, 200, 200, icon(c.get('weather_code'), bool(c.get('is_day', 1))))
        lay.label(MARGIN + 220, BOTTOM - 180, 600, 70, ctx.u.temp(c.get('temperature_2m')), 'xl', color=WHITE)
        lay.label(MARGIN + 220, BOTTOM - 100, 700, 50, weather_text(c.get('weather_code')), 'md', color=DIM)
    if ctx.thumb:
        base, radar_img = ctx.thumb
        x, y, w, h = W - MARGIN - 480, BOTTOM - 270, 480, 270
        lay.rect(x - 4, y - 4, w + 8, h + 8, '40FFFFFF')
        lay.image(x, y, w, h, base)
        if radar_img:
            lay.image(x, y, w, h, radar_img, 'C0FFFFFF')
        lay.image(x + w // 2 - 12, y + h // 2 - 12, 24, 24, 'pin.png', 'FFFFFFFF')
    return lay
