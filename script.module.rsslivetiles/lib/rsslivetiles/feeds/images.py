"""Image candidates for a feed item, ranked best first (spec section 3.3).

The parser hands over raw candidates as (source, url, width, height, mime). Priority:
  1 media:content (image)   2 media:group content   3 media:thumbnail
  4 <enclosure type=image>  5 itunes:image          6 Atom link rel=enclosure (image)
  7 first <img> in content:encoded, then in description / summary
Within a priority the largest declared width wins. Tiny, tracking, SVG and data: images
are dropped. Kodi loads the surviving URL itself (texture cache), so nothing is downloaded here.
"""

import re
from html.parser import HTMLParser
from urllib.parse import urljoin, urlparse

PRIORITY = {'media:content': 1, 'media:group': 2, 'media:thumbnail': 3, 'enclosure': 4, 'itunes:image': 5,
            'atom:enclosure': 6, 'content': 7, 'description': 8, 'og:image': 9}
MIN_SIDE = 120
RASTER_EXT = ('.jpg', '.jpeg', '.png', '.gif', '.webp', '.bmp')
NON_RASTER_EXT = ('.svg', '.svgz', '.ico', '.pdf', '.mp4', '.mp3', '.webm', '.mov')
TRACKER_HOSTS = ('feeds.feedburner.com', 'feedproxy.google.com', 'pixel.', 'doubleclick.net',
                 'google-analytics.com', 'stats.wordpress.com', 'pixel.wp.com', 'feedsportal.com',
                 'gravatar.com', 'scorecardresearch.com', 'quantserve.com', 'mf.tt', 'piwik', 'matomo')
TRACKER_PATHS = re.compile(r'(^|/)(pixel|tracker|track|beacon|spacer|blank|1x1|transparent)\.(gif|png)'
                           r'|/emoji/|/smilies/|/wp-includes/images/', re.I)

# Known CDNs that serve bigger renditions from the same path.
UPGRADES = [
    # BBC: https://ichef.bbci.co.uk/ace/standard/240/cpsprodpb/... (also /news/240/)
    (re.compile(r'^(https?://ichef\.bbci\.co\.uk/(?:ace/standard|news))/(\d{2,3})/'), 800),
]


class ImageRef(object):
    __slots__ = ('url', 'width', 'height', 'source')

    def __init__(self, url, width=0, height=0, source=''):
        self.url = url
        self.width = width
        self.height = height
        self.source = source

    def to_dict(self):
        return {'url': self.url, 'w': self.width, 'h': self.height, 's': self.source}

    @classmethod
    def from_dict(cls, d):
        return cls(d.get('url', ''), d.get('w', 0) or 0, d.get('h', 0) or 0, d.get('s', ''))

    def __repr__(self):
        return 'ImageRef(%r, %d, %d, %r)' % (self.url, self.width, self.height, self.source)


def to_int(value):
    try:
        return int(float(str(value).strip().rstrip('px')))
    except (TypeError, ValueError):
        return 0


def upgrade(url):
    for pattern, width in UPGRADES:
        match = pattern.match(url)
        if match and int(match.group(2)) < width:
            return '%s/%d/%s' % (match.group(1), width, url[match.end():])
    return url


def acceptable(url, width=0, height=0, mime=''):
    """False for images Kodi can't show or that are certainly not a picture of the story."""
    if not url:
        return False
    if url.startswith('data:'):
        return False          # Kodi image controls can't load data: URIs
    parsed = urlparse(url)
    if parsed.scheme not in ('http', 'https'):
        return False
    if mime and mime.lower().startswith('image/') and 'svg' in mime.lower():
        return False
    if mime and not mime.lower().startswith('image/') and mime.lower() not in ('', 'image'):
        return False
    path = parsed.path.lower()
    if path.endswith(NON_RASTER_EXT):
        return False
    host = parsed.netloc.lower()
    if any(t in host for t in TRACKER_HOSTS):
        return False
    if TRACKER_PATHS.search(path):
        return False
    if (width and width < MIN_SIDE) or (height and height < MIN_SIDE):
        return False
    return True


def rank(candidates, base=''):
    """[(source, url, width, height, mime)] -> [ImageRef] best first, deduplicated."""
    seen = set()
    scored = []
    for order, (source, url, width, height, mime) in enumerate(candidates):
        url = (url or '').strip()
        if base and url and not url.startswith(('http://', 'https://', 'data:')):
            url = urljoin(base, url)
        if url.startswith('//'):
            url = 'https:' + url
        width, height = to_int(width), to_int(height)
        if not acceptable(url, width, height, mime):
            continue
        url = upgrade(url)
        key = url.split('#')[0]
        if key in seen:
            continue
        seen.add(key)
        scored.append(((PRIORITY.get(source, 10), -width, order), ImageRef(url, width, height, source)))
    scored.sort(key=lambda pair: pair[0])
    return [ref for _score, ref in scored]


class _ImgFinder(HTMLParser):
    def __init__(self):
        HTMLParser.__init__(self, convert_charrefs=True)
        self.found = []

    def handle_starttag(self, tag, attrs):
        if tag != 'img':
            return
        a = dict(attrs)
        src = a.get('src') or a.get('data-src') or ''
        srcset = a.get('srcset') or a.get('data-srcset') or ''
        if srcset:
            best = best_from_srcset(srcset)
            if best:
                src = best[0]
                if best[1] and not a.get('width'):
                    a['width'] = best[1]
        self.found.append((src, a.get('width', 0), a.get('height', 0)))

    handle_startendtag = handle_starttag


def best_from_srcset(srcset):
    """'a.jpg 320w, b.jpg 800w' -> ('b.jpg', 800)."""
    best = None
    for part in srcset.split(','):
        bits = part.strip().split()
        if not bits:
            continue
        width = 0
        if len(bits) > 1 and bits[1].endswith('w'):
            width = to_int(bits[1][:-1])
        if best is None or width > best[1]:
            best = (bits[0], width)
    return best


def from_html(fragment, source, limit=3):
    """The first few <img> in an HTML fragment as candidates."""
    if not fragment or '<img' not in fragment.lower():
        return []
    finder = _ImgFinder()
    try:
        finder.feed(fragment)
    except Exception:
        return []
    return [(source, src, w, h, '') for src, w, h in finder.found[:limit]]


OG_IMAGE = re.compile(r'<meta[^>]+(?:property|name)=["\'](?:og:image|twitter:image)(?::src)?["\'][^>]*>', re.I)
CONTENT_ATTR = re.compile(r'content=["\']([^"\']+)["\']', re.I)


def og_image(page_html):
    """The og:image (or twitter:image) URL of an article page, or ''."""
    for tag in OG_IMAGE.findall(page_html or ''):
        match = CONTENT_ATTR.search(tag)
        if match:
            return match.group(1).strip()
    return ''
