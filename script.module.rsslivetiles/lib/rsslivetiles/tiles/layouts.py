"""Layout strategies (spec 4.1a). Each turns the feeds (Sources) into placed Tiles with the
packing engine. ctx keys:

  rows        tile rows (6 in the program, 7 in the screensaver)
  left, top   where the first band starts
  max_bands   None in the program (the hub scrolls); the screen's width in the screensaver
  show_images False draws every tile as text
  clock       add a clock tile (screensaver)
  limit       most item tiles in a wall (program)
  group_items item tiles per feed group (Feed groups)
  shade       alternate text tiles between the accent and a darker tint
"""

from .. import theme
from . import geometry as g
from .layout import Packer
from .model import Layout, Tile

NAMES = ('feed_groups', 'mixed_wall', 'magazine', 'spotlight', 'mosaic')
WALL_PATTERN = ('large', 'medium', 'wide', 'medium', 'medium', 'wide', 'medium', 'large', 'medium', 'wide')
MOSAIC_PATTERN = ('large', 'medium', 'small', 'small', 'wide', 'medium', 'small', 'small', 'medium', 'large',
                  'small', 'wide', 'small', 'medium')
PAGE_GAP = g.SCREEN_W - g.SS_BANDS * g.BAND_STEP
SMALLER = {'large': ('wide', 'medium'), 'wide': ('medium',), 'medium': (), 'small': ()}


def _has_image(item, ctx):
    return ctx.get('show_images', True) and bool(item.images)


def _colour(tiles, ctx):
    """Shade variation: alternate the accent within each group / source."""
    counters = {}
    for t in tiles:
        if t.source is None:
            continue
        key = (t.group, t.source.id)
        n = counters.get(key, 0)
        counters[key] = n + 1
        t.colour = theme.tile_colour(t.source.accent, n, ctx) if ctx.get('shade', True) else t.source.accent


def _packer(ctx, group_bands=None, gap=g.GROUP_GAP):
    return Packer(ctx.get('rows', g.HUB_ROWS), ctx.get('left', g.MARGIN_X), ctx.get('top', g.HUB_TOP),
                  ctx.get('max_bands'), group_bands, gap)


def _place_fallback(packer, tile):
    """Try the tile's size, then smaller ones (walls on a fixed-size screen)."""
    if packer.place(tile):
        return True
    for size in SMALLER.get(tile.size, ()):
        tile.size = size
        if packer.place(tile):
            return True
    return False


def _newest(sources, ctx):
    items = []
    for src in sources:
        for item in src.items:
            items.append((item, src))
    items.sort(key=lambda pair: pair[0].published, reverse=True)
    return items


def _fill_holes(packer, tiles, extra_items, sources, ctx, used):
    """Fill free 1x1 cells: count tiles for feeds first (screensaver walls), then thumbnails."""
    if ctx.get('counts_in_holes'):
        for src in sources:
            if not packer.holes():
                break
            tid = 'c:' + src.id
            if tid in used:
                continue
            tile = Tile(tid, 'count', 'small', src)
            if packer.place(tile):
                tiles.append(tile)
                used.add(tid)
    for item, src in extra_items:
        if not packer.holes():
            break        # never open a band just for thumbnails
        if not _has_image(item, ctx):
            continue
        tid = 't:' + item.id
        if tid in used or ('i:' + item.id) in used:
            continue
        tile = Tile(tid, 'thumb', 'small', src, [item])
        if packer.place(tile):
            tiles.append(tile)
            used.add(tid)


def _clock(packer, tiles, ctx):
    if ctx.get('clock'):
        tile = Tile('clock', 'clock', 'medium')
        if packer.place(tile):
            tiles.append(tile)


# ------------------------------------------------------------------ strategies

def feed_groups(sources, ctx):
    packer = _packer(ctx)
    tiles, headers = [], []
    per_group = ctx.get('group_items', 4)
    for src in sources:
        packer.new_group()
        group_tiles = [Tile('f:' + src.id, 'feed', src.feed.tile_size or 'wide', src, src.items),
                       Tile('c:' + src.id, 'count', 'small', src)]
        for item in src.items[1:1 + per_group]:
            group_tiles.append(Tile('i:' + item.id, 'item', 'medium', src, [item]))
        placed = []
        for tile in group_tiles:
            if packer.place(tile):
                placed.append(tile)
        used = set(t.id for t in placed)
        rest = [(i, src) for i in src.items[1 + per_group:]]
        _fill_holes(packer, placed, rest, [src], ctx, used)
        tiles += placed
        x0, _x1 = packer.group_x(packer.group)
        if x0 is not None:
            headers.append((x0, src.title))
    _colour(tiles, ctx)
    return Layout('feed_groups', tiles, headers, packer.width)


def mixed_wall(sources, ctx):
    packer = _packer(ctx)
    packer.new_group()
    tiles = []
    _clock(packer, tiles, ctx)
    newest = _newest(sources, ctx)
    limit = ctx.get('limit', 48) if ctx.get('max_bands') is None else 10 ** 6
    used = set()
    shown = 0
    pattern = 0
    leftovers = []
    for item, src in newest:
        if shown >= limit:
            leftovers.append((item, src))
            continue
        if _has_image(item, ctx):
            size = WALL_PATTERN[pattern % len(WALL_PATTERN)]
            pattern += 1
        else:
            size = 'medium'
        tile = Tile('i:' + item.id, 'item', size, src, [item])
        if _place_fallback(packer, tile):
            tiles.append(tile)
            used.add(tile.id)
            shown += 1
        else:
            leftovers.append((item, src))
            if ctx.get('max_bands') is not None and not packer.holes():
                break
    _fill_holes(packer, tiles, leftovers, sources, dict(ctx, counts_in_holes=True), used)
    _colour(tiles, ctx)
    return Layout('mixed_wall', tiles, [], packer.width)


def magazine(sources, ctx):
    packer = _packer(ctx)
    packer.new_group()
    tiles = []
    _clock(packer, tiles, ctx)
    newest = _newest(sources, ctx)
    with_image = [p for p in newest if _has_image(p[0], ctx)]
    order = []
    if with_image:
        order.append((with_image[0], 'large'))
    rest = [p for p in newest if not order or p[0] is not order[0][0][0]]
    # Prefer pictures for the column of wide tiles.
    wide = [p for p in rest if _has_image(p[0], ctx)][:4]
    wide_ids = set(id(p[0]) for p in wide)
    for p in wide:
        order.append((p, 'wide'))
    for p in rest:
        if id(p[0]) not in wide_ids:
            order.append((p, 'medium'))
    limit = ctx.get('limit', 48) if ctx.get('max_bands') is None else 10 ** 6
    used = set()
    leftovers = []
    for (item, src), size in order:
        if len(used) >= limit:
            leftovers.append((item, src))
            continue
        tile = Tile('i:' + item.id, 'item', size, src, [item])
        if _place_fallback(packer, tile):
            tiles.append(tile)
            used.add(tile.id)
        else:
            leftovers.append((item, src))
    _fill_holes(packer, tiles, leftovers, sources, dict(ctx, counts_in_holes=True), used)
    _colour(tiles, ctx)
    return Layout('magazine', tiles, [], packer.width)


def spotlight(sources, ctx):
    """One feed per page; a page is 3 bands and pages are exactly one screen apart, so the
    program and the screensaver can snap from page to page."""
    packer = _packer(dict(ctx, max_bands=None), group_bands=g.SS_BANDS, gap=PAGE_GAP)
    tiles, headers, pages = [], [], []
    for src in sources:
        if not src.items and not src.error:
            continue
        packer.new_group()
        page = []
        items = list(src.items)
        hero = next((i for i in items if _has_image(i, ctx)), items[0] if items else None)
        if hero is None:
            page.append(Tile('f:' + src.id, 'feed', 'large', src, []))
        else:
            items.remove(hero)
            page.append(Tile('i:' + hero.id, 'item', 'large', src, [hero]))
        for item in items[:3]:
            page.append(Tile('i:' + item.id, 'item', 'wide', src, [item]))
        page.append(Tile('c:' + src.id, 'count', 'small', src))
        for item in items[3:12]:
            page.append(Tile('i:' + item.id, 'item', 'medium', src, [item]))
        placed = [t for t in page if packer.place(t)]
        used = set(t.id for t in placed)
        _fill_holes(packer, placed, [(i, src) for i in items[12:]], [src], ctx, used)
        tiles += placed
        x0, _x1 = packer.group_x(packer.group)
        if x0 is not None:
            headers.append((x0, src.title))
            pages.append(x0)
    _colour(tiles, ctx)
    return Layout('spotlight', tiles, headers, packer.width, pages)


def mosaic(sources, ctx):
    newest = [p for p in _newest(sources, ctx) if _has_image(p[0], ctx)]
    if not newest:
        return mixed_wall(sources, ctx)
    packer = _packer(ctx)
    packer.new_group()
    tiles = []
    _clock(packer, tiles, ctx)
    limit = ctx.get('limit', 60) if ctx.get('max_bands') is None else 10 ** 6
    for n, (item, src) in enumerate(newest):
        if len(tiles) >= limit:
            break
        size = MOSAIC_PATTERN[n % len(MOSAIC_PATTERN)]
        kind = 'thumb' if size == 'small' else 'item'
        tile = Tile(('t:' if kind == 'thumb' else 'i:') + item.id, kind, size, src, [item], notitle=True)
        if not _place_fallback(packer, tile):
            if ctx.get('max_bands') is not None and not packer.holes():
                break
            continue
        tiles.append(tile)
    _colour(tiles, ctx)
    return Layout('mosaic', tiles, [], packer.width)


STRATEGIES = {'feed_groups': feed_groups, 'mixed_wall': mixed_wall, 'magazine': magazine, 'spotlight': spotlight,
              'mosaic': mosaic}


def build(name, sources, ctx):
    return STRATEGIES.get(name, mixed_wall)(sources, ctx)
