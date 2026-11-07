"""Card and Deck, plus the screensaver's shuffle bag."""

import random


class Card(object):
    __slots__ = ('id', 'question', 'answer', 'gid', 'deck', 'index')

    def __init__(self, cid, question, answer, gid, deck, index):
        self.id = cid
        self.question = question
        self.answer = answer
        self.gid = gid
        self.deck = deck          # deck (tab) title
        self.index = index        # position in the sheet

    def __repr__(self):
        return 'Card(%s, %r)' % (self.id, self.question[:30])


class Deck(object):
    def __init__(self, gid, title, index, cards):
        self.gid = gid
        self.title = title
        self.index = index
        self.cards = cards

    @property
    def key(self):
        """What the 'decks' setting stores: the gid, or the title for a name-only tab."""
        return self.gid if self.gid is not None else self.title

    def __len__(self):
        return len(self.cards)


def select(decks, keys):
    """The decks named in keys (gids or titles); all non-empty decks if keys is empty or
    matches nothing."""
    keys = [k for k in (keys or []) if k]
    usable = [d for d in decks if d.cards]
    chosen = [d for d in usable if d.key in keys or d.title in keys]
    return chosen or usable


def parse_keys(text):
    return [k.strip() for k in (text or '').split(',') if k.strip()]


class ShuffleBag(object):
    """Every card once before any repeats; no immediate repeat across a reshuffle."""

    def __init__(self, cards, rng=None):
        self.rng = rng or random.Random()
        self.cards = list(cards)
        self.bag = []
        self.last = None

    def replace(self, cards):
        """New data at a card boundary: keep going, but draw from the new set."""
        ids = set(c.id for c in cards)
        by_id = dict((c.id, c) for c in cards)
        self.cards = list(cards)
        self.bag = [by_id[c.id] for c in self.bag if c.id in ids]

    def next(self):
        if not self.cards:
            return None
        if not self.bag:
            self.bag = list(self.cards)
            self.rng.shuffle(self.bag)
            if len(self.bag) > 1 and self.last is not None and self.bag[-1].id == self.last.id:
                self.bag[0], self.bag[-1] = self.bag[-1], self.bag[0]
        self.last = self.bag.pop()
        return self.last
