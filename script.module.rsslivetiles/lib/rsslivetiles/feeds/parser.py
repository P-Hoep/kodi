"""RSS 2.0, RSS 1.0 (RDF) and Atom 1.0 (and 0.3) -> FeedInfo + [FeedItem].

A small, tolerant parser on top of ElementTree instead of feedparser (not in Kodi's Omega
repository). Namespaces handled: media (Media RSS), content, dc, itunes, atom.
Malformed feeds get a second chance: HTML entities, stray '&' and control characters are
repaired before parsing again.
"""

import datetime
import email.utils
import hashlib
import html
import html.entities
import re
import xml.etree.ElementTree as ET
from urllib.parse import urljoin

from . import images, sanitize

NS = {
    'http://www.w3.org/2005/Atom': 'atom',
    'http://purl.org/atom/ns#': 'atom',
    'http://purl.org/rss/1.0/': '',
    'http://my.netscape.com/rdf/simple/0.9/': '',
    'http://www.w3.org/1999/02/22-rdf-syntax-ns#': 'rdf',
    'http://search.yahoo.com/mrss/': 'media',
    'http://search.yahoo.com/mrss': 'media',
    'http://purl.org/rss/1.0/modules/content/': 'content',
    'http://purl.org/dc/elements/1.1/': 'dc',
    'http://purl.org/dc/terms/': 'dcterms',
    'http://www.itunes.com/dtds/podcast-1.0.dtd': 'itunes',
    'http://www.google.com/schemas/play-podcasts/1.0': 'googleplay',
}
SUMMARY_CHARS = 500
EPOCH = datetime.datetime(1970, 1, 1, tzinfo=datetime.timezone.utc)


class FeedError(Exception):
    pass


class Enclosure(object):
    __slots__ = ('url', 'mime', 'length')

    def __init__(self, url, mime='', length=0):
        self.url = url
        self.mime = mime
        self.length = length

    @property
    def kind(self):
        mime = (self.mime or '').lower()
        if mime.startswith('audio/'):
            return 'audio'
        if mime.startswith('video/') or mime in ('application/x-mpegurl', 'application/vnd.apple.mpegurl'):
            return 'video'
        path = self.url.lower().split('?')[0]
        if path.endswith(('.mp3', '.m4a', '.aac', '.ogg', '.opus', '.flac', '.wav')):
            return 'audio'
        if path.endswith(('.mp4', '.m4v', '.mkv', '.webm', '.mov', '.m3u8')):
            return 'video'
        return ''

    def to_dict(self):
        return {'url': self.url, 'type': self.mime, 'len': self.length}

    @classmethod
    def from_dict(cls, d):
        return cls(d.get('url', ''), d.get('type', ''), d.get('len', 0) or 0)


class FeedItem(object):
    """One article. published is a UTC epoch (float)."""

    __slots__ = ('id', 'feed_id', 'title', 'summary', 'content_html', 'link', 'author', 'published',
                 'images', 'enclosures', 'dated')

    def __init__(self, id, feed_id='', title='', summary='', content_html='', link='', author=None,
                 published=0.0, images=None, enclosures=None, dated=True):
        self.id = id
        self.feed_id = feed_id
        self.title = title
        self.summary = summary
        self.content_html = content_html
        self.link = link
        self.author = author
        self.published = published
        self.images = images or []
        self.enclosures = enclosures or []
        self.dated = dated            # False when published fell back to the fetch time

    @property
    def image(self):
        return self.images[0].url if self.images else ''

    @property
    def media(self):
        """The first playable enclosure, or None."""
        for enc in self.enclosures:
            if enc.kind:
                return enc
        return None

    def to_dict(self):
        return {'id': self.id, 'feed': self.feed_id, 'title': self.title, 'summary': self.summary,
                'html': self.content_html, 'link': self.link, 'author': self.author,
                'published': self.published, 'dated': self.dated,
                'images': [i.to_dict() for i in self.images], 'enc': [e.to_dict() for e in self.enclosures]}

    @classmethod
    def from_dict(cls, d):
        return cls(d.get('id', ''), d.get('feed', ''), d.get('title', ''), d.get('summary', ''), d.get('html', ''),
                   d.get('link', ''), d.get('author'), float(d.get('published') or 0),
                   [images.ImageRef.from_dict(i) for i in d.get('images', [])],
                   [Enclosure.from_dict(e) for e in d.get('enc', [])], d.get('dated', True))

    def __repr__(self):
        return 'FeedItem(%r, %r)' % (self.id, self.title[:40])


class FeedInfo(object):
    __slots__ = ('title', 'link', 'image', 'description', 'kind')

    def __init__(self, title='', link='', image='', description='', kind=''):
        self.title = title
        self.link = link
        self.image = image
        self.description = description
        self.kind = kind              # 'rss', 'rdf' or 'atom'

    def to_dict(self):
        return {'title': self.title, 'link': self.link, 'image': self.image, 'description': self.description,
                'kind': self.kind}

    @classmethod
    def from_dict(cls, d):
        d = d or {}
        return cls(d.get('title', ''), d.get('link', ''), d.get('image', ''), d.get('description', ''),
                   d.get('kind', ''))


# ------------------------------------------------------------------ element helpers

def qname(tag):
    """'{http://www.w3.org/2005/Atom}link' -> 'atom:link'; un-namespaced and RSS 1.0 -> 'link'."""
    if not isinstance(tag, str):
        return ''
    if tag[:1] == '{':
        uri, _, local = tag[1:].partition('}')
        prefix = NS.get(uri)
        if prefix is None:
            prefix = 'x'
        return '%s:%s' % (prefix, local) if prefix else local
    return tag


def children(el, *names):
    return [c for c in el if qname(c.tag) in names]


def child(el, *names):
    for name in names:
        for c in el:
            if qname(c.tag) == name:
                return c
    return None


def text_of(el):
    """Text content, including any (X)HTML children serialised back to markup."""
    if el is None:
        return ''
    if len(el) == 0:
        return (el.text or '').strip()
    parts = [el.text or '']
    for c in el:
        markup = re.sub(r'\s?xmlns(:\w+)?="[^"]*"', '', ET.tostring(c, encoding='unicode'))
        parts.append(re.sub(r'<(/?)\w+:', r'<\1', markup))     # <html:p> -> <p>
    return ''.join(parts).strip()


def first_text(el, *names):
    for name in names:
        c = child(el, name)
        if c is not None:
            value = text_of(c)
            if value:
                return value
    return ''


# ------------------------------------------------------------------ dates

ISO = re.compile(r'^(\d{4})-?(\d{2})-?(\d{2})(?:[T ](\d{2}):?(\d{2})(?::?(\d{2})(?:[.,]\d+)?)?)?\s*'
                 r'(Z|[+-]\d{2}:?\d{2}|[+-]\d{2})?$', re.I)
TZ_NAMES = {'UT': 0, 'UTC': 0, 'GMT': 0, 'Z': 0, 'EST': -5, 'EDT': -4, 'CST': -6, 'CDT': -5, 'MST': -7,
            'MDT': -6, 'PST': -8, 'PDT': -7, 'BST': 1, 'CET': 1, 'CEST': 2, 'IST': 5.5, 'JST': 9, 'AEST': 10}


def parse_date(text):
    """RFC 822 / RFC 3339 / ISO 8601 (and common sloppy variants) -> UTC epoch, or None."""
    text = (text or '').strip()
    if not text:
        return None
    match = ISO.match(text)
    if match:
        y, mo, d, h, mi, s, tz = match.groups()
        try:
            dt = datetime.datetime(int(y), int(mo), int(d), int(h or 0), int(mi or 0), int(s or 0),
                                   tzinfo=datetime.timezone.utc)
        except ValueError:
            return None
        offset = 0
        if tz and tz.upper() != 'Z':
            sign = -1 if tz[0] == '-' else 1
            digits = tz[1:].replace(':', '')
            offset = sign * (int(digits[:2]) * 60 + (int(digits[2:4]) if len(digits) >= 4 else 0))
        return (dt - EPOCH).total_seconds() - offset * 60
    cleaned = re.sub(r'\s+', ' ', text.replace(',', ', ')).strip()
    try:
        parsed = email.utils.parsedate_tz(cleaned)
    except (TypeError, ValueError):
        parsed = None
    if parsed:
        tz = parsed[9]
        if tz is None:
            name = cleaned.split()[-1].upper()
            tz = int(TZ_NAMES.get(name, 0) * 3600)
        try:
            dt = datetime.datetime(*parsed[:6], tzinfo=datetime.timezone.utc)
        except ValueError:
            return None
        return (dt - EPOCH).total_seconds() - tz
    return None


# ------------------------------------------------------------------ parsing

def _decode(data, content_type=''):
    """Bytes -> text, honouring the XML declaration, then the HTTP charset, then UTF-8."""
    if isinstance(data, str):
        return data
    head = data[:200].decode('ascii', 'replace')
    declared = re.search(r'<\?xml[^>]*encoding=["\']([\w.-]+)["\']', head)
    http = re.search(r'charset=([\w.-]+)', content_type or '', re.I)
    if data.startswith(b'\xef\xbb\xbf'):
        data = data[3:]
    for enc in [e for e in (declared and declared.group(1), http and http.group(1), 'utf-8') if e]:
        try:
            return data.decode(enc)
        except (LookupError, UnicodeDecodeError):
            continue
    return data.decode('utf-8', 'replace')


XML_SAFE = {'amp', 'lt', 'gt', 'quot', 'apos'}
CONTROL = re.compile('[\x00-\x08\x0b\x0c\x0e-\x1f￾￿]')


def repair(text):
    """Make a sloppy feed well-formed enough for ElementTree."""
    text = CONTROL.sub('', text)

    def entity(m):
        name = m.group(1)
        if name in XML_SAFE:
            return m.group(0)
        code = html.entities.name2codepoint.get(name)
        return '&#%d;' % code if code else '&amp;%s;' % name

    text = re.sub(r'&([A-Za-z][A-Za-z0-9]*);', entity, text)
    text = re.sub(r'&(?!(?:[A-Za-z][A-Za-z0-9]*|#\d+|#x[0-9A-Fa-f]+);)', '&amp;', text)
    # A doctype can declare entities ElementTree refuses; drop it.
    text = re.sub(r'<!DOCTYPE[^>\[]*(\[[^\]]*\])?>', '', text, flags=re.I)
    return text


def _root(text):
    text = re.sub(r'^\s*<\?xml[^>]*\?>', '', text.lstrip('﻿'))
    try:
        return ET.fromstring(text)
    except ET.ParseError:
        pass
    try:
        return ET.fromstring(repair(text))
    except ET.ParseError as err:
        raise FeedError('not a valid feed: %s' % err)


def parse(data, feed_id='', url='', content_type='', now=0.0):
    """Bytes or text of a feed -> (FeedInfo, [FeedItem]). Raises FeedError."""
    text = _decode(data, content_type)
    if not text.strip():
        raise FeedError('empty response')
    if re.match(r'\s*(<!doctype html|<html)', text[:500], re.I):
        raise FeedError('this is a web page, not a feed')
    root = _root(text)
    kind = qname(root.tag)
    if kind == 'rss':
        channel = child(root, 'channel')
        if channel is None:
            raise FeedError('RSS without a channel')
        return _rss(channel, list(children(channel, 'item')), feed_id, url, now, 'rss')
    if kind == 'rdf:RDF':
        channel = child(root, 'channel')
        return _rss(channel if channel is not None else root, list(children(root, 'item')), feed_id, url, now,
                    'rdf', root)
    if kind == 'atom:feed':
        return _atom(root, feed_id, url, now)
    raise FeedError('unknown feed type <%s>' % kind)


def _link_from(el, base):
    link = first_text(el, 'link')
    if not link:
        for l in children(el, 'atom:link'):
            if l.get('rel', 'alternate') == 'alternate' and l.get('href'):
                link = l.get('href')
                break
    return urljoin(base, link) if base and link else link


def _rss(channel, items, feed_id, url, now, kind, rdf_root=None):
    base = url or ''
    link = _link_from(channel, base)
    image = ''
    img = child(channel, 'image')
    if img is None and rdf_root is not None:
        img = child(rdf_root, 'image')
    if img is not None:
        image = first_text(img, 'url') or img.get('{http://www.w3.org/1999/02/22-rdf-syntax-ns#}resource', '')
    if not image:
        it = child(channel, 'itunes:image')
        image = (it.get('href', '') if it is not None else '') or first_text(channel, 'atom:logo', 'atom:icon')
    info = FeedInfo(sanitize.clean_title(first_text(channel, 'title')), link, image,
                    sanitize.to_text(first_text(channel, 'description', 'itunes:summary'), 300), kind)
    out = []
    for i, el in enumerate(items):
        item = _rss_item(el, feed_id, link or base, now, i)
        if item:
            out.append(item)
    return info, out


def _media_candidates(el):
    cands = []
    for mc in children(el, 'media:content'):
        medium = (mc.get('medium') or '').lower()
        mime = (mc.get('type') or '').lower()
        if medium == 'image' or mime.startswith('image/') or (not medium and not mime and mc.get('url')
                                                              and images.acceptable(mc.get('url'))):
            if medium in ('', 'image') and not mime.startswith(('video/', 'audio/')):
                cands.append(('media:content', mc.get('url'), mc.get('width'), mc.get('height'), mime))
        for th in children(mc, 'media:thumbnail'):
            cands.append(('media:thumbnail', th.get('url'), th.get('width'), th.get('height'), ''))
    for group in children(el, 'media:group'):
        for source, url, w, h, mime in _media_candidates(group):
            cands.append(('media:group' if source == 'media:content' else source, url, w, h, mime))
    for th in children(el, 'media:thumbnail'):
        cands.append(('media:thumbnail', th.get('url'), th.get('width'), th.get('height'), ''))
    return cands


def _media_enclosures(el):
    out = []
    for mc in children(el, 'media:content'):
        medium = (mc.get('medium') or '').lower()
        mime = (mc.get('type') or '').lower()
        if medium in ('audio', 'video') or mime.startswith(('audio/', 'video/')):
            out.append(Enclosure(mc.get('url', ''), mime or medium + '/*', images.to_int(mc.get('fileSize'))))
    for group in children(el, 'media:group'):
        out.extend(_media_enclosures(group))
    return out


def _item_id(guid, link, title, published):
    if guid:
        return guid
    raw = '%s|%s' % (link, title) if (link or title) else str(published)
    return 'h:' + hashlib.sha1(raw.encode('utf-8', 'replace')).hexdigest()[:16]


def _finish(feed_id, guid, title, summary_src, content, link, author, published, cands, enclosures, base,
            now):
    title = sanitize.clean_title(title)
    summary = sanitize.to_text(summary_src or content, SUMMARY_CHARS)
    if not title:
        title = sanitize.shorten(summary, 120) if summary else ''
    if not title and not link:
        return None
    dated = published is not None
    ranked = images.rank(cands, base)
    return FeedItem(_item_id(guid, link, title, published), feed_id, title, summary, content or summary_src or '',
                    link, author or None, published if dated else float(now), ranked,
                    [e for e in enclosures if e.url], dated)


def _rss_item(el, feed_id, base, now, index):
    title = first_text(el, 'title', 'dc:title')
    description = first_text(el, 'description', 'atom:summary', 'itunes:summary', 'media:description')
    content = first_text(el, 'content:encoded', 'atom:content')
    link = first_text(el, 'link')
    guid_el = child(el, 'guid')
    guid = text_of(guid_el) if guid_el is not None else ''
    if not guid:
        guid = el.get('{http://www.w3.org/1999/02/22-rdf-syntax-ns#}about', '') or first_text(el, 'atom:id')
    if not link:
        alt = [l for l in children(el, 'atom:link') if l.get('rel', 'alternate') == 'alternate']
        if alt:
            link = alt[0].get('href', '')
        elif guid_el is not None and guid_el.get('isPermaLink', 'true') != 'false' and guid.startswith('http'):
            link = guid
    link = urljoin(base, link) if base and link else link
    author = first_text(el, 'dc:creator', 'author', 'itunes:author')
    if author and '@' in author and '(' in author:      # "mail@x.com (Name)"
        author = author[author.find('(') + 1:author.rfind(')')] or author
    published = parse_date(first_text(el, 'pubDate', 'dc:date', 'atom:published', 'atom:updated',
                                      'dcterms:modified'))
    cands = _media_candidates(el)
    enclosures = _media_enclosures(el)
    for enc in children(el, 'enclosure'):
        mime = (enc.get('type') or '').lower()
        url = enc.get('url', '')
        if mime.startswith('image/') or (not mime and images.acceptable(url) and
                                         url.lower().split('?')[0].endswith(images.RASTER_EXT)):
            cands.append(('enclosure', url, 0, 0, mime))
        else:
            enclosures.append(Enclosure(url, mime, images.to_int(enc.get('length'))))
    it = child(el, 'itunes:image')
    if it is not None:
        cands.append(('itunes:image', it.get('href', ''), 0, 0, ''))
    for l in children(el, 'atom:link'):
        if l.get('rel') == 'enclosure':
            mime = (l.get('type') or '').lower()
            if mime.startswith('image/'):
                cands.append(('atom:enclosure', l.get('href'), 0, 0, mime))
            else:
                enclosures.append(Enclosure(l.get('href', ''), mime, images.to_int(l.get('length'))))
    cands += images.from_html(content, 'content') + images.from_html(description, 'description')
    return _finish(feed_id, guid, title, description, content, link, author, published, cands, enclosures,
                   base, now)


def _atom(root, feed_id, url, now):
    base = root.get('{http://www.w3.org/XML/1998/namespace}base') or url or ''
    link = ''
    for l in children(root, 'atom:link'):
        if l.get('rel', 'alternate') == 'alternate' and l.get('href'):
            link = urljoin(base, l.get('href'))
            break
    info = FeedInfo(sanitize.clean_title(first_text(root, 'atom:title')), link,
                    first_text(root, 'atom:logo', 'atom:icon'),
                    sanitize.to_text(first_text(root, 'atom:subtitle', 'atom:tagline'), 300), 'atom')
    if info.image:
        info.image = urljoin(base, info.image)
        info.image = re.sub(r'(\.(?:png|jpe?g|gif|webp|ico))/$', r'\1', info.image, flags=re.I)
    out = []
    for entry in children(root, 'atom:entry'):
        item = _atom_entry(entry, feed_id, link or base, now)
        if item:
            out.append(item)
    return info, out


def _atom_entry(el, feed_id, base, now):
    title = first_text(el, 'atom:title')
    summary = first_text(el, 'atom:summary', 'media:description')
    content = first_text(el, 'atom:content')
    if not summary:
        group = child(el, 'media:group')
        if group is not None:
            summary = first_text(group, 'media:description')
    link = ''
    enclosures = []
    cands = _media_candidates(el)
    for l in children(el, 'atom:link'):
        rel = l.get('rel', 'alternate')
        href = urljoin(base, l.get('href', ''))
        mime = (l.get('type') or '').lower()
        if rel == 'alternate' and not link:
            link = href
        elif rel == 'enclosure':
            if mime.startswith('image/'):
                cands.append(('atom:enclosure', href, 0, 0, mime))
            else:
                enclosures.append(Enclosure(href, mime, images.to_int(l.get('length'))))
    enclosures += _media_enclosures(el)
    author_el = child(el, 'atom:author')
    author = first_text(author_el, 'atom:name') if author_el is not None else ''
    published = parse_date(first_text(el, 'atom:published', 'atom:updated', 'atom:issued', 'atom:modified'))
    cands += images.from_html(content, 'content') + images.from_html(summary, 'description')
    return _finish(feed_id, first_text(el, 'atom:id'), title, summary, content, link, author, published,
                   cands, enclosures, base, now)
