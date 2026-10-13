"""Draw each screensaver's loading splash as SVG, then render it to PNG with headless Chrome.

  python3 tools/make_splash.py            # all add-ons
  python3 tools/make_splash.py godseye    # names containing 'godseye'

Writes tools/splash/<addon>.svg (the source, kept for editing) and
<addon>/resources/media/splash.png (960x760, transparent; resources/lib/splash.py centres it
on black) plus splash_dots.png, the white loading dots that splash.py tints and pulses.
Needs Pillow (to read God's World's land map) and Google Chrome; fonts are macOS's Avenir
Next and STIX Two, baked into the PNG.
"""

import math
import os
import random
import subprocess
import sys
import tempfile

from PIL import Image

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.normpath(os.path.join(HERE, '..'))
OUT_SVG = os.path.join(HERE, 'splash')
CHROME = '/Applications/Google Chrome.app/Contents/MacOS/Google Chrome'
W, H = 960, 760
CX, CY = 480, 300          # centre of the art; the title sits below it
TITLE_Y, TAG_Y = 636, 712

TITLE_FONT = "font-family=\"'Avenir Next', 'Helvetica Neue', sans-serif\""
MATH_FONT = "font-family=\"'STIX Two Text', 'STIXGeneral', 'Times New Roman', serif\""


def svg(body, defs=''):
    return ('<svg xmlns="http://www.w3.org/2000/svg" width="%d" height="%d" viewBox="0 0 %d %d">\n'
            '<defs>\n'
            '<filter id="glow" x="-50%%" y="-50%%" width="200%%" height="200%%">'
            '<feGaussianBlur stdDeviation="6" result="b"/>'
            '<feMerge><feMergeNode in="b"/><feMergeNode in="SourceGraphic"/></feMerge></filter>\n'
            '<filter id="soft" x="-50%%" y="-50%%" width="200%%" height="200%%">'
            '<feGaussianBlur stdDeviation="18"/></filter>\n'
            '%s\n</defs>\n%s\n</svg>\n' % (W, H, W, H, defs, body))


def title(text, tagline, accent):
    return ('<text x="%d" y="%d" text-anchor="middle" %s font-weight="600" font-size="50" '
            'letter-spacing="12" fill="#FFFFFF">%s</text>\n'
            '<rect x="%d" y="%d" width="64" height="3" rx="1.5" fill="%s"/>\n'
            '<text x="%d" y="%d" text-anchor="middle" %s font-weight="400" font-size="24" '
            'letter-spacing="4" fill="#FFFFFF" fill-opacity="0.55">%s</text>'
            % (W // 2 + 6, TITLE_Y, TITLE_FONT, text, W // 2 - 32, TITLE_Y + 28, accent,
               W // 2 + 2, TAG_Y, TITLE_FONT, tagline))


def polar(r, deg, cx=CX, cy=CY):
    a = math.radians(deg - 90)   # 0 degrees = up, clockwise
    return cx + r * math.cos(a), cy + r * math.sin(a)


# ---------------------------------------------------------------- God's Eye Map

def godseye():
    mint, sky, amber = '#69F0AE', '#4FC3F7', '#FFD54F'
    r_iris = 120
    parts = []
    # HUD ring with degree ticks behind the eye.
    parts.append('<circle cx="%d" cy="%d" r="250" fill="none" stroke="%s" stroke-opacity="0.18" '
                 'stroke-width="2"/>' % (CX, CY, mint))
    for deg in range(0, 360, 5):
        long_tick = deg % 45 == 0
        x1, y1 = polar(250, deg)
        x2, y2 = polar(250 - (18 if long_tick else 8), deg)
        parts.append('<line x1="%.1f" y1="%.1f" x2="%.1f" y2="%.1f" stroke="%s" stroke-opacity="%.2f" '
                     'stroke-width="%d"/>' % (x1, y1, x2, y2, mint, 0.6 if long_tick else 0.25,
                                               3 if long_tick else 2))
    for deg, label in ((0, 'N'),):
        x, y = polar(282, deg)
        parts.append('<text x="%.1f" y="%.1f" text-anchor="middle" %s font-size="22" font-weight="600" '
                     'fill="%s" fill-opacity="0.7">%s</text>' % (x, y + 8, TITLE_FONT, mint, label))
    # The eye: a soft glow, the almond and its fill.
    eye = 'M%d,%d C%d,%d %d,%d %d,%d C%d,%d %d,%d %d,%d Z' % (
        CX - 300, CY, CX - 170, CY - 190, CX + 170, CY - 190, CX + 300, CY,
        CX + 170, CY + 190, CX - 170, CY + 190, CX - 300, CY)
    parts.append('<path d="%s" fill="%s" fill-opacity="0.25" filter="url(#soft)"/>' % (eye, mint))
    parts.append('<path d="%s" fill="url(#eyefill)" stroke="%s" stroke-width="6" '
                 'stroke-linejoin="round"/>' % (eye, mint))
    # Iris: a little map seen from above, clipped to a circle.
    m = ['<circle cx="%d" cy="%d" r="%d" fill="url(#iris)"/>' % (CX, CY, r_iris)]
    for k in range(-6, 7):
        off = k * 22
        m.append('<line x1="%d" y1="%d" x2="%d" y2="%d" stroke="%s" stroke-opacity="0.16" stroke-width="2"/>'
                 % (CX - 130, CY + off, CX + 130, CY + off + 6, mint))
        m.append('<line x1="%d" y1="%d" x2="%d" y2="%d" stroke="%s" stroke-opacity="0.16" stroke-width="2"/>'
                 % (CX + off, CY - 130, CX + off - 6, CY + 130, mint))
    m.append('<path d="M%d,%d C%d,%d %d,%d %d,%d" fill="none" stroke="%s" stroke-opacity="0.55" '
             'stroke-width="9" stroke-linecap="round"/>' % (CX - 140, CY + 40, CX - 60, CY + 10,
                                                            CX - 20, CY + 90, CX + 140, CY + 60, sky))
    m.append('<path d="M%d,%d L%d,%d" stroke="%s" stroke-opacity="0.75" stroke-width="5"/>'
             % (CX - 140, CY - 58, CX + 140, CY - 40, mint))
    m.append('<path d="M%d,%d L%d,%d" stroke="%s" stroke-opacity="0.75" stroke-width="5"/>'
             % (CX + 38, CY - 140, CX + 52, CY + 140, mint))
    # Radar sweep: a wedge fading towards its trailing edge.
    x1, y1 = polar(r_iris, 20)
    x2, y2 = polar(r_iris, 80)
    m.append('<path d="M%d,%d L%.1f,%.1f A%d,%d 0 0 1 %.1f,%.1f Z" fill="url(#sweep)"/>'
             % (CX, CY, x1, y1, r_iris, r_iris, x2, y2))
    m.append('<line x1="%d" y1="%d" x2="%.1f" y2="%.1f" stroke="%s" stroke-width="3"/>' % (CX, CY, x2, y2, mint))
    for r in (40, 80):
        m.append('<circle cx="%d" cy="%d" r="%d" fill="none" stroke="%s" stroke-opacity="0.35" '
                 'stroke-width="2" stroke-dasharray="6 6"/>' % (CX, CY, r, mint))
    # A plane crossing the iris.
    m.append('<g transform="translate(%d,%d) rotate(45) scale(1.15)" fill="#FFFFFF" filter="url(#glow)">'
             '<path d="M0,-22 C3,-22 4,-18 4,-12 L4,-4 L22,6 L22,11 L4,5 L4,14 L10,19 L10,23 L0,20 '
             'L-10,23 L-10,19 L-4,14 L-4,5 L-22,11 L-22,6 L-4,-4 L-4,-12 C-4,-18 -3,-22 0,-22 Z"/></g>'
             % (CX - 58, CY - 52))
    parts.append('<g clip-path="url(#irisclip)">%s</g>' % '\n'.join(m))
    parts.append('<circle cx="%d" cy="%d" r="%d" fill="none" stroke="%s" stroke-width="4"/>'
                 % (CX, CY, r_iris, mint))
    # Crosshair ticks around the iris.
    for deg in (0, 90, 180, 270):
        xa, ya = polar(r_iris + 10, deg)
        xb, yb = polar(r_iris + 34, deg)
        parts.append('<line x1="%.1f" y1="%.1f" x2="%.1f" y2="%.1f" stroke="%s" stroke-width="4" '
                     'stroke-linecap="round"/>' % (xa, ya, xb, yb, mint))
    # Pupil: the home marker.
    parts.append('<circle cx="%d" cy="%d" r="26" fill="%s" fill-opacity="0.25" filter="url(#soft)"/>'
                 % (CX, CY, amber))
    parts.append('<path d="M%d,%d L%d,%d L%d,%d L%d,%d L%d,%d Z" fill="%s" stroke="#0B1118" '
                 'stroke-width="3" stroke-linejoin="round"/>'
                 % (CX, CY - 20, CX + 18, CY - 4, CX + 13, CY + 17, CX - 13, CY + 17, CX - 18, CY - 4, amber))
    parts.append('<rect x="%d" y="%d" width="8" height="11" fill="#0B1118"/>' % (CX - 4, CY + 6))
    parts.append(title("GOD'S EYE MAP", 'LIVE OVER HOME', mint))
    defs = ('<radialGradient id="eyefill" cx="50%%" cy="50%%" r="60%%">'
            '<stop offset="0" stop-color="#0E2A26"/><stop offset="1" stop-color="#020807"/></radialGradient>'
            '<radialGradient id="iris" cx="50%%" cy="50%%" r="50%%">'
            '<stop offset="0" stop-color="#123C36"/><stop offset="1" stop-color="#061614"/></radialGradient>'
            '<linearGradient id="sweep" x1="0" y1="0" x2="1" y2="1">'
            '<stop offset="0" stop-color="%s" stop-opacity="0.05"/>'
            '<stop offset="1" stop-color="%s" stop-opacity="0.45"/></linearGradient>'
            '<clipPath id="irisclip"><circle cx="%d" cy="%d" r="%d"/></clipPath>' % (mint, mint, CX, CY, r_iris))
    return svg('\n'.join(parts), defs), mint


# ---------------------------------------------------------------- God's World Map

def ortho(lat, lon, lat0, lon0):
    """Orthographic projection: (x, y, visible) on a unit disc, y down."""
    la, lo, la0 = math.radians(lat), math.radians(lon - lon0), math.radians(lat0)
    cosc = math.sin(la0) * math.sin(la) + math.cos(la0) * math.cos(la) * math.cos(lo)
    x = math.cos(la) * math.sin(lo)
    y = math.cos(la0) * math.sin(la) - math.sin(la0) * math.cos(la) * math.cos(lo)
    return x, -y, cosc > 0


def inverse_ortho(x, y, lat0, lon0):
    rho = math.hypot(x, y)
    if rho > 1:
        return None
    c = math.asin(rho)
    la0 = math.radians(lat0)
    y = -y
    if rho == 0:
        return lat0, lon0
    lat = math.asin(math.cos(c) * math.sin(la0) + y * math.sin(c) * math.cos(la0) / rho)
    lon = math.radians(lon0) + math.atan2(x * math.sin(c),
                                          rho * math.cos(la0) * math.cos(c) - y * math.sin(la0) * math.sin(c))
    return math.degrees(lat), (math.degrees(lon) + 540) % 360 - 180


def godsworld():
    sky, amber = '#4FC3F7', '#FFB74D'
    R = 215
    lat0, lon0 = 22, -38
    land = Image.open(os.path.join(REPO, 'screensaver.godsworld.map', 'resources', 'media', 'world',
                                   'landclass.png'))
    lw, lh = land.size
    px = land.load()
    parts = []
    # Orbit ring, back half (drawn before the globe so the globe hides it).
    orbit = 'transform="rotate(-18 %d %d)"' % (CX, CY)
    parts.append('<ellipse cx="%d" cy="%d" rx="300" ry="78" fill="none" stroke="%s" stroke-opacity="0.35" '
                 'stroke-width="3" %s/>' % (CX, CY, sky, orbit))
    parts.append('<circle cx="%d" cy="%d" r="%d" fill="%s" fill-opacity="0.45" filter="url(#soft)"/>'
                 % (CX, CY, R + 10, sky))
    parts.append('<circle cx="%d" cy="%d" r="%d" fill="url(#ocean)"/>' % (CX, CY, R))
    # Graticule every 30 degrees.
    g = []
    for lon in range(-180, 180, 30):
        pts = [ortho(lat, lon, lat0, lon0) for lat in range(-90, 91, 3)]
        g.append('<path d="%s"/>' % path_of(pts, R))
    for lat in range(-60, 61, 30):
        pts = [ortho(lat, lon, lat0, lon0) for lon in range(-180, 181, 3)]
        g.append('<path d="%s"/>' % path_of(pts, R))
    parts.append('<g fill="none" stroke="%s" stroke-opacity="0.22" stroke-width="1.5">%s</g>' % (sky, ''.join(g)))
    # Land as a dot matrix, sampled from the add-on's own land-cover map.
    dots = []
    step = 8.5
    n = int(R / step) + 1
    for j in range(-n, n + 1):
        for i in range(-n, n + 1):
            x, y = i * step + (step / 2 if j % 2 else 0), j * step * 0.866
            ll = inverse_ortho(x / R, y / R, lat0, lon0)
            if ll is None:
                continue
            lat, lon = ll
            cls = px[int((lon + 180) / 360 * (lw - 1)), int((90 - lat) / 180 * (lh - 1))]
            if cls <= 3:   # water classes
                continue
            mu = math.sqrt(max(0.0, 1 - (x * x + y * y) / (R * R)))   # 1 at the centre, 0 at the limb
            r = 1.2 + 2.2 * mu ** 0.5
            colour = '#E8F6FF' if cls in (4, 5) else '#9EDCFF'
            dots.append('<circle cx="%.1f" cy="%.1f" r="%.2f" fill="%s" fill-opacity="%.2f"/>'
                        % (CX + x, CY + y, r, colour, 0.35 + 0.6 * mu))
    parts.append('<g>%s</g>' % ''.join(dots))
    # Night side and a lit limb.
    parts.append('<circle cx="%d" cy="%d" r="%d" fill="url(#night)"/>' % (CX, CY, R))
    parts.append('<circle cx="%d" cy="%d" r="%d" fill="none" stroke="%s" stroke-opacity="0.8" '
                 'stroke-width="3"/>' % (CX, CY, R, sky))
    # Flights: great-circle arcs between cities on the near side.
    cities = {'nyc': (40.7, -74.0), 'lon': (51.5, -0.1), 'rio': (-22.9, -43.2), 'lag': (6.5, 3.4),
              'mad': (40.4, -3.7), 'mia': (25.8, -80.2), 'rey': (64.1, -21.9)}
    for a, b in (('nyc', 'lon'), ('mia', 'mad'), ('rio', 'lag'), ('nyc', 'rey')):
        pts = great_circle(cities[a], cities[b], 40)
        lifted = []
        for k, (lat, lon) in enumerate(pts):
            x, y, vis = ortho(lat, lon, lat0, lon0)
            h = 1 + 0.06 * math.sin(math.pi * k / (len(pts) - 1))   # arcs rise off the surface
            lifted.append((x * h, y * h, vis))
        parts.append('<path d="%s" fill="none" stroke="%s" stroke-width="2.5" stroke-dasharray="1 7" '
                     'stroke-linecap="round" stroke-opacity="0.95"/>' % (path_of(lifted, R), amber))
        x, y, _v = lifted[-1]
        parts.append('<circle cx="%.1f" cy="%.1f" r="4.5" fill="%s" filter="url(#glow)"/>'
                     % (CX + x * R, CY + y * R, amber))
        x, y, _v = lifted[0]
        parts.append('<circle cx="%.1f" cy="%.1f" r="3" fill="%s"/>' % (CX + x * R, CY + y * R, amber))
    # Orbit ring, front half, and a satellite on it.
    parts.append('<g clip-path="url(#front)"><ellipse cx="%d" cy="%d" rx="300" ry="78" fill="none" '
                 'stroke="%s" stroke-width="3" %s/></g>' % (CX, CY, sky, orbit))
    a = math.radians(62)
    sx, sy = 300 * math.cos(a), 78 * math.sin(a)
    t = math.radians(-18)
    sx, sy = CX + sx * math.cos(t) - sy * math.sin(t), CY + sx * math.sin(t) + sy * math.cos(t)
    parts.append('<g transform="translate(%.1f,%.1f) rotate(-18)" filter="url(#glow)">'
                 '<rect x="-20" y="-5" width="13" height="10" fill="%s"/><rect x="7" y="-5" width="13" '
                 'height="10" fill="%s"/><rect x="-6" y="-7" width="12" height="14" rx="2" fill="#FFFFFF"/></g>'
                 % (sx, sy, sky, sky))
    parts.append(title("GOD'S WORLD MAP", 'THE WHOLE PLANET, LIVE', sky))
    defs = ('<radialGradient id="ocean" cx="40%%" cy="35%%" r="75%%">'
            '<stop offset="0" stop-color="#123A63"/><stop offset="1" stop-color="#030A16"/></radialGradient>'
            '<linearGradient id="night" x1="0" y1="0" x2="1" y2="0.4">'
            '<stop offset="0.45" stop-color="#000000" stop-opacity="0"/>'
            '<stop offset="1" stop-color="#000000" stop-opacity="0.7"/></linearGradient>'
            # The front half of the orbit: everything below the globe's centre line (tilted), plus
            # anything outside the globe.
            '<clipPath id="front"><path fill-rule="evenodd" d="M0,0 H%d V%d H0 Z M%d,%d m-%d,0 a%d,%d 0 1,0 %d,0 '
            'a%d,%d 0 1,0 -%d,0 Z"/><path d="M0,%d L%d,%d L%d,%d L0,%d Z" transform="rotate(-18 %d %d)"/></clipPath>'
            % (W, H, CX, CY, R, R, R, 2 * R, R, R, 2 * R, CY, W, CY, W, H, H, CX, CY))
    return svg('\n'.join(parts), defs), sky


def great_circle(a, b, n):
    (la1, lo1), (la2, lo2) = [(math.radians(p[0]), math.radians(p[1])) for p in (a, b)]
    v1 = (math.cos(la1) * math.cos(lo1), math.cos(la1) * math.sin(lo1), math.sin(la1))
    v2 = (math.cos(la2) * math.cos(lo2), math.cos(la2) * math.sin(lo2), math.sin(la2))
    d = math.acos(sum(p * q for p, q in zip(v1, v2)))
    out = []
    for k in range(n + 1):
        t = k / n
        s1, s2 = math.sin((1 - t) * d) / math.sin(d), math.sin(t * d) / math.sin(d)
        x, y, z = [s1 * p + s2 * q for p, q in zip(v1, v2)]
        out.append((math.degrees(math.asin(z)), math.degrees(math.atan2(y, x))))
    return out


def path_of(pts, R):
    """SVG path data through the visible points (x, y, visible) of a unit-disc polyline."""
    d, pen = [], False
    for x, y, vis in pts:
        if not vis:
            pen = False
            continue
        d.append('%s%.1f,%.1f' % ('L' if pen else 'M', CX + x * R, CY + y * R))
        pen = True
    return ' '.join(d)


# ---------------------------------------------------------------- Math Clock

def mathclock():
    coral = '#FF8A65'
    R = 230
    parts = []
    # Faint graph paper with axes and a sine curve behind the face.
    grid = []
    for k in range(-10, 11):
        grid.append('<line x1="%d" y1="%d" x2="%d" y2="%d"/>' % (CX + k * 30, CY - 300, CX + k * 30, CY + 300))
        grid.append('<line x1="%d" y1="%d" x2="%d" y2="%d"/>' % (CX - 300, CY + k * 30, CX + 300, CY + k * 30))
    parts.append('<g stroke="#FFFFFF" stroke-opacity="0.09" stroke-width="1" mask="url(#paper)">%s</g>'
                 % ''.join(grid))
    # Floating symbols.
    for sym, x, y, size, op in (('∫', 150, 140, 88, 0.22), ('∑', 790, 120, 70, 0.2), ('∞', 800, 470, 64, 0.2),
                                ('∂', 160, 480, 64, 0.2), ('√', 110, 320, 56, 0.14), ('Δ', 850, 300, 50, 0.14)):
        parts.append('<text x="%d" y="%d" text-anchor="middle" %s font-size="%d" font-style="italic" '
                     'fill="#FFFFFF" fill-opacity="%.2f">%s</text>' % (x, y, MATH_FONT, size, op, sym))
    # The face.
    parts.append('<circle cx="%d" cy="%d" r="%d" fill="url(#face)" stroke="#FFFFFF" stroke-width="5"/>'
                 % (CX, CY, R))
    parts.append('<circle cx="%d" cy="%d" r="%d" fill="none" stroke="#FFFFFF" stroke-opacity="0.25" '
                 'stroke-width="1.5"/>' % (CX, CY, R - 16))
    for k in range(60):
        major = k % 5 == 0
        x1, y1 = polar(R - 16, k * 6)
        x2, y2 = polar(R - (34 if major else 24), k * 6)
        parts.append('<line x1="%.1f" y1="%.1f" x2="%.1f" y2="%.1f" stroke="#FFFFFF" stroke-opacity="%.2f" '
                     'stroke-width="%d" stroke-linecap="round"/>' % (x1, y1, x2, y2, 0.9 if major else 0.35,
                                                                    4 if major else 2))
    # Hours written as sums.
    def num(text, deg, size=40):
        x, y = polar(R - 78, deg)
        return ('<text x="%.1f" y="%.1f" text-anchor="middle" %s font-size="%d" fill="#FFFFFF">%s</text>'
                % (x, y + size * 0.33, MATH_FONT, size, text))
    parts.append(num('√<tspan text-decoration="overline">144</tspan>', 0))
    parts.append(num('⌊<tspan font-style="italic">π</tspan>⌋', 90))
    parts.append(num('3!', 180))
    parts.append(num('3²', 270))
    for h in (1, 2, 4, 5, 7, 8, 10, 11):
        x, y = polar(R - 72, h * 30)
        parts.append('<circle cx="%.1f" cy="%.1f" r="4" fill="%s"/>' % (x, y, coral))
    # Hands at 10:09:40.
    def hand(deg, length, width, colour, tail=24):
        x1, y1 = polar(-tail, deg)
        x2, y2 = polar(length, deg)
        return ('<line x1="%.1f" y1="%.1f" x2="%.1f" y2="%.1f" stroke="%s" stroke-width="%d" '
                'stroke-linecap="round"/>' % (x1, y1, x2, y2, colour, width))
    parts.append(hand(10 * 30 + 4.75, 110, 12, '#FFFFFF'))
    parts.append(hand(9.67 * 6, 168, 8, '#FFFFFF'))
    parts.append(hand(40 * 6, 180, 3, coral, 40))
    parts.append('<circle cx="%d" cy="%d" r="11" fill="%s"/><circle cx="%d" cy="%d" r="4" fill="#000000"/>'
                 % (CX, CY, coral, CX, CY))
    parts.append(title('MATH CLOCK', 'TELL THE TIME, SHOW YOUR WORK', coral))
    defs = ('<radialGradient id="face" cx="50%%" cy="40%%" r="65%%">'
            '<stop offset="0" stop-color="#1E1E24"/><stop offset="1" stop-color="#08080A"/></radialGradient>'
            '<radialGradient id="fade"><stop offset="0.55" stop-color="#FFFFFF"/>'
            '<stop offset="1" stop-color="#FFFFFF" stop-opacity="0"/></radialGradient>'
            '<mask id="paper"><circle cx="%d" cy="%d" r="300" fill="url(#fade)"/></mask>' % (CX, CY))
    return svg('\n'.join(parts), defs), coral


# ---------------------------------------------------------------- Couchstronomy

def couchstronomy():
    warm, starblue = '#FFE6B0', '#BFD4FF'
    R = 270
    rng = random.Random(7)
    sky = []
    sky.append('<circle cx="%d" cy="%d" r="%d" fill="url(#night)"/>' % (CX, CY, R))
    # Milky-way haze across the sky.
    sky.append('<ellipse cx="%d" cy="%d" rx="320" ry="46" fill="%s" fill-opacity="0.10" filter="url(#soft)" '
               'transform="rotate(-28 %d %d)"/>' % (CX, CY - 30, starblue, CX, CY))
    for _ in range(260):
        x, y = CX + rng.uniform(-R, R), CY + rng.uniform(-R, R * 0.55)
        r = rng.choice((0.8, 1.0, 1.2, 1.4, 1.8, 2.4))
        sky.append('<circle cx="%.1f" cy="%.1f" r="%.1f" fill="#FFFFFF" fill-opacity="%.2f"/>'
                   % (x, y, r, rng.uniform(0.35, 0.95)))
    # The Big Dipper, joined up.
    dipper = [(300, 205), (360, 192), (412, 210), (462, 236), (480, 292), (560, 300), (570, 236)]
    sky.append('<path d="M%s Z" fill="none" stroke="%s" stroke-opacity="0.5" stroke-width="2"/>'
               % (' L'.join('%d,%d' % p for p in dipper[3:]), starblue))
    sky.append('<path d="M%s" fill="none" stroke="%s" stroke-opacity="0.5" stroke-width="2"/>'
               % (' L'.join('%d,%d' % p for p in dipper[:4]), starblue))
    for x, y in dipper:
        sky.append(sparkle(x, y, 13, '#FFFFFF'))
    # Moon, ringed planet and a shooting star.
    sky.append('<circle cx="640" cy="130" r="44" fill="%s" fill-opacity="0.35" filter="url(#soft)"/>' % warm)
    sky.append('<path d="M640,86 A44,44 0 1,0 684,130 A36,36 0 1,1 640,86 Z" fill="%s"/>' % warm)
    sky.append('<g transform="translate(316,118) rotate(-20)"><circle r="18" fill="#F4C27A"/>'
               '<ellipse rx="34" ry="8" fill="none" stroke="%s" stroke-width="3"/>'
               '<path d="M-18,0 A18,18 0 0,1 18,0" fill="#F4C27A"/></g>' % warm)
    sky.append('<line x1="700" y1="200" x2="610" y2="240" stroke="url(#streak)" stroke-width="3" '
               'stroke-linecap="round"/>')
    # Ground and the couch.
    ground = 'M%d,%d C%d,%d %d,%d %d,%d L%d,%d L%d,%d Z' % (
        CX - R - 10, CY + 150, CX - 120, CY + 118, CX + 120, CY + 132, CX + R + 10, CY + 140,
        CX + R + 10, CY + R + 10, CX - R - 10, CY + R + 10)
    sky.append('<path d="%s" fill="#070B14"/>' % ground)
    sky.append('<path d="M%d,%d C%d,%d %d,%d %d,%d" fill="none" stroke="%s" stroke-opacity="0.35" '
               'stroke-width="2"/>' % (CX - R - 10, CY + 150, CX - 120, CY + 118, CX + 120, CY + 132,
                                       CX + R + 10, CY + 140, starblue))
    cx0, base = CX - 30, CY + 196
    couch = [
        # back, seat, arms and feet
        '<rect x="%d" y="%d" width="210" height="62" rx="18"/>' % (cx0 - 105, base - 112),
        '<rect x="%d" y="%d" width="230" height="44" rx="12"/>' % (cx0 - 115, base - 62),
        '<rect x="%d" y="%d" width="42" height="80" rx="18"/>' % (cx0 - 145, base - 86),
        '<rect x="%d" y="%d" width="42" height="80" rx="18"/>' % (cx0 + 103, base - 86),
        '<rect x="%d" y="%d" width="10" height="16" rx="3"/>' % (cx0 - 128, base - 10),
        '<rect x="%d" y="%d" width="10" height="16" rx="3"/>' % (cx0 + 118, base - 10),
    ]
    sky.append('<g fill="#1A2236" stroke="%s" stroke-opacity="0.75" stroke-width="3">%s</g>'
               % (warm, ''.join(couch)))
    sky.append('<path d="M%d,%d H%d" stroke="%s" stroke-opacity="0.4" stroke-width="2"/>'
               % (cx0 - 2, base - 106, cx0 - 2, warm))
    sky.append('<line x1="%d" y1="%d" x2="%d" y2="%d" stroke="%s" stroke-opacity="0.4" stroke-width="2"/>'
               % (cx0, base - 104, cx0, base - 56, warm))
    # Telescope on a tripod, pointed at the Dipper.
    tx, ty = CX + 160, CY + 128
    sky.append('<g stroke="%s" stroke-width="4" stroke-linecap="round" stroke-opacity="0.85">'
               '<line x1="%d" y1="%d" x2="%d" y2="%d"/><line x1="%d" y1="%d" x2="%d" y2="%d"/>'
               '<line x1="%d" y1="%d" x2="%d" y2="%d"/></g>'
               % (warm, tx, ty, tx - 26, ty + 58, tx, ty, tx + 24, ty + 58, tx, ty, tx + 2, ty + 62))
    sky.append('<g transform="translate(%d,%d) rotate(-148)"><rect x="-44" y="-11" width="84" height="22" rx="5" '
               'fill="#1A2236" stroke="%s" stroke-width="3"/><rect x="-56" y="-14" width="14" height="28" rx="3" '
               'fill="%s"/></g>' % (tx, ty - 6, warm, warm))
    body = ['<g clip-path="url(#round)">%s</g>' % '\n'.join(sky),
            '<circle cx="%d" cy="%d" r="%d" fill="none" stroke="%s" stroke-opacity="0.45" stroke-width="3"/>'
            % (CX, CY, R, warm)]
    body.append(title('COUCHSTRONOMY', 'THE SKY ABOVE YOUR COUCH', warm))
    defs = ('<radialGradient id="night" cx="50%%" cy="30%%" r="75%%">'
            '<stop offset="0" stop-color="#1A2B55"/><stop offset="0.7" stop-color="#0A1226"/>'
            '<stop offset="1" stop-color="#04070F"/></radialGradient>'
            '<linearGradient id="streak" x1="1" y1="0" x2="0" y2="1">'
            '<stop offset="0" stop-color="#FFFFFF" stop-opacity="0"/>'
            '<stop offset="1" stop-color="#FFFFFF" stop-opacity="0.95"/></linearGradient>'
            '<clipPath id="round"><circle cx="%d" cy="%d" r="%d"/></clipPath>' % (CX, CY, R))
    return svg('\n'.join(body), defs), warm


def sparkle(x, y, size, colour):
    s, t = size, size * 0.18
    return ('<g transform="translate(%.1f,%.1f)" filter="url(#glow)"><path d="M0,-%.1f L%.1f,-%.1f L%.1f,0 '
            'L%.1f,%.1f L0,%.1f L-%.1f,%.1f L-%.1f,0 L-%.1f,-%.1f Z" fill="%s"/></g>'
            % (x, y, s, t, t, s, t, t, s, t, t, s, t, t, colour))


# ---------------------------------------------------------------- SkyWatch

def skywatch():
    sky = '#4FC3F7'
    random.seed(7)
    parts = []
    # A radar scope: range rings, a sweep and soft echoes, with a location pin in the middle.
    for r in (90, 170, 250):
        parts.append('<circle cx="%d" cy="%d" r="%d" fill="none" stroke="%s" stroke-opacity="%.2f" '
                     'stroke-width="2"/>' % (CX, CY, r, sky, 0.12 + 0.06 * (250 - r) / 80.0))
    for deg in range(0, 360, 30):
        x1, y1 = polar(250, deg)
        x2, y2 = polar(262, deg)
        parts.append('<line x1="%.1f" y1="%.1f" x2="%.1f" y2="%.1f" stroke="%s" stroke-opacity="0.4" '
                     'stroke-width="2"/>' % (x1, y1, x2, y2, sky))
    x1, y1 = polar(250, 20)
    x2, y2 = polar(250, 70)
    parts.append('<path d="M%d %d L%.1f %.1f A250 250 0 0 1 %.1f %.1f Z" fill="url(#sweep)"/>'
                 % (CX, CY, x1, y1, x2, y2))
    echoes = [(-90, 50, 110, 60, '#1FBF3F'), (-70, 44, 60, 34, '#F5E000'), (-62, 40, 26, 16, '#F53C00'),
              (110, -70, 70, 40, '#1FBF3F'), (118, -74, 30, 18, '#F5E000'), (40, 150, 80, 34, '#1FBF3F')]
    parts.append('<g filter="url(#soft)" opacity="0.9">')
    for dx, dy, rx, ry, colour in echoes:
        parts.append('<ellipse cx="%d" cy="%d" rx="%d" ry="%d" fill="%s"/>' % (CX + dx, CY + dy, rx, ry, colour))
    parts.append('</g>')
    parts.append('<circle cx="%d" cy="%d" r="22" fill="none" stroke="#FFFFFF" stroke-width="8"/>' % (CX, CY))
    parts.append('<circle cx="%d" cy="%d" r="8" fill="#FFFFFF"/>' % (CX, CY))
    parts.append(title('SKYWATCH', 'YOUR WEATHER STATION', sky))
    defs = ('<linearGradient id="sweep" x1="0" y1="1" x2="1" y2="0">'
            '<stop offset="0" stop-color="%s" stop-opacity="0"/><stop offset="1" stop-color="%s" '
            'stop-opacity="0.5"/></linearGradient>' % (sky, sky))
    return svg('\n'.join(parts), defs), sky


DOTS = ('<svg xmlns="http://www.w3.org/2000/svg" width="120" height="24" viewBox="0 0 120 24">'
        '<circle cx="28" cy="12" r="6" fill="#FFFFFF"/><circle cx="60" cy="12" r="6" fill="#FFFFFF"/>'
        '<circle cx="92" cy="12" r="6" fill="#FFFFFF"/></svg>')

ADDONS = [('screensaver.godseye.map', godseye), ('screensaver.godsworld.map', godsworld),
          ('screensaver.math.clock', mathclock), ('screensaver.couchstronomy', couchstronomy),
          ('screensaver.skywatch', skywatch)]


def render(svg_text, out_png, w, h):
    with tempfile.TemporaryDirectory() as tmp:
        src = os.path.join(tmp, 'art.svg')
        with open(src, 'w') as f:
            f.write(svg_text)
        subprocess.run([CHROME, '--headless=new', '--disable-gpu', '--hide-scrollbars',
                        '--force-device-scale-factor=1', '--default-background-color=00000000',
                        '--window-size=%d,%d' % (w, h), '--screenshot=' + out_png, 'file://' + src],
                       check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    img = Image.open(out_png).convert('RGBA')
    assert img.size == (w, h), img.size
    img.save(out_png, optimize=True)


def main(args):
    os.makedirs(OUT_SVG, exist_ok=True)
    for addon, draw in ADDONS:
        if args and not any(a in addon for a in args):
            continue
        text, _accent = draw()
        with open(os.path.join(OUT_SVG, addon + '.svg'), 'w') as f:
            f.write(text)
        media = os.path.join(REPO, addon, 'resources', 'media')
        render(text, os.path.join(media, 'splash.png'), W, H)
        render(DOTS, os.path.join(media, 'splash_dots.png'), 120, 24)
        print('%s: %d KB' % (addon, os.path.getsize(os.path.join(media, 'splash.png')) // 1024))


if __name__ == '__main__':
    main(sys.argv[1:])
