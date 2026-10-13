"""Shared scene context and helpers. No Kodi imports."""

import hashlib
import os
import time

from .. import cache
from ..layout import ACCENT, DIM, SOFT, WHITE, Layout

W, H = 1920, 1080
MARGIN = 96
TOP = 200          # content starts below the title and the overlay clock
BOTTOM = 1010      # the attribution footer sits below

# WMO weather codes -> (text, day icon, night icon)
WMO = {
    0: ('Clear', 'clear-day', 'clear-night'),
    1: ('Mostly clear', 'partly-cloudy-day', 'partly-cloudy-night'),
    2: ('Partly cloudy', 'partly-cloudy-day', 'partly-cloudy-night'),
    3: ('Overcast', 'overcast-day', 'overcast-night'),
    45: ('Fog', 'fog-day', 'fog-night'), 48: ('Freezing fog', 'fog-day', 'fog-night'),
    51: ('Light drizzle', 'partly-cloudy-day-drizzle', 'partly-cloudy-night-drizzle'),
    53: ('Drizzle', 'drizzle', 'drizzle'), 55: ('Heavy drizzle', 'drizzle', 'drizzle'),
    56: ('Freezing drizzle', 'sleet', 'sleet'), 57: ('Freezing drizzle', 'sleet', 'sleet'),
    61: ('Light rain', 'partly-cloudy-day-rain', 'partly-cloudy-night-rain'),
    63: ('Rain', 'rain', 'rain'), 65: ('Heavy rain', 'rain', 'rain'),
    66: ('Freezing rain', 'sleet', 'sleet'), 67: ('Freezing rain', 'sleet', 'sleet'),
    71: ('Light snow', 'partly-cloudy-day-snow', 'partly-cloudy-night-snow'),
    73: ('Snow', 'snow', 'snow'), 75: ('Heavy snow', 'snow', 'snow'), 77: ('Snow grains', 'snow', 'snow'),
    80: ('Showers', 'partly-cloudy-day-rain', 'partly-cloudy-night-rain'),
    81: ('Showers', 'rain', 'rain'), 82: ('Violent showers', 'rain', 'rain'),
    85: ('Snow showers', 'partly-cloudy-day-snow', 'partly-cloudy-night-snow'),
    86: ('Heavy snow showers', 'snow', 'snow'),
    95: ('Thunderstorms', 'thunderstorms-day-rain', 'thunderstorms-night-rain'),
    96: ('Thunderstorms with hail', 'thunderstorms-rain', 'thunderstorms-rain'),
    99: ('Thunderstorms with hail', 'hail', 'hail'),
}
DAYS = ['Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat', 'Sun']
LONG_DAYS = ['Monday', 'Tuesday', 'Wednesday', 'Thursday', 'Friday', 'Saturday', 'Sunday']
MONTHS = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec']


def weather_text(code):
    return WMO.get(code, ('Weather', 'not-available', 'not-available'))[0]


def icon(code, is_day=True):
    entry = WMO.get(code)
    if not entry:
        return 'icons/not-available.png'
    return 'icons/%s.png' % (entry[1] if is_day else entry[2])


class Context(object):
    """What a scene needs: settings, units, the data hub and the location."""

    def __init__(self, settings, units, hub, profile, place, now=None):
        self.s = settings
        self.u = units
        self.hub = hub
        self.profile = profile
        self.place = place
        self.now = time.time() if now is None else now
        self.lat, self.lon = settings['lat'], settings['lon']
        self.fc = hub.get('forecast') if hub else None
        self.offset = (self.fc or {}).get('offset', 0)
        self.thumb = None

    def local(self, epoch):
        return time.gmtime(epoch + self.offset)

    def day_name(self, epoch, long=False):
        tm = self.local(epoch)
        today = self.local(self.now)
        if tm.tm_yday == today.tm_yday and tm.tm_year == today.tm_year:
            return 'Today'
        return (LONG_DAYS if long else DAYS)[tm.tm_wday]

    def date_text(self, epoch):
        tm = self.local(epoch)
        return '%s %s %d' % (DAYS[tm.tm_wday], MONTHS[tm.tm_mon - 1], tm.tm_mday)

    def clock(self, epoch):
        return self.u.clock(epoch, self.offset) if epoch else '--'

    def hour(self, epoch):
        return self.u.hour(epoch, self.offset)

    def chart(self, name, chart_png):
        """Write chart PNG bytes under profile/charts with a content-hash name (Kodi caches
        textures by path), delete older versions, and return the path."""
        digest = hashlib.md5(chart_png).hexdigest()[:10]
        folder = os.path.join(self.profile, 'charts')
        path = os.path.join(folder, '%s_%s.png' % (name, digest))
        if not os.path.exists(path):
            cache.write_atomic(path, chart_png)
        try:
            for other in os.listdir(folder):
                if other.startswith(name + '_') and other != os.path.basename(path):
                    full = os.path.join(folder, other)
                    if time.time() - os.path.getmtime(full) > 120:
                        os.remove(full)
        except OSError:
            pass
        return path

    def hourly_index(self):
        """Index of the current hour in the forecast's hourly arrays."""
        times = ((self.fc or {}).get('hourly') or {}).get('time') or []
        for i, t in enumerate(times):
            if t > self.now - 3600:
                return i
        return 0


def header(title, subtitle='', background='bg.jpg'):
    """A layout with the scene title at the top left."""
    lay = Layout(title, background)
    lay.rect(MARGIN, 66, 8, 64, ACCENT)
    lay.label(MARGIN + 30, 58, 1100, 70, title, 'xl', color=WHITE)
    if subtitle:
        lay.label(MARGIN + 32, 136, 1150, 40, subtitle, 'sm', color=SOFT)
    return lay


def wrap(text, chars, lines=2):
    """Greedy word wrap into at most `lines` lines of about `chars` characters."""
    words = (text or '').split()
    out, cur = [], ''
    for w in words:
        if len(cur) + len(w) + (1 if cur else 0) <= chars:
            cur = (cur + ' ' + w).strip()
        else:
            if cur:
                out.append(cur)
            cur = w
            if len(out) == lines:
                break
    if cur and len(out) < lines:
        out.append(cur)
    if len(out) == lines and len(' '.join(out)) < len(' '.join(words)):
        out[-1] = out[-1][:max(1, chars - 1)].rstrip() + '…'
    return out


def tile(lay, x, y, w, h, caption, value, sub='', icon_path=None, value_color=WHITE):
    """A labelled value tile: caption small and dim, value large."""
    lay.card(x, y, w, h)
    tx = x + 28
    if icon_path:
        lay.image(x + 16, y + (h - 96) // 2, 96, 96, icon_path)
        tx = x + 120
    lay.label(tx, y + 18, w - (tx - x) - 16, 34, caption.upper(), 'xs', color=DIM)
    lay.label(tx, y + 50, w - (tx - x) - 16, 60, value, 'lg', color=value_color)
    if sub:
        lay.label(tx, y + h - 46, w - (tx - x) - 16, 34, sub, 'xs', color=SOFT)


def series(fc, name, start=None, end=None):
    """(times, values) from the forecast's hourly arrays between start and end."""
    hourly = (fc or {}).get('hourly') or {}
    times = hourly.get('time') or []
    values = hourly.get(name) or [None] * len(times)
    out_t, out_v = [], []
    for t, v in zip(times, values):
        if (start is None or t >= start) and (end is None or t <= end):
            out_t.append(t)
            out_v.append(v)
    return out_t, out_v


def no_data(lay, text='Waiting for data...'):
    lay.label(W // 2, H // 2 - 30, 1200, 60, text, 'lg', 'center', SOFT)
    return lay


def place_chart(lay, ctx, name, chart, x0, y0, min_width=200):
    """Put a chart image and its text labels on the layout at (x0, y0)."""
    lay.image(x0, y0, chart.w, chart.h, ctx.chart(name, chart.png()))
    for x, y, text, align, size, color in chart.labels:
        width = max(min_width, int(len(text) * {'xs': 14, 'sm': 18, 'md': 22, 'lg': 27, 'xl': 36}.get(size, 18)))
        if align == 'center':
            lx = x0 + x - width // 2
        elif align == 'right':
            lx = x0 + x - width
        else:
            lx = x0 + x
        lay.label(lx, y0 + y, width, 34, text, size, align, color)
