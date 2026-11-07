"""Accent colours, Day / Night tokens, theme scheduling and a local sunrise / sunset
calculation (NOAA's algorithm, no network). Colours are Kodi AARRGGBB strings; the window
reads them from properties, so a theme change needs no XML edits.
"""

import datetime
import math
import re

# Windows Phone 8 accents (spec 2.4), in the order the settings list shows them.
ACCENTS = [
    ('Lime', 'A4C400'), ('Green', '60A917'), ('Emerald', '008A00'), ('Teal', '00ABA9'), ('Cyan', '1BA1E2'),
    ('Cobalt', '0050EF'), ('Indigo', '6A00FF'), ('Violet', 'AA00FF'), ('Pink', 'F472D0'), ('Magenta', 'D80073'),
    ('Crimson', 'A20025'), ('Red', 'E51400'), ('Orange', 'FA6800'), ('Amber', 'F0A30A'), ('Yellow', 'E3C800'),
    ('Brown', '825A2C'), ('Olive', '6D8764'), ('Steel', '647687'), ('Mauve', '76608A'), ('Taupe', '87794E'),
]
ACCENT_NAMES = [name for name, _hex in ACCENTS] + ['Custom']
CUSTOM = len(ACCENTS)
DEFAULT_ACCENT = 5            # Cobalt

MODE_NIGHT, MODE_DAY, MODE_SCHEDULED, MODE_SUN = 0, 1, 2, 3
MIN_CONTRAST = 3.0            # WCAG AA for large text

NIGHT = {'bg': 'FF000000', 'text': 'FFFFFFFF', 'text2': 'FFA0A0A0', 'panel': 'FF111111', 'scrim': 'B3000000',
         'tile': 'FF1C1C1C', 'hairline': '33FFFFFF', 'name': 'night'}
DAY = {'bg': 'FFFFFFFF', 'text': 'FF000000', 'text2': 'FF5A5A5A', 'panel': 'FFF2F2F2', 'scrim': '99000000',
       'tile': 'FFE6E6E6', 'hairline': '33000000', 'name': 'day'}


def parse_hex(text):
    """'#AbC123', 'abc123', 'FFABC123' or 'abc' -> 'ABC123'; None if not a colour."""
    t = (text or '').strip().lstrip('#').upper()
    if re.match(r'^[0-9A-F]{6}$', t):
        return t
    if re.match(r'^[0-9A-F]{8}$', t):
        return t[2:]
    if re.match(r'^[0-9A-F]{3}$', t):
        return ''.join(ch * 2 for ch in t)
    return None


def accent_hex(value):
    """A palette name ('Cobalt'), an index, or a hex string -> 'RRGGBB', or None."""
    if value is None or value == '':
        return None
    if isinstance(value, int):
        return ACCENTS[value][1] if 0 <= value < len(ACCENTS) else None
    for name, hexa in ACCENTS:
        if str(value).strip().lower() == name.lower():
            return hexa
    return parse_hex(str(value))


def rgb(hexa):
    hexa = hexa[-6:]
    return tuple(int(hexa[i:i + 2], 16) for i in (0, 2, 4))


def luminance(hexa):
    def channel(v):
        v /= 255.0
        return v / 12.92 if v <= 0.03928 else ((v + 0.055) / 1.055) ** 2.4
    r, g, b = (channel(v) for v in rgb(hexa))
    return 0.2126 * r + 0.7152 * g + 0.0722 * b


def contrast(a, b):
    la, lb = luminance(a), luminance(b)
    hi, lo = max(la, lb), min(la, lb)
    return (hi + 0.05) / (lo + 0.05)


def white_contrast(hexa):
    return contrast('FFFFFF', hexa)


def shade(hexa, amount):
    """Darken (amount < 0) or lighten (amount > 0) by a fraction, e.g. -0.12."""
    r, g, b = rgb(hexa)
    if amount < 0:
        f = 1 + amount
        r, g, b = r * f, g * f, b * f
    else:
        r, g, b = r + (255 - r) * amount, g + (255 - g) * amount, b + (255 - b) * amount
    return '%02X%02X%02X' % tuple(int(round(max(0, min(255, v)))) for v in (r, g, b))


def argb(hexa, alpha='FF'):
    return alpha + hexa[-6:]


# ------------------------------------------------------------------ schedule

def minutes(text, default):
    """'07:00' -> 420."""
    try:
        h, m = (text or '').split(':')[:2]
        return (int(h) % 24) * 60 + int(m) % 60
    except (ValueError, AttributeError):
        return default


def in_window(t, start, end):
    """t, start, end in minutes since midnight; the window may wrap past midnight."""
    if start == end:
        return True
    if start < end:
        return start <= t < end
    return t >= start or t < end


def sun_times(date, lat, lon):
    """(sunrise, sunset) in minutes after UTC midnight of date, for latitude / longitude in
    degrees (east positive). (None, None) on a polar night, (0, 1440) on a polar day.
    NOAA solar calculator equations; accurate to a minute or two."""
    n = date.timetuple().tm_yday
    gamma = 2 * math.pi / 365 * (n - 1)
    eqtime = 229.18 * (0.000075 + 0.001868 * math.cos(gamma) - 0.032077 * math.sin(gamma)
                       - 0.014615 * math.cos(2 * gamma) - 0.040849 * math.sin(2 * gamma))
    decl = (0.006918 - 0.399912 * math.cos(gamma) + 0.070257 * math.sin(gamma) - 0.006758 * math.cos(2 * gamma)
            + 0.000907 * math.sin(2 * gamma) - 0.002697 * math.cos(3 * gamma) + 0.00148 * math.sin(3 * gamma))
    phi = math.radians(lat)
    cos_ha = (math.cos(math.radians(90.833)) / (math.cos(phi) * math.cos(decl)) - math.tan(phi) * math.tan(decl))
    if cos_ha > 1:
        return None, None
    if cos_ha < -1:
        return 0.0, 1440.0
    ha = math.degrees(math.acos(cos_ha))
    sunrise = 720 - 4 * (lon + ha) - eqtime
    sunset = 720 - 4 * (lon - ha) - eqtime
    return sunrise, sunset


def is_day_by_sun(now, lat, lon, offset_min=0, utc_offset_min=None):
    """now: a local naive datetime. utc_offset_min: local time minus UTC (computed from the
    system when None)."""
    if utc_offset_min is None:
        utc_offset_min = local_utc_offset(now)
    rise, sset = sun_times(now.date(), lat, lon)
    if rise is None:
        return False
    if rise == 0.0 and sset == 1440.0:
        return True
    t = now.hour * 60 + now.minute
    rise_local = (rise + utc_offset_min + offset_min) % 1440
    set_local = (sset + utc_offset_min - offset_min) % 1440
    return in_window(t, rise_local, set_local)


def local_utc_offset(now):
    import time
    try:
        stamp = time.mktime(now.timetuple())
        local = datetime.datetime.fromtimestamp(stamp)
        utc = datetime.datetime.utcfromtimestamp(stamp)
        return int(round((local - utc).total_seconds() / 60.0))
    except (OverflowError, ValueError, OSError):
        return 0


def is_day(settings, now):
    mode = settings.get('theme_mode', MODE_NIGHT)
    if mode == MODE_DAY:
        return True
    if mode == MODE_SCHEDULED:
        t = now.hour * 60 + now.minute
        return in_window(t, minutes(settings.get('day_start'), 420), minutes(settings.get('night_start'), 1140))
    if mode == MODE_SUN:
        try:
            lat = float(settings.get('latitude', 0) or 0)
            lon = float(settings.get('longitude', 0) or 0)
        except (TypeError, ValueError):
            lat, lon = 0.0, 0.0
        return is_day_by_sun(now, lat, lon, int(settings.get('sun_offset', 0) or 0),
                             settings.get('utc_offset'))
    return False


# ------------------------------------------------------------------ palette

def global_accent(settings):
    index = settings.get('accent', DEFAULT_ACCENT)
    if index == CUSTOM:
        return parse_hex(settings.get('accent_custom', '')) or ACCENTS[DEFAULT_ACCENT][1]
    return accent_hex(index) or ACCENTS[DEFAULT_ACCENT][1]


def custom_accent_warning(settings):
    """True when a custom accent is too light for white tile text (below 3:1)."""
    if settings.get('accent', DEFAULT_ACCENT) != CUSTOM:
        return False
    hexa = parse_hex(settings.get('accent_custom', ''))
    return bool(hexa) and white_contrast(hexa) < MIN_CONTRAST


def resolve(settings, now):
    """Theme tokens + accent for the window properties."""
    day = is_day(settings, now)
    palette = dict(DAY if day else NIGHT)
    accent = global_accent(settings)
    palette['accent_hex'] = accent
    palette['accent'] = argb(accent)
    return palette


def feed_accent(feed, settings, global_hex):
    if settings.get('per_feed_accents', True) and feed is not None and feed.accent:
        return accent_hex(feed.accent) or global_hex
    return global_hex


def tile_colour(accent, index, settings):
    """Tile shade variation: every other text tile 12 % darker (or lighter on a dark accent)."""
    if settings.get('shade_variation', True) and index % 2 == 1:
        return shade(accent, 0.14 if luminance(accent) < 0.04 else -0.14)
    return accent


PROPERTIES = ('bg', 'text', 'text2', 'panel', 'scrim', 'tile', 'hairline', 'accent')
