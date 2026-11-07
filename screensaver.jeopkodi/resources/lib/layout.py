"""Lay text out in pre-rendered glyph images. No Kodi imports.

metrics.json (written by tools/make_jeopkodi_media.py) has, for the font size the glyphs were
drawn at (SIZE): every glyph's advance, left bearing and image width, the kerning pairs, the
image height and the baseline. A line is the glyph images placed side by side, so wrapping and
centring need no text measuring at run time.
"""

import json
import re
import unicodedata

LINE_PITCH = 1.14        # line spacing in ems


class Font(object):
    def __init__(self, path):
        with open(path) as f:
            m = json.load(f)
        self.size = float(m['size'])
        self.height = m['height']
        self.space = m['space']
        self.adv = dict((int(k), v) for k, v in m['adv'].items())
        self.kern = dict((tuple(int(x) for x in k.split(',')), v) for k, v in m['kern'].items())

    def codes(self, text):
        """The character codes of text that have glyphs; accents the font lacks fall back to the
        plain letter, anything else is dropped. Spaces are 32."""
        out = []
        for ch in text:
            code = ord(ch)
            if ch == ' ' or code in self.adv:
                out.append(code)
                continue
            base = unicodedata.normalize('NFKD', ch).encode('ascii', 'ignore').decode()
            out.extend(ord(c) for c in base if c == ' ' or ord(c) in self.adv)
        return out

    def advance(self, code, nxt=None):
        if code == 32:
            return self.space
        a = self.adv[code][0]
        if nxt is not None and nxt != 32:
            a += self.kern.get((code, nxt), 0)
        return a

    def word_width(self, word):
        return sum(self.advance(c, word[i + 1] if i + 1 < len(word) else None) for i, c in enumerate(word))


def words_of(font, text):
    return [w for w in (font.codes(p) for p in re.split(r'\s+', text.strip())) if w]


def wrap(font, words, limit):
    """Greedy wrap; limit is in glyph units (ems times font.size). Returns lines of word lists."""
    lines, cur, width = [], [], 0.0
    for w in words:
        ww = font.word_width(w)
        add = ww if not cur else font.space + ww
        if cur and width + add > limit:
            lines.append(cur)
            cur, width = [w], ww
        else:
            cur.append(w)
            width += add
    if cur:
        lines.append(cur)
    return lines


def line_width(font, line):
    return sum(font.word_width(w) for w in line) + font.space * (len(line) - 1)


def fit(font, text, box_w, box_h, max_px, min_px):
    """Pick the biggest font size (px, within [min_px, max_px]) at which text fits the box, then
    narrow the wrap width so the lines come out about equally long, like on the show.
    Returns (px, lines) where lines are lists of words (lists of character codes)."""
    words = words_of(font, text)
    if not words:
        return min_px, []
    widest = max(font.word_width(w) for w in words)
    px = max_px
    while True:
        scale = px / font.size
        limit = box_w / scale
        lines = wrap(font, words, max(limit, widest if px <= min_px else 0))
        if (len(lines) * px * LINE_PITCH <= box_h and widest <= limit) or px <= min_px:
            break
        px -= 2
    # balance: the narrowest wrap that keeps the same number of lines
    lo, hi, n = max(widest, 1.0), box_w / (px / font.size), len(lines)
    for _ in range(14):
        mid = (lo + hi) / 2
        if len(wrap(font, words, mid)) <= n:
            hi = mid
        else:
            lo = mid
    lines = wrap(font, words, max(hi, widest))
    return px, lines


def place(font, lines, px, cx, top):
    """Glyph rectangles for centred lines: [(code, x, y, w, h)], x, y of the image's top left."""
    scale = px / font.size
    out = []
    for i, line in enumerate(lines):
        x = cx - line_width(font, line) * scale / 2
        y = top + i * px * LINE_PITCH
        flat = []
        for j, w in enumerate(line):
            if j:
                flat.append(32)
            flat.extend(w)
        for k, code in enumerate(flat):
            if code != 32:
                adv, left, width = font.adv[code]
                out.append((code, x - left * scale, y, width * scale, font.height * scale))
            x += font.advance(code, flat[k + 1] if k + 1 < len(flat) else None) * scale
    return out


def block_height(lines, px):
    return len(lines) * px * LINE_PITCH
