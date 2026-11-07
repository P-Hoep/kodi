"""HTML from feeds -> plain text (tiles, summaries) or Kodi label markup (the detail view).

Kodi labels understand [B], [I], [CR] and a few more tags; everything else in a feed's HTML
is dropped. Links keep their text, scripts / styles / iframes / images disappear entirely.
"""

import html
import re
from html.parser import HTMLParser

BLOCK = {'p', 'div', 'section', 'article', 'header', 'footer', 'blockquote', 'pre', 'table', 'tr',
         'ul', 'ol', 'dl', 'figure', 'figcaption', 'h1', 'h2', 'h3', 'h4', 'h5', 'h6', 'hr'}
DROP = {'script', 'style', 'iframe', 'object', 'embed', 'noscript', 'svg', 'video', 'audio', 'form',
        'button', 'select', 'textarea', 'head', 'title'}
BOLD = {'b', 'strong', 'h1', 'h2', 'h3', 'h4', 'h5', 'h6'}
ITALIC = {'i', 'em', 'cite'}
KODI_TAGS = re.compile(r'\[(/?(?:B|I|CR|COLOR[^\]]*|UPPERCASE|LOWERCASE|CAPITALIZE|LIGHT|TABS[^\]]*))\]', re.I)
# Reddit appends "submitted by /u/name [link] [comments]" to every post.
REDDIT_TAIL = re.compile(r'\s*submitted by\s+/u/\S+\s*(\[link\])?\s*(\[comments\])?\s*$', re.I)


class _Walker(HTMLParser):
    def __init__(self, markup):
        HTMLParser.__init__(self, convert_charrefs=True)
        self.markup = markup
        self.out = []
        self.drop = 0
        self.bold = 0
        self.italic = 0
        self.lists = []

    # -- output helpers
    def brk(self, n):
        """Ensure the output ends with at least n line breaks (0 = a space)."""
        if not self.out:
            return
        text = ''.join(self.out[-4:])
        have = len(text) - len(text.rstrip('\n'))
        if n == 0:
            if not text.endswith((' ', '\n')):
                self.out.append(' ')
        elif have < n:
            self.out.append('\n' * (n - have))

    def handle_starttag(self, tag, attrs):
        if tag in DROP:
            self.drop += 1
            return
        if self.drop:
            return
        if tag == 'br':
            self.brk(1) if self.out else None
        elif tag == 'li':
            self.brk(1)
            self.out.append('• ')
        elif tag in ('td', 'th', 'dd', 'dt'):
            self.brk(0)
        elif tag in BLOCK:
            self.brk(2)
        if self.markup and tag in BOLD:
            self.bold += 1
            if self.bold == 1:
                self.out.append('[B]')
        elif self.markup and tag in ITALIC:
            self.italic += 1
            if self.italic == 1:
                self.out.append('[I]')

    def handle_startendtag(self, tag, attrs):
        if tag == 'br' and not self.drop:
            self.brk(1)
        elif tag == 'hr' and not self.drop:
            self.brk(2)

    def handle_endtag(self, tag):
        if tag in DROP:
            self.drop = max(0, self.drop - 1)
            return
        if self.drop:
            return
        if self.markup and tag in BOLD and self.bold:
            self.bold -= 1
            if not self.bold:
                self.out.append('[/B]')
        elif self.markup and tag in ITALIC and self.italic:
            self.italic -= 1
            if not self.italic:
                self.out.append('[/I]')
        if tag in BLOCK or tag == 'li':
            self.brk(2 if tag in BLOCK else 1)

    def handle_data(self, data):
        if self.drop:
            return
        data = re.sub(r'[ \t\r\n\f\v ]+', ' ', data)
        if self.markup:
            data = KODI_TAGS.sub(lambda m: '(' + m.group(1) + ')', data)
        if self.out and self.out[-1].endswith('\n'):
            data = data.lstrip(' ')
        self.out.append(data)

    def text(self):
        if self.bold:
            self.out.append('[/B]')
        if self.italic:
            self.out.append('[/I]')
        text = ''.join(self.out)
        text = re.sub(r' *\n *', '\n', text)
        text = re.sub(r'\n{3,}', '\n\n', text)
        text = re.sub(r' {2,}', ' ', text)
        # Formatting tags around nothing.
        text = re.sub(r'\[B\]\s*\[/B\]|\[I\]\s*\[/I\]', '', text)
        return text.strip()


def _walk(fragment, markup):
    fragment = fragment or ''
    if '<' not in fragment and '&' not in fragment:
        text = re.sub(r'\s+', ' ', fragment).strip()
        return KODI_TAGS.sub(lambda m: '(' + m.group(1) + ')', text) if markup else text
    walker = _Walker(markup)
    try:
        walker.feed(fragment)
        walker.close()
    except Exception:
        return re.sub(r'\s+', ' ', html.unescape(re.sub(r'<[^>]*>', ' ', fragment))).strip()
    return walker.text()


def to_text(fragment, limit=None):
    """Plain text on one line (paragraph breaks become spaces), optionally cut at a word
    boundary with an ellipsis."""
    text = _walk(fragment, False)
    text = re.sub(r'\s*\n\s*', ' ', text).replace('• ', '')
    text = REDDIT_TAIL.sub('', text).strip()
    return shorten(text, limit) if limit else text


def to_kodi(fragment):
    """Kodi label markup: [B], [I] and [CR] line breaks."""
    text = _walk(fragment, True)
    text = REDDIT_TAIL.sub('', text).strip()
    return text.replace('\n', '[CR]')


def shorten(text, limit):
    """Cut text to at most limit characters at a word boundary, adding an ellipsis."""
    text = (text or '').strip()
    if len(text) <= limit:
        return text
    cut = text[:limit - 1]
    space = cut.rfind(' ')
    if space > limit * 0.6:
        cut = cut[:space]
    return cut.rstrip(' ,;:.-–—') + '…'


def clean_title(text):
    """Titles may carry HTML (Atom type="html") or stray entities."""
    return to_text(text) if text else ''
