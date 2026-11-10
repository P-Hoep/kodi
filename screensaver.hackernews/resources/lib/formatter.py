"""Hacker News HTML into plain Kodi label text.

Comments and Ask HN posts arrive as a small, predictable subset of HTML: paragraphs, line
breaks, italics, links and <pre><code> blocks. Kodi labels are plain text with a few tags of
their own, so this module turns the HTML into text with [I]…[/I] for emphasis, indented lines
for code, the visible text of links (or just their domain when the text is a raw URL), real
characters for entities, and literal brackets as parentheses so nothing is mistaken for a Kodi
tag. Long comments are cut at a sentence or word boundary with an ellipsis.

No Kodi imports: the tests use it directly.
"""

import re
from html.parser import HTMLParser
from urllib.parse import urlsplit

INDENT = '    '
ELLIPSIS = '…'
URL_START = ('http://', 'https://', 'www.')


def domain(url):
    """'https://www.example.com/a?b=1' -> 'example.com'. Text posts have no URL."""
    try:
        host = urlsplit(url or '').netloc.lower()
    except ValueError:
        host = ''
    if host.startswith('www.'):
        host = host[4:]
    return host or 'news.ycombinator.com'


def _is_url(text):
    text = text.strip().lower()
    return text.startswith(URL_START)


class _Extractor(HTMLParser):
    """One pass over the HTML, producing runs of {'text', 'italic', 'break'}."""

    BLOCK_TAGS = {'p', 'div', 'blockquote', 'h1', 'h2', 'h3', 'h4', 'h5', 'h6', 'table', 'tr'}
    ITALIC_TAGS = {'i', 'em'}
    VOID_TAGS = {'br', 'hr', 'img', 'input', 'wbr'}

    def __init__(self):
        HTMLParser.__init__(self, convert_charrefs=True)
        self.runs = []
        self.buffer = []
        self.italic = 0
        self.pre = 0
        self.pre_buffer = []
        self.anchor_href = None
        self.anchor_text = []
        self.break_pending = 0

    # ------------------------------------------------------------ output

    def _append_break(self, level):
        if self.runs and self.runs[-1]['break']:
            self.runs[-1]['text'] = '\n' * max(level, len(self.runs[-1]['text']))
        else:
            self.runs.append({'text': '\n' * level, 'italic': False, 'break': True})

    def _break(self, level=1):
        self._flush()
        self.break_pending = max(self.break_pending, level)

    def _emit(self, text, italic=None, pre=False):
        if not text:
            return
        if self.break_pending:
            self._append_break(self.break_pending)
            self.break_pending = 0
        self.runs.append({'text': text, 'italic': self.italic > 0 if italic is None else italic,
                          'break': False, 'pre': pre})

    def _flush(self):
        text = ''.join(self.buffer)
        self.buffer = []
        text = re.sub(r'[ \t\r\n\f\v]+', ' ', text)
        if text:
            self._emit(text)

    # ------------------------------------------------------------ HTML callbacks

    def handle_starttag(self, tag, attrs):
        tag = tag.lower()
        if tag == 'br':
            self._break(1)
        elif tag in self.BLOCK_TAGS:
            self._break(2)
        elif tag in ('ul', 'ol'):
            self._break(2)
        elif tag == 'li':
            self._break(1)
            self._emit('• ', italic=False)
        elif tag == 'pre':
            self._break(2)
            self.pre += 1
            self.pre_buffer = []
        elif tag in self.ITALIC_TAGS and not self.pre:
            self._flush()
            self.italic += 1
        elif tag == 'a':
            self._flush()
            self.anchor_href = dict(attrs).get('href') or ''
            self.anchor_text = []

    def handle_startendtag(self, tag, attrs):
        self.handle_starttag(tag, attrs)
        if tag.lower() not in self.VOID_TAGS:
            self.handle_endtag(tag)

    def handle_endtag(self, tag):
        tag = tag.lower()
        if tag == 'br':
            return
        if tag in self.BLOCK_TAGS or tag in ('ul', 'ol'):
            self._break(2)
        elif tag == 'li':
            self._break(1)
        elif tag == 'pre' and self.pre:
            self.pre -= 1
            self._flush_pre()
            self.break_pending = max(self.break_pending, 2)
        elif tag in self.ITALIC_TAGS and not self.pre:
            self._flush()
            self.italic = max(0, self.italic - 1)
        elif tag == 'a':
            self._flush_anchor()

    def handle_data(self, data):
        if self.pre:
            self.pre_buffer.append(data)
        elif self.anchor_href is not None:
            self.anchor_text.append(data)
        else:
            self.buffer.append(data)

    # ------------------------------------------------------------ pieces

    def _flush_pre(self):
        text = ''.join(self.pre_buffer)
        self.pre_buffer = []
        lines = text.replace('\r\n', '\n').replace('\r', '\n').split('\n')
        while lines and not lines[0].strip():
            lines.pop(0)
        while lines and not lines[-1].strip():
            lines.pop()
        if not lines:
            return
        block = '\n'.join((INDENT + line.rstrip()) if line.strip() else '' for line in lines)
        self._emit(block, italic=False, pre=True)

    def _flush_anchor(self):
        href = self.anchor_href or ''
        visible = re.sub(r'\s+', ' ', ''.join(self.anchor_text)).strip()
        self.anchor_href = None
        self.anchor_text = []
        if not visible:
            self._emit(domain(href) if href else '')
        elif _is_url(visible) or visible == href:
            self._emit(domain(visible) if _is_url(visible) else domain(href))
        else:
            self._emit(visible)

    def close(self):
        HTMLParser.close(self)
        self._flush()

    def pieces(self):
        return [run for run in self.runs if run['text']]


def _clean_pieces(pieces):
    """Fix whitespace at run boundaries and drop leading/trailing blank runs."""
    out = []
    for piece in pieces:
        text = piece['text']
        if not text:
            continue
        if piece['break']:
            if out and out[-1]['break']:
                out[-1]['text'] = '\n' * max(len(out[-1]['text']), len(text))
                continue
            if not out:
                continue
        if out:
            previous = out[-1]['text']
            if previous.endswith('\n') or previous.endswith(' '):
                text = text.lstrip(' ')
            if previous.endswith(' ') and text.startswith('\n'):
                out[-1]['text'] = previous.rstrip()
            if previous.endswith('\n') and not text.strip():
                continue
        if out and not text:
            continue
        out.append(dict(piece, text=text))
    while out and not out[0]['text'].strip():
        out.pop(0)
    while out and not out[-1]['text'].strip():
        out.pop()
    if out:
        if not out[0].get('pre'):
            out[0]['text'] = out[0]['text'].lstrip()
        out[-1]['text'] = out[-1]['text'].rstrip()
    return out


def _truncate(pieces, limit):
    plain = ''.join(p['text'] for p in pieces)
    if limit <= 0 or len(plain) <= limit:
        return pieces, plain, False
    head = plain[:limit]
    cut = None
    for match in re.finditer(r'[.!?](?=\s|$)', head):
        if match.end() >= limit * 0.5:
            cut = match.end()
    if cut is None:
        match = re.search(r'\s+\S*$', head)
        if match and match.start() >= limit * 0.3:
            cut = match.start()
    if not cut:
        cut = limit
    kept = []
    used = 0
    for piece in pieces:
        text = piece['text']
        if used + len(text) <= cut:
            kept.append(piece)
            used += len(text)
            continue
        room = cut - used
        if room > 0:
            kept.append(dict(piece, text=text[:room]))
        break
    kept = _clean_pieces(kept)
    if not kept:
        return [], '', True
    kept[-1]['text'] = kept[-1]['text'].rstrip() + ELLIPSIS
    return kept, ''.join(p['text'] for p in kept), True


def _escape(text):
    return text.replace('[', '(').replace(']', ')')


def _render(pieces):
    out = []
    for piece in pieces:
        text = _escape(piece['text'])
        if not text:
            continue
        if piece['italic'] and text.strip():
            out.append('[I]%s[/I]' % text)
        else:
            out.append(text)
    return ''.join(out)


def parse(text):
    """HTML -> (label text, plain text, truncated)."""
    extractor = _Extractor()
    try:
        extractor.feed(text or '')
        extractor.close()
    except Exception:
        # HTMLParser is very forgiving, but a malformed fragment should never end the show.
        pass
    return extractor.pieces()


def to_label(text, max_chars=700):
    """The Kodi label for a comment or story text, cut to max_chars with an ellipsis."""
    pieces = _clean_pieces(parse(text))
    pieces, _visible, _cut = _truncate(pieces, max_chars)
    return _render(pieces)


def plain_text(text, max_chars=0):
    """The visible text with no Kodi tags, for word counts and the minimum length check."""
    pieces = _clean_pieces(parse(text))
    pieces, visible, _cut = _truncate(pieces, max_chars)
    return ''.join(p['text'] for p in pieces)


def words(text):
    return len(plain_text(text).split())


def display_seconds(plain, wpm=220, minimum=6, maximum=30):
    """How long a comment stays on screen, from its visible text: reading time, clamped."""
    seconds = len(plain.split()) * 60.0 / max(1, wpm)
    return max(minimum, min(maximum, seconds))


def age_text(timestamp, now, just_now='just now', template='%s ago'):
    age = max(0, int(now - (timestamp or 0)))
    if age < 90:
        return just_now
    if age < 3600:
        value = '%d min' % max(1, round(age / 60.0))
    elif age < 86400:
        value = '%d h' % max(1, round(age / 3600.0))
    elif age < 30 * 86400:
        value = '%d d' % max(1, round(age / 86400.0))
    else:
        value = '%d mo' % max(1, round(age / (30 * 86400.0)))
    return template % value
