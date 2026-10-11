"""Generate the world data bundled with God's World Map (needs Pillow and numpy).

  python3 tools/make_world_data.py            # downloads into tools/.world-cache, writes media/world
  python3 tools/make_world_data.py --offline  # reuse the download cache only

Everything the screensaver decodes in Python is written as an unfiltered PNG (filter 0 on
every row), which the add-on's pure-Python reader turns into pixels with zlib alone. That
matters on a Fire TV Stick, where there is no imaging library. Images Kodi only displays
(background, icons) can be any format.

Sources (all free to redistribute):
  NASA Blue Marble Next Generation, VIIRS city lights 2012, GIBS land/water map (NASA GIBS)
  Elevation: Mapzen/Tilezen terrarium tiles (AWS Open Data; SRTM, GMTED, ETOPO1 and others)
  Borders and coastlines: Natural Earth 1:50m (public domain)
  Glyphs: DejaVu Sans Mono Bold (Bitstream Vera licence), shipped with matplotlib
"""

import io
import json
import math
import os
import struct
import sys
import urllib.request
import zlib

import numpy as np
from PIL import Image, ImageDraw, ImageFilter, ImageFont

HERE = os.path.dirname(os.path.abspath(__file__))
ADDON = os.path.normpath(os.path.join(HERE, '..', 'screensaver.godsworld.map'))
OUT = os.path.join(ADDON, 'resources', 'media')
CACHE = os.path.join(HERE, '.world-cache')
sys.path.insert(0, ADDON)
from resources.lib import ascii as ascii_mode  # noqa: E402  (CHARSET and cell sizes)
from resources.lib import landclass  # noqa: E402  (class ids)

GIBS = ('https://gibs.earthdata.nasa.gov/wms/epsg4326/best/wms.cgi?SERVICE=WMS&REQUEST=GetMap'
        '&VERSION=1.1.1&SRS=EPSG:4326&BBOX=-180,-90,180,90&FORMAT=image/png&TRANSPARENT=TRUE'
        '&LAYERS=%s&WIDTH=%d&HEIGHT=%d')
TERRARIUM = 'https://s3.amazonaws.com/elevation-tiles-prod/terrarium/%d/%d/%d.png'
NATURAL_EARTH = 'https://raw.githubusercontent.com/nvkelso/natural-earth-vector/master/geojson/%s.geojson'
OFFLINE = '--offline' in sys.argv
SW, SH = 2048, 1024        # imagery size
CW, CH = 1024, 512         # land class size


def fetch(url, name):
    path = os.path.join(CACHE, name)
    if not os.path.exists(path):
        if OFFLINE:
            sys.exit('not cached: %s' % name)
        print('  download', name)
        req = urllib.request.Request(url, headers={'User-Agent': 'GodsWorldMap-build/0.1'})
        data = urllib.request.urlopen(req, timeout=180).read()
        with open(path, 'wb') as handle:
            handle.write(data)
    with open(path, 'rb') as handle:
        return handle.read()


def gibs(layer, w, h):
    return Image.open(io.BytesIO(fetch(GIBS % (layer, w, h), '%s_%d.png' % (layer, w))))


def write_png(path, array):
    """Unfiltered PNG from a uint8 array (H, W) gray or (H, W, 3/4) RGB(A)."""
    array = np.ascontiguousarray(array, dtype=np.uint8)
    h, w = array.shape[:2]
    channels = 1 if array.ndim == 2 else array.shape[2]
    ctype = {1: 0, 2: 4, 3: 2, 4: 6}[channels]
    rows = array.reshape(h, w * channels)
    raw = np.zeros((h, w * channels + 1), dtype=np.uint8)
    raw[:, 1:] = rows

    def chunk(kind, body):
        return struct.pack('>I4s', len(body), kind) + body + struct.pack('>I', zlib.crc32(kind + body) & 0xFFFFFFFF)
    data = (b'\x89PNG\r\n\x1a\n' + chunk(b'IHDR', struct.pack('>IIBBBBB', w, h, 8, ctype, 0, 0, 0))
            + chunk(b'IDAT', zlib.compress(raw.tobytes(), 9)) + chunk(b'IEND', b''))
    with open(path, 'wb') as handle:
        handle.write(data)
    print('  %-28s %5d x %-5d %6.0f KB' % (os.path.relpath(path, OUT), w, h, len(data) / 1024.0))


# ---------------------------------------------------------------- imagery

def imagery():
    bm = np.array(gibs('BlueMarble_NextGeneration', SW, SH).convert('RGB'))
    write_png(os.path.join(OUT, 'world', 'bluemarble.png'), bm)
    # City lights: the 2012 composite is warm lights on a dark blue Earth. Lights are where
    # red rises above the bluish ground; a soft curve keeps faint towns visible.
    cl = np.array(gibs('VIIRS_CityLights_2012', SW, SH).convert('RGB')).astype(np.float32)
    lum = cl[..., 0] * 0.6 + cl[..., 1] * 0.4 - cl[..., 2] * 0.45
    lights = np.clip((lum - 12.0) / 150.0, 0, 1) ** 0.8 * 255
    write_png(os.path.join(OUT, 'world', 'lights.png'), lights.astype(np.uint8))
    return bm, lights


def elevation():
    """Metres on the CW x CH equirectangular grid, from terrarium tiles at zoom 3 (Web Mercator)."""
    z, n = 3, 8
    mosaic = np.zeros((256 * n, 256 * n), dtype=np.float32)
    for ty in range(n):
        for tx in range(n):
            tile = np.array(Image.open(io.BytesIO(fetch(TERRARIUM % (z, tx, ty), 'terr_%d_%d_%d.png' % (z, tx, ty))))
                            .convert('RGB')).astype(np.float32)
            mosaic[ty * 256:(ty + 1) * 256, tx * 256:(tx + 1) * 256] = \
                tile[..., 0] * 256 + tile[..., 1] + tile[..., 2] / 256 - 32768
    lats = 90 - (np.arange(CH) + 0.5) * 180.0 / CH
    lons = -180 + (np.arange(CW) + 0.5) * 360.0 / CW
    lat_c = np.clip(lats, -85.05, 85.05)
    my = (1 - np.log(np.tan(np.radians(45 + lat_c / 2))) / math.pi) / 2 * mosaic.shape[0]
    mx = (lons + 180) / 360.0 * mosaic.shape[1]
    yy = np.clip(my.astype(int), 0, mosaic.shape[0] - 1)
    xx = np.clip(mx.astype(int), 0, mosaic.shape[1] - 1)
    elev = mosaic[yy[:, None], xx[None, :]]
    elev[lats < -85] = 2800.0   # Antarctic plateau beyond Web Mercator
    elev[lats > 85] = -3000.0   # Arctic Ocean
    return elev


def lines():
    """Coastlines and land borders as classes on the SW x SH grid: 0 none, 1 border, 2 coast."""
    img = Image.new('L', (SW, SH), 0)
    draw = ImageDraw.Draw(img)

    def xy(pt):
        return ((pt[0] + 180) / 360.0 * SW, (90 - pt[1]) / 180.0 * SH)

    for name, value in (('ne_50m_admin_0_boundary_lines_land', 1), ('ne_50m_coastline', 2)):
        doc = json.loads(fetch(NATURAL_EARTH % name, name + '.geojson').decode('utf-8'))
        for feature in doc['features']:
            geom = feature['geometry']
            parts = geom['coordinates'] if geom['type'] == 'MultiLineString' else [geom['coordinates']]
            for part in parts:
                pts = [xy(p) for p in part]
                for a, b in zip(pts, pts[1:]):
                    if abs(a[0] - b[0]) < SW / 2:  # skip segments that wrap the dateline
                        draw.line([a, b], fill=value, width=1)
    arr = np.array(img)
    write_png(os.path.join(OUT, 'world', 'lines.png'), arr)
    return arr


def classify(bm, lights, elev, line_arr):
    """Land-cover classes for the geographic ASCII mode (see resources/lib/landclass.py)."""
    C = landclass
    small = np.array(Image.fromarray(bm).resize((CW, CH), Image.BILINEAR)).astype(np.float32)
    r, g, b = small[..., 0], small[..., 1], small[..., 2]
    bright = (r + g + b) / 3
    sat = (np.max(small, axis=2) - np.min(small, axis=2))
    water_img = np.array(gibs('OSM_Land_Water_Map', CW * 2, CH * 2).convert('L').resize((CW, CH), Image.BILINEAR))
    water = water_img > 101   # land is grey 75, water 128
    lt = np.array(Image.fromarray(lights.astype(np.uint8)).resize((CW, CH), Image.BILINEAR)).astype(np.float32)
    lats = (90 - (np.arange(CH) + 0.5) * 180.0 / CH)[:, None] * np.ones((1, CW))
    alat = np.abs(lats)
    # Local relief: max - min elevation over a 5 x 5 neighbourhood.
    pad = np.pad(elev, 2, mode='edge')
    stack = np.stack([pad[dy:dy + CH, dx:dx + CW] for dy in range(5) for dx in range(5)])
    relief = stack.max(0) - stack.min(0)

    cls = np.full((CH, CW), C.PLAINS, dtype=np.uint8)
    greenness = g - (r + b) / 2
    cls[(greenness > -4) & (bright < 115)] = C.GRASS
    cls[(greenness > 2) & (bright < 70)] = C.FOREST
    cls[(greenness > 2) & (bright < 75) & (alat < 18)] = C.JUNGLE
    cls[(r > g * 1.05) & (bright > 120) & (alat < 50)] = C.DESERT
    cls[(alat > 58) & (cls != C.FOREST)] = C.TUNDRA
    cls[(elev > 500) & (relief > 450)] = C.HILLS
    cls[(elev > 1500) & (relief > 700) | (elev > 2600)] = C.MOUNTAINS
    cls[(elev > 3800) | ((elev > 2800) & (relief > 1800))] = C.PEAKS
    ice = ((bright > 185) & (sat < 40)) | (lats < -62)
    cls[ice] = C.ICE
    cls[lt > 150] = C.URBAN
    sea = water & (elev <= 5)
    cls[water & (elev > 5)] = C.LAKE
    cls[sea] = C.OCEAN
    cls[sea & (elev > -150)] = C.SHALLOW
    cls[sea & (elev < -3500)] = C.DEEP
    cls[water & (bright > 190) & (sat < 30)] = C.SEA_ICE  # frozen sea (Arctic, Antarctic shelves)
    write_png(os.path.join(OUT, 'world', 'landclass.png'), cls)
    preview = np.array([C.PREVIEW[i] for i in range(len(C.PREVIEW))], dtype=np.uint8)[cls]
    Image.fromarray(preview).save(os.path.join(CACHE, 'landclass_preview.png'))
    return cls


# ---------------------------------------------------------------- glyphs and display media

def glyphs():
    import matplotlib
    path = os.path.join(os.path.dirname(matplotlib.__file__), 'mpl-data', 'fonts', 'ttf', 'DejaVuSansMono-Bold.ttf')
    for cw, ch in ascii_mode.CELL_SIZES:
        size = ch
        # Largest font size whose advance fits the cell width and whose height fits the cell.
        while size > 4:
            font = ImageFont.truetype(path, size)
            if font.getlength('M') <= cw and (font.getbbox('Ég')[3] - font.getbbox('Ég')[1]) <= ch:
                break
            size -= 1
        ascent, descent = font.getmetrics()
        atlas = Image.new('L', (cw * len(ascii_mode.CHARSET), ch), 0)
        draw = ImageDraw.Draw(atlas)
        top = (ch - (ascent + descent)) // 2
        for i, c in enumerate(ascii_mode.CHARSET):
            if c in ascii_mode.BLOCKS:
                fill_block(draw, c, i * cw, cw, ch)
                continue
            x = i * cw + (cw - font.getlength(c)) / 2.0
            draw.text((x, top), c, font=font, fill=255)
        arr = (np.array(atlas) > 110).astype(np.uint8) * 255  # crisp 1-bit glyphs
        write_png(os.path.join(OUT, 'glyphs', 'glyphs_%dx%d.png' % (cw, ch)), arr)


def fill_block(draw, c, x0, cw, ch):
    """Shade and block characters drawn exactly to the cell, so they tile without seams."""
    if c == '█':
        draw.rectangle([x0, 0, x0 + cw - 1, ch - 1], fill=255)
        return
    step = {'░': 4, '▒': 2, '▓': 1}[c]
    for y in range(ch):
        for x in range(cw):
            if c == '▓':
                on = (x + y) % 4 != 0
            else:
                on = (x % step == 0) and (y % step == (x // step) % 2 * (step // 2))
            if on:
                draw.point((x0 + x, y), fill=255)


def background():
    """Deep space: a faint radial glow and a few thousand stars."""
    w, h = 1920, 1080
    rng = np.random.RandomState(7)
    yy, xx = np.mgrid[0:h, 0:w]
    d = np.hypot((xx - w / 2) / w, (yy - h / 2) / h)
    base = np.clip(1 - d * 1.4, 0, 1) ** 2
    img = np.zeros((h, w, 3), dtype=np.float32)
    img[..., 0] = 4 + 10 * base
    img[..., 1] = 7 + 14 * base
    img[..., 2] = 14 + 26 * base
    for _ in range(2600):
        x, y = rng.randint(0, w), rng.randint(0, h)
        v = rng.uniform(40, 200) * (1 if rng.rand() > 0.02 else 1.3)
        tint = [(1, 1, 1), (1, 0.9, 0.8), (0.8, 0.9, 1)][rng.randint(0, 3)]
        img[y, x] = np.minimum(255, img[y, x] + np.array(tint) * v)
    Image.fromarray(np.clip(img, 0, 255).astype(np.uint8)).save(os.path.join(OUT, 'background.jpg'), quality=92)


def globe_media():
    """Shading laid over the globe (darker limb) and an atmosphere halo just outside it.
    Both are drawn for a globe of radius R inside a canvas of 1.12 R; Kodi scales them."""
    n = 1024
    R = n / 2 / 1.12
    yy, xx = np.mgrid[0:n, 0:n]
    r = np.hypot(xx + 0.5 - n / 2, yy + 0.5 - n / 2) / R
    rgba = np.zeros((n, n, 4), dtype=np.float32)
    inside = r <= 1
    mu = np.sqrt(np.clip(1 - r ** 2, 0, 1))
    rgba[..., 0:3] = 0
    rgba[..., 3] = np.where(inside, (1 - mu) ** 2.2 * 150, 0)
    # Atmosphere: a blue rim fading out over 12% of the radius, plus a faint inner glow.
    halo = np.where(r > 1, np.clip(1 - (r - 1) / 0.12, 0, 1) ** 2.5, np.clip((r - 0.86) / 0.14, 0, 1) ** 3 * 0.55)
    a_h = halo * 200
    col = np.array([90, 160, 255], dtype=np.float32)
    total = a_h + rgba[..., 3] * (1 - a_h / 255)
    for c in range(3):
        rgba[..., c] = np.where(total > 0, (col[c] * a_h) / np.maximum(total, 1e-6), 0)
    rgba[..., 3] = total
    Image.fromarray(np.clip(rgba, 0, 255).astype(np.uint8)).save(os.path.join(OUT, 'globe_shade.png'))


def legend():
    from resources.lib import overlays
    w, h = 512, 20
    arr = np.zeros((h, w, 4), dtype=np.uint8)
    for x in range(w):
        t = overlays.TEMP_MIN + (overlays.TEMP_MAX - overlays.TEMP_MIN) * x / (w - 1.0)
        arr[:, x, :3] = overlays.temperature_color(t)
        arr[:, x, 3] = 255
    Image.fromarray(arr).save(os.path.join(OUT, 'legend_temp.png'))


def small_icons():
    Image.new('RGBA', (8, 8), (255, 255, 255, 255)).save(os.path.join(OUT, 'white.png'))
    # Bottom shade behind the status line and credits: transparent at the top, dark below.
    h = 110
    a = (np.linspace(0, 1, h) ** 1.6 * 170).astype(np.uint8)
    shade = np.zeros((h, 8, 4), dtype=np.uint8)
    shade[..., 3] = a[:, None]
    Image.fromarray(shade).save(os.path.join(OUT, 'shade_bottom.png'))
    n = 32
    yy, xx = np.mgrid[0:n, 0:n]
    d = np.hypot(xx + 0.5 - n / 2, yy + 0.5 - n / 2) / (n / 2)
    a = (np.clip(1 - d, 0, 1) ** 1.5 * 255).astype(np.uint8)
    dot = np.dstack([np.full((n, n), 255, np.uint8)] * 3 + [a])
    Image.fromarray(dot).save(os.path.join(OUT, 'particle.png'))
    # Storm: a hurricane symbol (two curved arms around an eye), white so Kodi can tint it.
    n = 128
    img = Image.new('RGBA', (n, n), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    d.ellipse([40, 40, 88, 88], outline=(255, 255, 255, 255), width=10)
    d.arc([6, 34, 70, 98], 180, 300, fill=(255, 255, 255, 255), width=10)
    d.arc([58, 30, 122, 94], 0, 120, fill=(255, 255, 255, 255), width=10)
    img.filter(ImageFilter.SMOOTH).save(os.path.join(OUT, 'storm.png'))
    # ISS: a body with two wide solar wings, drawn at 4x and scaled down for smooth edges.
    n = 256
    img = Image.new('RGBA', (n, n), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    gold, white = (255, 214, 90, 255), (255, 255, 255, 255)
    d.rectangle([n * 0.40, n * 0.36, n * 0.60, n * 0.64], fill=white)
    d.line([(n * 0.12, n * 0.5), (n * 0.88, n * 0.5)], fill=white, width=10)
    for x0 in (0.06, 0.22, 0.66, 0.82):
        d.rectangle([n * x0, n * 0.22, n * (x0 + 0.12), n * 0.42], fill=gold)
        d.rectangle([n * x0, n * 0.58, n * (x0 + 0.12), n * 0.78], fill=gold)
    img.resize((64, 64), Image.LANCZOS).save(os.path.join(OUT, 'iss.png'))


def icon(bm):
    """Add-on icon: the globe over Africa and Europe, drawn with the add-on's own projection code."""
    from resources.lib import projections
    n = 256
    proj = projections.get('orthographic')
    img = np.zeros((n, n, 4), dtype=np.uint8)
    img[..., :3] = (8, 14, 28)
    img[..., 3] = 255
    for y in range(n):
        for x in range(n):
            px = (x + 0.5 - n / 2) / (n * 0.42)
            py = -(y + 0.5 - n / 2) / (n * 0.42)
            ll = proj.ortho_inverse(px, py, 15.0, 20.0)
            if ll:
                lon, lat = ll
                u = int((lon + 180) / 360.0 * SW) % SW
                v = min(SH - 1, int((90 - lat) / 180.0 * SH))
                shade = 0.55 + 0.45 * math.sqrt(max(0.0, 1 - px * px - py * py))
                img[y, x, :3] = np.clip(bm[v, u] * shade * 1.15, 0, 255)
    Image.fromarray(img).save(os.path.join(ADDON, 'icon.png'))


def main():
    for d in (CACHE, os.path.join(OUT, 'world'), os.path.join(OUT, 'glyphs')):
        if not os.path.isdir(d):
            os.makedirs(d)
    print('imagery')
    bm, lights = imagery()
    print('elevation, coastlines and borders')
    elev = elevation()
    line_arr = lines()
    print('land classes')
    classify(bm, lights, elev, line_arr)
    print('glyphs')
    glyphs()
    print('display media')
    background()
    globe_media()
    legend()
    small_icons()
    icon(bm)


if __name__ == '__main__':
    main()
