"""Build Jeopkodi's clue database from the J! Archive TSV.

Run: python3 tools/make_jeopkodi_db.py path/to/combined_season1-42.tsv

The TSV is the J! Archive season dump (columns round, clue_value, daily_double_value, category,
comments, answer, question, air_date, notes). It is not kept in the repository; the database it
produces is.

Keeps clues that read fine as plain text (drops the ones that need a picture, video or audio
clip), tidies the text, and writes screensaver.jeopkodi/resources/data/clues.db with the rows in
random order. The screensaver then reads random blocks of consecutive ids, which is a cheap way
to get shuffled chunks without scanning the table.

level: 1-5 is the row on the board, so a $200 clue before the 2001 value doubling and a $400
clue after it are both level 2. Daily Doubles keep their board level. level 6 is Final Jeopardy.
"""

import csv
import html
import os
import random
import re
import sqlite3
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(HERE, '..', 'screensaver.jeopkodi', 'resources', 'data', 'clues.db')
DOUBLED = '2001-11-26'     # values doubled on this date
MAX_CLUE = 240
MAX_RESPONSE = 80

MEDIA = re.compile(r'seen here|heard here|shown here|clue crew|audio clue|video clue|[\[\]<>]|'
                   r'\bhere\b.*\b(?:video|clip|photo|picture)\b|\(\s*(?:sarah|jimmy|kelly|cory|'
                   r'jon|sofia|jesse)\b', re.I)
TAGS = re.compile(r'<[^>]*>')


def clean(text):
    text = html.unescape(TAGS.sub('', text))
    text = text.replace('\\"', '"').replace("\\'", "'").replace('\\', '')
    text = text.replace('’', "'").replace('‘', "'").replace('“', '"').replace('”', '"')
    text = text.replace('–', '-').replace('—', '-').replace('…', '...')
    return re.sub(r'\s+', ' ', text).strip()


def main():
    if len(sys.argv) != 2:
        sys.exit(__doc__)
    src = sys.argv[1]
    csv.field_size_limit(10 ** 9)
    rows, seen = [], set()
    with open(src, encoding='utf-8', newline='') as f:
        for r in csv.DictReader(f, delimiter='\t', quoting=csv.QUOTE_NONE):
            try:
                rnd, value, dd = int(r['round']), int(r['clue_value']), int(r['daily_double_value'])
            except (TypeError, ValueError):
                continue
            clue, resp, cat = clean(r['answer'] or ''), clean(r['question'] or ''), clean(r['category'] or '')
            if not clue or not resp or not cat or MEDIA.search(clue) or MEDIA.search(cat):
                continue
            if len(clue) > MAX_CLUE or len(resp) > MAX_RESPONSE or len(cat) > 40:
                continue
            if rnd == 3:
                level, value = 6, 0
            else:
                unit = (100 if (r['air_date'] or '') < DOUBLED else 200) * (2 if rnd == 2 else 1)
                level = value // unit
                if not 1 <= level <= 5:
                    continue
            key = (clue.lower(), resp.lower())
            if key in seen:
                continue
            seen.add(key)
            rows.append((level, value, 1 if dd else 0, cat.upper(), clue.upper(), resp.upper(),
                         int((r['air_date'] or '0')[:4] or 0)))
    random.Random(42).shuffle(rows)
    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    if os.path.exists(OUT):
        os.remove(OUT)
    db = sqlite3.connect(OUT)
    db.execute('PRAGMA page_size=4096')
    db.execute('CREATE TABLE clues (id INTEGER PRIMARY KEY, level INTEGER, value INTEGER, daily INTEGER, '
               'category TEXT, clue TEXT, response TEXT, year INTEGER)')
    db.executemany('INSERT INTO clues VALUES (NULL,?,?,?,?,?,?,?)', rows)
    db.commit()
    db.execute('VACUUM')
    db.close()
    print('%d clues, %.1f MB' % (len(rows), os.path.getsize(OUT) / 1e6))


if __name__ == '__main__':
    main()
