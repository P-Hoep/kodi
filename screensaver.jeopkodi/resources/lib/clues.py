"""Shuffled clues from the SQLite database. No Kodi imports.

The table was written in random order, so a block of consecutive ids is already a random sample.
Each chunk is one such block (an indexed range read, so it is fast on any device) that is
filtered by the settings and shuffled again. Blocks are visited in a random order without
repeats until all of them have been used, and then the round starts over.
"""

import random
import re
import sqlite3

BLOCK = 600          # rows read per chunk

PLURAL = re.compile(r'\b(THESE|THEY|THEM|THEIR)\b')
PERSON = re.compile(r'\b(HE|SHE|HIS|HER|HERS|HIM|WHO|WHOSE|WHOM)\b|\b(THIS|THESE) (MAN|MEN|WOMAN|WOMEN|PERSON|'
                    r'PEOPLE|ACTOR|ACTORS|ACTRESS|AUTHOR|AUTHORS|PRESIDENT|PRESIDENTS|SINGER|POET|WRITER|'
                    r'ARTIST|PAINTER|COMPOSER|KING|QUEEN|SCIENTIST|DIRECTOR|PLAYWRIGHT|COMEDIAN|EXPLORER|'
                    r'GENERAL|POPE|SAINT|WIFE|HUSBAND|SON|DAUGHTER|BROTHER|BROTHERS|SISTER|FATHER|MOTHER|'
                    r'NOVELIST|PHILOSOPHER|SENATOR|GOVERNOR|EMPEROR|DUO|BAND|GROUP|PAIR|FIRST LADY|'
                    r'LEADER|PRIME MINISTER|CHARACTER|COMPANION|DETECTIVE|ATHLETE|PLAYER|COACH|BOXER|'
                    r'ASTRONAUT|PHYSICIST|CHEF|MONARCH|SOVEREIGN|GODDESS|GOD|HERO|VILLAIN)\b')


def response_form(clue, response):
    """'WHAT IS THE JORDAN' / 'WHO WAS ...' style: the show wants the response as a question."""
    upper = response.upper()
    if re.match(r'^(WHO|WHAT|WHERE|WHEN|WHY|HOW)\b', upper):
        return upper + '?'
    who = 'WHO' if PERSON.search(clue.upper()) else 'WHAT'
    verb = 'ARE' if PLURAL.search(clue.upper()) else 'IS'
    return '%s %s %s?' % (who, verb, upper)


class Clues(object):
    def __init__(self, db_path, levels, daily):
        self.db = sqlite3.connect('file:%s?mode=ro' % db_path, uri=True, check_same_thread=False)
        self.levels = [int(v) for v in levels]
        self.daily = daily
        self.count = self.db.execute('SELECT MAX(id) FROM clues').fetchone()[0] or 0
        self.blocks = []
        self.queue = []

    def _next_block(self):
        if not self.blocks:
            n = (self.count + BLOCK - 1) // BLOCK
            self.blocks = list(range(n))
            random.shuffle(self.blocks)
        return self.blocks.pop()

    def _load(self):
        for _ in range(60):          # a block can be empty after filtering; try another
            start = self._next_block() * BLOCK + 1
            sql = ('SELECT level, value, daily, category, clue, response FROM clues '
                   'WHERE id >= ? AND id < ? AND level IN (%s)' % ','.join('?' * len(self.levels)))
            if not self.daily:
                sql += ' AND daily = 0'
            rows = self.db.execute(sql, [start, start + BLOCK] + self.levels).fetchall()
            if rows:
                random.shuffle(rows)
                self.queue = rows
                return
        raise RuntimeError('no clues match the settings')

    def next(self):
        """(level, value, daily, category, clue, response)"""
        if not self.queue:
            self._load()
        return self.queue.pop()

    def close(self):
        self.db.close()
