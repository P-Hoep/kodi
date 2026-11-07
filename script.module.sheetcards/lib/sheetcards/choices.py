"""Multiple-choice distractors drawn from other cards' answers (or questions for A -> Q).

Plausible rather than random: candidates of the same kind (number, year, date, single word,
short phrase, sentence) come first, then those closest in length. Pure Python with a seeded
random.Random, so it is unit-tested outside Kodi.
"""

import math
import re

TOP = 8
LONG_OPTION = 90

_MONTHS = ('jan|feb|mar|apr|may|jun|jul|aug|sep|sept|oct|nov|dec|january|february|march|april|june|july|'
           'august|september|october|november|december')
_DATE = re.compile(r'^(\d{4}-\d{1,2}-\d{1,2}|\d{1,2}[/.\-]\d{1,2}[/.\-]\d{2,4}|'
                   r'\d{1,2}(st|nd|rd|th)?\s+(%s)\.?,?\s+\d{2,4}|(%s)\.?\s+\d{1,2}(st|nd|rd|th)?,?\s+\d{2,4})$'
                   % (_MONTHS, _MONTHS), re.I)
_INT = re.compile(r'^[+-]?(\d{1,3}(,\d{3})+|\d+)$')
_DEC = re.compile(r'^[+-]?(\d{1,3}(,\d{3})+|\d*)[.]\d+%?$|^[+-]?\d+%$')


def normalise(text):
    """Lower case, trimmed, single spaces, no trailing punctuation."""
    text = re.sub(r'\s+', ' ', text or '').strip().lower()
    return re.sub(r'[\s.,;:!?]+$', '', text)


def classify(text):
    t = re.sub(r'\s+', ' ', text or '').strip()
    bare = t.rstrip('.')
    if re.match(r'^\d{4}$', bare) and 1000 <= int(bare) <= 2999:
        return 'year'
    if _INT.match(bare):
        return 'integer'
    if _DEC.match(bare):
        return 'decimal'
    if _DATE.match(bare):
        return 'date'
    words = len(t.split(' ')) if t else 0
    if words <= 1:
        return 'word'
    if words <= 4:
        return 'phrase'
    return 'sentence'


def closeness(a, b):
    """0 when equally long, growing with the length ratio's distance from 1."""
    return abs(math.log(max(1, len(a)) / float(max(1, len(b)))))


def distractors(correct, pool, count, rng):
    """Up to count wrong options for correct, from pool (strings). [] if the pool is too small."""
    key = normalise(correct)
    seen, candidates = set([key]), []
    for text in pool:
        k = normalise(text)
        if k and k not in seen:
            seen.add(k)
            candidates.append(text)
    if len(candidates) < count:
        return []
    kind = classify(correct)
    same = sorted((c for c in candidates if classify(c) == kind), key=lambda c: closeness(c, correct))
    other = sorted((c for c in candidates if classify(c) != kind), key=lambda c: closeness(c, correct))
    if len(same) >= count:
        return rng.sample(same[:max(TOP, count)], count)
    # Too few of the same kind: all of them, topped up with the next best of other kinds.
    return list(same) + other[:count - len(same)]


def build(prompt_side, card, pool_cards, count, rng):
    """Options for one card: (options, correct index) or None to show it as a flashcard.
    prompt_side 'q' asks the question (options are answers); 'a' asks the answer."""
    if prompt_side == 'q':
        correct = card.answer
        pool = [c.answer for c in pool_cards if c.id != card.id]
    else:
        correct = card.question
        pool = [c.question for c in pool_cards if c.id != card.id]
    wrong = distractors(correct, pool, count - 1, rng)
    if len(wrong) < count - 1:
        return None
    options = wrong + [correct]
    rng.shuffle(options)
    return options, options.index(correct)


def distinct_count(texts):
    return len(set(normalise(t) for t in texts if normalise(t)))


def stacked(options):
    """One column when any option is longer than 90 characters."""
    return any(len(o) > LONG_OPTION for o in options)
