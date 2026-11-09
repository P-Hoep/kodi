"""Draws the app's text with the pre-rendered Doto atlases.

Kodi only lets the active skin declare fonts, so an add-on cannot hand a TTF to a label.
The media generator therefore bakes Doto into texture atlases (white with a soft glow in the
alpha channel) and this module turns strings into small RGBA images with the colour baked in.
The images go straight into xbmcgui image controls, which keeps the vintage lettering exact and
still lets the app recolour text per contact (normal, selected, emergency, military, dim).
"""

import json
import math
import os

from . import pngcodec


class TextImage(object):
    """One composed string: an image plus the offsets needed to place it like GL text()."""

    __slots__ = ('path', 'width', 'height', 'text_width', 'dx', 'dy', 'key')

    def __init__(self, path, width, height, text_width, dx, dy, key):
        self.path = path
        self.width = width
        self.height = height
        self.text_width = text_width
        self.dx = dx          # add to the text origin for the control's left edge
        self.dy = dy          # add to y_top for the control's top edge
        self.key = key

    def place(self, x, y, align=0):
        """Control position for text drawn at (x, y_top) with align 0 left, 1 centre, 2 right."""
        if align == 1:
            x -= self.text_width * 0.5
        elif align == 2:
            x -= self.text_width
        return int(round(x + self.dx)), int(round(y + self.dy))

    def right(self):
        return self.dx + self.width


class Glyph(object):
    __slots__ = ('advance', 'pixels')

    def __init__(self, advance, pixels):
        self.advance = advance
        self.pixels = pixels   # [(dx, dy, alpha)]


class Atlas(object):
    def __init__(self, png_path, json_path):
        with open(json_path) as handle:
            meta = json.load(handle)
        self.meta = meta
        self.size = float(meta['size'])
        self.ascent = float(meta['ascent'])
        self.descent = float(meta['descent'])
        self.line_height = float(meta.get('line_height', self.size * 1.35))
        self.cell_w = int(meta['cell_w'])
        self.cell_h = int(meta['cell_h'])
        self.cell_ox = int(meta['cell_ox'])
        self.cell_oy = int(meta['cell_oy'])
        self.columns = int(meta.get('columns', 16))
        with open(png_path, 'rb') as handle:
            width, height, pixels = pngcodec.decode(handle.read())
        self.atlas_w = width
        self.atlas_h = height
        self.glyphs = {}
        fallback = None
        for index, glyph in enumerate(meta.get('glyphs') or []):
            cp = int(glyph.get('cp', -1))
            if cp < 0:
                continue
            col = index % self.columns
            row = index // self.columns
            self.glyphs[cp] = Glyph(float(glyph.get('advance', 0.0)),
                                    self._cell_pixels(pixels, col * self.cell_w, row * self.cell_h))
        self.fallback = self.glyphs.get(ord('?'))
        self.space = self.glyphs.get(ord(' '))
        self.shift = max(0, -int(round(self.ascent + self.cell_oy)))

    def _cell_pixels(self, pixels, x0, y0):
        out = []
        stride = self.atlas_w * 4
        for y in range(self.cell_h):
            base = (y0 + y) * stride + x0 * 4
            for x in range(self.cell_w):
                alpha = pixels[base + x * 4 + 3]
                if alpha:
                    out.append((x, y, alpha))
        return out

    def glyph(self, cp):
        return self.glyphs.get(cp) or self.fallback

    def width(self, text, tracking=0.0):
        total = 0.0
        count = 0
        for char in text:
            glyph = self.glyph(ord(char))
            if glyph is None:
                continue
            if count:
                total += tracking
            total += glyph.advance
            count += 1
        return total


class Renderer(object):
    """Composes strings into PNG files under `workdir`, caching by content and colour."""

    def __init__(self, media_dir, workdir, max_entries=900):
        fonts = os.path.join(media_dir, 'fonts')
        self.atlases = {}
        for name in ('tiny', 'small', 'mid', 'big'):
            png = os.path.join(fonts, 'app_%s.png' % name)
            meta = os.path.join(fonts, 'app_%s.json' % name)
            if os.path.exists(png) and os.path.exists(meta):
                self.atlases[name] = Atlas(png, meta)
        if not self.atlases:
            raise RuntimeError('no font atlases in %s' % fonts)
        self.workdir = workdir
        self.max_entries = max_entries
        self.cache = {}
        self.order = []
        self.counter = 0
        self.protected = set()
        self._doomed = []
        os.makedirs(workdir, exist_ok=True)
        self._clear_old_files()

    def _clear_old_files(self):
        # The text images are a cache, not content: start each session from an empty directory.
        try:
            for name in os.listdir(self.workdir):
                if name.startswith('t') and name.endswith('.png'):
                    try:
                        os.remove(os.path.join(self.workdir, name))
                    except OSError:
                        pass
        except OSError:
            pass

    def protect(self, keys):
        """Mark the images currently on screen; they are never evicted or deleted."""
        self.protected = set(keys)

    def atlas(self, name):
        if name in self.atlases:
            return self.atlases[name]
        if name == 'tiny' and 'small' in self.atlases:
            return self.atlases['small']
        return next(iter(self.atlases.values()))

    def width(self, text, name='small', tracking=0.0):
        return self.atlas(name).width(text, tracking)

    def image(self, text, name='small', color=(255, 255, 255), tracking=0.0, alpha=1.0):
        atlas = self.atlas(name)
        key = (text, name, tuple(color), round(tracking, 2), round(alpha, 2))
        hit = self.cache.get(key)
        if hit is not None:
            return hit
        image = self._render(atlas, text, color, tracking, alpha, key)
        self.cache[key] = image
        self.order.append(key)
        if len(self.order) > self.max_entries:
            self._trim()
        return image

    def _trim(self):
        # Files evicted last time are unlinked now, so Kodi has had a frame to load them.
        doomed, self._doomed = self._doomed, []
        for path in doomed:
            try:
                os.remove(path)
            except OSError:
                pass
        attempts = 0
        while len(self.order) > self.max_entries and attempts < len(self.order):
            key = self.order[0]
            if key in self.protected:
                self.order.append(self.order.pop(0))
                attempts += 1
                continue
            attempts = 0
            self.order.pop(0)
            image = self.cache.pop(key, None)
            if image is not None:
                self._doomed.append(image.path)

    def _render(self, atlas, text, color, tracking, alpha, key):
        text_width = atlas.width(text, tracking)
        width = int(math.ceil(text_width)) + 2 * atlas.cell_ox + 2
        width = max(width, 2)
        height = int(math.ceil(max(atlas.cell_h + atlas.shift, atlas.line_height + atlas.shift)))
        height = max(height, 2)
        canvas = bytearray(width * height * 4)
        red, green, blue = color
        pen = float(atlas.cell_ox)
        first = True
        top = atlas.shift + int(round(atlas.ascent + atlas.cell_oy))
        for char in text:
            glyph = atlas.glyph(ord(char))
            if glyph is None:
                continue
            if not first:
                pen += tracking
            if char != ' ':
                gx = int(round(pen - atlas.cell_ox))
                for dx, dy, value in glyph.pixels:
                    x = gx + dx
                    if x < 0 or x >= width:
                        continue
                    y = top + dy
                    if y < 0 or y >= height:
                        continue
                    source = int(value * alpha)
                    if source <= 0:
                        continue
                    index = (y * width + x) * 4
                    dest = canvas[index + 3]
                    if dest:
                        source = source + (dest * (255 - source)) // 255
                    canvas[index] = red
                    canvas[index + 1] = green
                    canvas[index + 2] = blue
                    canvas[index + 3] = source
            pen += glyph.advance
            first = False
        path = os.path.join(self.workdir, 't%05d.png' % self.counter)
        self.counter += 1
        with open(path, 'wb') as handle:
            handle.write(pngcodec.encode_rgba(width, height, canvas))
        return TextImage(path, width, height, text_width, -atlas.cell_ox,
                         -atlas.shift, key)
