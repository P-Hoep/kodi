"""Sensor looks, after God's Eye View's GLSL styles. No Kodi imports.

Kodi can't run shaders, so each look is built from what a Python screensaver can do:
  * a colour tint Kodi multiplies into every map tile (night vision, CRT) — any base map;
  * recolouring OpenStreetMap tiles when they are cached (FLIR, ironbow, noir). OSM tiles
    are 8-bit palette PNGs, so recolouring rewrites 256 palette entries, not 65k pixels;
  * full-screen overlay images: vignette, scanlines, animated grain.
"""

import struct
import zlib


class Look(object):
    def __init__(self, lid, name, tile_tint=None, recolor=None, marker_color=None,
                 vignette=0, scanlines=0, grain=0):
        self.id = lid
        self.name = name
        self.tile_tint = tile_tint        # ARGB multiplied into tiles, e.g. 'FF29FF38'
        self.recolor = recolor            # f(r, g, b) -> (r, g, b) for palette tiles
        self.marker_color = marker_color  # ARGB for every marker, or None to keep layer colours
        self.vignette = vignette          # overlay opacities, 0-255
        self.scanlines = scanlines
        self.grain = grain

    @property
    def badge_color(self):
        """Tint for detailed icons (home, bus badges). A near-black marker colour (black-hot)
        would hide their doors, windows and windscreens, so those stay white."""
        c = self.marker_color
        if c and int(c[2:4], 16) + int(c[4:6], 16) + int(c[6:8], 16) < 200:
            return 'FFFFFFFF'
        return c


# ---------------------------------------------------------------- tile recolouring

def _luma(r, g, b):
    return (0.299 * r + 0.587 * g + 0.114 * b) / 255.0


def heat(r, g, b):
    """A made-up "temperature" 0-1 for an OpenStreetMap colour, so the street map reads
    like a thermal image: roads and buildings warm, land cool, water and parks cold."""
    luma = _luma(r, g, b)
    hi, lo = max(r, g, b), min(r, g, b)
    saturation = (hi - lo) / float(hi) if hi else 0.0
    if luma < 0.45:
        return 0.04            # text, borders, rail lines: cold black outlines
    if b > r + 15 and b >= g:
        return 0.12            # water
    if g > r + 8 and g >= b:
        return 0.30            # parks, woods, grass
    if saturation > 0.25:
        return 0.97            # coloured roads (motorways, primaries)
    if luma > 0.985:
        return 0.82            # white minor roads
    if luma < 0.85:
        return 0.66            # buildings
    if luma < 0.90:
        return 0.50            # residential and other built-up areas
    return 0.32                # bare land


def _gray(v):
    v = int(round(max(0.0, min(1.0, v)) * 255))
    return v, v, v


IRONBOW = [(0.0, 0.0, 0.0), (0.13, 0.0, 0.30), (0.49, 0.0, 0.45), (0.86, 0.10, 0.18),
           (1.0, 0.55, 0.0), (1.0, 0.91, 0.32), (1.0, 1.0, 1.0)]


def ironbow(t):
    """God's Eye View's ironbow ramp: black, purple, magenta, red, orange, yellow, white."""
    s = max(0.0, min(1.0, t)) * (len(IRONBOW) - 1)
    i = min(int(s), len(IRONBOW) - 2)
    f = s - i
    a, b = IRONBOW[i], IRONBOW[i + 1]
    return tuple(int(round((a[k] + (b[k] - a[k]) * f) * 255)) for k in range(3))


def white_hot(r, g, b):
    return _gray(heat(r, g, b))


def black_hot(r, g, b):
    return _gray(1.0 - heat(r, g, b))


def ironbow_color(r, g, b):
    return ironbow(heat(r, g, b))


def noir(r, g, b):
    # Desaturate, then stretch the narrow band of light OSM tones into deep shadows and
    # bright highlights: buildings go near-black, open land mid-grey, roads bright.
    v = (_luma(r, g, b) - 0.90) * 3.5 + 0.45
    v = max(0.0, min(1.0, v))
    return _gray(v * v * (3 - 2 * v))


LOOKS = [
    Look('off', 'Off'),
    Look('nvg', 'Night vision', tile_tint='FF29FF38', marker_color='FFC8FFC0',
         vignette=235, grain=70),
    Look('crt', 'CRT terminal', tile_tint='FFFFF5EF', vignette=170, scanlines=110, grain=25),
    Look('flir_white', 'FLIR white-hot', recolor=white_hot, marker_color='FFFFFFFF',
         vignette=150, grain=45),
    Look('flir_black', 'FLIR black-hot', recolor=black_hot, marker_color='FF000000',
         vignette=110, grain=45),
    Look('ironbow', 'Ironbow thermal', recolor=ironbow_color, marker_color='FFFFF59D',
         vignette=150, grain=35),
    Look('noir', 'Noir', recolor=noir, marker_color='FFFFFFFF', vignette=200, grain=55),
]


def by_index(index):
    return LOOKS[index] if 0 <= index < len(LOOKS) else LOOKS[0]


# ---------------------------------------------------------------- PNG palette rewrite

PNG_SIGNATURE = b'\x89PNG\r\n\x1a\n'


def recolor_palette_png(data, fn):
    """Return data with every PLTE entry passed through fn, or None if it isn't a palette PNG."""
    if not data.startswith(PNG_SIGNATURE):
        return None
    out = [PNG_SIGNATURE]
    i = len(PNG_SIGNATURE)
    palette_done = False
    while i + 8 <= len(data):
        length, kind = struct.unpack('>I4s', data[i:i + 8])
        body = data[i + 8:i + 8 + length]
        if kind == b'IHDR' and body[9] != 3:
            return None  # not colour type 3 (palette)
        if kind == b'PLTE':
            colours = bytearray()
            for p in range(0, len(body) - 2, 3):
                colours.extend(bytes(fn(body[p], body[p + 1], body[p + 2])))
            body = bytes(colours)
            palette_done = True
        out.append(struct.pack('>I4s', len(body), kind) + body
                   + struct.pack('>I', zlib.crc32(kind + body) & 0xFFFFFFFF))
        i += 12 + length
        if kind == b'IEND':
            break
    return b''.join(out) if palette_done else None
