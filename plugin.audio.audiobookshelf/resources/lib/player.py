"""The background service: follows Kodi's player while one of our books plays and keeps
Audiobookshelf's progress up to date.

The plugin starts playback and leaves the session (id, tracks, chapters, where to start)
in a window property. Here we
  - seek to the resume point once the right track has started,
  - turn Kodi's track + time into book time,
  - send it every N seconds, on pause, and when playback stops or the book ends,
  - show the current chapter as the playing title (Kodi 20+),
  - keep positions that couldn't be sent and retry them later.
Stop and end events are confirmed a moment later, because Kodi also fires them when one
track hands over to the next, or when another book replaces this one.
"""

import os
import time

import xbmc

from . import api, model, sync
from .kodiutil import (SEEK_PROP, SESSION_PROP, client, device_info, get_json_prop, log, notify, profile,
                       set_json_prop, set_music_info, settings)
from .plugin import current_track

CONFIRM_DELAY = 2.5
PENDING_EVERY = 300
START_TOLERANCE = 15.0   # seconds between where playback is and where it was asked to start
START_PATIENCE = 20.0    # how long to keep trying to get there before giving up


class Player(xbmc.Player):
    def __init__(self, service):
        xbmc.Player.__init__(self)
        self.service = service

    def onAVStarted(self):
        self.service.on_started()

    def onPlayBackPaused(self):
        self.service.on_paused()

    def onPlayBackStopped(self):
        self.service.on_stopped(ended=False)

    def onPlayBackEnded(self):
        self.service.on_stopped(ended=True)

    def onPlayBackError(self):
        self.service.on_error()


class Monitor(xbmc.Monitor):
    def __init__(self, service):
        xbmc.Monitor.__init__(self)
        self.service = service

    def onSettingsChanged(self):
        self.service.reload()


class Service(object):
    def __init__(self):
        self.s = settings()
        self.api = client(self.s)
        self.pending = sync.Pending(os.path.join(profile(), 'pending.json'))
        self.active = None       # the session dict from the plugin
        self.tracker = None
        self.expect = None       # (book time, track, offset, deadline, next try) still to be reached
        self.blocked = False     # never reached the start point: report nothing for this session
        self.check_at = None     # when to confirm a stop/end event
        self.ended = False
        self.chapter = -1
        self.player = Player(self)
        self.monitor = Monitor(self)
        self.next_pending = time.time() + 20

    def reload(self):
        self.s = settings()
        self.api = client(self.s)
        if self.tracker:
            self.tracker.interval = self.s['sync_interval']

    # -- events (called on Kodi's callback thread; keep them short) ------------------------

    def on_started(self):
        self.check_at = None
        self.ended = False

    def on_paused(self):
        if self.tracker:
            self.tracker.last_sent = 0  # report at the next tick

    def on_stopped(self, ended):
        if self.active:
            self.ended = self.ended or ended
            self.check_at = time.time() + CONFIRM_DELAY

    def on_error(self):
        if self.active:
            notify("Kodi couldn't play this audio (connection lost or unsupported format)")
            self.check_at = time.time() + CONFIRM_DELAY

    # -- the loop ----------------------------------------------------------------------------

    def run(self):
        log('service started')
        while not self.monitor.abortRequested():
            try:
                self.step(time.time())
            except Exception:
                import traceback
                log('service step failed:\n' + traceback.format_exc(), xbmc.LOGERROR)
            if self.monitor.waitForAbort(1):
                break
        if self.active:
            self.finish(self.tracker.position if self.tracker else None, ended=False, timeout=5)
        log('service stopped')

    def step(self, now):
        handed = get_json_prop(SESSION_PROP)
        if handed and (not self.active or handed.get('session_id') != self.active.get('session_id')):
            if self.active:
                self.finish(self.tracker.position, ended=False)
            self.adopt(handed, now)

        if self.active:
            index = current_track(self.active, self.player) if self.player.isPlayingAudio() else None
            if index is not None:
                self.playing(index, now)
            elif self.check_at and now >= self.check_at:
                ended = self.ended and sync.near_end(self.tracker.position, self.active['duration'])
                self.finish(self.tracker.position, ended=ended)
            if self.active and not self.blocked and self.tracker.due(now):
                self.report(now)

        if now >= self.next_pending and not self.active:
            self.next_pending = now + PENDING_EVERY
            if self.api.configured():
                self.pending.flush(self.api, log)

    def adopt(self, handed, now):
        self.active = handed
        self.tracker = sync.Tracker(handed.get('duration') or 0, self.s['sync_interval'], now)
        self.expect = None
        self.blocked = False
        index = handed.get('start_index', 0)
        offset = handed.get('start_offset', 0) or 0
        if offset > 1 or index:
            self.expect = [model.book_time(handed['tracks'], index, offset), index, offset, now + START_PATIENCE, 0]
        self.check_at = None
        self.ended = False
        self.chapter = -1
        log('following session %s for %s' % (handed.get('session_id'), handed.get('item_id')))

    def playing(self, index, now):
        a = self.active
        self.check_at = None
        seek = get_json_prop(SEEK_PROP)
        if seek and seek.get('session_id') == a['session_id']:
            set_json_prop(SEEK_PROP, None)
            self.expect = [model.book_time(a['tracks'], seek['index'], seek.get('offset', 0)), seek['index'],
                           seek.get('offset', 0), now + START_PATIENCE, 0]
        try:
            offset = self.player.getTime()
        except RuntimeError:
            return
        position = model.book_time(a['tracks'], index, offset)
        if self.blocked:
            return
        if self.expect and not self.reached(index, position, now):
            return
        paused = xbmc.getCondVisibility('Player.Paused')
        self.tracker.tick(position, not paused, now)
        self.show_chapter(position)

    def reached(self, index, position, now):
        """True once playback is where it was asked to start (resume point, chapter, skip).
        Until then nothing is reported, so a seek Kodi ignored can't overwrite the saved
        position with the start of the file."""
        target, want_index, want_offset, deadline, next_try = self.expect
        if index == want_index and abs(position - target) <= START_TOLERANCE:
            self.expect = None
            self.tracker.last_tick = None  # don't count the time spent getting here
            return True
        if now >= deadline:
            self.expect = None
            self.blocked = True
            log('playback never reached %s; not reporting progress for this session' % model.clock(target),
                xbmc.LOGWARNING)
            notify("Couldn't jump to your saved position; it was left unchanged")
            return False
        if now >= next_try and index == want_index:
            self.player.seekTime(want_offset)
            self.expect[4] = now + 3
        return False

    def show_chapter(self, position):
        chapters = self.active.get('chapters') or []
        i = model.chapter_at(chapters, position)
        if i == self.chapter or i < 0:
            return
        self.chapter = i
        if not hasattr(self.player, 'updateInfoTag'):  # Kodi 19
            return
        a = self.active
        title = chapters[i]['title']
        try:
            item = self.player.getPlayingItem()
            item.setLabel(title)
            set_music_info(item, {'title': title, 'artist': [a['author']] if a.get('author') else [],
                                  'album': a.get('title'), 'tracknumber': i + 1})
            self.player.updateInfoTag(item)
        except Exception as error:
            log('chapter title: %s' % error, xbmc.LOGDEBUG)

    # -- talking to the server -------------------------------------------------------------

    def report(self, now):
        payload = self.tracker.payload()
        try:
            self.api.sync_session(self.active['session_id'], **_args(payload))
            self.tracker.sent(payload, now)
        except api.NotFound:
            log('session %s has gone; reopening' % self.active['session_id'], xbmc.LOGWARNING)
            self.reopen(payload, now)
        except api.ApiError as error:
            self.tracker.failed(now)
            log('progress sync failed (%s); will retry' % error, xbmc.LOGWARNING)

    def reopen(self, payload, now):
        """The server forgot the session (restart, expiry): start a new one for the same
        book and carry on; if that fails too, write the position directly."""
        try:
            session = self.api.start_session(self.active['item_id'], device_info())
            self.active['session_id'] = session['id']
            set_json_prop(SESSION_PROP, self.active)
            self.api.sync_session(session['id'], **_args(payload))
            self.tracker.sent(payload, now)
        except api.ApiError as error:
            log('reopening failed (%s); updating progress directly' % error, xbmc.LOGWARNING)
            try:
                self.api.update_progress(self.active['item_id'], payload['currentTime'], payload['duration'])
                self.tracker.sent(payload, now)
            except api.ApiError:
                self.tracker.failed(now)

    def finish(self, position, ended, timeout=None):
        """Close the session with the last position (the full length if the book ran to its
        end; the server then marks it finished). Falls back to the progress endpoint, then
        to the pending file."""
        a, tracker = self.active, self.tracker
        self.active = None
        self.tracker = None
        self.check_at = None
        if get_json_prop(SESSION_PROP) and get_json_prop(SESSION_PROP).get('session_id') == a['session_id']:
            set_json_prop(SESSION_PROP, None)
        if self.blocked:
            position = None
        if position is None:
            # Nothing played (unplayable file, or replaced at once): close without moving
            # the saved position.
            log('session %s closed before anything played' % a['session_id'])
            try:
                self.api.close_session(a['session_id'], a.get('resume_time') or 0, 0, a.get('duration') or 0)
            except api.ApiError:
                pass
            return
        payload = tracker.payload(ended=ended)
        log('closing session %s at %s%s (%.0f s listened)' % (a['session_id'], model.clock(payload['currentTime']),
                                                             ' (end of book)' if ended else '',
                                                             payload['timeListened']))
        saved_timeout = self.api.timeout
        if timeout:
            self.api.timeout = timeout
        try:
            self.api.close_session(a['session_id'], **_args(payload))
            return
        except api.NotFound:
            pass
        except api.ApiError as error:
            log('closing the session failed: %s' % error, xbmc.LOGWARNING)
        finally:
            self.api.timeout = saved_timeout
        try:
            self.api.update_progress(a['item_id'], payload['currentTime'], payload['duration'])
        except api.ApiError as error:
            log('saving progress failed (%s); kept for later' % error, xbmc.LOGWARNING)
            self.pending.add(a['item_id'], payload['currentTime'], payload['duration'])
            self.next_pending = time.time() + 60
            notify('Could not reach the server. Your position is saved and will be sent later.')


def _args(payload):
    return {'current_time': payload['currentTime'], 'time_listened': payload['timeListened'],
            'duration': payload['duration']}


def run():
    Service().run()
