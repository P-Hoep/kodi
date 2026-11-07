"""The letter grid and the rules that turn a time into lit words. No Kodi imports.

The grid is the reference word clock, letter for letter (docs/wordclock.md §2).
"""

ROWS = [
    'ITLISASAMPM',
    'ACQUARTERDC',
    'TWENTYFIVEX',
    'HALFBTENFTO',
    'PASTERUNINE',
    'ONESIXTHREE',
    'FOURFIVETWO',
    'EIGHTELEVEN',
    'SEVENTWELVE',
    'TENSEOCLOCK',
    'MIDNIGHTNOO',
]
SIZE = 11

# word key -> (row, first column, length), all 0-based.
WORDS = {
    'IT': (0, 0, 2), 'IS': (0, 3, 2), 'AM': (0, 7, 2), 'PM': (0, 9, 2),
    'A': (1, 0, 1), 'QUARTER': (1, 2, 7),
    'TWENTY': (2, 0, 6), 'M_FIVE': (2, 6, 4),
    'HALF': (3, 0, 4), 'M_TEN': (3, 5, 3), 'TO': (3, 9, 2),
    'PAST': (4, 0, 4), 'NINE': (4, 7, 4),
    'ONE': (5, 0, 3), 'SIX': (5, 3, 3), 'THREE': (5, 6, 5),
    'FOUR': (6, 0, 4), 'FIVE': (6, 4, 4), 'TWO': (6, 8, 3),
    'EIGHT': (7, 0, 5), 'ELEVEN': (7, 5, 6),
    'SEVEN': (8, 0, 5), 'TWELVE': (8, 5, 6),
    'TEN': (9, 0, 3), 'OCLOCK': (9, 5, 6),
    'MIDNIGHT': (10, 0, 8),
}

HOURS = ['TWELVE', 'ONE', 'TWO', 'THREE', 'FOUR', 'FIVE', 'SIX', 'SEVEN', 'EIGHT', 'NINE', 'TEN', 'ELEVEN']

# m5 -> minute words and whether the phrase names the next hour.
MINUTES = {
    0: ([], False),
    5: (['M_FIVE', 'PAST'], False),
    10: (['M_TEN', 'PAST'], False),
    15: (['A', 'QUARTER', 'PAST'], False),
    20: (['TWENTY', 'PAST'], False),
    25: (['TWENTY', 'M_FIVE', 'PAST'], False),
    30: (['HALF', 'PAST'], False),
    35: (['TWENTY', 'M_FIVE', 'TO'], True),
    40: (['TWENTY', 'TO'], True),
    45: (['A', 'QUARTER', 'TO'], True),
    50: (['M_TEN', 'TO'], True),
    55: (['M_FIVE', 'TO'], True),
}

DEFAULT_OPTIONS = dict(rounding=0, it_is=True, quarter_a=True, ampm=True, midnight=True, dots=False)


def word_letters(key):
    row, col, n = WORDS[key]
    return ROWS[row][col:col + n]


def cells(key):
    """Cell indexes (row * 11 + column) of a word."""
    row, col, n = WORDS[key]
    return [row * SIZE + col + i for i in range(n)]


def step(hour, minute, second=0, rounding=0):
    """(hour, m5, extra minutes) after rounding to five minutes. rounding 0 = down, 1 = nearest."""
    if rounding == 1:
        total = ((hour * 60 + minute) * 60 + second + 150) // 300 * 5   # minutes, rounded
        total %= 24 * 60
        return total // 60, total % 60, 0
    return hour, minute - minute % 5, minute % 5


def phrase(hour, minute, second=0, options=None):
    """The lit words for a time, in reading order, and the number of minute dots."""
    o = dict(DEFAULT_OPTIONS)
    o.update(options or {})
    h, m5, extra = step(hour, minute, second, o['rounding'])
    minute_words, names_next = MINUTES[m5]
    named = (h + 1) % 24 if names_next else h
    words = ['IT', 'IS'] if o['it_is'] else []
    words += [w for w in minute_words if w != 'A' or o['quarter_a']]
    if named == 0 and o['midnight']:
        words.append('MIDNIGHT')
    else:
        words.append(HOURS[named % 12])
        if m5 == 0:
            words.append('OCLOCK')
        if o['ampm']:
            words.append('AM' if named < 12 else 'PM')
    dots = extra if (o['dots'] and o['rounding'] == 0) else 0
    return sort_words(words), dots


def sort_words(words):
    return sorted(words, key=lambda w: (WORDS[w][0], WORDS[w][1]))


def lit_cells(words):
    out = set()
    for w in words:
        out.update(cells(w))
    return out


def text(words):
    """'IT IS FIVE TO TWO PM' (spoken order differs from grid order only for AM/PM)."""
    spoken = [w for w in words if w not in ('AM', 'PM')] + [w for w in words if w in ('AM', 'PM')]
    return ' '.join("O'CLOCK" if w == 'OCLOCK' else word_letters(w) for w in spoken)


def letters():
    return sorted(set(''.join(ROWS)))
