"""What a tile face shows, as the window properties the XML reads (rt.<slot>.<face>.<key>).

Face kinds (spec 4.2):
  image   full-bleed picture, scrim, headline (bottom aligned, 1-3 lines), source label;
          the text layer underneath shows when the picture peeks away or fails to load
  text    accent background, headline, summary on wide / large, "SOURCE . 12 MIN AGO", feed icon
  count   feed icon (or initials) and the number of new items
  clock   the time and date (screensaver)

ctx: style, palette, now, strings (relative time words, labels), show_images.
"""

from . import geometry as g
from . import styles, text

KEYS = ('kind', 'bg', 'fg', 'fg2', 'body', 'panel', 'img', 'title', 'tl', 'sum', 'meta', 'icon', 'ini', 'num',
        'itl', 'ititle', 'notitle')


def _blank():
    return dict((k, '') for k in KEYS)


def _colours(face, tile, ctx):
    c = styles.colours(ctx['style'], tile.colour, ctx['palette'])
    face.update(bg=c['bg'], fg=c['fg'], fg2=c['fg2'], body=c['body'], panel=c['panel'])
    return c


def meta_line(source_title, published, ctx, dated=True):
    parts = []
    if source_title:
        parts.append(source_title.upper())
    if published and dated:
        parts.append(text.relative(published, ctx['now'], ctx['strings']))
    return '  ·  '.join(parts)


def summary_lines(size, title_lines):
    """How many summary lines fit under a headline of title_lines lines."""
    spec = g.FACES[size]
    if not spec['summary']:
        return 0
    left, top, width, label_y = g.text_area(size)
    tfont, _ = spec['title']
    sfont, smax = spec['summary']
    start = top + title_lines * g.line_px(tfont) + 8
    return max(0, min(smax, (label_y - start - 4) // g.line_px(sfont)))


def _text_layer(face, size, title, summary, ctx, inset, summary_mode=False):
    spec = g.FACES[size]
    left, top, width, label_y = g.text_area(size, inset)
    tfont, tmax = spec['title']
    if summary_mode and spec['summary']:
        tmax = min(tmax, 2 if size != 'large' else 3)
    elif size == 'wide' and summary and spec['summary']:
        tmax = min(tmax, 2)
    fitted, lines = text.fit(title, width, g.FONT_PX[tfont], tmax)
    face['title'] = fitted
    face['tl'] = str(max(1, lines))
    want_summary = summary and spec['summary'] and (summary_mode or size in ('wide', 'large'))
    if want_summary:
        n = summary_lines(size, max(1, lines))
        if n:
            sfont = spec['summary'][0]
            face['sum'] = text.fit(summary, width, g.FONT_PX[sfont], n)[0]


def item_face(tile, item, ctx, summary_mode=False):
    """An article on a tile. summary_mode: the text face with the summary under a shorter
    headline (the back of a text tile)."""
    face = _blank()
    _colours(face, tile, ctx)
    st = styles.STYLES[ctx['style']]
    inset = st['inset'] + (st['image_inset'] if st['border'] else 0)
    size = tile.size
    src = tile.source.title if tile.source else ''
    has_image = ctx.get('show_images', True) and bool(item.images)
    if size != 'small':
        _text_layer(face, size, item.title, item.summary, ctx, inset, summary_mode)
        face['meta'] = meta_line(src, item.published, ctx, item.dated)
        face['icon'] = tile.source.icon if tile.source else ''
    else:
        face['ini'] = text.initials(src)
        fitted, lines = text.fit(item.title, g.PIXELS['small'][0] - 20, g.FONT_PX['font10'], 3)
        face['title'] = fitted
        face['tl'] = str(max(1, lines))
    if has_image and not summary_mode:
        face['kind'] = 'image'
        face['img'] = item.images[0].url
        spec = g.FACES[size]
        if spec['image_title'] and not tile.notitle:
            font, n = spec['image_title']
            pad = spec['pad'] + st['inset'] + st['image_inset']
            width = tile.w - 2 * pad
            fitted, lines = text.fit(item.title, width, g.FONT_PX[font], n)
            face['ititle'] = fitted
            face['itl'] = str(max(1, lines))
        else:
            face['notitle'] = '1'
    else:
        face['kind'] = 'text'
    return face


def count_face(tile, ctx, back=False):
    face = _blank()
    _colours(face, tile, ctx)
    src = tile.source
    title = src.title if src else ''
    if back:
        face['kind'] = 'text'
        st = styles.STYLES[ctx['style']]
        width = tile.w - 2 * (g.FACES[tile.size]['pad'] + st['inset'])
        face['title'] = text.fit(title, width, g.FONT_PX[g.FACES[tile.size]['title'][0]], 3)[0]
        face['tl'] = '3'
        if src and src.error:
            face['meta'] = ctx['strings']['offline']
        elif tile.count:
            face['meta'] = ctx['strings']['new'] % tile.count
        else:
            face['meta'] = ctx['strings']['up_to_date']
        return face
    face['kind'] = 'count'
    face['icon'] = src.icon if src else ''
    face['ini'] = text.initials(title)
    face['num'] = str(tile.count) if tile.count else ''
    return face


def feed_face(tile, ctx):
    """A feed tile with nothing to show yet: its title and why."""
    face = _blank()
    _colours(face, tile, ctx)
    src = tile.source
    st = styles.STYLES[ctx['style']]
    detail = ctx['strings']['offline_body'] if src and src.error else ctx['strings']['empty']
    _text_layer(face, tile.size, src.title if src else '', detail, ctx, st['inset'], summary_mode=True)
    face['kind'] = 'text'
    face['meta'] = ctx['strings']['offline'] if src and src.error else ''
    face['icon'] = src.icon if src else ''
    if tile.size == 'small':
        face['ini'] = text.initials(src.title if src else '')
    return face


def clock_face(tile, ctx):
    face = _blank()
    _colours(face, tile, ctx)
    face['kind'] = 'clock'
    return face


def front(tile, ctx):
    """The face a tile shows when it is first bound."""
    if tile.kind == 'clock':
        return clock_face(tile, ctx)
    if tile.kind == 'count':
        return count_face(tile, ctx, back=(tile.side == 'back'))
    item = tile.item
    if item is None:
        return feed_face(tile, ctx)
    return item_face(tile, item, ctx, summary_mode=(tile.kind == 'item' and tile.side == 'back'))
