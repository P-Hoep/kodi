"""Fitting text into tiles, and relative times.

Kodi neither ellipsises multi-line text nor aligns a textbox to the bottom, so headlines are
wrapped here with an estimate of Noto Sans glyph widths (slightly generous, so Kodi never needs
an extra line) and joined with [CR]. The line count picks the bottom-aligned variant on image
faces.
"""

import re

NARROW = set("iljtfrI.,:;'!|()[]{} ")
WIDE = set('mwMW@%')
EM = {'narrow': 0.30, 'wide': 0.88, 'upper': 0.66, 'digit': 0.58, 'lower': 0.54}
SLACK = 1.06
ELLIPSIS = '…'


def char_em(ch):
    if ch in NARROW:
        return EM['narrow']
    if ch in WIDE:
        return EM['wide']
    if ch.isdigit():
        return EM['digit']
    if ch.isupper():
        return EM['upper']
    if ord(ch) > 0x2E80:          # CJK and friends: full width
        return 1.0
    return EM['lower']


def width_px(text, font_px):
    return sum(char_em(ch) for ch in text) * font_px * SLACK


def wrap(text, width, font_px, max_lines):
    """-> (lines, truncated). Words longer than a line are broken."""
    words = re.sub(r'\s+', ' ', (text or '').strip()).split(' ')
    if words == ['']:
        return [], False
    lines, current = [], ''
    i = 0
    while i < len(words):
        word = words[i]
        candidate = word if not current else current + ' ' + word
        if width_px(candidate, font_px) <= width:
            current = candidate
            i += 1
            continue
        if not current:
            # A single word wider than the line: split it.
            cut = len(word)
            while cut > 1 and width_px(word[:cut], font_px) > width:
                cut -= 1
            lines.append(word[:cut])
            words[i] = word[cut:]
        else:
            lines.append(current)
            current = ''
        if len(lines) == max_lines:
            break
    if current and len(lines) < max_lines:
        lines.append(current)
        current = ''
    truncated = bool(current) or i < len(words)
    if truncated and lines:
        last = lines[-1]
        while last and width_px(last + ELLIPSIS, font_px) > width:
            last = last[:-1]
        last = last.rstrip(' ,;:.-–—')
        if ' ' in last and len(last) > 12 and not last.endswith(' '):
            # Prefer cutting at a word boundary when that does not waste much.
            head = last.rsplit(' ', 1)[0]
            if width_px(head, font_px) > width * 0.7:
                last = head.rstrip(' ,;:.-–—')
        lines[-1] = last + ELLIPSIS
    return lines, truncated


def fit(text, width, font_px, max_lines):
    """-> (Kodi text with [CR] between lines, line count)."""
    lines, _ = wrap(text, width, font_px, max_lines)
    return '[CR]'.join(lines), len(lines)


def initials(title):
    words = [w for w in re.split(r'[\s/_\-.:]+', title or '') if w and w[0].isalnum()]
    if not words:
        return '?'
    if len(words) == 1:
        return words[0][:2].upper()
    return (words[0][0] + words[1][0]).upper()


def relative(published, now, strings):
    """'NOW', '12 MIN AGO', '3 H AGO', 'YESTERDAY', '4 DAYS AGO' (from strings: a dict with
    now, min, hours, yesterday, days)."""
    seconds = max(0, now - published)
    if seconds < 90:
        return strings['now']
    if seconds < 3600:
        return strings['min'] % int(seconds // 60)
    if seconds < 86400:
        return strings['hours'] % int(seconds // 3600)
    if seconds < 2 * 86400:
        return strings['yesterday']
    return strings['days'] % int(seconds // 86400)


ENGLISH = {'now': 'NOW', 'min': '%d MIN AGO', 'hours': '%d H AGO', 'yesterday': 'YESTERDAY',
           'days': '%d DAYS AGO'}
