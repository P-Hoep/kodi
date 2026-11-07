"""Palette resolution: Night / Day / Auto, accent presets, custom colours and contrast.

Colours are Kodi's AARRGGBB hex strings. The window reads them from properties
(sc.bg, sc.card, ...) in colordiffuse / textcolor, so a theme change needs no XML edits.
"""

import re

NIGHT = {'bg': 'FF0E1116', 'card': 'FF1A1F27', 'text': 'FFF2F4F7', 'muted': 'FF9AA3AF',
         'hairline': '1FFFFFFF', 'good': 'FF34C77B', 'bad': 'FFFF5C5C'}
DAY = {'bg': 'FFF4F5F7', 'card': 'FFFFFFFF', 'text': 'FF14171C', 'muted': 'FF5B6472',
       'hairline': '1A000000', 'good': 'FF1F9D5A', 'bad': 'FFE5484D'}
ACCENTS = ['FF6366F1', 'FF14B8A6', 'FFFF6B5B', 'FFF5A524', 'FFEC4899', 'FF38BDF8']
ACCENT_NAMES = ['Indigo', 'Teal', 'Coral', 'Amber', 'Rose', 'Sky', 'Custom']
CUSTOM = len(ACCENTS)
MODE_NIGHT, MODE_DAY, MODE_AUTO = 0, 1, 2
GLOW_ALPHA = '2E'   # 18 %
MIN_CONTRAST = 4.5


def parse_hex(text):
    """'#AbC123', 'abc123' or 'FFABC123' -> 'FFABC123'; None if not a colour."""
    t = (text or '').strip().lstrip('#').upper()
    if re.match(r'^[0-9A-F]{6}$', t):
        return 'FF' + t
    if re.match(r'^[0-9A-F]{8}$', t):
        return 'FF' + t[2:]
    if re.match(r'^[0-9A-F]{3}$', t):
        return 'FF' + ''.join(ch * 2 for ch in t)
    return None


def rgb(colour):
    return tuple(int(colour[i:i + 2], 16) for i in (2, 4, 6))


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


def resolve(settings, now):
    """settings: theme_mode, day_starts, night_starts, accent, accent_custom, bg_custom,
    card_custom, background_style. -> dict of tokens plus 'glow' and 'name'."""
    mode = settings.get('theme_mode', MODE_NIGHT)
    day = mode == MODE_DAY or (mode == MODE_AUTO and is_day(now, settings.get('day_starts', '07:00'),
                                                            settings.get('night_starts', '19:00')))
    palette = dict(DAY if day else NIGHT)
    palette['name'] = 'day' if day else 'night'
    accent_index = settings.get('accent', 0)
    if accent_index == CUSTOM:
        accent = parse_hex(settings.get('accent_custom', '')) or ACCENTS[0]
    else:
        accent = ACCENTS[accent_index] if 0 <= accent_index < len(ACCENTS) else ACCENTS[0]
    palette['accent'] = accent
    bg = parse_hex(settings.get('bg_custom', ''))
    card = parse_hex(settings.get('card_custom', ''))
    if bg:
        palette['bg'] = bg
    if card:
        palette['card'] = card
    if bg or card:
        fix_text(palette)
    palette['glow'] = GLOW_ALPHA + accent[2:]
    palette['soft'] = '33' + accent[2:]          # 20 % accent: chips, selected tiles
    palette['on_accent'] = 'FFFFFFFF' if contrast('FFFFFFFF', accent) >= contrast('FF14171C', accent) else 'FF14171C'
    palette['shadow'] = '90000000' if is_dark(palette['bg']) else '26000000'
    palette['glow_on'] = '1' if settings.get('background_style', 1) == 1 else ''
    return palette


def fix_text(palette):
    """Custom background or card: pick light or dark text, whichever reads better on the card."""
    card = palette['card']
    light = NIGHT if contrast(NIGHT['text'], card) >= contrast(DAY['text'], card) else DAY
    palette['text'] = light['text']
    palette['muted'] = light['muted'] if contrast(light['muted'], card) >= 3.0 else light['text']
    palette['hairline'] = '1FFFFFFF' if is_dark(card) else '1A000000'
    return palette


PROPERTIES = ('bg', 'card', 'text', 'muted', 'hairline', 'accent', 'good', 'bad', 'glow', 'soft', 'on_accent',
              'shadow', 'glow_on')
