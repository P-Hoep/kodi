"""The slide queue: one story slide, then a slide per comment, for each story in rank order.

Everything here is plain data and arithmetic so the tests can build queues from recorded
stories without Kodi. `tr` is the translator (Kodi's getLocalizedString) and supplies the
labels for points, comments and ages.
"""

import random
import time

from . import formatter

STORY = 'story'
COMMENT = 'comment'

POINTS, COMMENTS, BY, AGO, JUST_NOW = 32006, 32005, 32007, 32008, 32011


def build(data, settings, tr, now=None, rng=None):
    """data is a cache dict with 'stories'; returns the slides in display order."""
    stories = [story for story in (data or {}).get('stories') or [] if story.get('title')]
    if not stories:
        return []
    rng = rng or random.Random()
    now = time.time() if now is None else now
    order = list(range(len(stories)))
    if settings.get('randomize', True) and len(order) > 1:
        start = rng.randrange(len(order))
        order = order[start:] + order[:start]

    slides = []
    for index in order:
        story = stories[index]
        slides.append(story_slide(story, index + 1, settings, tr, now))
        slides.extend(comment_slides(story, index + 1, settings, tr, now))
    return slides


def _meta(story, settings, tr, now):
    parts = [formatter.domain(story.get('url'))]
    if settings.get('meta', True):
        if story.get('score'):
            parts.append(tr(POINTS) % story['score'])
        if story.get('by'):
            parts.append(tr(BY) % story['by'])
        if story.get('time'):
            parts.append(formatter.age_text(story['time'], now, tr(JUST_NOW), tr(AGO)))
    if story.get('descendants'):
        parts.append(tr(COMMENTS) % story['descendants'])
    return ' · '.join(parts)


def story_slide(story, rank, settings, tr, now):
    body = ''
    if story.get('text'):
        body = formatter.to_label(story['text'], settings.get('max_chars', 700))
    return {
        'kind': STORY,
        'story_id': story.get('id'),
        'rank': rank,
        'title': story.get('title') or '',
        'meta': _meta(story, settings, tr, now),
        'body': body,
        'seconds': float(settings.get('story_seconds', 8)),
    }


def _comment_label(comment, settings):
    max_chars = settings.get('max_chars', 700)
    label = formatter.to_label(comment.get('text') or '', max_chars)
    plain = formatter.plain_text(comment.get('text') or '', max_chars)
    if settings.get('include_reply') and comment.get('reply'):
        reply_text = comment['reply'].get('text') or ''
        reply_plain = formatter.plain_text(reply_text, min(300, max_chars))
        if reply_plain.strip():
            label += '\n\n> ' + formatter.to_label(reply_text, min(300, max_chars))
            plain += '\n> ' + reply_plain
    return label, plain


def comment_slides(story, rank, settings, tr, now):
    limit = max(0, settings.get('comments', 3))
    comments = [c for c in story.get('comments') or [] if c.get('text')]
    if limit <= 0 or not comments:
        return []
    minimum = max(0, settings.get('min_chars', 40))
    chosen = []
    short = []
    for comment in comments:
        label, plain = _comment_label(comment, settings)
        if not label.strip():
            continue
        entry = (comment, label, plain)
        if len(plain) >= minimum:
            chosen.append(entry)
        else:
            short.append(entry)
        if len(chosen) >= limit:
            break
    if not chosen and short:
        # Nothing long enough: show the longest one rather than nothing at all.
        chosen = [max(short, key=lambda e: len(e[2]))]
    slides = []
    for comment, label, plain in chosen[:limit]:
        slides.append({
            'kind': COMMENT,
            'story_id': story.get('id'),
            'rank': rank,
            'head': '#%d  %s' % (rank, story.get('title') or ''),
            'author': '%s · %s' % (tr(BY) % (comment.get('by') or '?'),
                                   formatter.age_text(comment.get('time') or 0, now,
                                                      tr(JUST_NOW), tr(AGO))),
            'text': label,
            'seconds': formatter.display_seconds(
                plain, settings.get('wpm', 220), settings.get('comment_min', 6),
                settings.get('comment_max', 30)),
        })
    return slides


def refresh_due(fetched_at, now, refresh_seconds):
    return (now - float(fetched_at or 0)) >= max(1, refresh_seconds)
