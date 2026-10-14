"""Turns Audiobookshelf JSON into plain book records and does the timeline maths
(book time <-> track and offset, chapters). No Kodi imports.

The server returns the same item in two shapes: minified lists carry authorName,
narratorName and seriesName strings; expanded items carry authors, narrators and series
lists (and a single series dict when a list is filtered by series). Both are handled,
and anything missing falls back to an empty value rather than an error.
"""

import re

NEAR_END = 30.0  # seconds; resuming closer than this to the end starts again


def text(value):
    return value.strip() if isinstance(value, str) else ''


def number(value, default=0.0):
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def names(values):
    out = []
    for v in values or []:
        name = text(v.get('name')) if isinstance(v, dict) else text(v)
        if name:
            out.append(name)
    return out


def series_list(metadata):
    """[(id, name, sequence)] from either shape. seriesName strings look like
    'Dune #2, Other Series'."""
    raw = metadata.get('series')
    if isinstance(raw, dict):
        raw = [raw]
    if isinstance(raw, list) and raw:
        return [(s.get('id'), text(s.get('name')), text(s.get('sequence'))) for s in raw
                if isinstance(s, dict) and text(s.get('name'))]
    out = []
    for part in text(metadata.get('seriesName')).split(', '):
        match = re.match(r'^(.*?)(?: #(\S+))?$', part.strip())
        if match and match.group(1):
            out.append((None, match.group(1), match.group(2) or ''))
    return out


def book(item, progress=None):
    """A flat record for one library item. progress: the user's media-progress dict."""
    media = item.get('media') or {}
    meta = media.get('metadata') or {}
    authors = names(meta.get('authors')) or [a for a in [text(meta.get('authorName'))] if a]
    narrators = names(meta.get('narrators')) or [n for n in [text(meta.get('narratorName'))] if n]
    if progress is None:
        progress = item.get('userMediaProgress')
    return {
        'id': item.get('id'),
        'title': text(meta.get('title')) or text(item.get('relPath')) or 'Untitled',
        'subtitle': text(meta.get('subtitle')),
        'author': ', '.join(authors),
        'author_ids': [(a.get('id'), text(a.get('name'))) for a in meta.get('authors') or []
                       if isinstance(a, dict) and a.get('id')],
        'narrator': ', '.join(narrators),
        'series': series_list(meta),
        'description': text(meta.get('descriptionPlain')) or strip_html(text(meta.get('description'))),
        'year': text(meta.get('publishedYear')),
        'genres': [g for g in meta.get('genres') or [] if isinstance(g, str)],
        'duration': number(media.get('duration')),
        'has_cover': bool(media.get('coverPath')),
        'updated_at': item.get('updatedAt'),
        'added_at': item.get('addedAt'),
        'missing': bool(item.get('isMissing')),
        'invalid': bool(item.get('isInvalid')),
        'num_chapters': media.get('numChapters') if media.get('numChapters') is not None
        else len(media.get('chapters') or []),
        'chapters': chapters(media.get('chapters')),
        'progress': progress_state(progress, number(media.get('duration'))),
    }


def strip_html(value):
    value = re.sub(r'<br\s*/?>|</p>', '\n', value, flags=re.I)
    value = re.sub(r'<[^>]+>', '', value)
    for entity, char in (('&amp;', '&'), ('&lt;', '<'), ('&gt;', '>'), ('&quot;', '"'), ('&#39;', "'"),
                         ('&nbsp;', ' ')):
        value = value.replace(entity, char)
    return re.sub(r'\n{3,}', '\n\n', value).strip()


def progress_state(p, duration=0.0):
    """{'state': 'new'|'progress'|'finished', 'time', 'fraction', 'updated'}."""
    if not isinstance(p, dict):
        return {'state': 'new', 'time': 0.0, 'fraction': 0.0, 'updated': 0}
    total = number(p.get('duration')) or duration
    time_ = number(p.get('currentTime'))
    fraction = number(p.get('progress'))
    if not fraction and total:
        fraction = time_ / total
    if p.get('isFinished'):
        state = 'finished'
    elif time_ > 0 or fraction > 0:
        state = 'progress'
    else:
        state = 'new'
    return {'state': state, 'time': time_, 'fraction': max(0.0, min(1.0, fraction)),
            'updated': p.get('lastUpdate') or 0}


def progress_map(me):
    """libraryItemId -> progress dict, books only (episodes have an episodeId)."""
    out = {}
    for p in (me or {}).get('mediaProgress') or []:
        if isinstance(p, dict) and p.get('libraryItemId') and not p.get('episodeId'):
            out[p['libraryItemId']] = p
    return out


def chapters(raw):
    out = []
    for c in raw or []:
        if isinstance(c, dict):
            start, end = number(c.get('start')), number(c.get('end'))
            if end > start:
                out.append({'start': start, 'end': end, 'title': text(c.get('title'))})
    out.sort(key=lambda c: c['start'])
    for i, c in enumerate(out):
        c['title'] = c['title'] or 'Chapter %d' % (i + 1)
    return out


def chapter_at(chapter_list, t):
    """Index of the chapter playing at book time t, or -1."""
    for i in range(len(chapter_list) - 1, -1, -1):
        if t >= chapter_list[i]['start'] - 0.5:
            return i
    return -1


def tracks(session):
    """Playable tracks of a session in order: [{'start', 'duration', 'path', 'mime'}]."""
    out = []
    for t in session.get('audioTracks') or []:
        if isinstance(t, dict) and t.get('contentUrl'):
            out.append({'index': t.get('index') or 0, 'start': number(t.get('startOffset')),
                        'duration': number(t.get('duration')), 'path': t['contentUrl'],
                        'mime': text(t.get('mimeType'))})
    out.sort(key=lambda t: (t['start'], t['index']))
    return out


def locate(track_list, t):
    """Book time -> (track index, offset in that track)."""
    if not track_list:
        return 0, 0.0
    t = max(0.0, t)
    for i in range(len(track_list) - 1, -1, -1):
        if t >= track_list[i]['start']:
            offset = t - track_list[i]['start']
            if track_list[i]['duration']:
                offset = min(offset, max(0.0, track_list[i]['duration'] - 1))
            return i, offset
    return 0, 0.0


def book_time(track_list, index, offset):
    if not track_list or index < 0 or index >= len(track_list):
        return None
    return track_list[index]['start'] + max(0.0, offset)


def start_position(progress, duration, rewind=0):
    """Where Resume starts: the saved time, minus the rewind, except that a finished book
    or one stopped in its last seconds starts from the beginning."""
    if progress['state'] == 'finished':
        return 0.0
    t = progress['time']
    if duration and t >= duration - NEAR_END:
        return 0.0
    return max(0.0, t - rewind)


def sequence_key(value):
    """'2', '2.5', '1-3', '' -> sortable tuple; blanks go last."""
    match = re.match(r'\s*(\d+(?:\.\d+)?)', value or '')
    return (0, float(match.group(1)), value) if match else (1, 0.0, value or '')


def sequence_in(b, series_id=None, series_name=None):
    for sid, name, seq in b['series']:
        if (series_id and sid == series_id) or (series_name and name == series_name):
            return seq
    return ''


def clock(seconds):
    seconds = int(max(0, seconds))
    h, rem = divmod(seconds, 3600)
    m, s = divmod(rem, 60)
    return '%d:%02d:%02d' % (h, m, s) if h else '%d:%02d' % (m, s)


def length(seconds):
    """'12h 05m', '45m', '30s'."""
    seconds = int(max(0, seconds))
    h, rem = divmod(seconds, 3600)
    m = rem // 60
    if h:
        return '%dh %02dm' % (h, m)
    if m:
        return '%dm' % m
    return '%ds' % seconds
