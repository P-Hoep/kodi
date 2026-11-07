"""The detail view (spec 5), in the same window as the board so the tile can expand into it:

1. a solid "zoomer" in the tile's colour grows from the tile's rectangle to full screen
   (a Kodi zoom animation set with setAnimations, centred so the full-screen rect maps onto
   the tile), while the board zooms back to 95 % and fades (XML, on the detail property);
2. the detail layer fades in on top;
3. Back reverses it into the tile.
"""

import time

import xbmc
import xbmcgui

from .. import kodi, qr, theme
from ..feeds import sanitize
from ..tiles import geometry as g, styles, text
from . import screen as sc

BODY_LINES_STEP = 4
HEADLINE_FONT = 'font45'
LEFT_W = int(g.SCREEN_W * 0.55)
RIGHT_W = g.SCREEN_W - LEFT_W - 64 - 80


def zoom_params(rect):
    """Zoom start (percent) and centre that map the full screen onto rect = (x, y, w, h)."""
    x, y, w, h = rect
    sx, sy = w * 100.0 / g.SCREEN_W, h * 100.0 / g.SCREEN_H
    cx = x / (1 - sx / 100.0) if sx < 99.9 else x
    cy = y / (1 - sy / 100.0) if sy < 99.9 else y
    return sx, sy, int(round(cx)), int(round(cy))


class Detail(object):
    def __init__(self, screen, board, settings, on_other=None):
        self.screen = screen
        self.on_other = on_other or (lambda event: None)
        self.board = board
        self.settings = settings
        self.body = screen.control(g.DETAIL_BODY)
        self.byline = screen.control(972)
        self.zoomer = screen.control(g.ZOOMER)
        self.items = []
        self.index = 0
        self.tile = None
        self.line = 0

    def prop(self, key, value):
        self.board.prop(key, value)

    def open(self, tile, items, index, source):
        """Expand tile into the detail view and run it until Back. Returns an action for the
        caller ('menu' for the context menu) or None."""
        self.tile = tile
        self.items = items
        self.index = index
        self.source = source
        rect = self.board.screen_rect(tile)
        sx, sy, cx, cy = zoom_params(rect)
        colour = styles.colours(self.board.style, tile.colour, self.board.palette)['bg']
        if self.board.style == 'outline':
            colour = theme.argb(tile.colour)
        self.prop('d.zcolor', colour)
        self.prop('d.accent', theme.argb(tile.colour))
        self.prop('d.accent_text', self.accent_text(tile.colour))
        anims = [
            ('visible', 'effect=zoom start=%.2f,%.2f end=100,100 center=%d,%d time=%d tween=cubic easing=out'
             % (sx, sy, cx, cy, g.EXPAND_MS)),
            ('hidden', 'effect=zoom start=100,100 end=%.2f,%.2f center=%d,%d time=%d tween=cubic easing=in'
             % (sx, sy, cx, cy, g.EXPAND_MS - 50)),
            ('hidden', 'effect=fade start=100 end=0 time=120 delay=%d' % (g.EXPAND_MS - 120)),
        ]
        if self.zoomer is not None:
            self.zoomer.setAnimations(anims)
        self.show(self.index)
        self.prop('zoom', '1')
        self.prop('detail', '1')
        try:
            return self.loop()
        finally:
            self.prop('detail', '')
            time.sleep(0.1)
            self.prop('zoom', '')
            time.sleep(g.EXPAND_MS / 1000.0)

    def accent_text(self, hexa):
        """The accent as text on the detail panel; lightened / darkened when it would not read."""
        panel = self.board.palette['panel'][2:]
        colour = hexa
        for _ in range(6):
            if theme.contrast(colour, panel) >= 3.0:
                break
            colour = theme.shade(colour, 0.25 if theme.luminance(panel) < 0.2 else -0.25)
        return theme.argb(colour)

    # ------------------------------------------------------------ content

    def show(self, index):
        item = self.items[index]
        self.index = index
        src = self.source
        show_images = self.settings.get('show_images', True)
        self.prop('d.img', item.images[0].url if item.images and show_images else '')
        self.prop('d.icon', src.icon if src else '')
        self.prop('d.ini', text.initials(src.title if src else ''))
        self.prop('d.source', src.title if src else '')
        title, lines = text.fit(item.title, RIGHT_W, g.FONT_PX[HEADLINE_FONT], 3)
        self.prop('d.title', title)
        bits = []
        if item.author:
            bits.append(item.author)
        if item.dated:
            stamp = time.localtime(item.published)
            bits.append(text.relative(item.published, time.time(), kodi.relative_strings()).capitalize()
                        + time.strftime('  ·  %d %b %Y, %H:%M', stamp))
        self.prop('d.byline', '  ·  '.join(bits))
        body = sanitize.to_kodi(item.content_html) or item.summary
        self.prop('d.body', body)
        media = item.media
        self.prop('d.play', '1' if media else '')
        self.prop('d.pos', kodi.tr(32021) % (index + 1, len(self.items)))
        self.prop('d.qr', self.qr_for(item.link) if self.settings.get('show_qr', True) else '')
        # The headline is 1-3 lines; the byline and body move up under it.
        lh = g.line_px(HEADLINE_FONT)
        top = 110 + max(1, lines) * lh + 18
        if self.byline is not None:
            self.byline.setPosition(LEFT_W + 64, top)
        if self.body is not None:
            self.body.setPosition(LEFT_W + 64, top + 52)
            self.body.setHeight(820 - (top + 52))
            self.line = 0
            try:
                self.body.scroll(0)
            except Exception:
                pass

    def qr_for(self, link):
        if not link or not link.startswith(('http://', 'https://')):
            return ''
        try:
            return qr.write(link, kodi.store().qr_path(link))
        except Exception as err:
            kodi.log('QR code failed: %s' % err)
            return ''

    def step(self, delta):
        target = self.index + delta
        if not 0 <= target < len(self.items):
            return
        self.prop('dswap', 'next' if delta > 0 else 'prev')
        time.sleep(0.16)
        self.show(target)
        self.prop('dswap', '')

    def scroll(self, delta):
        if self.body is None:
            return
        self.line = max(0, self.line + delta)
        try:
            self.body.scroll(self.line)
        except Exception:
            pass

    def play(self):
        item = self.items[self.index]
        media = item.media
        if not media:
            return
        li = xbmcgui.ListItem(item.title)
        li.setArt({'thumb': item.image, 'fanart': item.image})
        tag = li.getMusicInfoTag() if media.kind == 'audio' else li.getVideoInfoTag()
        try:
            tag.setTitle(item.title)
        except Exception:
            pass
        xbmc.Player().play(media.url, li)

    def loop(self):
        while True:
            event = self.screen.wait(1.0)
            if event is None:
                continue
            kind, value = event[0], event[1] if len(event) > 1 else None
            if kind not in ('action', 'click'):
                self.on_other(event)
                continue
            if kind == 'click' or (kind == 'action' and value in (sc.ACTION_SELECT, sc.ACTION_PLAYER_PLAY)):
                self.play()
            elif kind == 'action':
                if value in sc.BACK_ACTIONS:
                    return None
                if value == sc.ACTION_RIGHT:
                    self.step(1)
                elif value == sc.ACTION_LEFT:
                    self.step(-1)
                elif value in (sc.ACTION_DOWN, sc.ACTION_SCROLL_DOWN, sc.ACTION_MOUSE_WHEEL_DOWN):
                    self.scroll(BODY_LINES_STEP)
                elif value in (sc.ACTION_UP, sc.ACTION_SCROLL_UP, sc.ACTION_MOUSE_WHEEL_UP):
                    self.scroll(-BODY_LINES_STEP)
                elif value == sc.ACTION_PAGE_DOWN:
                    self.scroll(3 * BODY_LINES_STEP)
                elif value == sc.ACTION_PAGE_UP:
                    self.scroll(-3 * BODY_LINES_STEP)
                elif value in sc.MENU_ACTIONS:
                    return 'menu'

    @property
    def current(self):
        return self.items[self.index] if self.items else None
