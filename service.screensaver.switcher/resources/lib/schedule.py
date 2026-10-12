"""Which screensaver the schedule wants at a given time. Pure Python, no Kodi imports.

A window runs from its start up to (not including) its end. A window whose end is
earlier than its start crosses midnight (22:00-06:00); start == end covers the whole day.
When windows overlap, the lowest-numbered one wins.

A window with a second screensaver alternates between the two every `alternate_minutes`,
counted from the window's start, so the choice depends only on the clock.
"""

from . import config


def minutes(text):
    """'HH:MM' -> minutes after midnight, or None if it isn't a time."""
    try:
        hours, mins = text.strip().split(':')[:2]
        hours, mins = int(hours), int(mins)
    except (AttributeError, ValueError):
        return None
    if not (0 <= hours < 24 and 0 <= mins < 60):
        return None
    return hours * 60 + mins


def contains(start, end, now):
    if start == end:
        return True
    if start < end:
        return start <= now < end
    return now >= start or now < end


def windows(settings):
    """The usable windows: [(slot, start, end, [screensaver ids])], in slot order."""
    out = []
    for n in range(1, config.SLOTS + 1):
        if not settings.get('w%d_on' % n):
            continue
        start = minutes(settings.get('w%d_start' % n, ''))
        end = minutes(settings.get('w%d_end' % n, ''))
        pool = [settings.get('w%d_screensaver' % n, ''), settings.get('w%d_alt' % n, '')]
        pool = [p for i, p in enumerate(pool) if p and p not in pool[:i]]
        if start is None or end is None or not pool:
            continue
        out.append((n, start, end, pool))
    return out


def pick(pool, start, now, every):
    """The pool member for `now`: the next one each `every` minutes after `start`."""
    return pool[((now - start) % 1440) // max(1, every) % len(pool)]


def wanted(settings, now):
    """(slot, screensaver id) for `now` (minutes after midnight). slot is 0 for the default;
    the id is '' when nothing is scheduled and the screensaver should be left alone."""
    every = settings.get('alternate_minutes', 30)
    for n, start, end, pool in windows(settings):
        if contains(start, end, now):
            return n, pick(pool, start, now, every)
    return 0, settings.get('default_screensaver', '')


def clock(mins):
    return '%02d:%02d' % divmod(mins, 60)
