"""Theme resolution: Ink / Paper / Midnight / Auto, an accent preset or a custom colour, and a
custom colour for each surface. Colours are Kodi's AARRGGBB hex strings. The window reads them
from properties (ot.bg, ot.card, ...) in colordiffuse and textcolor, so changing a theme needs
no XML edits. No Kodi imports.
"""

import re

INK = {'bg': 'FF0B0D11', 'card': 'FF15181E', 'option': 'FF1C2029',
       'text': 'FFF4F0E7', 'muted': 'FF8E96A4', 'hairline': '1FFFFFFF',
       'accent': 'FFE2B96A', 'good': 'FF57B98B', 'bad': 'FFE26464'}
PAPER = {'bg': 'FFECE6D9', 'card': 'FFFFFCF6', 'option': 'FFF5F0E5',
         'text': 'FF191B1E', 'muted': 'FF6C7178', 'hairline': '22000000',
         'accent': 'FFA65A2E', 'good': 'FF2F7D5B', 'bad': 'FFC0392B'}
MIDNIGHT = {'bg': 'FF070C1A', 'card': 'FF10182B', 'option': 'FF18223A',
            'text': 'FFEFF3FB', 'muted': 'FF8D99B3', 'hairline': '1FFFFFFF',
            'accent': 'FF7CA4FF', 'good': 'FF54C79A', 'bad': 'FFFF6B7A'}

THEMES = [INK, PAPER, MIDNIGHT]
THEME_NAMES = ['Ink', 'Paper', 'Midnight', 'Auto']
MODE_INK, MODE_PAPER, MODE_MIDNIGHT, MODE_AUTO = 0, 1, 2, 3

ACCENTS = ['FFE2B96A', 'FFC9643A', 'FF3BB7A9', 'FF7CA4FF', 'FFE68AA5']
ACCENT_NAMES = ['Theme', 'Gold', 'Rust', 'Teal', 'Blue', 'Rose', 'Custom']
THEME_ACCENT = 0                       # the accent each theme was designed with
CUSTOM = len(ACCENTS) + 1              # 6

INK_TEXT = 'FF14171C'
WHITE = 'FFFFFFFF'
SCRIM = 'A6000000'


def parse_hex(text):
    """'#AbC123', 'abc123' or 'FFABC123' -> 'FFABC123'; None if it is not a colour."""
    t = (text or '').strip().lstrip('#').upper()
    if re.match(r'^[0-9A-F]{6}$', t):
        return 'FF' + t
    if re.match(r'^[0-9A-F]{8}$', t):
        return t
    if re.match(r'^[0-9A-F]{3}$', t):
        return 'FF' + ''.join(ch * 2 for ch in t)
    return None


def rgb(colour):
    return tuple(int(colour[i:i + 2], 16) for i in (2, 4, 6))


def rgba(colour):
    return int(colour[:2], 16), rgb(colour)


def hex_of(r, g, b, alpha=255):
    return '%02X%02X%02X%02X' % (alpha, max(0, min(255, int(r))), max(0, min(255, int(g))),
                                 max(0, min(255, int(b))))


def luminance(colour):
    def channel(v):
        v /= 255.0
        return v / 12.92 if v <= 0.03928 else ((v + 0.055) / 1.055) ** 2.4
    r, g, b = (channel(v) for v in rgb(colour))
    return 0.2126 * r + 0.7152 * g + 0.0722 * b


def contrast(a, b):
    la, lb = luminance(a), luminance(b)
    hi, lo = max(la, lb), min(la, lb)
    return (hi + 0.05) / (lo + 0.05)


def is_dark(colour):
    return luminance(colour) < 0.18


def mix(a, b, t):
    """t of b mixed into a (0 keeps a, 1 returns b), keeping a's alpha."""
    ar, ag, ab = rgb(a)
    br, bg, bb = rgb(b)
    return hex_of(ar + (br - ar) * t, ag + (bg - ag) * t, ab + (bb - ab) * t, rgba(a)[0])


def with_alpha(colour, alpha):
    return '%02X%s' % (max(0, min(255, int(alpha))), colour[2:])


def lighten_or_darken(colour, amount):
    """Move a surface a little towards white (dark surfaces) or black (light surfaces)."""
    target = WHITE if is_dark(colour) else 'FF000000'
    return mix(colour, target, amount)


def minutes(text, default):
    """'07:00' -> 420."""
    try:
        h, m = (text or '').split(':')[:2]
        return (int(h) % 24) * 60 + int(m) % 60
    except (ValueError, AttributeError):
        return default


def is_day(now, day_starts='07:00', night_starts='19:00'):
    t = now.hour * 60 + now.minute
    start, end = minutes(day_starts, 420), minutes(night_starts, 1140)
    if start == end:
        return True
    if start < end:
        return start <= t < end
    return t >= start or t < end


def on_colour(background):
    """White or ink, whichever reads better on this colour."""
    return WHITE if contrast(WHITE, background) >= contrast(INK_TEXT, background) else INK_TEXT


def resolve(settings, now):
    """settings: theme, day_starts, night_starts, accent, accent_custom, bg_custom, card_custom,
    option_custom, text_custom, muted_custom, good_custom, bad_custom, background_style.
    -> dict of colour tokens plus 'glow_on' and 'name'."""
    mode = settings.get('theme', MODE_INK)
    if mode == MODE_AUTO:
        day = is_day(now, settings.get('day_starts', '07:00'), settings.get('night_starts', '19:00'))
        mode = MODE_PAPER if day else MODE_INK
    palette = dict(THEMES[mode] if 0 <= mode < len(THEMES) else INK)
    palette['name'] = ['ink', 'paper', 'midnight'][mode] if 0 <= mode < 3 else 'ink'

    accent_index = settings.get('accent', THEME_ACCENT)
    if accent_index == CUSTOM:
        accent = parse_hex(settings.get('accent_custom', '')) or palette['accent'] or ACCENTS[0]
    elif 1 <= accent_index <= len(ACCENTS):
        accent = ACCENTS[accent_index - 1]
    else:
        accent = palette['accent'] or ACCENTS[0]   # Theme (or an invalid value)
    palette['accent'] = accent

    custom = {
        'bg': parse_hex(settings.get('bg_custom', '')),
        'card': parse_hex(settings.get('card_custom', '')),
        'option': parse_hex(settings.get('option_custom', '')),
        'text': parse_hex(settings.get('text_custom', '')),
        'muted': parse_hex(settings.get('muted_custom', '')),
        'good': parse_hex(settings.get('good_custom', '')),
        'bad': parse_hex(settings.get('bad_custom', '')),
    }
    for key, value in custom.items():
        if value:
            palette[key] = value

    # A custom card with no custom text: pick the text that reads better on it.
    if custom['card'] and not custom['text']:
        palette['text'] = on_colour(palette['card'])
        if not custom['muted']:
            palette['muted'] = mix(palette['card'], palette['text'], 0.55)
    if not custom['card'] and custom['bg']:
        palette['card'] = lighten_or_darken(palette['bg'], 0.055)
    if not custom['option'] and (custom['card'] or custom['bg']):
        palette['option'] = lighten_or_darken(palette['card'], 0.075)
    palette['hairline'] = '1FFFFFFF' if is_dark(palette['card']) else '22000000'

    palette['on_accent'] = on_colour(palette['accent'])
    palette['on_good'] = on_colour(palette['good'])
    palette['on_bad'] = on_colour(palette['bad'])
    palette['soft'] = with_alpha(palette['accent'], 0x2E)       # chips, selected tiles
    palette['glow'] = with_alpha(palette['accent'], 0x22)       # the soft background glow
    palette['shadow'] = '90000000' if is_dark(palette['bg']) else '26000000'
    palette['scrim'] = SCRIM
    palette['glow_on'] = '1' if settings.get('background_style', 1) == 1 else ''
    palette['dim_alpha'] = '%02X' % int(round(settings.get('dim', 0) * 2.55))
    return palette


PROPERTIES = ('bg', 'card', 'option', 'text', 'muted', 'hairline', 'accent', 'good', 'bad',
              'on_accent', 'on_good', 'on_bad', 'soft', 'glow', 'shadow', 'scrim', 'glow_on')
