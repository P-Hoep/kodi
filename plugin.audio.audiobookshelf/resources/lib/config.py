"""Every setting in one table: tools/make_settings_audiobookshelf.py turns it into
settings.xml and strings.po, and read() loads values with the right types and defaults.
No Kodi imports.
"""

ADDON_ID = 'plugin.audio.audiobookshelf'
ADDON_NAME = 'Audiobookshelf'
PLUGIN = 'plugin://%s/' % ADDON_ID

# Sort orders the library items endpoint honours (checked against a 2.28 server; it
# silently ignores media.metadata.seriesName, so series order comes from the Series view).
SORTS = [
    ('Title', 'media.metadata.title', False),
    ('Author', 'media.metadata.authorNameLF', False),
    ('Recently added', 'addedAt', True),
]

CATEGORIES = [
    ('Server', [
        dict(id='server_url', type='string', label='Server address (e.g. http://192.168.1.10:13378)', default=''),
        dict(id='api_key', type='string', label='API key (Audiobookshelf: Settings > API Keys)', default='',
             hidden=True),
        dict(id='test_connection', type='action', label='Test connection...',
             data='RunPlugin(%s?action=test)' % PLUGIN),
        dict(id='choose_library', type='action', label='Choose library...',
             data='RunPlugin(%s?action=choose_library)' % PLUGIN),
        dict(id='library_id', type='string', label='Library id (blank = first audiobook library)', default=''),
        dict(id='timeout', type='slider', label='Connection timeout (seconds)', default=15, min=5, max=60, step=5),
    ]),
    ('Playback', [
        dict(id='skip_back', type='slider', label='Skip back (seconds)', default=15, min=5, max=120, step=5),
        dict(id='skip_forward', type='slider', label='Skip forward (seconds)', default=30, min=5, max=300, step=5),
        dict(id='resume_rewind', type='slider', label='Step back when resuming (seconds)', default=0,
             min=0, max=30, step=1),
    ]),
    ('Progress & library', [
        dict(id='sync_interval', type='slider', label='Send progress every (seconds)', default=30,
             min=10, max=120, step=5),
        dict(id='page_size', type='slider', label='Books per page', default=50, min=25, max=200, step=25),
        dict(id='sort', type='options', label='Sort All Audiobooks by', default=0,
             options=[name for name, _key, _desc in SORTS]),
        dict(id='cache_minutes', type='slider', label='Keep library lists for (minutes, 0 = always refresh)',
             default=15, min=0, max=240, step=5),
        dict(id='clear_cache', type='action', label='Clear cached library data',
             data='RunPlugin(%s?action=clear_cache)' % PLUGIN),
    ]),
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
            elif s['type'] == 'options':
                out[s['id']] = min(len(s['options']) - 1, max(0, int(getters['integer'](s['id']))))
            else:
                out[s['id']] = getters['string'](s['id']).strip()
        except Exception:
            out[s['id']] = s['default']
    out['server_url'] = normalise_url(out['server_url'])
    return out


def defaults():
    return dict((s['id'], s['default']) for s in all_settings())


def normalise_url(url):
    """'192.168.1.10:13378/' -> 'http://192.168.1.10:13378'. Blank stays blank."""
    url = (url or '').strip().rstrip('/')
    if url and '://' not in url:
        url = 'http://' + url
    return url
