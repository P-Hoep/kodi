"""Build SkyWatch's media: weather icons, big-number glyphs, backgrounds, pin, legend, icon.

  python3 tools/make_skywatch_media.py

Needs Pillow and Google Chrome (to render SVG). Downloads into tools/.skywatch-cache:
  - Meteocons by Bas Milius (MIT), the static "fill" SVGs, rendered to 256 px PNGs
  - Inter by Rasmus Andersson (SIL OFL 1.1), for the big-number glyphs
Writes screensaver.skywatch/resources/media/... and icon.png. Licences go to
resources/media/LICENSES.txt.
"""

import json
import os
import subprocess
import sys
import tempfile
import urllib.request

from PIL import Image, ImageDraw, ImageFilter, ImageFont

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.normpath(os.path.join(HERE, '..', 'screensaver.skywatch'))
MEDIA = os.path.join(ROOT, 'resources', 'media')
CACHE = os.path.join(HERE, '.skywatch-cache')
CHROME = '/Applications/Google Chrome.app/Contents/MacOS/Google Chrome'
METEOCONS = 'https://cdn.jsdelivr.net/gh/basmilius/weather-icons@2.0.0/design/fill/export/wi_%s.svg'
METEOCONS_LICENSE = 'https://cdn.jsdelivr.net/gh/basmilius/weather-icons@2.0.0/LICENSE'
INTER = 'https://cdn.jsdelivr.net/gh/rsms/inter@v3.19/docs/font-files/Inter-%s.otf'
INTER_LICENSE = 'https://cdn.jsdelivr.net/gh/rsms/inter@v3.19/LICENSE.txt'

ICONS = """clear-day clear-night partly-cloudy-day partly-cloudy-night overcast overcast-day overcast-night
cloudy fog fog-day fog-night drizzle partly-cloudy-day-drizzle partly-cloudy-night-drizzle rain
partly-cloudy-day-rain partly-cloudy-night-rain sleet partly-cloudy-day-sleet partly-cloudy-night-sleet
snow partly-cloudy-day-snow partly-cloudy-night-snow thunderstorms-rain thunderstorms-day-rain
thunderstorms-night-rain hail sunrise sunset moonrise moonset raindrop raindrops umbrella wind humidity
barometer thermometer uv-index compass not-available tornado windsock horizon pressure-high pressure-low
thermometer-warmer thermometer-colder smoke-particles star""".split()

GLYPHS = '0123456789:-°%.+ AMP'
GLYPH_PX = 240          # rendered line height; bignum.py scales from this
GLYPH_FONTS = {'light': 'Light', 'medium': 'Medium'}

# NWS-style reflectivity colours (dBZ) for the legend bar; IEM's n0q ramp follows these.
DBZ = [(5, '04e9e7'), (10, '019ff4'), (15, '0300f4'), (20, '02fd02'), (25, '01c501'), (30, '008e00'),
       (35, 'fdf802'), (40, 'e5bc00'), (45, 'fd9500'), (50, 'fd0000'), (55, 'd40000'), (60, 'bc0000'),
       (65, 'f800fd'), (70, '9854c6'), (75, 'fdfdfd')]


def download(url, path):
    if not os.path.exists(path):
        with urllib.request.urlopen(url, timeout=30) as r:
            body = r.read()
        with open(path, 'wb') as f:
            f.write(body)
    return path


def chrome_png(svg_text, out, w, h):
    with tempfile.TemporaryDirectory() as tmp:
        src = os.path.join(tmp, 'a.html')
        with open(src, 'w') as f:
            f.write('<html><body style="margin:0;background:transparent">'
                    '<img src="data:image/svg+xml;base64,%s" width="%d" height="%d"></body></html>'
                    % (__import__('base64').b64encode(svg_text.encode()).decode(), w, h))
        subprocess.run([CHROME, '--headless=new', '--disable-gpu', '--hide-scrollbars', '--force-device-scale-factor=1',
                        '--default-background-color=00000000', '--window-size=%d,%d' % (w, h),
                        '--screenshot=' + out, 'file://' + src],
                       check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    img = Image.open(out).convert('RGBA')
    img.save(out, optimize=True)


def icons():
    folder = os.path.join(MEDIA, 'icons')
    os.makedirs(folder, exist_ok=True)
    src = os.path.join(CACHE, 'meteocons')
    os.makedirs(src, exist_ok=True)
    for name in ICONS:
        svg = download(METEOCONS % name, os.path.join(src, name + '.svg'))
        out = os.path.join(folder, name + '.png')
        if not os.path.exists(out):
            chrome_png(open(svg).read(), out, 256, 256)
    print('icons: %d' % len(ICONS))


def glyphs():
    folder = os.path.join(MEDIA, 'glyphs')
    os.makedirs(folder, exist_ok=True)
    metrics = {'height': GLYPH_PX, 'fonts': {}}
    for key, weight in GLYPH_FONTS.items():
        path = download(INTER % weight, os.path.join(CACHE, 'Inter-%s.otf' % weight))
        size = int(GLYPH_PX * 0.86)
        font = ImageFont.truetype(path, size)
        ascent, descent = font.getmetrics()
        top_pad = (GLYPH_PX - (ascent + descent)) // 2
        table = {}
        for ch in GLYPHS:
            advance = int(round(font.getlength(ch)))
            if ch in 'AMP':
                # Smaller caps for AM/PM, drawn at the same baseline.
                small = ImageFont.truetype(path, int(size * 0.42))
                advance = int(round(small.getlength(ch)))
            if ch == ' ':
                table[ch] = [int(size * 0.25), None]
                continue
            if ch in ':':
                advance = int(advance * 1.1)
            img = Image.new('RGBA', (max(1, advance), GLYPH_PX), (255, 255, 255, 0))
            d = ImageDraw.Draw(img)
            if ch in 'AMP':
                d.text((0, top_pad + ascent), ch, font=small, fill=(255, 255, 255, 255), anchor='ls')
            else:
                d.text((advance / 2.0, top_pad + ascent), ch, font=font, fill=(255, 255, 255, 255), anchor='ms')
            name = '%s_%04x.png' % (key, ord(ch))
            img.save(os.path.join(folder, name), optimize=True)
            table[ch] = [advance, name]
        metrics['fonts'][key] = table
    with open(os.path.join(folder, 'metrics.json'), 'w') as f:
        json.dump(metrics, f, indent=1, sort_keys=True)
    print('glyphs: %d per weight' % len(GLYPHS))


def backgrounds():
    # Panel scenes: a deep blue-black gradient with a soft glow top left.
    w, h = 1920, 1080
    img = Image.new('RGB', (w, h))
    px = img.load()
    for y in range(h):
        for x in range(0, w):
            t = y / float(h)
            r = int(10 + 6 * (1 - t))
            g = int(16 + 10 * (1 - t))
            b = int(28 + 22 * (1 - t))
            px[x, y] = (r, g, b)
    glow = Image.new('L', (w, h), 0)
    ImageDraw.Draw(glow).ellipse((-500, -600, 1100, 700), fill=70)
    glow = glow.filter(ImageFilter.GaussianBlur(220))
    tint = Image.new('RGB', (w, h), (40, 90, 150))
    img = Image.composite(tint, img, glow)
    img.save(os.path.join(MEDIA, 'bg.jpg'), quality=90)
    # Night: nearly black, a hint of red-brown for low light.
    night = Image.new('RGB', (w, h), (6, 4, 4))
    night.save(os.path.join(MEDIA, 'bg_night.jpg'), quality=90)
    # A soft vertical fade used under text on maps (top and bottom bars).
    fade = Image.new('RGBA', (8, 256))
    for y in range(256):
        fade.putpixel((0, y), (0, 0, 0, int(255 * (1 - y / 255.0) ** 1.6)))
        for x in range(1, 8):
            fade.putpixel((x, y), fade.getpixel((0, y)))
    fade.save(os.path.join(MEDIA, 'fade.png'))
    fade.transpose(Image.FLIP_TOP_BOTTOM).save(os.path.join(MEDIA, 'fade_up.png'))
    print('backgrounds')


def shapes():
    s = 4   # supersample
    # Location pin: a ring with a dot, white with a dark halo, drawn white for tinting.
    n = 96 * s
    img = Image.new('RGBA', (n, n), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    c = n / 2
    d.ellipse((c - 40 * s, c - 40 * s, c + 40 * s, c + 40 * s), fill=(0, 0, 0, 110))
    d.ellipse((c - 26 * s, c - 26 * s, c + 26 * s, c + 26 * s), outline=(255, 255, 255, 255), width=7 * s)
    d.ellipse((c - 10 * s, c - 10 * s, c + 10 * s, c + 10 * s), fill=(255, 255, 255, 255))
    img.resize((96, 96), Image.LANCZOS).save(os.path.join(MEDIA, 'pin.png'))
    # Filled circle and ring for timeline dots and dials.
    for name, width in (('dot', 0), ('ring', 10)):
        img = Image.new('RGBA', (128 * s, 128 * s), (0, 0, 0, 0))
        d = ImageDraw.Draw(img)
        if width:
            d.ellipse((s, s, 127 * s, 127 * s), outline=(255, 255, 255, 255), width=width * s)
        else:
            d.ellipse((s, s, 127 * s, 127 * s), fill=(255, 255, 255, 255))
        img.resize((128, 128), Image.LANCZOS).save(os.path.join(MEDIA, name + '.png'))
    # Arrow pointing up (rotated by Kodi for wind and trends).
    img = Image.new('RGBA', (128 * s, 128 * s), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    d.polygon([(64 * s, 8 * s), (110 * s, 116 * s), (64 * s, 90 * s), (18 * s, 116 * s)], fill=(255, 255, 255, 255))
    img.resize((128, 128), Image.LANCZOS).save(os.path.join(MEDIA, 'arrow.png'))
    # Rounded pill for chips and the timeline track.
    img = Image.new('RGBA', (256 * s, 64 * s), (0, 0, 0, 0))
    ImageDraw.Draw(img).rounded_rectangle((0, 0, 256 * s - 1, 64 * s - 1), radius=32 * s, fill=(255, 255, 255, 255))
    img.resize((256, 64), Image.LANCZOS).save(os.path.join(MEDIA, 'pill.png'))
    # Rounded card (scaled by Kodi; corners stay acceptable at typical card sizes).
    img = Image.new('RGBA', (400 * s, 400 * s), (0, 0, 0, 0))
    ImageDraw.Draw(img).rounded_rectangle((0, 0, 400 * s - 1, 400 * s - 1), radius=28 * s, fill=(255, 255, 255, 255))
    img.resize((400, 400), Image.LANCZOS).save(os.path.join(MEDIA, 'card.png'))
    print('shapes')


def legend():
    w, h = 600, 24
    img = Image.new('RGBA', (w, h))
    d = ImageDraw.Draw(img)
    seg = w / float(len(DBZ))
    for i, (_dbz, colour) in enumerate(DBZ):
        rgb = tuple(int(colour[k:k + 2], 16) for k in (0, 2, 4))
        d.rectangle((int(i * seg), 0, int((i + 1) * seg), h), fill=rgb + (255,))
    img.save(os.path.join(MEDIA, 'legend_dbz.png'))
    # Precipitation type (HRRR REFP): rain, snow, freezing rain, ice pellets.
    ptype = [('02fd02', 'e5bc00', 'fd0000'), ('9ad7ff', '3b7dff', '1a3fbf'), ('ffb3e6', 'f05cd5', 'a1007f'),
             ('e0b0ff', 'a46ef0', '6a3cc6')]
    img = Image.new('RGBA', (w, h))
    d = ImageDraw.Draw(img)
    quarter = w / 4.0
    for q, ramp in enumerate(ptype):
        for i, colour in enumerate(ramp):
            rgb = tuple(int(colour[k:k + 2], 16) for k in (0, 2, 4))
            x0 = q * quarter + i * quarter / 3.0
            d.rectangle((int(x0), 0, int(x0 + quarter / 3.0), h), fill=rgb + (255,))
    img.save(os.path.join(MEDIA, 'legend_ptype.png'))
    print('legends')


ICON_SVG = """<svg xmlns="http://www.w3.org/2000/svg" width="512" height="512" viewBox="0 0 512 512">
<defs>
 <radialGradient id="bg" cx="35%" cy="25%" r="85%"><stop offset="0" stop-color="#1d3d66"/><stop offset="1" stop-color="#070d18"/></radialGradient>
 <linearGradient id="sweep" x1="0" y1="0" x2="1" y2="0"><stop offset="0" stop-color="#4FC3F7" stop-opacity="0"/><stop offset="1" stop-color="#4FC3F7" stop-opacity="0.55"/></linearGradient>
 <filter id="soft"><feGaussianBlur stdDeviation="9"/></filter>
</defs>
<rect width="512" height="512" rx="96" fill="url(#bg)"/>
<g transform="translate(256 270)">
 <circle r="190" fill="none" stroke="#4FC3F7" stroke-opacity="0.18" stroke-width="3"/>
 <circle r="130" fill="none" stroke="#4FC3F7" stroke-opacity="0.22" stroke-width="3"/>
 <circle r="70" fill="none" stroke="#4FC3F7" stroke-opacity="0.28" stroke-width="3"/>
 <path d="M0 0 L190 0 A190 190 0 0 0 95 -164.5 Z" fill="url(#sweep)" transform="rotate(-20)"/>
 <g filter="url(#soft)" opacity="0.95">
  <ellipse cx="-70" cy="40" rx="78" ry="46" fill="#02c802"/>
  <ellipse cx="-50" cy="34" rx="40" ry="24" fill="#f5e000"/>
  <ellipse cx="-44" cy="32" rx="18" ry="11" fill="#f53c00"/>
  <ellipse cx="80" cy="-60" rx="50" ry="28" fill="#02c802"/>
  <ellipse cx="88" cy="-62" rx="20" ry="12" fill="#f5e000"/>
 </g>
 <circle r="16" fill="none" stroke="#fff" stroke-width="7"/>
 <circle r="6" fill="#fff"/>
</g>
</svg>"""


def addon_icon():
    out = os.path.join(ROOT, 'icon.png')
    chrome_png(ICON_SVG, out, 512, 512)
    img = Image.open(out).convert('RGBA').resize((256, 256), Image.LANCZOS)
    img.save(out, optimize=True)
    with open(os.path.join(CACHE, 'icon.svg'), 'w') as f:
        f.write(ICON_SVG)
    print('icon.png')


def licences():
    mit = open(download(METEOCONS_LICENSE, os.path.join(CACHE, 'LICENSE-Meteocons.txt'))).read()
    ofl = open(download(INTER_LICENSE, os.path.join(CACHE, 'LICENSE-Inter.txt'))).read()
    with open(os.path.join(MEDIA, 'LICENSES.txt'), 'w') as f:
        f.write('media/icons: Meteocons by Bas Milius, https://github.com/basmilius/weather-icons\n\n')
        f.write(mit.strip() + '\n\n' + '-' * 72 + '\n\n')
        f.write('media/glyphs: rendered from Inter by Rasmus Andersson, https://rsms.me/inter\n\n')
        f.write(ofl.strip() + '\n\n' + '-' * 72 + '\n\n')
        f.write('media/moon: from God\'s Eye Map in this repository (MIT).\n')


def main(args):
    os.makedirs(MEDIA, exist_ok=True)
    os.makedirs(CACHE, exist_ok=True)
    steps = {'icons': icons, 'glyphs': glyphs, 'backgrounds': backgrounds, 'shapes': shapes, 'legend': legend,
             'icon': addon_icon, 'licences': licences}
    for name, fn in steps.items():
        if not args or name in args:
            fn()


if __name__ == '__main__':
    main(sys.argv[1:])
