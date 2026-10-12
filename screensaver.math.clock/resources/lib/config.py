"""Every setting in one table: tools/make_settings_mathclock.py turns it into settings.xml
and strings.po, and read() loads values with the right types and defaults. No Kodi imports.

The first six map themathclock.com's settings dialog (Show Seconds, 24 hour clock,
Inverted Colors, Date, Labels, Day/Night Display mode); the rest are screensaver extras.
"""

from . import equations

ADDON_ID = 'screensaver.math.clock'

COLOURS = ['Light (original)', 'Dark (original "Inverted Colors")',
           'Day/night: light 8:00-16:59, dark otherwise (original "Day/Night")']


def B(sid, label, default, **kw):
    return dict(id=sid, type='boolean', label=label, default=default, **kw)


def O(sid, label, default, options, **kw):
    return dict(id=sid, type='options', label=label, default=default, options=options, **kw)


def S(sid, label, default, lo, hi, step=1, **kw):
    return dict(id=sid, type='slider', label=label, default=default, min=lo, max=hi, step=step, **kw)


CATEGORIES = [
    ('Clock', [
        B('seconds', 'Show seconds', True),
        B('military', '24-hour clock', False),
        B('military_badge', 'Show a 24h badge in the corner', True, visible='military'),
        B('date', 'Show the date (year, month, day)', True),
        O('date_order', 'Date order', 0, ['Year, month, day (original)', 'Month, day, year',
                                           'Day, month, year'], visible='date'),
        B('labels', 'Label each row (year, month, day, hours...)', True),
        O('variables', 'Variable letters', 0, ['m for month and minute (original)',
                                               'M for month, m for minute']),
    ]),
    ('Equations', [
        O('equation_set', 'Kinds of equations', 3, equations.SET_NAMES),
        O('refresh', 'New equations for the date and hour rows', 0,
          ['Every minute (original)', 'Every 30 seconds', 'Every 10 seconds']),
    ]),
    ('Appearance', [
        O('colours', 'Colours', 1, COLOURS),
        S('text_size', 'Text size (%)', 100, 60, 140, 10),
        B('separators', 'Lines between rows', True),
        O('transition', 'When an equation changes', 0, ['Fade', 'Cut']),
        S('dim', 'Dim (%)', 0, 0, 80, 10),
        B('drift', 'Slowly drift the layout (protects OLED/plasma screens)', True),
    ]),
]


def all_settings():
    for _title, settings in CATEGORIES:
        for s in settings:
            if s['type'] != 'action':
                yield s


def read(getters):
    """Settings as a dict. getters: {'boolean': f(id), 'integer': f(id)} (the Kodi layer
    passes Addon accessors). Bad or missing values fall back to defaults."""
    out = {}
    for s in all_settings():
        try:
            if s['type'] == 'boolean':
                out[s['id']] = bool(getters['boolean'](s['id']))
            else:
                value = int(getters['integer'](s['id']))
                if s['type'] == 'options' and not 0 <= value < len(s['options']):
                    value = s['default']
                if s['type'] == 'slider':
                    value = min(s['max'], max(s['min'], value))
                out[s['id']] = value
        except Exception:
            out[s['id']] = s['default']
    return out


def defaults():
    return dict((s['id'], s['default']) for s in all_settings())
