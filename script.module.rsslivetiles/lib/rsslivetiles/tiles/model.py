"""Tiles and what they show.

A Source is one feed as the layouts see it: its config, its cached data, the items to show
(hidden ones removed) and how many are new since the user last looked.

A Tile is one rectangle on the board:
  feed    one per feed (Feed groups / Spotlight); cycles through the feed's latest items
  item    a single article; image tiles peek to their text, text tiles flip to a summary
  count   small: the feed icon and how many items are new; pulses when the count changes
  thumb   small: just an item's picture (fills holes in walls)
  clock   the screensaver's clock
"""

from . import geometry

KINDS = ('feed', 'item', 'count', 'thumb', 'clock')


class Source(object):
    def __init__(self, feed, data, items, new_count=0, accent='0050EF'):
        self.feed = feed
        self.data = data
        self.items = items
        self.new_count = new_count
        self.accent = accent

    @property
    def id(self):
        return self.feed.id

    @property
    def title(self):
        return self.feed.title or (self.data.info.title if self.data else '') or self.feed.url

    @property
    def icon(self):
        return self.data.info.image if self.data else ''

    @property
    def error(self):
        return self.data.error if self.data else ''

    def image_items(self):
        return [i for i in self.items if i.images]


class Tile(object):
    def __init__(self, tid, kind, size, source=None, items=None, notitle=False):
        self.id = tid
        self.kind = kind
        self.size = size
        self.source = source
        self.items = list(items or [])
        self.notitle = notitle          # Mosaic: picture only until it peeks
        self.cursor = 0                 # feed tiles: which item is showing
        self.side = 'front'             # item / count tiles: front or back face
        self.colour = source.accent if source else '0050EF'
        self.band = self.col = self.row = 0
        self.x = self.y = 0             # position on the strip, in px
        self.group = 0
        self.slot = None                # the window slot showing it, when bound
        self.shown_at = 0.0             # when its content last changed (screensaver rotation)
        self.count = source.new_count if source else 0

    @property
    def w(self):
        return geometry.PIXELS[self.size][0]

    @property
    def h(self):
        return geometry.PIXELS[self.size][1]

    @property
    def item(self):
        if not self.items:
            return None
        return self.items[self.cursor % len(self.items)]

    @property
    def live(self):
        """Can this tile animate by itself?"""
        if self.kind == 'feed':
            return len(self.items) > 1
        if self.kind == 'item':
            item = self.item
            if item is None:
                return False
            if item.images and not self.size == 'small':
                return True
            return bool(item.summary) and self.size != 'small'
        if self.kind == 'count':
            return True
        return False

    def __repr__(self):
        return 'Tile(%s %s %s @%d,%d)' % (self.id, self.kind, self.size, self.x, self.y)


class Layout(object):
    """The output of a layout strategy: placed tiles, group headers and the strip width.
    pages: x positions the program snaps to (Spotlight), empty for free scrolling."""

    def __init__(self, name, tiles, headers, width, pages=None):
        self.name = name
        self.tiles = tiles
        self.headers = headers          # [(x, text)]
        self.width = width
        self.pages = pages or []

    def find(self, tile_id):
        for t in self.tiles:
            if t.id == tile_id:
                return t
        return None
