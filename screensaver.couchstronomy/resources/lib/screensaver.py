"""The screensaver window: Kodi controls, timing and threads.

Three threads besides Kodi's:
  render  - owns the scene Model: computes the sky for a moment just ahead, draws the
            star layer (full resolution), the Milky Way and ground layer and the sky-colour
            layer to PNG files, places labels, and posts all of it to the engine.
  engine  - owns the Kodi controls: swaps posted images in (double-buffered, so there is
            never a gap while Kodi loads one), moves satellites once a tick with a slide
            animation that Kodi plays at the display frame rate, and keeps the clock,
            labels, spotlight and status line current. It never does heavy work.
  orbits  - downloads orbital elements when they are due and keeps the satellite
            keyframes ahead of the clock (satellites.py).

Time always comes from the system clock at the moment of drawing, never from when the
screensaver started, so after a suspend the sky is simply recomputed for the new time.
"""

import os
import re
import shutil
import threading
import time

import xbmc
import xbmcaddon
import xbmcgui
import xbmcvfs

from . import astro, camera, config, draw, satellites, scene, skylayer

ADDON_ID = config.ADDON_ID
W, H = 1920, 1080              # skin coordinates (1080i)
MAX_LABELS = 70
MAX_SATS = 30
MAX_TWINKLES = 10
SAT_PX = 18
SPOT_PX = 84
SIDEREAL_RATE = 7.2921159e-5   # rad/s
LABEL_COLOURS = {'star': 'D8E4F0FF', 'planet': 'F0FFE2A0', 'moon': 'E8F0F0F0', 'sun': 'F0FFE6AA',
                 'dso': 'C0A0D0B0', 'const': '9078A0E0', 'compass': 'D0F0C080', 'sat': 'D0B8F0D0'}
BACKGROUND_SECONDS = 30.0      # sky colour refresh while the Sun or Moon affects it


def log(message, level=xbmc.LOGINFO):
    xbmc.log('[%s] %s' % (ADDON_ID, message), level)


def profile_dir():
    addon = xbmcaddon.Addon(ADDON_ID)
    path = xbmcvfs.translatePath(addon.getAddonInfo('profile'))
    if not os.path.isdir(path):
        os.makedirs(path)
    return path


def read_settings(addon):
    try:
        st = addon.getSettings()   # Kodi 20+
        getters = {'boolean': st.getBool, 'integer': st.getInt, 'number': st.getNumber,
                   'string': st.getString, 'list': st.getIntList}
    except AttributeError:
        getters = {'boolean': addon.getSettingBool, 'integer': addon.getSettingInt,
                   'number': addon.getSettingNumber, 'string': addon.getSettingString,
                   'list': lambda sid: [v for v in re.split(r'[,|]', addon.getSetting(sid)) if v.strip()]}
    return config.read(getters)


def clear_cache():
    path = profile_dir()
    for name in ('cache', 'frames'):
        shutil.rmtree(os.path.join(path, name), ignore_errors=True)
    xbmcgui.Dialog().notification('Couchstronomy', 'Downloaded data deleted', xbmcgui.NOTIFICATION_INFO, 4000)


def update_satellites():
    """Settings action: download every selected group now."""
    addon = xbmcaddon.Addon(ADDON_ID)
    s = read_settings(addon)
    store = satellites.ElementStore(os.path.join(profile_dir(), 'cache'))
    groups = [config.SAT_GROUPS[i][1] for i in s['sat_groups']]
    errors = []
    for g in groups:
        try:
            store.download(g)
        except Exception as error:
            errors.append(str(error))
    count = len(store.load(groups))
    if errors:
        xbmcgui.Dialog().notification('Couchstronomy', 'Some downloads failed: %s' % errors[0][:80],
                                      xbmcgui.NOTIFICATION_WARNING, 6000)
    else:
        xbmcgui.Dialog().notification('Couchstronomy', 'Orbital elements for %d satellites' % count,
                                      xbmcgui.NOTIFICATION_INFO, 4000)


def anim_slide(dx, dy, ms):
    return ('conditional', 'effect=slide start=%d,%d end=0,0 time=%d condition=true' % (dx, dy, ms))


def anim_fade(start, end, ms):
    return ('conditional', 'effect=fade start=%d end=%d time=%d condition=true' % (start, end, ms))


def fmt_age(days):
    if days is None:
        return '?'
    hours = days * 24.0
    if hours < 1.5:
        return '%d min' % max(1, round(hours * 60))
    if hours < 48:
        return '%.0f h' % hours
    return '%.0f days' % days


def _process_cpu():
    """CPU seconds used by this process (Kodi), or None where unavailable."""
    try:
        return time.process_time()
    except Exception:
        return None


class ExitMonitor(xbmc.Monitor):
    def __init__(self, app):
        xbmc.Monitor.__init__(self)
        self.app = app

    def onScreensaverDeactivated(self):
        log('screensaver deactivated by Kodi')
        self.app.exit()

    def onNotification(self, sender, method, data):
        if method in ('System.OnWake', 'System.OnQuit'):
            log('notification %s' % method)
            if method == 'System.OnWake':
                self.app.on_wake()
            else:
                self.app.exit()


class SaverWindow(xbmcgui.WindowXMLDialog):
    def __init__(self, *args, **kwargs):
        self.app = kwargs['app']
        self.built = False

    def onInit(self):
        if not self.built:
            self.built = True
            self.app.attach(self)

    def onAction(self, action):
        log('action %d closes the screensaver' % action.getId())
        self.app.exit()


class Posted(object):
    """What the render thread hands the engine."""

    def __init__(self):
        self.stars = self.mw = self.bg = None
        self.labels = []
        self.spotlight = []
        self.twinkles = []
        self.limit = 6.0
        self.sun_alt = -90.0
        self.render_ms = 0.0
        self.points = 0


class Screensaver(object):
    def __init__(self):
        self.addon = xbmcaddon.Addon(ADDON_ID)
        self.path = self.addon.getAddonInfo('path')
        self.media = os.path.join(self.path, 'resources', 'media')
        self.data = os.path.join(self.path, 'resources', 'data')
        self.profile = profile_dir()
        self.frames = os.path.join(self.profile, 'frames')
        shutil.rmtree(self.frames, ignore_errors=True)
        os.makedirs(self.frames)
        self.s = s = read_settings(self.addon)
        self.is_android = xbmc.getCondVisibility('System.Platform.Android')
        self.rw, self.rh = (1920, 1080) if s['quality'] == 0 else (1280, 720)
        self.k = W / float(self.rw)                   # render pixels -> skin pixels
        self.view = scene.View(s, self.rw, self.rh)
        self.cam = self.view.camera
        log('%s at %.4f, %.4f; %s' % (s['place'], s['lat'], s['lon'], self.cam.describe()))
        self.stop = threading.Event()
        self.wake_render = threading.Event()
        self.wake_orbits = threading.Event()
        self.lock = threading.Lock()
        self.monitor = ExitMonitor(self)
        self.window = None
        self.threads = []
        self.posted = None
        self.counter = 0
        # Kodi caches textures by path: names must never repeat, even across runs.
        self.session = '%x' % int(time.time() * 1000)
        self.sats_on = s['show_satellites'] and self.view.time_speed == 1 and bool(s['sat_groups'])
        self.tracker = None
        self.sat_status = ''
        self.store = satellites.ElementStore(os.path.join(self.profile, 'cache'))
        self.observer = satellites.Observer(self.view.lat, self.view.lon, self.view.elevation)

    # ------------------------------------------------------------ lifecycle

    def run(self):
        self.window = SaverWindow('screensaver-couchstronomy.xml', self.path, 'Default', '1080i', app=self)
        try:
            self.window.doModal()
        finally:
            self.stop.set()
            self.wake_render.set()
            self.wake_orbits.set()
            for t in self.threads:
                t.join(2.0)
            shutil.rmtree(self.frames, ignore_errors=True)
            del self.window
            del self.monitor

    def attach(self, window):
        self.build_controls(window)
        targets = [(self.render_loop, 'couch-render'), (self.engine_loop, 'couch-engine')]
        if self.sats_on:
            targets.append((self.orbits_loop, 'couch-orbits'))
        for target, name in targets:
            t = threading.Thread(target=target, name=name)
            t.daemon = True
            t.start()
            self.threads.append(t)

    def exit(self):
        if not self.stop.is_set():
            self.stop.set()
            self.wake_render.set()
            self.wake_orbits.set()
            if self.window:
                self.window.close()

    def stopped(self):
        return self.stop.is_set() or self.monitor.abortRequested()

    def on_wake(self):
        """Back from suspend: redraw for the real time now and refresh satellite data."""
        if self.tracker is not None:
            self.tracker.window = None
        self.wake_render.set()
        self.wake_orbits.set()

    # ------------------------------------------------------------ controls

    def media_path(self, name):
        return os.path.join(self.media, name)

    def image(self, x, y, w, h, name='', diffuse=None):
        path = self.media_path(name) if name else ''
        if diffuse:
            return xbmcgui.ControlImage(x, y, w, h, path, aspectRatio=0, colorDiffuse=diffuse)
        return xbmcgui.ControlImage(x, y, w, h, path, aspectRatio=0)

    def label(self, x, y, w, h, text='', font='font10', color='FFFFFFFF', align=0):
        return xbmcgui.ControlLabel(x, y, w, h, text, font=font, textColor=color, alignment=align)

    def build_controls(self, window):
        s = self.s
        full = lambda: xbmcgui.ControlImage(0, 0, W, H, '', aspectRatio=0)  # noqa: E731
        self.bg = [full(), full()]
        self.mw = [full(), full()]
        self.st = [full(), full()]
        self.front = {'bg': 0, 'mw': 0, 'st': 0}
        self.shown = {'bg': None, 'mw': None, 'st': None}
        self.hide_later = []
        self.twinkle_controls = [self.image(0, 0, 8, 8, 'glow.png', 'A0FFFFFF') for _ in range(MAX_TWINKLES if s['twinkle'] else 0)]
        self.twinkle_state = [None] * len(self.twinkle_controls)
        n = MAX_SATS if self.sats_on else 0
        self.sat_dots = [self.image(0, 0, SAT_PX, SAT_PX, 'dot.png', 'FFFFFFFF') for _ in range(n)]
        self.sat_labels = [self.label(0, 0, 360, 30, font='font10', color=LABEL_COLOURS['sat']) for _ in range(n)]
        self.sat_slot = {}            # satellite number -> control index
        self.sat_pos = [None] * n     # (x, y) the dot is drawn at now
        self.sky_labels = [self.label(0, 0, 400, 30, font='font10') for _ in range(MAX_LABELS)]
        self.sky_label_state = [None] * MAX_LABELS
        self.reticle = self.image(0, 0, SPOT_PX, SPOT_PX, 'reticle.png', 'C0FFE0A0')
        self.card = self.image(40, H - 250, 620, 200, 'white.png', 'A0050810')
        self.card_title = self.label(64, H - 236, 580, 40, font='font13', color='FFFFE6B0')
        self.card_lines = [self.label(64, H - 192 + 34 * i, 580, 30, font='font10', color='D8E0E8F0') for i in range(4)]
        self.clock = self.label(48, 36, 600, 50, font='font13', color='C8E8ECF4')
        self.date = self.label(48, 80, 600, 34, font='font10', color='90C8D0DC')
        self.compass = self.label(48, H - 52, 760, 32, font='font10', color='A0D8D0B0')
        self.status = self.label(W - 1140, H - 52, 1100, 32, font='font10', color='90B8C4D4', align=1)
        self.perf = self.label(W - 1240, 36, 1200, 30, font='font10', color='C0A0FFA0', align=1)
        self.loading = self.label(0, H // 2 - 20, W, 40, 'Calculating the sky…', font='font13',
                                  color='A0FFFFFF', align=2)
        dim = int(s['dim'] * 255 / 100)
        self.dimmer = self.image(-50, -50, W + 100, H + 100, 'white.png', '%02X000000' % dim)
        controls = self.bg + self.mw + self.st + self.twinkle_controls + self.sat_dots + self.sat_labels
        controls += self.sky_labels + [self.reticle, self.card, self.card_title] + self.card_lines
        controls += [self.clock, self.date, self.compass, self.status, self.perf, self.loading, self.dimmer]
        window.addControls(controls)
        hidden = self.bg + self.mw + self.st + self.twinkle_controls + self.sat_dots + self.sat_labels
        hidden += self.sky_labels + [self.reticle, self.card, self.card_title] + self.card_lines
        if not s['show_clock']:
            hidden += [self.clock, self.date]
        if not s['show_compass']:
            hidden.append(self.compass)
        if not s['show_status']:
            hidden.append(self.status)
        if not s['show_perf']:
            hidden.append(self.perf)
        if dim == 0:
            hidden.append(self.dimmer)
        for c in hidden:
            c.setVisible(False)
        self.text = {}
        self.compass.setLabel(self.compass_text())
        self.spot_index = -1
        self.spot_key = None
        self.spot_until = 0.0

    def set_text(self, control, text):
        if self.text.get(id(control)) != text:
            self.text[id(control)] = text
            control.setLabel(text)

    def compass_text(self):
        c = self.cam
        tilt = 'level' if abs(c.tilt) < 0.5 else ('%.0f° %s' % (abs(c.tilt), 'up' if c.tilt > 0 else 'down'))
        return 'Facing %s (%.0f°)  ·  %s  ·  %.0f° × %.0f° field' % (camera.compass_name(c.azimuth), c.azimuth,
                                                                   tilt, c.hfov, c.vfov)

    # ------------------------------------------------------------ render thread

    def render_loop(self):
        try:
            self._render_loop()
        except Exception:
            import traceback
            log('render thread failed:\n%s' % traceback.format_exc(), xbmc.LOGERROR)

    def frame_path(self, layer):
        self.counter += 1
        prefix = '%s-%s-' % (layer, self.session)
        for name in os.listdir(self.frames):
            if name.startswith(prefix):
                try:
                    if int(name[len(prefix):-4]) < self.counter - 6:
                        os.remove(os.path.join(self.frames, name))
                except (ValueError, OSError):
                    pass
        return os.path.join(self.frames, '%s%d.png' % (prefix, self.counter))

    def write(self, layer, data):
        path = self.frame_path(layer)
        with open(path + '.tmp', 'wb') as handle:
            handle.write(data)
        os.replace(path + '.tmp', path)
        return path

    def _render_loop(self):
        s, view, cam = self.s, self.view, self.cam
        started = time.time()
        model = scene.Model(view)
        look = draw.Appearance(view.enhance, s['star_brightness'] / 100.0, scale=self.rw / 1920.0 * 0.5 + 0.5)
        layer = draw.StarLayer(self.rw, self.rh, look)
        moon_tex = draw.MoonTexture(os.path.join(self.data, 'moon.bin'))
        mw_w, mw_h = (480, 270) if not self.is_android else (384, 216)
        mw = skylayer.MilkyWay(cam, view.lat, s['horizon'], s['extinction'], mw_w, mw_h)
        bg = skylayer.Background(cam, *((256, 144) if not self.is_android else (192, 108)))
        log('ready in %.1f s (%d stars in the catalogue)' % (time.time() - started, model.stars.count))
        # How long until the sky moves half a pixel at the centre of the screen.
        px_per_s = cam.f * SIDEREAL_RATE * view.time_speed
        fixed = config.UPDATE_SECONDS[s['update']]
        interval = fixed or max(0.3 if view.time_speed > 1 else 1.0, min(10.0, 0.5 / px_per_s))
        mw_interval = max(2.0 if view.time_speed > 1 else 4.0,
                          min(60.0, 0.5 / (mw_w / float(self.rw) * px_per_s)))
        log('star layer every %.1f s, Milky Way every %.1f s' % (interval, mw_interval))
        last_mw = last_bg = -1e9
        bg_key = None
        render_ema = 0.3
        minute = {'start': time.time(), 'frames': 0, 'secs': 0.0, 'cpu': _process_cpu()}
        show_icons = s['labels'] == config.EXPLORER
        avoid = []
        if s['show_clock']:
            avoid.append((0, 0, 700 / self.k, 130 / self.k))
        avoid.append((0, (H - 70) / self.k, self.rw, self.rh))
        while not self.stopped():
            t_start = time.time()
            when = view.sky_time(t_start + render_ema)
            sc = model.build(when)
            raw = layer.render(sc, moon_tex, show_icons)
            post = Posted()
            post.stars = self.write('st', draw.encode_png(self.rw, self.rh, bytes(raw)))
            light = skylayer.SkyLight(sc.sun_alt, sc.sun_hor, sc.moon_alt, sc.moon_hor, sc.moon_illum,
                                      view.light_pollution, view.keep_dark)
            now = time.time()
            if now - last_mw >= mw_interval:
                gain = sc.mw_visibility * s['mw_brightness'] / 100.0 * 0.55
                post.mw = self.write('mw', mw.render(sc.frame.lst, gain, light.ground(), s['milky_way']))
                last_mw = now
            # The sky's colour changes only while the Sun or Moon is near or above the horizon.
            lit = (sc.sun_alt > -20 and not view.keep_dark) or sc.moon_alt > -3 or view.time_speed > 1
            key = 'lit' if lit else 'night'
            if bg_key != key or (lit and now - last_bg >= BACKGROUND_SECONDS / view.time_speed ** 0.5):
                post.bg = self.write('bg', bg.render(light))
                last_bg, bg_key = now, key
            if view.labels != config.NATURAL:
                post.labels = [(lab.text, lab.placed, lab.style) for lab in
                               scene.place_labels(sc.labels, self.rw, self.rh, avoid=avoid)]
            post.spotlight = sc.spotlight
            if s['twinkle']:
                bright = sorted((p for p in sc.points if p.mag < 1.2 and 0 <= p.x < self.rw and 0 <= p.y < self.rh),
                                key=lambda p: p.mag)[:MAX_TWINKLES]
                post.twinkles = [(p.x, p.y, p.mag, p.rgb) for p in bright]
            post.limit, post.sun_alt = sc.limit, sc.sun_alt
            post.points = len(sc.points)
            secs = time.time() - t_start
            render_ema = 0.7 * render_ema + 0.3 * secs
            minute['frames'] += 1
            minute['secs'] += secs
            if time.time() - minute['start'] >= 60.0:
                cpu = _process_cpu()
                wall = time.time() - minute['start']
                share = '' if cpu is None or minute['cpu'] is None else \
                    ', Kodi process %.0f%% of a core' % (100.0 * (cpu - minute['cpu']) / wall)
                log('last minute: %d star frames, %.0f ms each, %d objects%s' % (
                    minute['frames'], 1000.0 * minute['secs'] / minute['frames'], len(sc.points), share))
                minute = {'start': time.time(), 'frames': 0, 'secs': 0.0, 'cpu': cpu}
            post.render_ms = secs * 1000.0
            with self.lock:
                self.posted = post
            self.wake_render.wait(max(0.05, interval - secs))
            self.wake_render.clear()

    # ------------------------------------------------------------ orbits thread

    def orbits_loop(self):
        try:
            self._orbits_loop()
        except Exception:
            import traceback
            log('orbits thread failed:\n%s' % traceback.format_exc(), xbmc.LOGERROR)

    def _orbits_loop(self):
        s, view = self.s, self.view
        groups = [config.SAT_GROUPS[i][1] for i in s['sat_groups']]
        refresh = config.SAT_REFRESH_HOURS[s['sat_refresh']] * 3600.0
        max_age = config.SAT_MAX_AGE_DAYS[s['sat_max_age']]
        retry_at = 0.0
        loaded_stamp = None
        while not self.stopped():
            now = time.time()
            # Downloads: when due and allowed; failures keep the cached data and retry later.
            if s['auto_update'] and now >= retry_at:
                for g in groups:
                    fetched = self.store.fetched(g)
                    if fetched is None or now - fetched > refresh:
                        try:
                            self.store.download(g)
                            log('downloaded orbital elements: %s' % g)
                        except Exception as error:
                            log('orbital elements %s: %s' % (g, error), xbmc.LOGWARNING)
                            retry_at = now + 1800.0
                        if self.stopped():
                            return
            stamp = tuple(self.store.fetched(g) for g in groups)
            if stamp != loaded_stamp:
                sats = self.store.load(groups)
                self.tracker = satellites.Tracker(sats, self.observer, max_age) if sats else None
                loaded_stamp = stamp
                if self.tracker:
                    log('tracking %d satellites (%d with stale elements hidden)' %
                        (len(self.tracker.sats), self.tracker.stale))
            tr = self.tracker
            if tr is None:
                self.sat_status = 'Satellites: no orbital data yet' if s['auto_update'] else \
                    'Satellites: no orbital data (automatic downloads are off)'
            else:
                t = view.sky_time(time.time())
                if tr.window is None or t > tr.window[1] - tr.step / 3.0 or t < tr.window[0]:
                    tr.select(t)
                    tr.build(t - 1.0, stop=self.stopped)
                if not tr.sats:
                    self.sat_status = 'Satellites hidden: orbital data older than %d days' % max_age
                else:
                    self.sat_status = 'Satellite positions predicted from orbital data %s old' % fmt_age(tr.newest_days)
            self.wake_orbits.wait(1.0)
            self.wake_orbits.clear()

    # ------------------------------------------------------------ engine thread

    def engine_loop(self):
        try:
            self._engine_loop()
        except Exception:
            import traceback
            log('engine thread failed:\n%s' % traceback.format_exc(), xbmc.LOGERROR)

    def _engine_loop(self):
        rate = config.SAT_RATES[self.s['sat_rate']] if self.sats_on else 1
        tick = 1.0 / rate
        last = time.time()
        self.current = None
        self.fps_note = ''
        next_tick = time.time()
        while not self.stopped():
            now = time.time()
            if now - last > 5.0:
                log('clock jumped %.0f s (suspend?); recalculating' % (now - last))
                self.on_wake()
            last = now
            for c in self.hide_later:
                c.setVisible(False)
            self.hide_later = []
            with self.lock:
                post, self.posted = self.posted, None
            if post is not None:
                self.show(post)
            if self.current is not None:
                if self.sats_on:
                    self.update_satellites(now, tick)
                self.update_spotlight(now)
            self.update_hud(now)
            next_tick += tick
            delay = next_tick - time.time()
            if delay < -1.0:
                next_tick = time.time() + tick
                delay = tick
            if delay > 0:
                self.stop.wait(delay)

    def swap(self, name, controls, path, fade_ms=0):
        b = 1 - self.front[name]
        if fade_ms and self.shown[name] is not None:
            # Buffer 1 is drawn above buffer 0: fade 1 in, or put 0 behind and fade 1 out.
            if self.front[name] == 0:
                controls[1].setImage(path, False)
                controls[1].setVisible(True)
                controls[1].setAnimations([anim_fade(0, 100, fade_ms)])
                self.front[name] = 1
            else:
                controls[0].setImage(path, False)
                controls[1].setAnimations([anim_fade(100, 0, fade_ms)])
                self.front[name] = 0
            self.shown[name] = path
            return
        controls[b].setAnimations([])
        controls[b].setImage(path, False)
        controls[b].setVisible(True)
        if self.shown[name] is not None:
            self.hide_later.append(controls[1 - b])
        self.front[name] = b
        self.shown[name] = path

    def show(self, post):
        first = self.current is None
        if post.bg:
            self.swap('bg', self.bg, post.bg, 0 if first else 3000)
        if post.mw:
            self.swap('mw', self.mw, post.mw, 0 if first else 1500)
        if post.stars:
            self.swap('st', self.st, post.stars)
        if first:
            self.loading.setVisible(False)
        self.current = post
        self.place_sky_labels(post.labels)
        self.place_twinkles(post.twinkles)
        self.fps_note = 'frame %.0f ms  ·  %d objects drawn  ·  limiting magnitude %.1f' % (
            post.render_ms, post.points, post.limit)

    def place_sky_labels(self, labels):
        k = self.k
        for i, ctrl in enumerate(self.sky_labels):
            if i < len(labels):
                text, (x, y, w, h), style = labels[i]
                state = (text, int(x * k), int(y * k), style)
                if self.sky_label_state[i] != state:
                    if self.sky_label_state[i] is None or self.sky_label_state[i][0] != text or \
                            self.sky_label_state[i][3] != style:
                        ctrl.setLabel(text, font='font10', textColor=LABEL_COLOURS.get(style, 'D0FFFFFF'))
                    ctrl.setPosition(state[1], state[2])
                    if self.sky_label_state[i] is None:
                        ctrl.setVisible(True)
                    self.sky_label_state[i] = state
            elif self.sky_label_state[i] is not None:
                ctrl.setVisible(False)
                self.sky_label_state[i] = None

    def place_twinkles(self, twinkles):
        k = self.k
        for i, ctrl in enumerate(self.twinkle_controls):
            if i < len(twinkles):
                x, y, mag, rgb = twinkles[i]
                size = int((44 + 10 * (1.2 - mag)) * k ** 0.5)
                ctrl.setPosition(int(x * k - size / 2), int(y * k - size / 2))
                ctrl.setWidth(size)
                ctrl.setHeight(size)
                key = (i, rgb)
                if self.twinkle_state[i] != key:
                    ctrl.setColorDiffuse('90%02X%02X%02X' % rgb)
                    period = 600 + (i * 211) % 700
                    ctrl.setAnimations([('conditional', 'effect=fade start=100 end=35 time=%d '
                                         'tween=sine pulse=true condition=true' % period)])
                    ctrl.setVisible(True)
                    self.twinkle_state[i] = key
            elif self.twinkle_state[i] is not None:
                ctrl.setVisible(False)
                self.twinkle_state[i] = None

    # ------------------------------------------------------------ satellites

    def update_satellites(self, now, tick):
        tr = self.tracker
        view, cam, k = self.view, self.cam, self.k
        fixes = tr.fixes(view.sky_time(now + tick), shadowed=self.s['sat_shadowed']) if tr else []
        limit = self.current.limit if self.current else 6.0
        shown = []
        for f in fixes:
            if f.lit:
                if view.realistic and (f.mag > min(limit + 0.5, 6.0) or self.current.sun_alt > -3):
                    continue
                if not view.realistic and f.mag > 7.5:
                    continue
            hor = astro.refract_enu(f.hor) if view.refraction else f.hor
            p = cam.project(hor)
            if p is None or not cam.on_screen(p, margin=10):
                continue
            shown.append((f, p[0] * k, p[1] * k))
        shown.sort(key=lambda item: item[0].mag)
        shown = shown[:MAX_SATS]
        wanted = set(item[0].sat.number for item in shown)
        for num in list(self.sat_slot):
            if num not in wanted:
                i = self.sat_slot.pop(num)
                self.sat_dots[i].setVisible(False)
                self.sat_labels[i].setVisible(False)
                self.sat_pos[i] = None
        free = [i for i in range(len(self.sat_dots)) if i not in self.sat_slot.values()]
        ms = int(tick * 1000)
        labels_on = self.s['satellite_labels'] and view.labels != config.NATURAL
        explorer = view.labels == config.EXPLORER
        for f, x, y in shown:
            num = f.sat.number
            if num not in self.sat_slot:
                if not free:
                    continue
                self.sat_slot[num] = free.pop(0)
            i = self.sat_slot[num]
            dot, lab = self.sat_dots[i], self.sat_labels[i]
            if f.lit:
                size = int(max(9, min(26, 13 + (3.0 - f.mag) * 2.6)))
                alpha = int(255 * max(0.35, min(1.0, 0.55 + (4.0 - f.mag) * 0.15)))
                colour = '%02XFFFFF4' % alpha
            else:
                size, colour = 8, '60FF7060'
            half = size // 2
            nx, ny = int(x) - half, int(y) - half
            old = self.sat_pos[i]
            dot.setWidth(size)
            dot.setHeight(size)
            dot.setColorDiffuse(colour)
            dot.setPosition(nx, ny)
            text = ''
            if labels_on:
                name = f.sat.short_name()
                if explorer:
                    text = '%s  %s' % (name, ('mag %.1f' % f.mag) if f.lit else 'in shadow')
                elif f.sat.number in satellites.STD_MAG or f.mag < 2.0:
                    text = name
            if old is not None and abs(old[0] - nx) < 400 and abs(old[1] - ny) < 400:
                slide = [anim_slide(old[0] - nx, old[1] - ny, ms)]
                dot.setAnimations(slide)
                lab.setAnimations(slide)
            else:
                dot.setAnimations([anim_fade(0, 100, 400)])
                lab.setAnimations([anim_fade(0, 100, 400)])
                dot.setVisible(True)
            self.sat_pos[i] = (nx, ny)
            if text:
                lab.setPosition(nx + size + 6, ny + half - 15)
                self.set_text(lab, text)
                lab.setVisible(True)
            else:
                lab.setVisible(False)

    # ------------------------------------------------------------ spotlight and HUD

    def update_spotlight(self, now):
        if not (self.s['spotlight'] and self.view.labels == config.EXPLORER):
            return
        cands = self.current.spotlight
        if not cands:
            self.hide_spotlight()
            return
        k = self.k
        current = None
        if self.spot_key is not None:
            for c in cands:
                if (c[0], c[1]) == self.spot_key:
                    current = c
        if current is None or now >= self.spot_until:
            order = sorted(cands, key=lambda c: ({'moon': 0, 'planet': 1, 'sun': 2, 'dso': 3, 'star': 4}[c[0]], str(c[1])))
            self.spot_index = (self.spot_index + 1) % len(order)
            current = order[self.spot_index]
            self.spot_key = (current[0], current[1])
            self.spot_until = now + 30.0
            title, lines = current[4], current[5]
            x = current[2] * k
            cx = 40 if x > W / 2 else W - 660
            self.card.setPosition(cx, H - 270)
            self.card_title.setPosition(cx + 24, H - 256)
            for i, lab in enumerate(self.card_lines):
                lab.setPosition(cx + 24, H - 212 + 34 * i)
                self.set_text(lab, lines[i] if i < len(lines) else '')
                lab.setVisible(i < len(lines))
            self.set_text(self.card_title, title)
            for c in [self.card, self.card_title, self.reticle]:
                c.setAnimations([anim_fade(0, 100, 800)])
                c.setVisible(True)
        self.reticle.setPosition(int(current[2] * k - SPOT_PX / 2), int(current[3] * k - SPOT_PX / 2))

    def hide_spotlight(self):
        for c in [self.card, self.card_title, self.reticle] + self.card_lines:
            c.setVisible(False)
        self.spot_key = None

    def update_hud(self, now):
        s = self.s
        if s['show_clock']:
            self.set_text(self.clock, xbmc.getInfoLabel('System.Time'))
            place = (s['place'] + '  ·  ') if s['place'] else ''
            self.set_text(self.date, place + xbmc.getInfoLabel('System.Date'))
        if s['show_status']:
            bits = []
            v = self.view
            if not v.realistic:
                bits.append('Enhanced view')
            if v.time_speed > 1:
                bits.append('Time-lapse %d×' % v.time_speed)
            if v.time_offset:
                bits.append('Time shifted %+d h' % round(v.time_offset / 3600.0))
            if v.time_speed > 1 or v.time_offset:
                bits.append(time.strftime('%Y-%m-%d %H:%M', time.localtime(v.sky_time(now))))
            if self.sats_on and self.sat_status:
                bits.append(self.sat_status)
            self.set_text(self.status, '  ·  '.join(bits))
        if s['show_perf']:
            self.set_text(self.perf, 'Kodi %s fps  ·  %s' % (xbmc.getInfoLabel('System.FPS'), self.fps_note))


def run():
    Screensaver().run()
