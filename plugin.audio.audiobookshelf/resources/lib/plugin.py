"""The browsing side: Kodi calls default.py with a plugin:// URL for every screen, and
route() draws that screen. Playback is handed to the service (player.py) through a
window property; this process exits as soon as Kodi's player has the playlist.
"""

import json
import os
import sys
from urllib.parse import parse_qsl, urlencode

import xbmc
import xbmcgui
import xbmcplugin

from . import api, config, model, sync
from .kodiutil import (SEEK_PROP, SESSION_PROP, addon, cache, client, device_info, error_dialog, explain,
                       get_json_prop, list_item, log, notify, profile, set_json_prop, settings)

IN_PROGRESS = 'FF4FC3F7'
FINISHED = 'FF81C784'
DIM = 'FF9E9E9E'


def url(action, **params):
    params['action'] = action
    return config.PLUGIN + '?' + urlencode(dict((k, v) for k, v in params.items() if v is not None))


class Screen(object):
    def __init__(self, handle, params):
        self.handle = handle
        self.params = params
        self.s = settings()
        self.api = client(self.s)
        self.cache = cache(self.s)
        self._progress = None

    # -- helpers -----------------------------------------------------------------------

    def progress(self):
        """Fresh progress for every book (one request per screen; never cached)."""
        if self._progress is None:
            self._progress = model.progress_map(self.api.me())
        return self._progress

    def library(self):
        libraries = self.cache.fetch('libraries', self.api.libraries)
        if not libraries:
            return None
        wanted = self.s['library_id']
        for lib in libraries:
            if lib.get('id') == wanted:
                return lib
        if wanted:
            log('library %s not found; using %s' % (wanted, libraries[0].get('name')), xbmc.LOGWARNING)
        return libraries[0]

    def library_id(self):
        lib = self.library()
        if not lib:
            raise EmptyLibrary('This server has no audiobook libraries you can access.')
        return lib['id']

    def add(self, li, target, folder=True, context=None):
        if context:
            li.addContextMenuItems(context)
        xbmcplugin.addDirectoryItem(self.handle, target, li, isFolder=folder)

    def finish(self, content='', category=None, cache_to_disc=True):
        if category:
            xbmcplugin.setPluginCategory(self.handle, category)
        if content:
            xbmcplugin.setContent(self.handle, content)
        xbmcplugin.endOfDirectory(self.handle, succeeded=True, cacheToDisc=cache_to_disc)

    def message(self, text, icon='DefaultIconInfo.png'):
        """An empty category shows one explanatory row instead of an empty list."""
        li = list_item(text, art={'icon': icon, 'thumb': icon})
        self.add(li, url('noop'), folder=False)

    def cover(self, b):
        if not b['has_cover']:
            return {'icon': 'DefaultMusicAlbums.png', 'thumb': 'DefaultMusicAlbums.png'}
        image = self.api.cover_url(b['id'], b['updated_at'])
        return {'thumb': image, 'poster': image, 'icon': image, 'fanart': image}

    def book_item(self, b, series_id=None):
        p = b['progress']
        title = b['title']
        seq = model.sequence_in(b, series_id=series_id) if series_id else ''
        if seq:
            title = '%s. %s' % (seq, title)
        if b['missing'] or b['invalid']:
            label = '[COLOR %s]%s (files missing)[/COLOR]' % (DIM, title)
        elif p['state'] == 'finished':
            label = '[COLOR %s]%s[/COLOR]  [COLOR %s]Finished[/COLOR]' % (DIM, title, FINISHED)
        elif p['state'] == 'progress':
            label = '%s  [COLOR %s]%d%%[/COLOR]' % (title, IN_PROGRESS, int(p['fraction'] * 100))
        else:
            label = title
        series = ', '.join('%s #%s' % (name, seq_) if seq_ else name for _sid, name, seq_ in b['series'])
        li = list_item(label, b['author'], art=self.cover(b),
                       info={'title': b['title'], 'artist': [b['author']] if b['author'] else [],
                             'album': series or b['title'], 'comment': b['description'],
                             'duration': b['duration'], 'genre': b['genres'], 'year': b['year'],
                             'mediatype': 'album', 'playcount': 1 if p['state'] == 'finished' else 0})
        context = []
        if p['state'] == 'progress':
            context.append(('Resume from %s' % model.clock(p['time']),
                            'RunPlugin(%s)' % url('play', id=b['id'], mode='resume')))
        context.append(('Play from start', 'RunPlugin(%s)' % url('play', id=b['id'], mode='start')))
        context.append(('Refresh library', 'RunPlugin(%s)' % url('clear_cache')))
        self.add(li, url('book', id=b['id']), context=context)

    def books(self, items, series_id=None):
        progress = self.progress()
        for item in items:
            if isinstance(item, dict) and item.get('id'):
                self.book_item(model.book(item, progress.get(item['id'])), series_id)

    def next_page(self, action, page, total, limit, **params):
        pages = (total + limit - 1) // limit
        if page + 1 < pages:
            li = list_item('Next page (%d of %d)' % (page + 2, pages),
                           art={'icon': 'DefaultFolder.png', 'thumb': 'DefaultFolder.png'})
            self.add(li, url(action, page=page + 1, **params))

    # -- screens -----------------------------------------------------------------------

    def home(self):
        if not self.api.configured():
            li = list_item('Set up your Audiobookshelf server...',
                           art={'icon': 'DefaultAddonService.png', 'thumb': 'DefaultAddonService.png'})
            self.add(li, url('settings'), folder=False)
            return self.finish()
        entries = [('Continue Listening', 'continue', 'DefaultMusicRecentlyPlayed.png'),
                   ('Recently Added', 'recent', 'DefaultMusicRecentlyAdded.png'),
                   ('All Audiobooks', 'books', 'DefaultMusicAlbums.png'),
                   ('Series', 'series', 'DefaultMusicCompilations.png'),
                   ('Authors', 'authors', 'DefaultMusicArtists.png'),
                   ('Search', 'search', 'DefaultMusicSearch.png')]
        for label, action, icon in entries:
            self.add(list_item(label, art={'icon': icon, 'thumb': icon}), url(action))
        try:
            libraries = self.cache.fetch('libraries', self.api.libraries)
            if len(libraries) > 1:
                lib = self.library()
                li = list_item('Library: %s' % lib.get('name'), art={'icon': 'DefaultMusicSources.png'})
                self.add(li, url('choose_library'), folder=False)
        except api.ApiError as error:
            log('library list: %s' % error, xbmc.LOGWARNING)
        li = list_item('Settings', art={'icon': 'DefaultAddonService.png', 'thumb': 'DefaultAddonService.png'})
        self.add(li, url('settings'), folder=False)
        self.finish()

    def continue_listening(self):
        library_id = self.library_id()
        items = [i for i in self.api.items_in_progress(limit=100)
                 if i.get('libraryId') == library_id and i.get('mediaType') == 'book']
        if items:
            self.books(items)
        else:
            self.message('Nothing in progress. Books you start listening to appear here.')
        self.finish('albums', 'Continue Listening', cache_to_disc=False)

    def recent(self):
        self.book_page('recent', 'Recently Added', 'addedAt', True)

    def all_books(self):
        sort = self.params.get('sort')
        index = int(sort) if sort and sort.isdigit() and int(sort) < len(config.SORTS) else self.s['sort']
        name, key, desc = config.SORTS[index]
        if int(self.params.get('page', 0)) == 0:
            li = list_item('[COLOR %s]Sort: %s[/COLOR]' % (DIM, name),
                           art={'icon': 'DefaultIconInfo.png', 'thumb': 'DefaultIconInfo.png'})
            self.add(li, url('choose_sort', sort=index), folder=False)
        self.book_page('books', 'All Audiobooks', key, desc, sort=index)

    def book_page(self, action, title, sort_key, desc, **params):
        library_id = self.library_id()
        page = int(self.params.get('page', 0))
        limit = 25 if action == 'recent' else self.s['page_size']
        key = 'items/%s/%s/%s/%d/%d' % (library_id, sort_key, desc, page, limit)
        data = self.cache.fetch(key, lambda: self.api.items(library_id, page, limit, sort_key, desc))
        results = data.get('results') or []
        if results:
            self.books(results)
            if action != 'recent':
                self.next_page(action, page, int(data.get('total') or 0), limit, **params)
        else:
            self.message('This library is empty. Add audiobooks on the server, then scan the library.')
        self.finish('albums', title)

    def choose_sort(self):
        names = [name for name, _key, _desc in config.SORTS]
        current = int(self.params.get('sort', self.s['sort']))
        choice = xbmcgui.Dialog().select('Sort by', names, preselect=current)
        if choice >= 0 and choice != current:
            xbmc.executebuiltin('Container.Update(%s,replace)' % url('books', sort=choice))

    def series_list(self):
        library_id = self.library_id()
        page = int(self.params.get('page', 0))
        limit = self.s['page_size']
        data = self.cache.fetch('series/%s/%d/%d' % (library_id, page, limit),
                                lambda: self.api.series(library_id, page, limit))
        results = data.get('results') or []
        for s in results:
            books = s.get('books') or []
            first = books[0] if books else None
            art = self.cover(model.book(first)) if first else {'icon': 'DefaultMusicCompilations.png'}
            count = len(books)
            li = list_item(model.text(s.get('name')) or 'Unnamed series',
                           '%d book%s' % (count, '' if count == 1 else 's'), art=art,
                           info={'title': model.text(s.get('name')), 'comment': model.text(s.get('description')),
                                 'mediatype': 'album'})
            self.add(li, url('series_books', id=s.get('id'), name=s.get('name')))
        if not results:
            self.message('No series in this library.')
        self.next_page('series', page, int(data.get('total') or 0), limit)
        self.finish('albums', 'Series')

    def series_books(self):
        library_id = self.library_id()
        series_id = self.params['id']
        data = self.cache.fetch('series_books/%s' % series_id, lambda: self.api.items(
            library_id, 0, 500, 'media.metadata.title', False, 'series.' + api.b64(series_id), minified=False))
        results = data.get('results') or []
        progress = self.progress()
        books = [model.book(i, progress.get(i.get('id'))) for i in results if isinstance(i, dict)]
        books.sort(key=lambda b: (model.sequence_key(model.sequence_in(b, series_id=series_id)), b['title']))
        for b in books:
            self.book_item(b, series_id)
        if not books:
            self.message('No books found in this series.')
        self.finish('albums', self.params.get('name') or 'Series')

    def authors(self):
        library_id = self.library_id()
        authors = self.cache.fetch('authors/%s' % library_id, lambda: self.api.authors(library_id))
        authors = sorted((a for a in authors if isinstance(a, dict) and a.get('id')),
                         key=lambda a: (model.text(a.get('lastFirst')) or model.text(a.get('name'))).lower())
        for a in authors:
            art = {'icon': 'DefaultArtist.png', 'thumb': 'DefaultArtist.png'}
            if a.get('imagePath'):
                image = self.api.author_image_url(a['id'], a.get('updatedAt'))
                art = {'thumb': image, 'icon': image, 'fanart': image}
            count = a.get('numBooks') or 0
            li = list_item(model.text(a.get('name')) or 'Unknown author',
                           '%d book%s' % (count, '' if count == 1 else 's') if count else '', art=art,
                           info={'artist': [model.text(a.get('name'))], 'comment': model.text(a.get('description')),
                                 'mediatype': 'artist'})
            self.add(li, url('author_books', id=a['id'], name=a.get('name')))
        if not authors:
            self.message('No authors in this library.')
        self.finish('artists', 'Authors')

    def author_books(self):
        library_id = self.library_id()
        author_id = self.params['id']
        data = self.cache.fetch('author_books/%s' % author_id, lambda: self.api.items(
            library_id, 0, 500, 'media.metadata.title', False, 'authors.' + api.b64(author_id)))
        progress = self.progress()
        books = [model.book(i, progress.get(i.get('id'))) for i in data.get('results') or [] if isinstance(i, dict)]

        def order(b):  # series together, in sequence; standalone books after, by title
            if b['series']:
                _sid, name, seq = b['series'][0]
                return (0, name.lower(), model.sequence_key(seq), b['title'].lower())
            return (1, '', model.sequence_key(''), b['title'].lower())
        for b in sorted(books, key=order):
            self.book_item(b)
        if not books:
            self.message('No books by this author.')
        self.finish('albums', self.params.get('name') or 'Author')

    # -- search --------------------------------------------------------------------------

    def recent_searches(self):
        try:
            with open(os.path.join(profile(), 'searches.json')) as handle:
                return [q for q in json.load(handle) if isinstance(q, str)][:10]
        except (OSError, ValueError):
            return []

    def search(self):
        li = list_item('New search...', art={'icon': 'DefaultMusicSearch.png', 'thumb': 'DefaultMusicSearch.png'})
        self.add(li, url('search_prompt'), folder=False)
        for q in self.recent_searches():
            self.add(list_item(q, art={'icon': 'DefaultMusicSearch.png'}), url('search_results', q=q))
        self.finish(category='Search', cache_to_disc=False)

    def search_prompt(self):
        query = xbmcgui.Dialog().input('Search title, author or series').strip()
        if query:
            searches = [query] + [q for q in self.recent_searches() if q.lower() != query.lower()]
            with open(os.path.join(profile(), 'searches.json'), 'w') as handle:
                json.dump(searches[:10], handle)
            xbmc.executebuiltin('Container.Update(%s)' % url('search_results', q=query))

    def search_results(self):
        query = self.params.get('q', '')
        data = self.api.search(self.library_id(), query, limit=50)
        items, seen = [], set()
        for hit in data.get('book') or []:
            item = hit.get('libraryItem') if isinstance(hit, dict) else None
            if item and item.get('id') not in seen:
                seen.add(item['id'])
                items.append(item)
        for hit in data.get('series') or []:
            s = hit.get('series') or {}
            if s.get('id'):
                count = len(hit.get('books') or [])
                li = list_item('Series: %s' % s.get('name'), '%d book%s' % (count, '' if count == 1 else 's'),
                               art={'icon': 'DefaultMusicCompilations.png'})
                self.add(li, url('series_books', id=s['id'], name=s.get('name')))
        for a in data.get('authors') or []:
            if isinstance(a, dict) and a.get('id'):
                li = list_item('Author: %s' % a.get('name'), art={'icon': 'DefaultArtist.png'})
                self.add(li, url('author_books', id=a['id'], name=a.get('name')))
        self.books(items)
        if not items and not data.get('series') and not data.get('authors'):
            self.message('No matches for "%s".' % query)
        self.finish('albums', 'Search: %s' % query, cache_to_disc=False)

    # -- one book ------------------------------------------------------------------------

    def load_book(self, item_id):
        item = self.cache.fetch('item/%s' % item_id, lambda: self.api.item(item_id))
        item = dict(item, userMediaProgress=None)  # the cached copy's progress may be old
        return model.book(item, self.api.progress(item_id))

    def book(self):
        b = self.load_book(self.params['id'])
        p = b['progress']
        art = self.cover(b)
        info = {'title': b['title'], 'artist': [b['author']] if b['author'] else [], 'album': b['title'],
                'duration': b['duration'], 'comment': b['description']}
        if b['missing'] or b['invalid']:
            self.message('The audio files for this book are missing on the server.', 'DefaultIconWarning.png')
        elif p['state'] == 'progress':
            left = max(0.0, b['duration'] - p['time'])
            label = 'Resume from %s  [COLOR %s](%d%%, %s left)[/COLOR]' % (
                model.clock(p['time']), IN_PROGRESS, int(p['fraction'] * 100), model.length(left))
            self.add(list_item(label, art=art, info=info), url('play', id=b['id'], mode='resume'), folder=False)
        if not (b['missing'] or b['invalid']):
            label = 'Listen again from the start' if p['state'] == 'finished' else 'Play from start'
            self.add(list_item(label, model.length(b['duration']), art=art, info=info),
                     url('play', id=b['id'], mode='start'), folder=False)
            if b['chapters']:
                self.add(list_item('Chapters (%d)' % len(b['chapters']), art=art), url('chapters', id=b['id']))
        self.add(list_item('About this book', art=art, info=info), url('about', id=b['id']), folder=False)
        for sid, name, seq in b['series']:
            if sid:
                label = 'Series: %s%s' % (name, ' (book %s)' % seq if seq else '')
                self.add(list_item(label, art={'icon': 'DefaultMusicCompilations.png'}),
                         url('series_books', id=sid, name=name))
        for aid, name in b['author_ids']:
            self.add(list_item('More by %s' % name, art={'icon': 'DefaultArtist.png'}),
                     url('author_books', id=aid, name=name))
        self.finish('', b['title'], cache_to_disc=False)

    def chapters(self):
        b = self.load_book(self.params['id'])
        art = self.cover(b)
        current = model.chapter_at(b['chapters'], b['progress']['time']) if b['progress']['state'] == 'progress' else -1
        for i, c in enumerate(b['chapters']):
            label = '%d. %s' % (i + 1, c['title'])
            if i == current:
                label = '[COLOR %s]%s[/COLOR]' % (IN_PROGRESS, label)
            li = list_item(label, '%s  (%s)' % (model.clock(c['start']), model.length(c['end'] - c['start'])),
                           art=art, info={'title': c['title'], 'album': b['title'], 'tracknumber': i + 1,
                                          'duration': c['end'] - c['start']})
            self.add(li, url('play', id=b['id'], mode='chapter', t='%.3f' % c['start']), folder=False)
        self.finish('', 'Chapters: %s' % b['title'], cache_to_disc=False)

    def about(self):
        b = self.load_book(self.params['id'])
        p = b['progress']
        lines = ['[B]%s[/B]' % b['title']]
        if b['subtitle']:
            lines.append(b['subtitle'])
        lines.append('')
        for label, value in (('Author', b['author']), ('Narrator', b['narrator']),
                             ('Series', ', '.join('%s #%s' % (n, s) if s else n for _i, n, s in b['series'])),
                             ('Published', b['year']), ('Genres', ', '.join(b['genres'])),
                             ('Length', model.length(b['duration']) if b['duration'] else ''),
                             ('Chapters', str(len(b['chapters'])) if b['chapters'] else '')):
            if value:
                lines.append('[B]%s:[/B] %s' % (label, value))
        if p['state'] == 'finished':
            lines.append('[B]Progress:[/B] finished')
        elif p['state'] == 'progress':
            lines.append('[B]Progress:[/B] %s of %s (%d%%)' % (model.clock(p['time']), model.clock(b['duration']),
                                                              int(p['fraction'] * 100)))
        else:
            lines.append('[B]Progress:[/B] not started')
        if b['description']:
            lines += ['', b['description']]
        xbmcgui.Dialog().textviewer(b['title'], '\n'.join(lines))

    # -- playback ------------------------------------------------------------------------

    def play(self):
        item_id = self.params['id']
        mode = self.params.get('mode', 'resume')
        active = get_json_prop(SESSION_PROP)
        player = xbmc.Player()
        if active and active.get('item_id') == item_id and player.isPlayingAudio() and mode != 'resume':
            # Same book already playing: just move within it.
            seek_to(active, float(self.params.get('t', 0)) if mode == 'chapter' else 0.0)
            return
        if active and active.get('item_id') == item_id and player.isPlayingAudio():
            return  # already playing it; Resume is a no-op

        # A position that couldn't be sent earlier goes first, so the session starts from it.
        sync.Pending(os.path.join(profile(), 'pending.json')).flush(self.api, log)
        progress = model.progress_state(self.api.progress(item_id))
        dialog = xbmcgui.DialogProgress()
        dialog.create(config.ADDON_NAME, 'Starting playback...')
        try:
            session = self.api.start_session(item_id, device_info())
        finally:
            dialog.close()
        tracks = model.tracks(session)
        duration = model.number(session.get('duration')) or sum(t['duration'] for t in tracks)
        if not tracks:
            self.api.close_session(session.get('id'), model.number(session.get('currentTime')), 0, duration)
            raise PlaybackProblem('This book has no playable audio files on the server.')
        if progress['state'] == 'new' and model.number(session.get('currentTime')):
            # No progress record, but the session knows a position: trust the server.
            progress = model.progress_state({'currentTime': session.get('currentTime')}, duration)

        if mode == 'chapter':
            target = float(self.params.get('t', 0))
        elif mode == 'start':
            target = 0.0
        else:
            target = model.start_position(progress, duration, self.s['resume_rewind'])
        index, offset = model.locate(tracks, target)

        meta = session.get('mediaMetadata') or {}
        title = model.text(session.get('displayTitle')) or model.text(meta.get('title')) or 'Audiobook'
        author = model.text(session.get('displayAuthor'))
        cover = self.api.cover_url(item_id, (session.get('libraryItem') or {}).get('updatedAt'))
        chapters = model.chapters(session.get('chapters'))

        playlist = xbmc.PlayList(xbmc.PLAYLIST_MUSIC)
        playlist.clear()
        for i, t in enumerate(tracks):
            label = title if len(tracks) == 1 else '%s (part %d of %d)' % (title, i + 1, len(tracks))
            li = list_item(label, author, art={'thumb': cover, 'icon': cover, 'fanart': cover},
                           info={'title': label, 'artist': [author] if author else [], 'album': title,
                                 'duration': t['duration'], 'tracknumber': i + 1, 'mediatype': 'song'})
            if i == index and offset > 1:
                li.setProperty('StartOffset', '%.3f' % offset)  # Kodi opens the file there
            if t['mime']:
                li.setMimeType(t['mime'])
                li.setContentLookup(False)
            playlist.add(self.api.stream_url(t['path']), li)

        set_json_prop(SEEK_PROP, None)
        set_json_prop(SESSION_PROP, {
            'session_id': session.get('id'), 'item_id': item_id, 'title': title, 'author': author,
            'cover': cover, 'duration': duration, 'server': self.api.server,
            'tracks': [{'start': t['start'], 'duration': t['duration'], 'path': t['path']} for t in tracks],
            'chapters': chapters, 'start_index': index, 'start_offset': offset,
            'resume_time': model.number(session.get('currentTime'))})
        log('playing %s from %s (track %d/%d at %.0f s), session %s'
            % (item_id, model.clock(target), index + 1, len(tracks), offset, session.get('id')))
        player.play(playlist, startpos=index)

    def skip(self):
        active = get_json_prop(SESSION_PROP)
        player = xbmc.Player()
        if not active or not player.isPlayingAudio():
            return
        index = current_track(active, player)
        if index is None:
            return
        step = self.s['skip_forward'] if self.params.get('dir') == 'forward' else -self.s['skip_back']
        now = model.book_time(active['tracks'], index, player.getTime())
        seek_to(active, now + step)

    # -- settings actions ----------------------------------------------------------------

    def test(self):
        try:
            status = self.api.status()
            user = self.api.me()
            libraries = self.api.libraries()
        except api.ApiError as error:
            log('connection test failed: %s' % error, xbmc.LOGWARNING)
            xbmcgui.Dialog().ok(config.ADDON_NAME, 'Connection failed.\n' + explain(error))
            return
        names = ', '.join(lib.get('name', '?') for lib in libraries) or 'none'
        xbmcgui.Dialog().ok(config.ADDON_NAME, 'Connected to Audiobookshelf %s as %s.\nAudiobook libraries: %s'
                            % (status.get('serverVersion', '?'), user.get('username', '?'), names))

    def choose_library(self):
        libraries = self.api.libraries()
        if not libraries:
            xbmcgui.Dialog().ok(config.ADDON_NAME, 'This server has no audiobook libraries you can access.')
            return
        current = next((i for i, lib in enumerate(libraries) if lib.get('id') == self.s['library_id']), 0)
        choice = xbmcgui.Dialog().select('Library', [lib.get('name', '?') for lib in libraries], preselect=current)
        if choice >= 0:
            addon().setSettingString('library_id', libraries[choice]['id'])
            self.cache.clear()
            xbmc.executebuiltin('Container.Refresh')

    def clear_cache(self):
        self.cache.clear()
        notify('Library data will be reloaded')
        xbmc.executebuiltin('Container.Refresh')


class EmptyLibrary(Exception):
    pass


class PlaybackProblem(Exception):
    pass


def current_track(active, player):
    """Which of the session's tracks Kodi is playing, or None if it's something else."""
    try:
        playing = player.getPlayingFile()
    except RuntimeError:
        return None
    playing = playing.split('|')[0]
    for i, t in enumerate(active['tracks']):
        if playing == active['server'] + t['path']:
            return i
    return None


def seek_to(active, t):
    """Move to book time t: a seek within the playing track, or a jump to another track
    with the offset left for the service to apply once that track has started."""
    player = xbmc.Player()
    duration = active.get('duration') or 0
    t = max(0.0, min(t, duration - 1 if duration else t))
    index, offset = model.locate(active['tracks'], t)
    if current_track(active, player) == index:
        player.seekTime(offset)
    else:
        set_json_prop(SEEK_PROP, {'session_id': active['session_id'], 'index': index, 'offset': offset})
        player.playselected(index)


ROUTES = {
    'continue': Screen.continue_listening, 'recent': Screen.recent, 'books': Screen.all_books,
    'choose_sort': Screen.choose_sort, 'series': Screen.series_list, 'series_books': Screen.series_books,
    'authors': Screen.authors, 'author_books': Screen.author_books, 'search': Screen.search,
    'search_prompt': Screen.search_prompt, 'search_results': Screen.search_results, 'book': Screen.book,
    'chapters': Screen.chapters, 'about': Screen.about, 'play': Screen.play, 'skip': Screen.skip,
    'test': Screen.test, 'choose_library': Screen.choose_library, 'clear_cache': Screen.clear_cache,
}
DIRECTORIES = {'continue', 'recent', 'books', 'series', 'series_books', 'authors', 'author_books', 'search',
               'search_results', 'book', 'chapters'}


def route(argv):
    handle = int(argv[1]) if len(argv) > 1 and argv[1].lstrip('-').isdigit() else -1
    params = dict(parse_qsl(argv[2][1:])) if len(argv) > 2 else {}
    action = params.get('action', '')
    if action == 'settings':
        addon().openSettings()
        return
    if action == 'noop':
        return
    screen = None
    try:
        screen = Screen(handle, params)
        if not action:
            screen.home()
        elif action in ROUTES:
            ROUTES[action](screen)
        else:
            log('unknown action %r' % action, xbmc.LOGWARNING)
    except EmptyLibrary as error:
        if action in DIRECTORIES and handle >= 0:
            screen.message(str(error))
            screen.finish(cache_to_disc=False)
        else:
            xbmcgui.Dialog().ok(config.ADDON_NAME, str(error))
    except (api.ApiError, PlaybackProblem) as error:
        if isinstance(error, api.ApiError):
            error_dialog(error)
        else:
            log(str(error), xbmc.LOGWARNING)
            xbmcgui.Dialog().ok(config.ADDON_NAME, str(error))
        if action in DIRECTORIES and handle >= 0:
            xbmcplugin.endOfDirectory(handle, succeeded=False)
    except Exception:
        import traceback
        log('unexpected error in %r:\n%s' % (action, traceback.format_exc()), xbmc.LOGERROR)
        notify('Something went wrong. See the Kodi log.', xbmcgui.NOTIFICATION_ERROR)
        if action in DIRECTORIES and handle >= 0:
            xbmcplugin.endOfDirectory(handle, succeeded=False)


def run():
    route(sys.argv)
