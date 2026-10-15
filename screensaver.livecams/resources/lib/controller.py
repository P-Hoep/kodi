"""The camera session: window, player and the loop that ties catalogue, selector, resolvers,
watchdog, health and overlay together.

How it runs. Kodi wakes a screensaver as soon as anything starts playing, and stops the
screensaver's script a few seconds later. So the screensaver entry (default.py) hands
off to session.py, an ordinary script that Kodi leaves alone, and this session owns the
window and the player. Before the first camera plays, Kodi still counts the screensaver as
active: any key wakes it and the session closes on onScreensaverDeactivated. The wake-up
that our own play() causes is ignored. After that the session's window is on top and
every key, remote button, mouse move or CEC command reaches onAction, which ends it.

Threads: the loop thread selects, probes, plays and watches; a short-lived thread
refreshes the catalogue. GUI calls are cheap property sets, made from the loop thread.
"""

import os
import threading
import time
import traceback
from concurrent.futures import ThreadPoolExecutor

import xbmc
import xbmcaddon
import xbmcgui
import xbmcvfs

from . import catalog as catalog_mod
from . import config, health as health_mod, overlay as overlay_mod, player as player_mod
from . import resolvers, selector as selector_mod, splash

ADDON_ID = config.ADDON_ID
ACCENT = 'FF4DD0E1'
TICK = 0.25
MAX_FAILURES = 5          # consecutive stream failures before the fallback card
CARD_SECONDS = 60
PROBES_PER_SELECTION = 8  # draws per selection before giving up for this round
FIRST_BATCH = 3           # at activation, probe this many cameras at once to start fast
OFFLINE_STREAK = 3        # network errors in a row (no answer at all) = we are offline
OWN_WAKE_GRACE = 3.0      # seconds after play() in which a screensaver wake-up is ours
HEARTBEAT = 'livecams.session'
MUTED = 'livecams.muted'
HOME = 10000


def log(message, level=xbmc.LOGINFO):
    xbmc.log('[%s] %s' % (ADDON_ID, message), level)


def debug(message):
    log(message, xbmc.LOGDEBUG)


def read_settings(addon):
    try:
        st = addon.getSettings()   # Kodi 20+
        getters = {'boolean': st.getBool, 'integer': st.getInt, 'number': st.getNumber,
                   'string': st.getString, 'list': st.getIntList}
    except AttributeError:
        import re
        getters = {'boolean': addon.getSettingBool, 'integer': addon.getSettingInt,
                   'number': addon.getSettingNumber, 'string': addon.getSettingString,
                   'list': lambda sid: [v for v in re.split(r'[,|]', addon.getSetting(sid)) if v.strip()]}
    return config.read(getters)


def profile_dir(addon):
    path = xbmcvfs.translatePath(addon.getAddonInfo('profile'))
    if not os.path.isdir(path):
        os.makedirs(path)
    return path


def translator(addon):
    def translate(sid, text):
        try:
            return addon.getLocalizedString(sid) or text
        except Exception:
            return text
    return translate


def kodi_major():
    try:
        return int(xbmc.getInfoLabel('System.BuildVersion').split('.')[0])
    except (ValueError, IndexError):
        return 21


def has_addon(addon_id):
    return bool(xbmc.getCondVisibility('System.HasAddon(%s)' % addon_id))


def twenty_four_hour():
    return '%H' in (xbmc.getRegion('time') or '%H')


def session_alive():
    """True if a session is running (its loop refreshes the heartbeat every few seconds)."""
    try:
        return time.time() - float(xbmcgui.Window(HOME).getProperty(HEARTBEAT) or 0) < 10
    except ValueError:
        return False


def set_mute(on):
    xbmc.executeJSONRPC('{"jsonrpc":"2.0","method":"Application.SetMute","params":{"mute":%s},"id":1}'
                        % ('true' if on else 'false'))


def restore_mute():
    """Unmute if a session muted Kodi and then died without unmuting."""
    home = xbmcgui.Window(HOME)
    if home.getProperty(MUTED) and not session_alive():
        set_mute(False)
        home.clearProperty(MUTED)


class ExitMonitor(xbmc.Monitor):
    def __init__(self, session):
        xbmc.Monitor.__init__(self)
        self.session = session

    def onScreensaverDeactivated(self):
        self.session.on_wake()


class LiveWindow(xbmcgui.WindowXMLDialog):
    def __init__(self, *args, **kwargs):
        self.session = kwargs['session']
        self.built = False

    def onInit(self):
        if not self.built:
            self.built = True
            self.session.attach(self)

    def onAction(self, action):
        self.session.on_input(action.getId())


class Session(object):
    """mode: 'cams' (the screensaver proper) or 'clock' (the user's own media is loaded:
    show only a clock and never touch the player)."""

    def __init__(self, mode='cams', preview=False):
        self.mode = mode
        self.preview = preview
        self.addon = xbmcaddon.Addon(ADDON_ID)
        self.path = self.addon.getAddonInfo('path')
        self.media = os.path.join(self.path, 'resources', 'media')
        self.profile = profile_dir(self.addon)
        self.settings = read_settings(self.addon)
        self.translate = translator(self.addon)
        self.stop = threading.Event()
        self.started = time.time()
        self.window = None
        self.splash = None
        self.threads = []
        self.current = None           # camera on screen (or starting)
        self.item = None
        self.playing_path = None      # what Kodi reports as playing once our camera started
        self.foreign = False          # someone else's media took over the player
        self.shown = {}               # control -> visible, as last set
        self.last_play = 0.0
        self.played = False
        self.muted_by_us = False
        self.state = 'init'
        self.card_until = 0.0
        self.failures = 0
        self.overlay = overlay_mod.Overlay(self.settings.get('overlay', 1), self.settings.get('burnin', True))
        self.watchdog = player_mod.Watchdog()
        self.monitor = ExitMonitor(self)
        self.player = player_mod.CamPlayer(self.watchdog, time.time) if mode == 'cams' else None
        self.catalog = catalog_mod.Catalog(self.profile, debug)
        self.health = health_mod.Health(os.path.join(self.profile, 'health.json'))
        self.history = health_mod.History(os.path.join(self.profile, 'history.json'))
        self.selector = selector_mod.Selector(self.settings, self.health, self.history, log=log)
        self.refreshing = None
        self.twenty_four = twenty_four_hour()
        s = self.settings
        self.dwell = config.DWELL_SECONDS[s.get('dwell', 3)]
        self.cutoff = config.CUTOFF_SECONDS[s.get('cutoff', 2)]
        self.options = resolvers.Options(
            min_height=config.MIN_RES_PX[s.get('min_res', 2)], data_saver=s.get('data_saver', False),
            isa=s.get('isa', False) and has_addon('inputstream.adaptive'), insecure=s.get('insecure', True),
            kodi_major=kodi_major(), youtube_installed=has_addon('plugin.video.youtube'))

    # ------------------------------------------------------------ lifecycle

    def run(self):
        home = xbmcgui.Window(HOME)
        home.setProperty(HEARTBEAT, str(time.time()))
        self.window = LiveWindow('screensaver-livecams.xml', self.path, 'Default', '1080i', session=self)
        try:
            self.window.doModal()
        finally:
            self.shutdown()

    def attach(self, window):
        g = window.getControl
        white = os.path.join(self.media, 'white.png')
        g(1).setImage(white)
        g(3).setImage(white)
        g(4).setImage(white)
        self.c_bars = (g(3), g(4))
        self.bars_aspect = None
        g(11).setImage(os.path.join(self.media, 'fallback.jpg'))
        g(21).setImage(os.path.join(self.media, 'fade_up.png'))
        g(25).setImage(white)
        self.c_backdrop = g(1)
        self.c_card, self.c_card_bg, self.c_message = g(10), g(11), g(14)
        self.c_overlay, self.c_title, self.c_place, self.c_detail = g(20), g(22), g(23), g(24)
        self.c_clock = g(30)
        self.card_home = self.c_card.getPosition()
        self.clock_home = self.c_clock.getPosition()
        # Hidden from Python: a <visible> tag in the XML would override setVisible().
        for control in (self.c_card, self.c_card_bg, self.c_overlay, self.c_clock):
            self.set_visible(control, False)
        if self.mode == 'cams':
            self.splash = splash.Splash(window, self.media, ACCENT, 15.0, log)
        thread = threading.Thread(target=self.guard(self.loop), name='livecams-loop')
        thread.daemon = True
        self.threads.append(thread)
        thread.start()

    def guard(self, fn):
        def run():
            try:
                fn()
            except Exception:
                log(traceback.format_exc(), xbmc.LOGERROR)
                self.exit()
        return run

    def exit(self):
        if not self.stop.is_set():
            self.stop.set()
            self.stop_ours()
            if self.window:
                self.window.close()

    def shutdown(self):
        self.stop.set()
        if self.splash:
            self.splash.close()
        self.stop_ours()
        deadline = time.time() + 1.5   # Kodi kills a script that takes too long to stop
        for t in self.threads:
            t.join(max(0.05, deadline - time.time()))
        if self.muted_by_us:
            set_mute(False)
            xbmcgui.Window(HOME).clearProperty(MUTED)
        for store in (self.health, self.history):
            try:
                store.save()
            except Exception as error:
                log('saving %s: %s' % (store.path, error), xbmc.LOGWARNING)
        xbmcgui.Window(HOME).clearProperty(HEARTBEAT)
        del self.window
        del self.monitor
        del self.player

    def stop_ours(self):
        """Stop the player if it is playing our camera; never the user's media. A cams session
        only starts when nothing is playing, so anything playing is ours unless watch() saw
        another item take over."""
        self.watchdog.stop()
        if getattr(self, 'c_backdrop', None) is not None and not self.stop.is_set():
            self.set_visible(self.c_backdrop, True)
        if self.player and self.item is not None and not self.foreign:
            try:
                if self.player.isPlaying():
                    self.player.stop()
            except Exception:
                pass
        self.item = None

    # ------------------------------------------------------------ input

    def on_input(self, action_id):
        debug('input %d: exit' % action_id)
        self.exit()

    def on_wake(self):
        if time.time() - self.last_play < OWN_WAKE_GRACE:
            debug('screensaver woken by our own playback')
            return
        debug('screensaver deactivated: exit')
        self.exit()

    # ------------------------------------------------------------ the loop

    def loop(self):
        home = xbmcgui.Window(HOME)
        last_beat = last_save = 0.0
        if self.mode == 'clock':
            self.show_card(message='', background=False)
        else:
            self.start_catalog()
        while not self.stop.is_set() and not self.monitor.abortRequested():
            now = time.time()
            if now - last_beat >= 3:
                last_beat = now
                home.setProperty(HEARTBEAT, str(now))
            if self.mode == 'cams':
                self.step(now)
            self.update_card(now)
            if now - last_save >= 300:
                last_save = now
                self.health.save()
                self.history.save()
            self.stop.wait(TICK)
        if self.monitor.abortRequested():
            self.exit()

    def step(self, now):
        state = self.state
        if state == 'catalog':
            if self.refreshing is None or not self.refreshing.is_alive():
                if self.catalog.cams:
                    self.state = 'select'
                else:
                    self.show_card()
                    self.card_until = now + CARD_SECONDS
                    self.state = 'card'
        elif state == 'select':
            self.select_and_play(first=not self.played)
        elif state == 'card':
            if now >= self.card_until:
                self.hide_card()
                if not self.catalog.cams:
                    self.start_catalog()
                else:
                    self.state = 'select'
        elif state in ('starting', 'playing'):
            self.watch(now)
        elif state == 'idle':
            pass
        if self.state in ('starting', 'playing'):
            if self.cutoff and now - self.started >= self.cutoff:
                log('stopped streaming after %d minutes (idle cut-off): clock only' % (self.cutoff // 60))
                self.stop_ours()
                self.hide_overlay()
                self.show_card(message='', background=False)
                self.state = 'idle'
        self.update_overlay(now)

    # ------------------------------------------------------------ catalogue

    def start_catalog(self):
        """Load the cached index; download in the background when it is missing or stale."""
        if not self.catalog.cams:
            self.catalog.load()
        s = self.settings
        url = s.get('catalog_url') or config.CATALOG_URL
        self.state = 'select' if self.catalog.cams else 'catalog'
        if self.catalog.stale(url, s.get('refresh_days', 7)):
            self.refreshing = threading.Thread(target=self.guard_refresh(url), name='livecams-catalog')
            self.refreshing.daemon = True
            self.threads.append(self.refreshing)
            self.refreshing.start()

    def guard_refresh(self, url):
        def run():
            fresh = catalog_mod.Catalog(self.profile, debug)
            fresh.load()
            try:
                result = fresh.refresh(url)
                log('catalogue %s: %d cameras from %d features' % (result, len(fresh.cams), fresh.features))
            except Exception as error:
                log('catalogue refresh failed, keeping the cached one: %s' % error, xbmc.LOGWARNING)
                return
            self.catalog = fresh
            ids = [c.id for c in fresh.cams]
            self.health.prune(ids)
            self.history.prune(ids)
        return run

    # ------------------------------------------------------------ selection

    def resolve(self, cam):
        try:
            return cam, resolvers.resolve(cam, self.options), None
        except resolvers.ResolveError as error:
            return cam, None, error
        except Exception as error:
            return cam, None, resolvers.ResolveError(str(error), 'http')

    def select_and_play(self, first):
        """Draw and probe cameras until one answers, then play it. The camera on screen keeps
        playing while this runs, so a failed probe costs no screen time."""
        cams = self.catalog.cams
        tried = set()
        pending = []       # network failures: blamed on the camera only if the network works
        streak = 0
        batch = FIRST_BATCH if first else 1
        attempts = 0
        while attempts < PROBES_PER_SELECTION and not self.stop.is_set():
            draws = []
            for _ in range(batch):
                cam = self.selector.draw(cams, self.current, exclude=tried)
                if cam is None:
                    break
                tried.add(cam.id)
                draws.append(cam)
            if not draws:
                break
            attempts += len(draws)
            if len(draws) > 1:
                with ThreadPoolExecutor(len(draws)) as pool:
                    results = list(pool.map(self.resolve, draws))
            else:
                results = [self.resolve(draws[0])]
            for cam, item, error in results:
                if item is not None:
                    for bad in pending:
                        self.health.failed(bad)
                    if self.stop.is_set():
                        return
                    self.play(cam, item)
                    return
                if error.kind == 'skip':
                    debug('skipped %s: %s' % (cam.title, error))
                    if error.height:
                        self.health.saw_height(cam, error.height)
                    continue
                log('camera failed probe: %s (%s): %s' % (cam.title, cam.family, error))
                if error.kind == 'network':
                    pending.append(cam)
                    streak += 1
                else:
                    streak = 0
                    if self.health.failed(cam):
                        log('more than half of %s failed in the last hour: skipping it for 6 hours' % cam.family)
            if streak >= OFFLINE_STREAK:
                log('no camera host answers: offline?')
                break
            batch = 1
        if self.stop.is_set():
            return
        if not tried:
            log('no camera matches the filters, even relaxed', xbmc.LOGWARNING)
        self.stop_ours()
        self.hide_overlay()
        self.show_card()
        self.card_until = time.time() + CARD_SECONDS
        self.state = 'card'

    # ------------------------------------------------------------ playback

    def play(self, cam, item):
        title = cam.title
        place = overlay_mod.texts(cam, time.time(), self.catalog.sources, False, self.twenty_four)['place']
        listitem = xbmcgui.ListItem(title, path=item.url, offscreen=True)
        if item.mime:
            listitem.setMimeType(item.mime)
            listitem.setContentLookup(False)
        listitem.setProperty('IsPlayable', 'true')
        for key, value in item.properties.items():
            listitem.setProperty(key, value)
        try:
            tag = listitem.getVideoInfoTag()
            tag.setTitle(title)
            tag.setPlot(place)
            tag.setMediaType('video')
        except AttributeError:
            listitem.setInfo('video', {'title': title, 'plot': place})
        self.mute_if_needed()
        log('camera: %s, %s [%s %s]%s' % (title, place, cam.family, cam.id,
                                          ' (insecure TLS)' if item.insecure else ''))
        self.previous = self.current
        self.current, self.item = cam, item
        self.playing_path = None
        self.last_play = time.time()
        self.watchdog.play(self.last_play)
        self.played = True
        self.state = 'starting'
        self.player.play(item.url, listitem, windowed=True)

    def mute_if_needed(self):
        if self.settings.get('audio') or self.muted_by_us:
            return
        if not xbmc.getCondVisibility('Player.Muted'):
            set_mute(True)
            self.muted_by_us = True
            xbmcgui.Window(HOME).setProperty(MUTED, '1')

    def watch(self, now):
        cam = self.current
        if self.watchdog.t_av is None:
            if now - self.last_play > player_mod.CALLBACK_GRACE and self.player.isPlayingVideo():
                pos = self.player.position()
                if pos is not None and pos > 0.3:
                    self.watchdog.av_started(now)      # in case the callback never arrives
        elif self.playing_path is not None:
            path = self.player.playing_file()
            if path and path != self.playing_path:
                log('other media started playing: exit without touching it')
                self.foreign = True
                self.exit()
                return
        status = self.watchdog.check(now, self.player.position())
        if status == player_mod.FAILED:
            reason = self.watchdog.reason
            self.failures += 1
            log('camera failed: %s (%s): %s [%d in a row]' % (cam.title, cam.family, reason, self.failures))
            if self.health.failed(cam):
                log('more than half of %s failed in the last hour: skipping it for 6 hours' % cam.family)
            self.current = getattr(self, 'previous', None) if self.watchdog.t_av is None else cam
            if self.failures >= MAX_FAILURES:
                log('%d cameras failed in a row: fallback card for %d s' % (self.failures, CARD_SECONDS))
                self.failures = 0
                self.stop_ours()
                self.hide_overlay()
                self.show_card()
                self.card_until = now + CARD_SECONDS
                self.state = 'card'
            else:
                self.watchdog.stop()
                self.state = 'select'
            return
        if status == player_mod.STARTED:
            self.playing_path = self.player.playing_file() or None
            self.failures = 0
            self.state = 'playing'
            self.health.started(cam)
            self.history.add(cam.id)
            self.hide_card()
            self.fit_bars()
            self.set_visible(self.c_backdrop, False)    # the video layer is under the GUI
            self.overlay.changed(now)
            self.set_overlay(cam, now)
            if self.splash:
                self.splash.done()
            debug('first frame of %s after %.1f s' % (cam.title, now - self.last_play))
        elif status == player_mod.HEALTHY_NOW:
            self.health.healthy(cam)
        if self.state == 'playing' and now - self.watchdog.t_av < 10:
            self.fit_bars()          # the aspect can settle a moment after the first frame
        if self.state == 'playing' and self.dwell and now - self.watchdog.t_av >= self.dwell:
            self.state = 'select'

    def fit_bars(self):
        """Size the black bars to the strips the picture doesn't cover. Kodi fits the video to
        the real display keeping its aspect, while the 1920x1080 GUI grid is stretched over the
        display, so the bars are worked out in display proportions."""
        try:
            aspect = float(xbmc.getInfoLabel('VideoPlayer.VideoAspect') or 0)
        except ValueError:
            aspect = 0.0
        try:
            screen = float(xbmc.getInfoLabel('System.ScreenWidth')) / float(xbmc.getInfoLabel('System.ScreenHeight'))
        except (ValueError, ZeroDivisionError):
            screen = 16 / 9.0
        key = (round(aspect, 3), round(screen, 3))
        if key == self.bars_aspect:
            return
        self.bars_aspect = key
        a, b = self.c_bars
        if aspect and aspect < screen * 0.99:          # narrower picture: bars left and right
            bar = int(1920 * (1 - aspect / screen) / 2) + 2
            a.setPosition(-2, -2)
            b.setPosition(1920 - bar, -2)
            for c in (a, b):
                c.setWidth(bar + 2)
                c.setHeight(1084)
        elif aspect > screen * 1.01:                   # wider picture: bars top and bottom
            bar = int(1080 * (1 - screen / aspect) / 2) + 2
            a.setPosition(-2, -2)
            b.setPosition(-2, 1080 - bar)
            for c in (a, b):
                c.setWidth(1924)
                c.setHeight(bar + 2)
        else:
            for c in (a, b):
                c.setPosition(-10, -10)
                c.setWidth(1)
                c.setHeight(1)

    # ------------------------------------------------------------ overlay and card

    def set_overlay(self, cam, now):
        t = overlay_mod.texts(cam, now, self.catalog.sources, self.settings.get('local_time', True),
                              self.twenty_four, self.translate)
        self.c_title.setLabel(t['title'])
        self.c_place.setLabel(t['place'])
        self.c_detail.setLabel(t['detail'])
        self.overlay_label_time = now
        dx, dy = self.overlay.offset
        self.c_overlay.setPosition(dx, dy)
        cx, cy = self.clock_home
        self.c_clock.setPosition(cx + dx, cy - dy)

    def update_overlay(self, now):
        if self.state not in ('starting', 'playing') or self.current is None:
            return
        if self.state == 'playing':
            if self.overlay.tick(now) or now - getattr(self, 'overlay_label_time', 0) >= 30:
                self.set_overlay(self.current, now)    # move (burn-in) and refresh the local time
            visible = self.overlay.visible(now)
        else:
            visible = False
        self.set_visible(self.c_overlay, visible)
        self.set_visible(self.c_clock, bool(self.settings.get('clock')) and self.state == 'playing')

    def set_visible(self, control, visible):
        if self.shown.get(control) != visible:
            self.shown[control] = visible
            control.setVisible(visible)

    def hide_overlay(self):
        self.overlay.hide()
        self.set_visible(self.c_overlay, False)
        self.set_visible(self.c_clock, False)

    def show_card(self, message=None, background=True):
        if message is None:
            message = self.translate(32000, 'Live cams unavailable')
        self.c_message.setLabel(message)
        self.set_visible(self.c_card_bg, background)
        self.set_visible(self.c_card, True)
        if self.splash:
            self.splash.done()

    def hide_card(self):
        self.set_visible(self.c_card, False)
        self.set_visible(self.c_card_bg, False)

    def update_card(self, now):
        if not self.shown.get(self.c_card):
            return
        dx, dy = self.overlay.card_position(now)
        x, y = self.card_home
        if (x + dx, y + dy) != self.c_card.getPosition():
            self.c_card.setPosition(x + dx, y + dy)


def run_session(preview=False):
    restore_mute()
    if session_alive():
        log('a session is already running')
        return
    mode = 'clock' if xbmc.Player().isPlaying() else 'cams'
    if mode == 'clock':
        log("the user's own media is loaded: clock only, no camera")
    Session(mode, preview).run()


def run_clock():
    """The screensaver while the user's own media is loaded (paused): clock only."""
    restore_mute()
    Session('clock').run()
