"""CSV -> cards. Column A is the question, column B the answer; everything else is ignored."""

import csv
import hashlib
import io
import re

from .deck import Card

HEADERS = {('question', 'answer'), ('q', 'a'), ('front', 'back'), ('term', 'definition')}
HEADER_AUTO, HEADER_YES, HEADER_NO = 0, 1, 2


def clean(cell):
    """Strip, normalise line endings, keep line breaks, collapse 3+ blank lines into one."""
    text = (cell or '').replace('\r\n', '\n').replace('\r', '\n')
    text = '\n'.join(line.rstrip() for line in text.split('\n')).strip()
    return re.sub(r'\n(?:[ \t]*\n){3,}', '\n\n', text)


def norm_key(text):
    return re.sub(r'\s+', ' ', text).strip().casefold()


def is_header(a, b):
    return (a.strip().lower(), b.strip().lower()) in HEADERS


def rows(text, header=HEADER_AUTO):
    """CSV text -> [(question, answer)] with blanks skipped."""
    if text.startswith('﻿'):
        text = text[1:]
    out = []
    for i, row in enumerate(csv.reader(io.StringIO(text))):
        a = clean(row[0]) if len(row) > 0 else ''
        b = clean(row[1]) if len(row) > 1 else ''
        if i == 0 and (header == HEADER_YES or (header == HEADER_AUTO and is_header(a, b))):
            continue
        if a and b:
            out.append((a, b))
    return out


def card_id(sheet_id, tab_title, question):
    return hashlib.sha1((sheet_id + tab_title + question).encode('utf-8')).hexdigest()[:12]


def cards(sheet_id, tab, text, header=HEADER_AUTO, log=None):
    """tab: {'gid', 'title'} -> [Card]. Duplicate questions keep the first."""
    out, seen = [], set()
    for question, answer in rows(text, header):
        key = norm_key(question)
        if key in seen:
            if log:
                log('deck "%s": duplicate question skipped: %s' % (tab['title'], question[:60]))
            continue
        seen.add(key)
        out.append(Card(card_id(sheet_id, tab['title'], question), question, answer,
                        tab.get('gid'), tab['title'], len(out)))
    return out
