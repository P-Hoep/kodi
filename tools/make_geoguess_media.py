"""Generate the GeoGuess media: icon, fanart, the white backdrop texture, the bottom shade, the
answer map and its pin.

The backdrop and shade are drawn with Python in the add-on (resources/lib/saver.py): a plain
white texture tinted black and a transparent-to-black gradient behind the answer. The map is an
equirectangular world map rendered from Natural Earth 1:110m country polygons (public domain),
downloaded once into tools/.world-cache when missing. The pin is drawn separately and placed at
the row's coordinates by the screensaver.

Run:  python3 tools/make_geoguess_media.py
"""

import json
import os
import urllib.request

from PIL import Image, ImageDraw, ImageFilter

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
ADDON = os.path.join(ROOT, 'screensaver.geoguess')
MEDIA = os.path.join(ADDON, 'resources', 'skins', 'Default', 'media')
CACHE = os.path.join(HERE, '.world-cache')
COUNTRIES = os.path.join(CACHE, 'ne_110m_admin_0_countries.geojson')
NATURAL_EARTH = ('https://raw.githubusercontent.com/nvkelso/natural-earth-vector/master/'
                 'geojson/ne_110m_admin_0_countries.geojson')

SKY_TOP = (7, 17, 28)
SKY_BOTTOM = (38, 92, 122)
GROUND_TOP = (22, 62, 64)
GROUND_BOTTOM = (9, 24, 27)
SUN = (244, 183, 110)

# Map panel size on screen (Kodi's 1080i GUI); the file is drawn at twice that.
MAP_W, MAP_H = 720, 360
MAP_SCALE = 2
OCEAN = (10, 18, 28, 255)
GRID = (18, 31, 45, 255)
LAND = (52, 68, 90, 255)
EDGE = (92, 116, 145, 255)
BORDER = (78, 100, 126, 255)


def vertical_gradient(size, top, bottom):
    width, height = size
    image = Image.new('RGB', (1, height))
    pixels = image.load()
    for y in range(height):
        u = y / float(max(1, height - 1))
        pixels[0, y] = tuple(int(top[i] + (bottom[i] - top[i]) * u) for i in range(3))
    return image.resize((width, height), Image.NEAREST)


def add_glow(image, centre, radius, colour, strength=255, blur=0):
    """Composite a soft disc; drawn on a full-size layer so its edges never show."""
    layer = Image.new('RGBA', image.size, (0, 0, 0, 0))
    cx, cy = centre
    ImageDraw.Draw(layer).ellipse((cx - radius, cy - radius, cx + radius, cy + radius),
                                  fill=colour + (strength,))
    if blur:
        layer = layer.filter(ImageFilter.GaussianBlur(blur))
    return Image.alpha_composite(image, layer)


def add_gradient(image, top, bottom, y0):
    """Replace everything from y0 down with a fresh vertical gradient."""
    gradient = vertical_gradient((image.width, image.height - y0), top, bottom).convert('RGBA')
    layer = Image.new('RGBA', image.size, (0, 0, 0, 0))
    layer.paste(gradient, (0, y0))
    return Image.alpha_composite(image, layer)


def pin(draw, centre, radius, fill):
    """A map pin: a circle head with a tapering tip below it."""
    cx, cy = centre
    tip = (cx, cy + radius * 2.15)
    left = (cx - radius * 0.82, cy + radius * 0.36)
    right = (cx + radius * 0.82, cy + radius * 0.36)
    draw.polygon([left, tip, right], fill=fill)
    draw.ellipse((cx - radius, cy - radius, cx + radius, cy + radius), fill=fill)


def make_icon():
    scale = 2
    size = 512 * scale
    image = vertical_gradient((size, size), SKY_TOP, SKY_BOTTOM).convert('RGBA')

    # A soft sun sitting just above the horizon.
    sun_y = int(size * 0.52)
    image = add_glow(image, (int(size * 0.72), sun_y), int(size * 0.3), SUN, 100, int(size * 0.1))
    draw = ImageDraw.Draw(image)
    draw.ellipse((int(size * 0.66), sun_y - int(size * 0.09),
                  int(size * 0.78), sun_y + int(size * 0.09)), fill=SUN + (255,))

    # The ground and two hill layers.
    horizon = int(size * 0.66)
    image = add_gradient(image, GROUND_TOP, GROUND_BOTTOM, horizon)
    draw = ImageDraw.Draw(image)
    draw.polygon([(0, horizon), (int(size * 0.22), int(size * 0.52)), (int(size * 0.48), horizon)],
                 fill=(18, 48, 56, 255))
    draw.polygon([(int(size * 0.38), horizon), (int(size * 0.64), int(size * 0.56)),
                  (int(size * 0.92), horizon)], fill=(14, 39, 47, 255))

    # The pin, with a shadow beneath it and a hole punched through the head.
    cx, cy = int(size * 0.5), int(size * 0.34)
    radius = int(size * 0.17)
    draw.ellipse((cx - radius * 1.3, int(size * 0.86), cx + radius * 1.3, int(size * 0.93)),
                 fill=(0, 0, 0, 70))
    pin(draw, (cx, cy), radius, (250, 250, 248, 255))
    hole = int(radius * 0.46)
    draw.ellipse((cx - hole, cy - hole, cx + hole, cy + hole), fill=(19, 46, 62, 255))

    image = image.resize((512, 512), Image.LANCZOS).convert('RGB')
    image.save(os.path.join(ADDON, 'icon.png'), optimize=True)


def make_fanart():
    width, height = 1920, 1080
    image = vertical_gradient((width, height), (4, 9, 16), (30, 72, 96)).convert('RGBA')
    horizon = 640
    image = add_gradient(image, (7, 20, 24), (4, 11, 14), horizon)
    image = add_glow(image, (1280, 560), 420, SUN, 55, 150)
    draw = ImageDraw.Draw(image)
    draw.ellipse((1220, 500, 1340, 620), fill=SUN + (230,))
    draw.polygon([(0, horizon), (240, 470), (470, horizon)], fill=(12, 33, 43, 255))
    draw.polygon([(330, horizon), (660, 510), (980, horizon)], fill=(9, 26, 35, 255))
    draw.polygon([(760, horizon), (1040, 545), (1340, horizon)], fill=(7, 21, 29, 255))
    # Road to the vanishing point, with a dashed centre line.
    draw.polygon([(760, height), (1160, height), (975, horizon), (945, horizon)],
                 fill=(22, 26, 32, 255))
    for k in range(11):
        y0 = int(height - k * 46 - 34)
        y1 = int(height - k * 46)
        half = int(3 + 13 * (y0 / float(height)))
        draw.rectangle((960 - half, y0, 960 + half, y1), fill=(188, 174, 120, 200))
    pin(draw, (1440, 600), 92, (248, 248, 244, 255))
    draw.ellipse((1440 - 42, 600 - 42, 1440 + 42, 600 + 42), fill=(17, 44, 60, 255))
    image = image.filter(ImageFilter.GaussianBlur(0.4)).convert('RGB')
    image.save(os.path.join(ADDON, 'fanart.jpg'), quality=90, optimize=True)


def make_textures():
    os.makedirs(MEDIA, exist_ok=True)
    white = Image.new('RGBA', (16, 16), (255, 255, 255, 255))
    white.save(os.path.join(MEDIA, 'white.png'), optimize=True)
    shade = Image.new('RGBA', (1920, 460), (0, 0, 0, 0))
    pixels = shade.load()
    for y in range(460):
        alpha = int(200 * (y / 459.0) ** 1.6)
        for x in range(1920):
            pixels[x, y] = (0, 0, 0, alpha)
    shade.save(os.path.join(MEDIA, 'shade.png'), optimize=True)
    make_world_map()
    make_pin()


def countries():
    """The Natural Earth country polygons, downloaded once into the build cache."""
    if not os.path.exists(COUNTRIES):
        os.makedirs(CACHE, exist_ok=True)
        request = urllib.request.Request(NATURAL_EARTH,
                                         headers={'User-Agent': 'GeoGuess-build/0.3'})
        data = urllib.request.urlopen(request, timeout=180).read()
        with open(COUNTRIES, 'wb') as handle:
            handle.write(data)
    with open(COUNTRIES) as handle:
        return json.load(handle)


def _polygons(geometry):
    """The ring lists of a Polygon or of every polygon in a MultiPolygon."""
    if geometry.get('type') == 'Polygon':
        yield geometry.get('coordinates') or []
    elif geometry.get('type') == 'MultiPolygon':
        for polygon in geometry.get('coordinates') or []:
            yield polygon or []


def make_world_map():
    """A dark equirectangular world map: oceans, a 30-degree graticule, land and borders."""
    width, height = MAP_W * MAP_SCALE, MAP_H * MAP_SCALE
    image = Image.new('RGBA', (width, height), OCEAN)
    draw = ImageDraw.Draw(image)

    def xy(point):
        return ((point[0] + 180.0) / 360.0 * width, (90.0 - point[1]) / 180.0 * height)

    for lon in range(-150, 180, 30):
        x = (lon + 180.0) / 360.0 * width
        draw.line([(x, 0), (x, height)], fill=GRID, width=1)
    for lat in range(-60, 90, 30):
        y = (90.0 - lat) / 180.0 * height
        draw.line([(0, y), (width, y)], fill=GRID, width=1)

    features = [f for f in countries().get('features') or [] if f.get('geometry')]
    # Land first, then every outline on top, so borders are not covered by a neighbouring fill.
    for feature in features:
        for polygon in _polygons(feature['geometry']):
            if not polygon:
                continue
            ring = [xy(point) for point in polygon[0]]
            if len(ring) >= 3:
                draw.polygon(ring, fill=LAND)
            for hole in polygon[1:]:
                inner = [xy(point) for point in hole]
                if len(inner) >= 3:
                    draw.polygon(inner, fill=OCEAN)
    for feature in features:
        for polygon in _polygons(feature['geometry']):
            if polygon:
                ring = [xy(point) for point in polygon[0]]
                draw.line(ring + ring[:1], fill=EDGE, width=1, joint='curve')

    draw.rectangle((0, 0, width - 1, height - 1), outline=BORDER, width=2)
    image.convert('RGB').save(os.path.join(MEDIA, 'world.png'), optimize=True)


def make_pin():
    """A red map pin, its tip at the bottom centre so it can sit exactly on the coordinates."""
    scale = 4
    width, height = 44, 62
    w, h = width * scale, height * scale
    cx, head_y, r = w // 2, int(round(18 * scale)), int(round(14 * scale))
    tip = (cx, h)

    def shape(draw, fill, grow):
        rr = int(round(r * grow))
        stem = int(round(rr * 0.34))
        draw.polygon([(cx - int(round(rr * 0.78)), head_y + stem), tip,
                      (cx + int(round(rr * 0.78)), head_y + stem)], fill=fill)
        draw.ellipse((cx - rr, head_y - rr, cx + rr, head_y + rr), fill=fill)

    shadow = Image.new('RGBA', (w, h), (0, 0, 0, 0))
    shape(ImageDraw.Draw(shadow), (0, 0, 0, 255), 1.0)
    shadow = shadow.filter(ImageFilter.GaussianBlur(3 * scale))
    shadow.putalpha(shadow.split()[3].point(lambda a: int(a * 0.4)))

    image = Image.alpha_composite(Image.new('RGBA', (w, h), (0, 0, 0, 0)), shadow)
    draw = ImageDraw.Draw(image)
    shape(draw, (255, 255, 255, 255), 1.14)        # white rim
    shape(draw, (224, 76, 56, 255), 0.9)           # red body
    hole = int(round(4.6 * scale))
    draw.ellipse((cx - hole, head_y - hole, cx + hole, head_y + hole), fill=(255, 255, 255, 255))
    image.resize((width, height), Image.LANCZOS).save(os.path.join(MEDIA, 'pin.png'), optimize=True)


def main():
    make_icon()
    make_fanart()
    make_textures()
    print('media written to %s' % ADDON)


if __name__ == '__main__':
    main()
