"""Start and stall detection. Watchdog is pure logic (unit-tested); CamPlayer is the thin
xbmc.Player subclass that feeds it.

A camera fails when it hasn't started 15 s after play(), when its playback time stops
advancing for 10 s, or when Kodi reports an error or the end of a live stream. After 60 s of
good playback it counts as healthy.
"""

try:
    import xbmc
except ImportError:      # unit tests
    xbmc = None

START_TIMEOUT = 15.0
STALL = 10.0
HEALTHY = 60.0
CALLBACK_GRACE = 1.5     # callbacks this soon after play() belong to the previous item

STARTING, STARTED, PLAYING, HEALTHY_NOW = 'starting', 'started', 'playing', 'healthy'
FAILED = 'failed'


class Watchdog(object):
    def __init__(self):
        self.reset(0.0)
        self.active = False

    def reset(self, now):
        self.t_play = now
        self.t_av = None
        self.last_pos = None
        self.last_progress = now
        self.reason = None
        self.announced = False
        self.healthy_reported = False

    def play(self, now):
        self.reset(now)
        self.active = True

    def stop(self):
        self.active = False

    def av_started(self, now):
        if self.active and self.t_av is None and self.reason is None:
            self.t_av = now
            self.last_progress = now

    def fail(self, reason, now):
        if self.active and self.reason is None and now - self.t_play >= CALLBACK_GRACE:
            self.reason = reason

    def check(self, now, position=None):
        """STARTING, STARTED (once, at the first frame), PLAYING, HEALTHY_NOW (once) or FAILED
        (see .reason). position: the player's time in seconds, or None if unknown."""
        if self.reason:
            return FAILED
        if self.t_av is None:
            if now - self.t_play > START_TIMEOUT:
                self.reason = 'no picture after %d s' % START_TIMEOUT
                return FAILED
            return STARTING
        if not self.announced:
            self.announced = True
            self.last_pos = position
            return STARTED
        if position is not None and (self.last_pos is None or abs(position - self.last_pos) > 0.05):
            self.last_pos = position
            self.last_progress = now
        if now - self.last_progress > STALL:
            self.reason = 'stalled for %d s' % STALL
            return FAILED
        if not self.healthy_reported and now - self.t_av >= HEALTHY:
            self.healthy_reported = True
            return HEALTHY_NOW
        return PLAYING


if xbmc is not None:
    class CamPlayer(xbmc.Player):
        def __init__(self, watchdog, clock):
            xbmc.Player.__init__(self)
            self.watchdog = watchdog
            self.clock = clock

        def onAVStarted(self):
            self.watchdog.av_started(self.clock())

        def onPlayBackError(self):
            self.watchdog.fail('playback error', self.clock())

        def onPlayBackEnded(self):
            self.watchdog.fail('stream ended', self.clock())

        def position(self):
            try:
                return self.getTime() if self.isPlaying() else None
            except Exception:
                return None

        def playing_file(self):
            try:
                return self.getPlayingFile() if self.isPlaying() else ''
            except Exception:
                return ''
