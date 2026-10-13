"""A scene's screen content as plain data, so scenes can be built (and tested) without Kodi.
window.py maps each item onto a pooled Kodi control. No Kodi imports.

Coordinates are Kodi's 1920x1080 skin space. Fonts are size keys mapped to the skin's fonts
in window.py; colours are Kodi's AARRGGBB hex. Big numbers are built from pre-rendered
glyph images (media/glyphs) because skin fonts top out around 60 px.
"""

import json
import os

FONTS = ('xs', 'sm', 'md', 'lg', 'xl')
ALIGN = ('left', 'center', 'right')

WHITE = 'FFFFFFFF'
SOFT = 'FFC9D4E0'
DIM = 'B08FA3B8'
ACCENT = 'FF4FC3F7'
WARM = 'FFFFB74D'
COOL = 'FF64B5F6'
GOOD = 'FF69F0AE'
BAD = 'FFFF6E6E'
CARD = '66101C2C'


class Layout(object):
    def __init__(self, title='', background='bg.jpg'):
        self.title = title
        self.background = background
        self.items = []
        self.textbox = None      # (x, y, w, h, text) scrolling text, one per scene

    def label(self, x, y, w, h, text, font='sm', align='left', color=WHITE):
        self.items.append(('label', int(x), int(y), int(w), int(h), text, font, align, color))

    def image(self, x, y, w, h, path, color=None, aspect=0, rotate=0):
        self.items.append(('image', int(x), int(y), int(w), int(h), path, color, aspect, rotate))

    def rect(self, x, y, w, h, color):
        self.image(x, y, w, h, 'white.png', color)

    def card(self, x, y, w, h, color=CARD):
        self.image(x, y, w, h, 'card.png', color)

    def scroll(self, x, y, w, h, text):
        self.textbox = (int(x), int(y), int(w), int(h), text)

    def big(self, text, x, y, height, align='left', color=WHITE, weight='light'):
        """Glyph-image text; returns its width."""
        glyphs = Glyphs.get()
        width = glyphs.width(text, height, weight)
        if align == 'center':
            x -= width / 2.0
        elif align == 'right':
            x -= width
        scale = height / float(glyphs.height)
        cx = x
        for ch in text:
            advance, name = glyphs.table(weight).get(ch, (glyphs.height * 0.3, None))
            w = advance * scale
            if name:
                self.image(cx, y, w + 1, height, 'glyphs/' + name, color)
            cx += w
        return width

    def count(self):
        """Controls needed per kind, for sizing pools: {('label', font, align): n, 'image': n}."""
        out = {}
        for item in self.items:
            key = ('label', item[6], item[7]) if item[0] == 'label' else 'image'
            out[key] = out.get(key, 0) + 1
        return out

    def shifted(self, dx, dy):
        """A copy moved by (dx, dy): OLED pixel shift and the alert banner inset."""
        out = Layout(self.title, self.background)
        out.textbox = None if self.textbox is None else (self.textbox[0] + dx, self.textbox[1] + dy) + self.textbox[2:]
        for item in self.items:
            out.items.append((item[0], item[1] + dx, item[2] + dy) + item[3:])
        return out


class Glyphs(object):
    _instance = None
    media = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'media')

    def __init__(self):
        with open(os.path.join(self.media, 'glyphs', 'metrics.json')) as f:
            data = json.load(f)
        self.height = data['height']
        self.fonts = dict((k, dict((ch, tuple(v)) for ch, v in t.items())) for k, t in data['fonts'].items())

    @classmethod
    def get(cls):
        if cls._instance is None:
            cls._instance = Glyphs()
        return cls._instance

    def table(self, weight):
        return self.fonts.get(weight) or self.fonts['light']

    def width(self, text, height, weight='light'):
        t = self.table(weight)
        return sum(t.get(ch, (self.height * 0.3, None))[0] for ch in text) * height / float(self.height)
