"""Every setting in one table. tools/make_settings_opentrivia.py turns it into the app's and the
screensaver's settings.xml and strings.po; read() loads values with the right types and defaults.
No Kodi imports.

Each row says which front-end has it: 'both', 'app' (script.opentrivia) or 'ss' (the
screensaver). Category toggles, the look and the advanced settings are in both.
"""

from . import APP_ID, LIBRARY_ID, SCREENSAVER_ID
from .theme import ACCENT_NAMES, CUSTOM, THEME_NAMES

# The source files in OpenTrivia/categories, in the order the settings show them. The slug is
# the database's category column; the title is what the screen shows.
CATEGORIES = [
    ('animals', 'Animals'),
    ('brain-teasers', 'Brain Teasers'),
    ('celebrities', 'Celebrities'),
    ('entertainment', 'Entertainment'),
    ('for-kids', 'For Kids'),
    ('general', 'General'),
    ('geography', 'Geography'),
    ('history', 'History'),
    ('hobbies', 'Hobbies'),
    ('humanities', 'Humanities'),
    ('literature', 'Literature'),
    ('movies', 'Movies'),
    ('music', 'Music'),
    ('newest', 'Newest'),
    ('people', 'People'),
    ('rated', 'Rated'),
    ('religion-faith', 'Religion & Faith'),
    ('science-technology', 'Science & Technology'),
    ('sports', 'Sports'),
    ('television', 'Television'),
    ('video-games', 'Video Games'),
    ('world', 'World'),
]

TITLES = dict(CATEGORIES)
SESSION_LENGTHS = [10, 20, 30, 50, None]

# The setting id for a category, e.g. science-technology -> cat_science_technology. Kodi ids
# may not contain a hyphen.
def setting_id(slug):
    return 'cat_' + slug.replace('-', '_')


def category_slug(setting):
    return setting[4:].replace('_', '-')


def B(sid, label, default, who='both', **kw):
    return dict(id=sid, type='boolean', label=label, default=default, who=who, **kw)


def O(sid, label, default, options, who='both', **kw):
    return dict(id=sid, type='options', label=label, default=default, options=options, who=who, **kw)


def S(sid, label, default, lo, hi, step=1, who='both', **kw):
    return dict(id=sid, type='slider', label=label, default=default, min=lo, max=hi, step=step, who=who, **kw)


def T(sid, label, default='', who='both', **kw):
    return dict(id=sid, type='string', label=label, default=default, who=who, **kw)


def TIME(sid, label, default='07:00', who='both', **kw):
    return dict(id=sid, type='time', label=label, default=default, who=who, **kw)


def G(label):
    return dict(id='', type='group', label=label)


def _category_rows():
    groups = [
        ('Everyday', ['general', 'newest', 'rated', 'for-kids', 'people']),
        ('Arts & media', ['movies', 'music', 'television', 'celebrities', 'entertainment']),
        ('Knowledge', ['science-technology', 'history', 'geography', 'world', 'humanities']),
        ('Words & ideas', ['literature', 'religion-faith', 'brain-teasers']),
        ('Life & leisure', ['sports', 'hobbies', 'animals', 'video-games']),
    ]
    rows = [G('Categories to draw questions from (all are on at first)')]
    for title, slugs in groups:
        rows.append(G(title))
        for slug in slugs:
            rows.append(B(setting_id(slug), TITLES[slug], True))
    return rows


LAYOUTS = ['Auto', 'Cards', 'List']

SETTINGS = [
    ('Categories', _category_rows()),
    ('Quiz', [
        O('session_length', 'Questions per round', 1, ['10', '20', '30', '50', 'Endless'], who='app'),
        B('auto_advance', 'Move on automatically after an answer', True, who='app'),
        S('advance_correct_ms', 'After a correct answer (ms)', 1000, 300, 3000, 100, who='app',
          visible='auto_advance'),
        S('advance_wrong_ms', 'After a wrong answer (ms)', 2500, 500, 6000, 100, who='app',
          visible='auto_advance'),
    ]),
    ('Timing', [
        S('question_seconds', 'Seconds before the answer is revealed', 10, 3, 60, 1, who='ss'),
        S('reveal_seconds', 'Seconds the answer stays up', 6, 2, 30, 1, who='ss'),
        B('show_timer', 'Show the countdown bar', True, who='ss'),
        B('show_clock', 'Show the clock', True, who='ss'),
        S('dim_after_minutes', 'Dim after (minutes, 0 = never)', 0, 0, 120, 5, who='ss'),
    ]),
    ('Look', [
        O('theme', 'Theme', 0, THEME_NAMES),
        TIME('day_starts', 'Day starts at', '07:00', visible=('theme', 3)),
        TIME('night_starts', 'Night starts at', '19:00', visible=('theme', 3)),
        O('accent', 'Accent colour', 0, ACCENT_NAMES),
        T('accent_custom', 'Custom accent colour (hex RRGGBB)', visible=('accent', CUSTOM)),
        G('Custom colours (hex RRGGBB; empty uses the theme)'),
        T('bg_custom', 'Background'),
        T('card_custom', 'Question card'),
        T('option_custom', 'Answer options'),
        T('text_custom', 'Text'),
        T('muted_custom', 'Muted text'),
        T('good_custom', 'Correct answer'),
        T('bad_custom', 'Wrong answer'),
        G('Layout'),
        O('option_layout', 'Answer layout', 0, LAYOUTS),
        B('show_letters', 'Show the A/B/C/D letters', True),
        B('show_category', 'Show the category', True),
        B('show_number', 'Show the question number', True, who='app'),
        O('background_style', 'Background', 1, ['Solid', 'Soft glow']),
        S('text_size', 'Text size (%)', 100, 80, 130, 5),
        S('dim', 'Dim the screen (%)', 0, 0, 80, 5),
    ]),
    ('Advanced', [
        B('debug_log', 'Debug logging', False),
    ]),
]

# On-screen text, in the library's strings.po (ids from 32000). Both front-ends read these
# through kodi.tr(), with this table as the fallback before Kodi has loaded the new add-on.
STRINGS = {
    32000: 'Open Trivia',
    32001: 'A clean little quiz, drawn from the OpenTriviaQA collection.',
    32002: 'Start',
    32003: 'Settings',
    32004: 'Quit',
    32005: 'Play again',
    32006: 'Round complete',
    32007: '%d / %d',
    32008: '%d%% correct',
    32009: 'Best streak: %d',
    32010: 'Select an answer',
    32011: 'Select an answer  ·  Back to pause',
    32012: 'Next',
    32013: 'Correct',
    32014: 'Not quite',
    32015: 'Paused',
    32016: 'Resume',
    32017: 'End round',
    32018: 'No questions',
    32019: 'Turn on at least one category in the settings.',
    32020: 'All %d categories',
    32021: '%d categories',
    32022: '%d questions',
    32023: 'Question %d of %d',
    32024: 'Question %d',
    32025: 'Score',
    32026: 'Streak',
    32027: 'Settings saved',
    32028: 'Press Back to quit',
    32029: '%d correct',
    32030: '%d missed',
    32031: 'End of round',
    32032: 'Answer',
    32033: 'Open settings',
    32034: 'Back to start',
    32035: 'Something went wrong',
    32036: 'The question database is missing.',
    32037: 'Rebuild it with tools/make_opentrivia_db.py.',
    32038: 'Category',
    32039: 'All categories are off',
    32040: 'Showing every category',
    32041: '%d questions in play',
    32042: "Let's begin",
    32043: 'Your score',
    32044: 'Accuracy',
    32045: 'Best streak',
    32046: 'New best streak',
    32047: 'Choose categories in the settings',
    32048: 'Categories',
    32049: 'Next round',
    32050: 'Quit to Kodi',
    32051: 'Trivia',
    32052: '%s categories  ·  %s questions',
    32053: 'Auto',
    32054: 'Cards',
    32055: 'List',
    32056: 'Answer in %d',
    32057: 'Answer',
    32058: 'Reveal now',
    32059: '%d-question round',
    32060: 'Endless round',
}

# Window property -> string id for the static wording the skin shows. ui.View sets these once
# with kodi.tr(), so the generated XML only ever reads properties.
VIEW_STRINGS = {
    'title': 32000, 'tagline': 32001,
    't.start': 32002, 't.settings': 32003, 't.quit': 32004, 't.play_again': 32005,
    't.complete': 32006, 't.next': 32012, 't.correct': 32013, 't.not_quite': 32014,
    't.paused': 32015, 't.resume': 32016, 't.end': 32017, 't.no_questions': 32018,
    't.score': 32025, 't.streak': 32026, 't.back_quit': 32028, 't.answer': 32032,
    't.your_score': 32043, 't.accuracy': 32044, 't.best_streak': 32045, 't.quit_kodi': 32050,
}


def rows(who=None):
    for title, settings in SETTINGS:
        for s in settings:
            if who is None or s.get('who', 'both') in ('both', who):
                yield title, s


def all_settings(who=None):
    for _title, s in rows(who):
        if s['type'] != 'group':
            yield s


def defaults(who=None):
    return dict((s['id'], s['default']) for s in all_settings(who))


def read(getters, who):
    """Settings for one front-end as a dict. getters: {'boolean', 'integer', 'string'} -> f(id);
    the Kodi layer passes Addon accessors. Bad or missing values fall back to defaults."""
    out = {}
    for s in all_settings(who):
        kind = s['type']
        try:
            if kind == 'boolean':
                value = bool(getters['boolean'](s['id']))
            elif kind in ('options', 'slider'):
                value = int(getters['integer'](s['id']))
                if kind == 'options' and not 0 <= value < len(s['options']):
                    value = s['default']
                if kind == 'slider':
                    value = min(s['max'], max(s['min'], value))
            else:
                value = (getters['string'](s['id']) or '').strip()
                if kind == 'time' and not value:
                    value = s['default']
            out[s['id']] = value
        except Exception:
            out[s['id']] = s['default']
    return out


def selected_categories(settings):
    """The slugs whose toggle is on. Nothing ticked means every category (the same fallback as
    Jeopkodi's difficulty rows), so the add-on never sits there with no questions."""
    chosen = [slug for slug, _title in CATEGORIES if settings.get(setting_id(slug), True)]
    return chosen or [slug for slug, _title in CATEGORIES]


def category_title(slug):
    return TITLES.get(slug, slug.replace('-', ' ').title())


def number(value):
    """49110 -> '49,110', so the summary line stays readable."""
    return '{:,}'.format(int(value))


def session_length(settings):
    i = settings.get('session_length', 1)
    return SESSION_LENGTHS[i] if 0 <= i < len(SESSION_LENGTHS) else 20


ADDONS = {APP_ID: 'app', SCREENSAVER_ID: 'ss'}
LIBRARY = LIBRARY_ID
