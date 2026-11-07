"""OPML import and export of the feed list."""

from xml.sax.saxutils import quoteattr

from . import parser


def parse(data):
    """OPML text/bytes -> [(title, url)] for every outline with an xmlUrl (nested folders
    included), in document order, without duplicates."""
    root = parser._root(parser._decode(data))
    if parser.qname(root.tag) != 'opml':
        raise parser.FeedError('not an OPML file')
    out, seen = [], set()
    for el in root.iter():
        if parser.qname(el.tag) != 'outline':
            continue
        url = (el.get('xmlUrl') or el.get('xmlurl') or el.get('url') or '').strip()
        if not url or url in seen or el.get('type', 'rss').lower() not in ('rss', 'atom', 'feed', ''):
            continue
        seen.add(url)
        out.append(((el.get('title') or el.get('text') or '').strip(), url))
    return out


def export(feeds, title='RSS Live Tiles feeds'):
    lines = ['<?xml version="1.0" encoding="UTF-8"?>', '<opml version="2.0">',
             '  <head><title>%s</title></head>' % title.replace('&', '&amp;').replace('<', '&lt;'), '  <body>']
    for feed in feeds:
        name = feed.title or feed.url
        lines.append('    <outline type="rss" text=%s title=%s xmlUrl=%s/>' % (quoteattr(name), quoteattr(name),
                                                                                quoteattr(feed.url)))
    lines += ['  </body>', '</opml>', '']
    return '\n'.join(lines)
