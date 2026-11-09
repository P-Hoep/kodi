"""Presentation choices and a round's scoring, shared by both front-ends. No Kodi imports."""

from . import config

# The skin has one control per font bucket; the one named by ot.qsize / ot.osize shows. The
# limits are characters at 100% text size: the question card holds about four lines of font27.
QUESTION_BUCKETS = (('xl', 70), ('l', 150), ('m', 300))
OPTION_BUCKETS = (('m', 52), ('s', 110))
FALLBACK = 'xs'

LAYOUT_AUTO, LAYOUT_CARDS, LAYOUT_LIST = 0, 1, 2


def question_bucket(text, size=100):
    """A font bucket for the question. A larger text-size setting lowers the length each bucket
    accepts, which is how a skin-font window can honour a size preference."""
    n = len(text or '') * 100.0 / max(50, int(size or 100))
    for name, limit in QUESTION_BUCKETS:
        if n <= limit:
            return name
    return 's'


def option_bucket(text, size=100):
    n = len(text or '') * 100.0 / max(50, int(size or 100))
    for name, limit in OPTION_BUCKETS:
        if n <= limit:
            return name
    return FALLBACK


def layout(settings, choices):
    """'duo' for two answers, 'grid' for four short ones, 'stack' for the rest. A setting can
    force cards or a list, but two answers always get the two big side-by-side-less rows."""
    n = len(choices)
    if n <= 2:
        return 'duo'
    if n == 3:
        return 'stack'
    mode = settings.get('option_layout', LAYOUT_AUTO)
    if mode == LAYOUT_LIST:
        return 'stack'
    if mode == LAYOUT_CARDS:
        return 'grid'
    longest = max(len(c) for c in choices)
    return 'grid' if longest <= 64 else 'stack'


def category_label(settings, chosen):
    """The line under 'Open Trivia' on the start screen."""
    total = len(config.CATEGORIES)
    if len(chosen) >= total:
        return config.STRINGS[32020] % total
    return config.STRINGS[32021] % len(chosen)


class Round(object):
    """One quiz round: questions, score, streak. length None means endless."""

    def __init__(self, source, length, rng=None):
        self.source = source
        self.length = length
        self.question = None
        self.asked = 0
        self.score = 0
        self.streak = 0
        self.best = 0
        self.missed = 0
        self.answered = False

    @property
    def done(self):
        return self.length is not None and self.asked >= self.length

    @property
    def remaining(self):
        return None if self.length is None else max(0, self.length - self.asked)

    def next_question(self):
        if self.done:
            return None
        self.question = self.source.next()
        self.asked += 1
        self.answered = False
        return self.question

    def answer(self, picked):
        """True if the pick was right. Safe to call twice: the first answer counts."""
        if self.answered or self.question is None:
            return picked == self.question.correct
        self.answered = True
        correct = picked == self.question.correct
        if correct:
            self.score += 1
            self.streak += 1
            self.best = max(self.best, self.streak)
        else:
            self.streak = 0
            self.missed += 1
        return correct

    @property
    def accuracy(self):
        return 0.0 if not self.answered and not self.score else (
            100.0 * self.score / self.asked if self.asked else 0.0)
