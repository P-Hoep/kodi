"""Unit conversion and display formatting. Data is always fetched metric (°C, km/h, hPa,
mm, m) and converted here. No Kodi imports."""

import time

COMPASS = ['N', 'NNE', 'NE', 'ENE', 'E', 'ESE', 'SE', 'SSE', 'S', 'SSW', 'SW', 'WSW', 'W', 'WNW', 'NW', 'NNW']


class Units(object):
    def __init__(self, settings):
        s = settings
        self.fahrenheit = s.get('u_temp', 0) == 0
        self.wind = ['mph', 'km/h', 'm/s', 'kn'][s.get('u_wind', 0)]
        self.pressure = ['inHg', 'hPa', 'mmHg'][s.get('u_pressure', 0)]
        self.precip = ['in', 'mm'][s.get('u_precip', 0)]
        self.distance = ['mi', 'km'][s.get('u_distance', 0)]
        self.clock24 = s.get('clock24', 0) == 1

    # ------------------------------------------------------------ numbers

    def t(self, c):
        """°C -> display number (float) or None."""
        if c is None:
            return None
        return c * 9.0 / 5.0 + 32.0 if self.fahrenheit else c

    def dt(self, delta_c):
        """A temperature difference."""
        if delta_c is None:
            return None
        return delta_c * 9.0 / 5.0 if self.fahrenheit else delta_c

    def w(self, kmh):
        if kmh is None:
            return None
        return kmh * {'mph': 0.621371, 'km/h': 1.0, 'm/s': 1 / 3.6, 'kn': 0.539957}[self.wind]

    def p(self, hpa):
        if hpa is None:
            return None
        return hpa * {'inHg': 0.0295300, 'hPa': 1.0, 'mmHg': 0.750062}[self.pressure]

    def mm(self, mm):
        if mm is None:
            return None
        return mm / 25.4 if self.precip == 'in' else mm

    def km(self, km):
        if km is None:
            return None
        return km * 0.621371 if self.distance == 'mi' else km

    # ------------------------------------------------------------ text

    def temp(self, c, unit=False):
        v = self.t(c)
        if v is None:
            return '--'
        return '%d°%s' % (int(round(v)), ('F' if self.fahrenheit else 'C') if unit else '')

    def temp_delta(self, delta_c):
        v = self.dt(delta_c)
        if v is None:
            return '--'
        return '%+d°' % int(round(v))

    def wind_text(self, kmh):
        v = self.w(kmh)
        if v is None:
            return '--'
        return '%d %s' % (int(round(v)), self.wind)

    def pressure_text(self, hpa):
        v = self.p(hpa)
        if v is None:
            return '--'
        return ('%.2f %s' if self.pressure == 'inHg' else '%d %s') % (v if self.pressure == 'inHg' else int(round(v)),
                                                                     self.pressure)

    def precip_text(self, mm):
        v = self.mm(mm)
        if v is None:
            return '--'
        if self.precip == 'in':
            return '%.2f in' % v
        return '%.1f mm' % v

    def distance_text(self, km):
        v = self.km(km)
        if v is None:
            return '--'
        return ('%.1f %s' if v < 10 else '%d %s') % (v, self.distance)

    def clock(self, epoch, offset=None, seconds=False):
        """Clock time of epoch. offset: the location's UTC offset in seconds (default: this
        device's local time)."""
        tm = time.localtime(epoch) if offset is None else time.gmtime(epoch + offset)
        if self.clock24:
            return time.strftime('%H:%M:%S' if seconds else '%H:%M', tm)
        h = tm.tm_hour % 12 or 12
        return '%d:%02d%s %s' % (h, tm.tm_min, (':%02d' % tm.tm_sec) if seconds else '',
                                 'AM' if tm.tm_hour < 12 else 'PM')

    def hour(self, epoch, offset=None):
        """Short hour label: '3 PM' or '15'."""
        tm = time.localtime(epoch) if offset is None else time.gmtime(epoch + offset)
        if self.clock24:
            return '%02d' % tm.tm_hour
        h = tm.tm_hour % 12 or 12
        return '%d %s' % (h, 'AM' if tm.tm_hour < 12 else 'PM')


def compass(degrees):
    if degrees is None:
        return ''
    return COMPASS[int((degrees % 360) / 22.5 + 0.5) % 16]


def ago(seconds):
    """'just now', '3 min ago', '2 h ago'."""
    if seconds is None:
        return ''
    seconds = max(0, seconds)
    if seconds < 90:
        return 'just now'
    if seconds < 3600 * 1.5:
        return '%d min ago' % int(round(seconds / 60.0))
    if seconds < 86400 * 1.5:
        return '%d h ago' % int(round(seconds / 3600.0))
    return '%d days ago' % int(round(seconds / 86400.0))
