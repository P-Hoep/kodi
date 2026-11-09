"""Questions from the SQLite database, read in shuffled blocks. No Kodi imports.

The database is written with the rows in random order, so a block of consecutive ids is already
a random sample of the whole collection. Each block is one indexed range read (600 rows, cheap on
any device), filtered by the chosen categories and shuffled again. Blocks are visited in a
random order without repeats until all of them have been used, then the round starts over. That
is the same scheme Jeopkodi uses for its clues: one query per block, never one per question.
"""

import json
import random
import sqlite3

BLOCK = 600


class Question(object):
    """One question. choices is a tuple, correct is the index of the answer in it."""
    __slots__ = ('category', 'question', 'choices', 'correct')

    def __init__(self, category, question, choices, correct):
        self.category = category
        self.question = question
        self.choices = tuple(choices)
        self.correct = int(correct)

    @property
    def answer(self):
        return self.choices[self.correct]

    def __repr__(self):
        return 'Question(%r, %r, %d choices)' % (self.category, self.question[:40], len(self.choices))


class Questions(object):
    def __init__(self, db_path, categories=None, rng=None):
        self.db = sqlite3.connect('file:%s?mode=ro' % db_path, uri=True, check_same_thread=False)
        self.categories = list(categories or [])
        self.rng = rng or random.Random()
        self.count = self.db.execute('SELECT MAX(id) FROM questions').fetchone()[0] or 0
        self.blocks = []
        self.queue = []
        self._total = None

    def total(self):
        """How many questions the chosen categories hold (one indexed count, cached)."""
        if self._total is None:
            sql, params = 'SELECT COUNT(*) FROM questions', []
            if self.categories:
                sql += ' WHERE category IN (%s)' % ','.join('?' * len(self.categories))
                params = list(self.categories)
            self._total = self.db.execute(sql, params).fetchone()[0]
        return self._total

    def _next_block(self):
        if not self.blocks:
            n = (self.count + BLOCK - 1) // BLOCK
            self.blocks = list(range(n))
            self.rng.shuffle(self.blocks)
        return self.blocks.pop()

    def _load(self):
        # A block can be empty after the category filter (a narrow selection in a block that
        # only has other categories), so try every block in the round rather than give up after
        # a fixed number. _next_block() rebuilds the round once its blocks run out.
        nblocks = (self.count + BLOCK - 1) // BLOCK
        if not nblocks:
            raise RuntimeError('the question database is empty')
        sql = 'SELECT category, question, choices, correct FROM questions WHERE id >= ? AND id < ?'
        params = []
        if self.categories:
            sql += ' AND category IN (%s)' % ','.join('?' * len(self.categories))
            params.extend(self.categories)
        for _ in range(nblocks):
            start = self._next_block() * BLOCK + 1
            rows = self.db.execute(sql, [start, start + BLOCK] + params).fetchall()
            if rows:
                self.rng.shuffle(rows)
                queue = []
                for category, question, choices, correct in rows:
                    try:
                        options = tuple(json.loads(choices))
                        index = int(correct)
                    except (TypeError, ValueError):
                        continue
                    if question and len(options) >= 2 and 0 <= index < len(options):
                        queue.append(Question(category, question, options, index))
                if queue:
                    self.queue = queue
                    return
        raise RuntimeError('no questions match the settings')

    def next(self):
        if not self.queue:
            self._load()
        return self.queue.pop()

    def many(self, n):
        """Up to n questions in one go, loading blocks only when the queue runs out."""
        out = []
        while len(out) < n:
            if not self.queue:
                try:
                    self._load()
                except RuntimeError:
                    break
            take = min(n - len(out), len(self.queue))
            out.extend(self.queue[-take:])
            del self.queue[-take:]
        return out

    def close(self):
        self.db.close()
