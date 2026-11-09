"""Build OpenTrivia's question database from the OpenTriviaQA category files.

Run: python3 tools/make_opentrivia_db.py [path/to/OpenTrivia/categories]

The files are not kept in the add-on; the database this produces is:
script.module.opentrivia/resources/data/trivia.db

Format (one category per file):

    #Q The question, which may run over several lines
    ^ The correct answer
    A a wrong answer
    B another wrong answer
    C ...
    D ...

Questions are read as UTF-8, cleaned, de-duplicated across categories, capped at four answers
(the correct one plus three of its own distractors), and written with the rows in random order.
That random order is what makes a block of consecutive ids a random sample, so the add-ons can
read 600 questions with one indexed query and shuffle them, instead of querying per question.

The stat printed at the end is the same kind of summary Jeopkodi's clue builder prints.
"""

import glob
import html
import json
import os
import random
import re
import sqlite3
import sys
import unicodedata

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.normpath(os.path.join(HERE, '..'))
SOURCE = os.path.join(ROOT, 'OpenTrivia', 'categories')
OUT = os.path.join(ROOT, 'script.module.opentrivia', 'resources', 'data', 'trivia.db')

MAX_QUESTION = 420
MAX_ANSWER = 160
MAX_CHOICE = 160
MAX_CHOICES = 4
TAGS = re.compile(r'<[^>]*>')
CONTROL = re.compile(r'[\x00-\x1f\x7f]')
CHOICE = re.compile(r'^([A-Z])(?: (.*))?$')


def clean(text):
    text = unicodedata.normalize('NFC', text or '')
    text = html.unescape(TAGS.sub('', text))
    text = text.replace('�', '')
    text = text.replace('’', "'").replace('‘', "'").replace('“', '"').replace('”', '"')
    text = text.replace('–', '-').replace('—', '-').replace('…', '...')
    text = CONTROL.sub(' ', text)
    return re.sub(r'\s+', ' ', text).strip()


def parse(path):
    """[(question, answer, [choices])] from one category file. The format is line based, and a
    question may continue over any number of lines, so everything before ^ belongs to it. After
    ^ only the expected letter (A, then B, ...) starts a choice, which keeps a line such as
    'The one who...' from being mistaken for answer A."""
    out = []
    raw = open(path, 'rb').read().decode('utf-8', errors='replace')
    question, lines, answer, choices, expected = None, [], None, [], 0
    for line in raw.splitlines():
        s = line.strip()
        if s.startswith('#Q '):
            if question is not None:
                out.append((clean(' '.join(lines)), clean(answer or ''), [clean(c) for c in choices]))
            question, lines, answer, choices, expected = s[3:], [s[3:]], None, [], 0
            continue
        if question is None or not s:
            continue
        if s.startswith('^ '):
            answer = s[2:]
            continue
        if answer is None:
            lines.append(s)             # a question continuation, even if it starts with A
            continue
        match = CHOICE.match(s)
        if match and ord(match.group(1)) - 65 == expected:
            choices.append(match.group(2) or '')
            expected += 1
        # Anything else after the answer is a formatting stray and is ignored.
    if question is not None:
        out.append((clean(' '.join(lines)), clean(answer or ''), [clean(c) for c in choices]))
    return out


def prepare(question, answer, choices, rng):
    """The row to store, or None if the question is unusable. Returns (question, answer, options,
    correct index), with the options shuffled so the answer is in no habitual position."""
    if not question or not answer or '�' in question + answer:
        return None
    if len(question) > MAX_QUESTION or len(answer) > MAX_ANSWER:
        return None
    seen, options = set(), []
    for choice in choices:
        key = choice.lower()
        if choice and key not in seen and len(choice) <= MAX_CHOICE:
            seen.add(key)
            options.append(choice)
    if answer not in options:
        return None
    if len(options) < 2:
        return None
    if len(options) > MAX_CHOICES:
        wrong = [c for c in options if c != answer]
        options = [answer] + rng.sample(wrong, MAX_CHOICES - 1)
    rng.shuffle(options)
    return question, answer, options, options.index(answer)


def main():
    source = sys.argv[1] if len(sys.argv) > 1 else SOURCE
    if not os.path.isdir(source):
        sys.exit(__doc__)
    rng = random.Random(42)
    rows, seen_questions = [], set()
    dropped = {'empty': 0, 'long': 0, 'few choices': 0, 'answer missing': 0, 'duplicate': 0}
    counts = {}
    for path in sorted(glob.glob(os.path.join(source, '*'))):
        slug = os.path.basename(path)
        if slug.startswith('.'):
            continue
        counts[slug] = 0
        for question, answer, choices in parse(path):
            row = prepare(question, answer, choices, rng)
            if row is None:
                if not question or not answer:
                    dropped['empty'] += 1
                elif len(question) > MAX_QUESTION or len(answer) > MAX_ANSWER:
                    dropped['long'] += 1
                elif len(choices) < 2:
                    dropped['few choices'] += 1
                else:
                    dropped['answer missing'] += 1
                continue
            key = (row[0].lower(), tuple(sorted(c.lower() for c in row[2])))
            if key in seen_questions:
                dropped['duplicate'] += 1
                continue
            seen_questions.add(key)
            rows.append((slug, row[0], row[1], json.dumps(row[2], ensure_ascii=False,
                                                          separators=(',', ':')), row[3]))
            counts[slug] += 1
    rng.shuffle(rows)
    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    if os.path.exists(OUT):
        os.remove(OUT)
    db = sqlite3.connect(OUT)
    db.execute('PRAGMA page_size=4096')
    db.execute('PRAGMA journal_mode=OFF')
    db.execute('PRAGMA synchronous=OFF')
    db.execute('CREATE TABLE questions (id INTEGER PRIMARY KEY, category TEXT NOT NULL, '
               'question TEXT NOT NULL, answer TEXT NOT NULL, choices TEXT NOT NULL, correct INTEGER NOT NULL)')
    db.execute('CREATE TABLE meta (key TEXT PRIMARY KEY, value TEXT)')
    db.executemany('INSERT INTO questions (category, question, answer, choices, correct) '
                   'VALUES (?,?,?,?,?)', rows)
    db.executemany('INSERT INTO meta (key, value) VALUES (?,?)', [
        ('source', 'OpenTriviaQA (github.com/uberspot/OpenTriviaQA)'),
        ('license', 'CC BY-SA 4.0'),
        ('count', str(len(rows))),
        ('block', '600'),
        ('categories', json.dumps(sorted(counts), separators=(',', ':'))),
    ])
    db.commit()
    db.execute('VACUUM')
    db.close()
    print('%d questions, %.1f MB' % (len(rows), os.path.getsize(OUT) / 1e6))
    print('  ' + ', '.join('%s %d' % (k, counts[k]) for k in sorted(counts)))
    print('  dropped: ' + ', '.join('%s %d' % (k, v) for k, v in dropped.items()))


if __name__ == '__main__':
    main()
