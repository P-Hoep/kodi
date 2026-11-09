"""Every setting in one place. tools/make_settings_jeopkodi.py turns the table into
settings.xml and strings.po; read() loads values with the right types and defaults.
No Kodi imports.
"""

ADDON_ID = 'screensaver.jeopkodi'


def B(sid, label, default, **kw):
    return dict(id=sid, type='boolean', label=label, default=default, **kw)


def O(sid, label, default, options, **kw):
    return dict(id=sid, type='options', label=label, default=default, options=options, **kw)


def S(sid, label, default, lo, hi, step=1, **kw):
    return dict(id=sid, type='slider', label=label, default=default, min=lo, max=hi, step=step, **kw)


def G(label):
    return dict(id='', type='group', label=label)


# Board rows: level 1 is the cheapest row ($200, or $100 before November 2001), level 5 the top.
CATEGORIES = [
    ('Clues', [
        G('Difficulty (by the dollar value on the board)'),
        B('easy', 'Easy: the two cheapest rows ($200 and $400)', True),
        B('medium', 'Medium: the middle row ($600)', True),
        B('hard', 'Hard: the two top rows ($800 and $1000)', True),
        G('Special clues'),
        B('daily', 'Include Daily Doubles', True),
        B('final', 'Include Final Jeopardy clues', True),
        G('Years (season 1 aired in 1984, season 42 in 2026)'),
        S('year_min', 'Earliest year of clues to show', 1984, 1984, 2026, 1),
        S('year_max', 'Latest year of clues to show', 2026, 1984, 2026, 1),
    ]),
    ('Timing', [
        S('clue_seconds', 'Seconds a clue stays up before the response', 12, 4, 60, 1),
        B('read_time', 'Leave more time for long clues', True),
        S('response_seconds', 'Seconds the response stays up', 6, 2, 30, 1),
    ]),
    ('Display', [
        B('show_header', 'Show the category at the top and the value at the bottom left', True),
        B('show_year', "Show the year of the clue at the bottom right", True),
        B('form', 'Phrase the response as a question (WHAT IS ... / WHO IS ...)', True),
        S('text_size', 'Text size (%)', 100, 60, 120, 10),
        S('dim', 'Dim the screen (%)', 0, 0, 80, 10),
    ]),
]

LEVELS = (('easy', (1, 2)), ('medium', (3,)), ('hard', (4, 5)))


def all_settings():
    return [s for _c, ss in CATEGORIES for s in ss if s['type'] != 'group']


def read(getters):
    """Settings as a dict. getters: {'boolean': f(id), 'integer': f(id)} (the Kodi layer passes
    Addon accessors). Bad or missing values fall back to defaults."""
    out = {}
    for s in all_settings():
        try:
            if s['type'] == 'boolean':
                out[s['id']] = bool(getters['boolean'](s['id']))
            else:
                value = int(getters['integer'](s['id']))
                if s['type'] == 'slider':
                    value = min(s['max'], max(s['min'], value))
                out[s['id']] = value
        except Exception:
            out[s['id']] = s['default']
    return out


def levels(s):
    """Board rows to show: [1..6] (6 is Final Jeopardy)."""
    out = []
    for key, rows in LEVELS:
        if s[key]:
            out.extend(rows)
    if s['final']:
        out.append(6)
    return out or [1, 2, 3, 4, 5]


def years(s):
    """(earliest, latest) air year to show, swapped if the two sliders cross."""
    lo, hi = s['year_min'], s['year_max']
    return (lo, hi) if lo <= hi else (hi, lo)
