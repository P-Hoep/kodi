"""Every setting in one table: tools/make_settings_switcher.py turns it into settings.xml
and strings.po, and read() loads values with the right types and defaults. No Kodi imports.

A schedule is SLOTS time windows, each with an on/off switch, a start, an end, a
screensaver and optionally a second one to alternate with, plus a default screensaver for
the times no window covers.
"""

ADDON_ID = 'service.screensaver.switcher'
SCREENSAVER = 'xbmc.ui.screensaver'
SLOTS = 6

# Ready-to-use examples so the first window is obvious; all start switched off.
EXAMPLES = [('08:00', '17:00'), ('17:00', '22:00'), ('22:00', '06:00'),
            ('06:00', '08:00'), ('12:00', '13:00'), ('00:00', '00:00')]


def slot_settings(n):
    start, end = EXAMPLES[n - 1]
    on = 'w%d_on' % n
    return [
        dict(id='g%d' % n, type='group', label='Window %d' % n),
        dict(id=on, type='boolean', label='Use this window', default=False),
        dict(id='w%d_start' % n, type='time', label='Starts at', default=start, visible=on),
        dict(id='w%d_end' % n, type='time', label='Ends at (same as start = all day)', default=end, visible=on),
        dict(id='w%d_screensaver' % n, type='addon', label='Screensaver', default='',
             addontype=SCREENSAVER, visible=on),
        dict(id='w%d_alt' % n, type='addon', label='Alternate with (optional)', default='',
             addontype=SCREENSAVER, visible=on),
    ]


CATEGORIES = [
    ('General', [
        dict(id='enabled', type='boolean', label='Switch screensavers on a schedule', default=True),
        dict(id='default_screensaver', type='addon', label='Default screensaver (outside every window; blank = leave as is)',
             default='', addontype=SCREENSAVER),
        dict(id='alternate_minutes', type='slider', label='Alternate every (minutes)', default=30,
             min=5, max=240, step=5),
        dict(id='reload', type='boolean', label='Restart a running screensaver when the choice changes', default=True),
        dict(id='status', type='action', label='Show what is scheduled now...',
             data='RunScript(%s)' % ADDON_ID),
    ]),
    ('Windows 1-3', sum((slot_settings(n) for n in (1, 2, 3)), [])),
    ('Windows 4-6', sum((slot_settings(n) for n in (4, 5, 6)), [])),
]


def all_settings():
    for _title, settings in CATEGORIES:
        for s in settings:
            if s['type'] not in ('action', 'group'):
                yield s


def read(getters):
    """Settings as a dict. getters: {'boolean': f(id), 'integer': f(id), 'string': f(id)}
    (the Kodi layer passes Addon accessors). Bad or missing values fall back to defaults."""
    out = {}
    for s in all_settings():
        try:
            if s['type'] == 'boolean':
                out[s['id']] = bool(getters['boolean'](s['id']))
            elif s['type'] == 'slider':
                out[s['id']] = min(s['max'], max(s['min'], int(getters['integer'](s['id']))))
            else:
                out[s['id']] = getters['string'](s['id']).strip()
        except Exception:
            out[s['id']] = s['default']
    return out


def defaults():
    return dict((s['id'], s['default']) for s in all_settings())
