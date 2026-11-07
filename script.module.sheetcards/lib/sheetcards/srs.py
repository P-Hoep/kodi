"""Leitner spaced repetition and per-sheet stats, persisted as progress/{sheet_id}.json.

Five boxes with intervals 1, 2, 4, 8, 16 days; box 0 is an unseen card. Correct moves a card
up one box (due after that box's interval); wrong sends it back to box 1, due today.
"""

import datetime
import json
import os
import random

from .cache import atomic_write

INTERVALS = [1, 2, 4, 8, 16]
MAX_BOX = 5
PRUNE_DAYS = 90
ORDER_SMART, ORDER_SHUFFLE, ORDER_SHEET, ORDER_HARDEST = 0, 1, 2, 3


def iso_day(day):
    return day.isoformat()


def parse_day(text, default=None):
    try:
        return datetime.date(*[int(p) for p in text.split('-')])
    except (AttributeError, ValueError, TypeError):
        return default


class Progress(object):
    def __init__(self, path, sheet_id, log=None):
        self.path = path
        self.sheet_id = sheet_id
        self.log = log
        self.cards = {}
        self.stats = {'best_streak': 0, 'sessions': 0, 'answered': 0, 'correct': 0}
        self.load()

    # -------------------------------------------------------------- file

    def load(self):
        if not self.path or not os.path.exists(self.path):
            return
        try:
            with open(self.path, encoding='utf-8') as handle:
                data = json.load(handle)
            if not isinstance(data, dict) or not isinstance(data.get('cards', {}), dict):
                raise ValueError('not a progress file')
            self.cards = dict((k, v) for k, v in data.get('cards', {}).items() if isinstance(v, dict))
            stats = data.get('stats', {})
            for key in self.stats:
                self.stats[key] = int(stats.get(key, 0) or 0)
        except (ValueError, TypeError, OSError) as err:
            backup = self.path + '.bak'
            try:
                os.replace(self.path, backup)
            except OSError:
                pass
            if self.log:
                self.log('progress file was corrupt (%s); moved to %s, starting fresh' % (err, backup))
            self.cards = {}

    def save(self):
        if not self.path:
            return
        data = {'version': 1, 'sheet_id': self.sheet_id, 'cards': self.cards, 'stats': self.stats}
        atomic_write(self.path, json.dumps(data, indent=1, sort_keys=True).encode('utf-8'))

    # -------------------------------------------------------------- cards

    def box(self, card_id):
        return int(self.cards.get(card_id, {}).get('box', 0) or 0)

    def due(self, card_id, today):
        entry = self.cards.get(card_id)
        if not entry or not entry.get('box'):
            return None
        return parse_day(entry.get('due'), today)

    def is_due(self, card_id, today):
        due = self.due(card_id, today)
        return due is not None and due <= today

    def record(self, card_id, correct, now=None, srs=True):
        """One answer. Updates the box (when srs is on), counts and lifetime stats."""
        now = now or datetime.datetime.now()
        today = now.date()
        entry = self.cards.setdefault(card_id, {'box': 0, 'seen': 0, 'correct': 0})
        entry.pop('gone', None)
        entry['seen'] = int(entry.get('seen', 0)) + 1
        entry['last'] = now.replace(microsecond=0).isoformat()
        entry['result'] = 1 if correct else 0
        if correct:
            entry['correct'] = int(entry.get('correct', 0)) + 1
        else:
            entry['misses'] = int(entry.get('misses', 0)) + 1
        if srs:
            if correct:
                entry['box'] = min(MAX_BOX, int(entry.get('box', 0)) + 1)
                entry['due'] = iso_day(today + datetime.timedelta(days=INTERVALS[entry['box'] - 1]))
            else:
                entry['box'] = 1
                entry['due'] = iso_day(today)
        self.stats['answered'] += 1
        if correct:
            self.stats['correct'] += 1
        return entry

    def note_streak(self, streak):
        if streak > self.stats['best_streak']:
            self.stats['best_streak'] = streak

    def prune(self, present_ids, today):
        """Cards missing from the sheet are kept 90 days (moving a card between tabs keeps
        its progress for a while), then dropped."""
        present = set(present_ids)
        for cid in list(self.cards):
            entry = self.cards[cid]
            if cid in present:
                entry.pop('gone', None)
                continue
            gone = parse_day(entry.get('gone'))
            if gone is None:
                entry['gone'] = iso_day(today)
            elif (today - gone).days > PRUNE_DAYS:
                del self.cards[cid]

    def reset(self):
        self.cards = {}
        self.stats = {'best_streak': 0, 'sessions': 0, 'answered': 0, 'correct': 0}
        self.save()

    def accuracy(self):
        return (100.0 * self.stats['correct'] / self.stats['answered']) if self.stats['answered'] else None

    def mastery(self, cards):
        """0..1: how far up the boxes a deck is."""
        if not cards:
            return 0.0
        return sum(self.box(c.id) for c in cards) / float(MAX_BOX * len(cards))

    def due_count(self, cards, today):
        return sum(1 for c in cards if self.is_due(c.id, today))


# ------------------------------------------------------------------ sessions

def build_session(cards, progress, today, length, order=ORDER_SMART, new_per_session=10, srs=True, rng=None):
    """The cards for one session. length None = all."""
    rng = rng or random.Random()
    cards = list(cards)
    if not srs and order == ORDER_SMART:
        order = ORDER_SHUFFLE
    if order == ORDER_SHEET:
        chosen = cards
    elif order == ORDER_SHUFFLE:
        chosen = cards[:]
        rng.shuffle(chosen)
    elif order == ORDER_HARDEST:
        def hardness(c):
            entry = progress.cards.get(c.id, {})
            seen = int(entry.get('seen', 0) or 0)
            # Unseen cards are not "hard": after every card that has been answered.
            return (0 if seen else 1, progress.box(c.id), -int(entry.get('misses', 0) or 0), rng.random())
        chosen = sorted(cards, key=hardness)
    else:
        seen = [c for c in cards if progress.box(c.id) > 0]
        due = sorted((c for c in seen if progress.is_due(c.id, today)),
                     key=lambda c: (progress.due(c.id, today), c.index))
        new = [c for c in cards if progress.box(c.id) == 0][:max(0, new_per_session)]
        chosen = due + new
        if length is None or len(chosen) < length:
            rest = [c for c in seen if not progress.is_due(c.id, today)]
            rest.sort(key=lambda c: (progress.box(c.id), progress.due(c.id, today), c.index))
            chosen += rest
    return chosen if length is None else chosen[:length]


class Queue(object):
    """A session's running order: wrong cards come back 3-5 cards later, once."""

    def __init__(self, cards, rng=None):
        self.rng = rng or random.Random()
        self.items = list(cards)
        self.pos = 0
        self.requeued = set()
        self.total = len(self.items)

    def current(self):
        return self.items[self.pos] if self.pos < len(self.items) else None

    def advance(self):
        self.pos += 1
        return self.current()

    def requeue(self, card):
        if card.id in self.requeued:
            return False
        self.requeued.add(card.id)
        at = min(len(self.items), self.pos + 1 + self.rng.randint(3, 5))
        self.items.insert(at, card)
        return True

    @property
    def done(self):
        return self.pos >= len(self.items)

    @property
    def number(self):
        """1-based position for "7 / 20"."""
        return min(self.pos + 1, len(self.items))

    @property
    def length(self):
        """Cards in this session, including the ones that came back after a miss."""
        return len(self.items)
