"""The screensaver window: Kodi controls, timing and threads.

Three kinds of thread:
  render  - owns the World and the Renderer: loads data, builds lookup tables, renders
            frames (slow, pure Python). Posts finished scenes and frames to the engine.
  engine  - owns the Kodi controls: shows frames, moves the map and the markers, runs the
            clock and the cycling timer. Never does heavy work, so motion stays regular.
  fetch   - downloads into the disk cache (workers.py), then pokes the render thread.

Smooth motion comes from Kodi itself: the engine moves controls once a TICK and gives each
a slide animation from where it is drawn now, which Kodi plays at the display frame rate.
Spinning views (globe, rotating central meridian) are re-rendered frames, cross-faded.
"""

import math
import os
import random
import re
import shutil
import threading
import time

import xbmc
import xbmcaddon
import xbmcgui
import xbmcvfs

from . import config, flights, motion, overlays, projections, render, reproject, sources, splash
from . import world as world_mod
from .workers import Workers

ADDON_ID = config.ADDON_ID
W, H = 1920, 1080
TICK = 1.0                  # seconds between motion updates; Kodi animates in between
COMPOSITE_SECONDS = 120.0   # how often a still view is re-rendered for the moving terminator
FADE_MS = 900               # scene transitions
MAX_COPIES = 3              # side-by-side copies of a wrapping cylindrical map
LAYERS = ('base', 'temp', 'clouds', 'precip', 'fires', 'lightning', 'events', 'events2')
# The two phases of the event symbols pulse in opposite directions, so they alternate:
# quake rings throb, volcanoes glow, ASCII hazards flash. A full cycle lasts one TICK, so
# restarting the pulse with every tick's slide is seamless.
PULSE = {'events': (100, 12), 'events2': (12, 100)}
PULSE_MS = 500   # each way: start -> end -> start takes one TICK
ISS_PX = 44
MAX_STORMS = 12
PARTICLE_PX = 9
STORM_PX = 56
FLIGHT_PX = 28             # rotated plane images are padded so wingtips survive the turn
FLIGHT_STATIC_SECONDS = 15.0   # a still map: aircraft barely move a pixel in this time
FLIGHT_MAX_AGE = 5400.0    # stop flying an aircraft on after this long without a report
HEADING_STEP = 5           # media/rot/plane_<heading>.png exist every 5 degrees
SPLASH_MAX_SECONDS = 60.0  # the first run of a projection builds its lookup table (15-40 s on a stick)
LEGEND_W = 420


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
        getters = {'boolean': st.getBool, 'integer': st.getInt, 'list': st.getIntList, 'string': st.getString}
    except AttributeError:
        getters = {'boolean': addon.getSettingBool, 'integer': addon.getSettingInt,
                   'string': addon.getSettingString,
                   'list': lambda sid: [v for v in re.split(r'[,|]', addon.getSetting(sid)) if v.strip()]}
    return config.read(getters)


def clear_cache():
    path = profile_dir()
    for name in ('cache', 'lut', 'frames'):
        shutil.rmtree(os.path.join(path, name), ignore_errors=True)
    xbmcgui.Dialog().notification("God's World Map", 'Downloaded data and cached projections cleared',
                                  xbmcgui.NOTIFICATION_INFO, 4000)


def anim_slide(dx, dy, ms):
    return ('conditional', 'effect=slide start=%d,%d end=0,0 time=%d condition=true' % (dx, dy, ms))


def anim_fade(start, end, ms):
    return ('conditional', 'effect=fade start=%d end=%d time=%d condition=true' % (start, end, ms))


def fmt_age(seconds):
    """Short ages ('now', '12m', '3h', '2d'): the status line lists up to nine feeds."""
    if seconds < 90:
        return 'now'
    if seconds < 5400:
        return '%dm' % (seconds // 60)
    if seconds < 2 * 86400:
        return '%dh' % (seconds // 3600)
    return '%dd' % (seconds // 86400)


class ExitMonitor(xbmc.Monitor):
    def __init__(self, on_exit):
        xbmc.Monitor.__init__(self)
        self.on_exit = on_exit

    def onScreensaverDeactivated(self):
        log('screensaver deactivated by Kodi')
        self.on_exit()


class SaverWindow(xbmcgui.WindowXMLDialog):
    def __init__(self, *args, **kwargs):
        self.app = kwargs['app']
        self.built = False

    def onInit(self):
        if not self.built:
            self.built = True
            self.app.attach(self)

    def onAction(self, action):
        log('action %d (button %d) closes the screensaver' % (action.getId(), action.getButtonCode()))
        self.app.exit()


class Shown(object):
    """A scene as the engine shows it: geometry, motion and when it started."""

    def __init__(self, scene, geo, mov, t0, style_id):
        self.scene, self.geo, self.motion, self.t0 = scene, geo, mov, t0
        self.style_id = style_id
        self.copies = 1
        if mov.mode == 'scroll':
            self.copies = min(MAX_COPIES, int(math.ceil(W / float(geo.show_w))) + 1)
        self.rotation = mov.rotation(0.0)
        self.pos = None


class Screensaver(object):
    def __init__(self):
        self.addon = xbmcaddon.Addon(ADDON_ID)
        self.path = self.addon.getAddonInfo('path')
        self.media = os.path.join(self.path, 'resources', 'media')
        self.profile = profile_dir()
        self.s = read_settings(self.addon)
        self.stop = threading.Event()
        self.wake_engine = threading.Event()
        self.wake_render = threading.Event()
        self.lock = threading.Lock()
        self.monitor = ExitMonitor(self.exit)
        self.window = None
        self.splash = None
        self.threads = []
        self.store = sources.Store(os.path.join(self.profile, 'cache'))
        self.fetcher = Workers(2, 'godsworld-fetch', lambda e: log('fetch error: %s' % e, xbmc.LOGWARNING))
        self.inflight = set()
        self.ready_feeds = set()
        self.feeds = {}
        s = self.s
        for name, on in (('clouds', s['layer_clouds']), ('precip', s['layer_precip']),
                         ('weather', s['layer_temp'] or s['layer_wind'] or s['layer_precip']),
                         ('storms', s['layer_storms']), ('quakes', s['layer_quakes']),
                         ('volcanoes', s['layer_volcanoes']), ('fires', s['layer_fires']),
                         ('lightning', s['layer_lightning']), ('iss', s['layer_iss']),
                         ('flights', s['layer_flights'])):
            if on:
                self.feeds[name] = sources.WEATHER_FEEDS[name]()
        refresh = s['refresh_minutes'] * 60.0
        for name in ('clouds', 'precip'):
            if name in self.feeds:
                self.feeds[name].refresh = refresh
        if 'flights' in self.feeds:
            self.feeds['flights'].refresh = s['flight_refresh'] * 60.0
        self.layers = set()
        for layer, key in (('clouds', 'layer_clouds'), ('precip', 'layer_precip'), ('temp', 'layer_temp'),
                           ('wind', 'layer_wind'), ('storms', 'layer_storms'), ('quakes', 'layer_quakes'),
                           ('volcanoes', 'layer_volcanoes'), ('fires', 'layer_fires'),
                           ('lightning', 'layer_lightning'), ('iss', 'layer_iss'),
                           ('flights', 'layer_flights')):
            if s[key]:
                self.layers.add(layer)
        if 'quakes' in self.feeds:
            period = sources.QUAKE_FEEDS[s['quake_feed']]
            self.feeds['quakes'].download = lambda: sources.download_quakes(period)
        self.max_age = config.MAX_AGE_HOURS[s['max_age']]
        self.is_android = xbmc.getCondVisibility('System.Platform.Android')
        q = config.QUALITY_SCALE[s['quality']]
        self.auto_quality = q is None
        self.quality = q or (0.75 if self.is_android else 1.0)
        self.min_interval = 1.0 / max(1, s['max_fps'])
        self.rng = random.Random()
        self._plan_sequences()
        # Hand-over between threads (guarded by self.lock).
        self.posted_scene = None    # (Shown, frames)
        self.posted_frame = None    # (scene key, rotation, frames, render seconds)
        self.scene_request = True   # the render thread should prepare the next scene
        self.refresh_request = False
        self.shown = None
        self.frame_seconds = 0.0
        self.frames_shown = 0
        self.fps_window = []
        self.world = None
        self.renderer = None

    # ------------------------------------------------------------ planning

    def _plan_sequences(self):
        s = self.s
        ids = projections.IDS
        order_random = s['cycle_order'] == 1
        if s['cycle_projections']:
            items = [ids[i] for i in s['projection_list']]
            start = ids[s['projection']] if ids[s['projection']] in items else None
            self.proj_seq = motion.Sequence(items, order_random, start=start)
            if start is not None and not order_random:
                self.proj_seq.pos -= 1   # begin with the selected projection
        else:
            self.proj_seq = motion.Sequence([ids[s['projection']]])
        if s['cycle_styles']:
            items = [config.STYLE_IDS[i] for i in s['style_list']]
            self.style_seq = motion.Sequence(items, order_random)
        elif s['render_mode'] == 3:
            self.style_seq = motion.Sequence(['ascii_geo', 'ascii_image'])
        else:
            mode = s['render_mode']
            style = sources.BASEMAP_IDS[s['basemap']] if mode == 0 else ('ascii_geo', 'ascii_image')[mode - 1]
            self.style_seq = motion.Sequence([style])
        self.cycling = len(self.proj_seq.items) > 1 or len(self.style_seq.items) > 1

    def next_scene_spec(self):
        s = self.s
        proj = projections.get(self.proj_seq.next())
        style_id = self.style_seq.next()
        zoom = s['zoom'] / 100.0
        if s['auto_zoom'] and s['movement'] != motion.STATIC:
            if proj.kind == 'globe':
                zoom *= self.rng.choice([0.9, 1.0, 1.1])
            elif proj.kind == 'cylindrical':
                zoom *= self.rng.choice([1.0, 1.15, 1.3])
            else:
                zoom *= self.rng.choice([1.15, 1.35, 1.6])
        if style_id in ('ascii_geo', 'ascii_image'):
            style, base = style_id, sources.BASEMAP_IDS[s['basemap']]
        else:
            style, base = render.MAP, style_id
        quality = self.quality
        if proj.kind == 'globe' and self.is_android and self.auto_quality:
            quality = min(quality, 0.5)   # re-rendered every frame: keep it small on a stick
        scene = render.Scene(proj, style, W, H, zoom, quality, float(s['tilt']), config.ascii_options(s))
        return scene, base, style_id

    def base_options(self):
        s = self.s
        return {'borders': s['borders'], 'lights': s['lights'], 'lights_brightness': s['lights_brightness'],
                'lights_night_only': s['lights_night_only'], 'daynight': s['daynight'],
                'night_darkness': s['night_darkness']}

    # ------------------------------------------------------------ lifecycle

    def run(self):
        self.window = SaverWindow('screensaver-godsworld-map.xml', self.path, 'Default', '1080i', app=self)
        try:
            self.window.doModal()
        finally:
            self.stop.set()
            if self.splash:
                self.splash.close()
            self.wake_engine.set()
            self.wake_render.set()
            for t in self.threads:
                t.join(2.0)
            self.fetcher.shutdown()
            del self.window
            del self.monitor

    def attach(self, window):
        self.build_controls(window)
        self.splash = splash.Splash(window, self.media, 'FF4FC3F7', SPLASH_MAX_SECONDS, log)
        for target, name in ((self.render_loop, 'godsworld-render'), (self.engine_loop, 'godsworld-engine')):
            t = threading.Thread(target=target, name=name)
            t.daemon = True
            t.start()
            self.threads.append(t)

    def exit(self):
        if not self.stop.is_set():
            self.stop.set()
            self.wake_engine.set()
            self.wake_render.set()
            if self.window:
                self.window.close()

    def stopped(self):
        return self.stop.is_set() or self.monitor.abortRequested()

    # ------------------------------------------------------------ controls

    def media_path(self, name):
        return os.path.join(self.media, name)

    def image(self, x, y, w, h, name='', diffuse=None):
        path = self.media_path(name) if name else ''
        if diffuse:
            return xbmcgui.ControlImage(x, y, w, h, path, aspectRatio=0, colorDiffuse=diffuse)
        return xbmcgui.ControlImage(x, y, w, h, path, aspectRatio=0)

    def label(self, x, y, w, h, text='', font='font13', color='FFFFFFFF', align=0):
        return xbmcgui.ControlLabel(x, y, w, h, text, font=font, textColor=color, alignment=align)

    def build_controls(self, window):
        s = self.s
        if s['background'] == 1:
            self.background = self.image(0, 0, W, H, 'white.png', 'FF000000')
        else:
            self.background = self.image(0, 0, W, H, 'background.jpg')
        alpha = int(s['weather_opacity'] * 255 / 100)
        diffuse = {'base': None, 'fires': None, 'lightning': None, 'events': None, 'events2': None,
                   'temp': '%02XFFFFFF' % int(alpha * 0.75), 'clouds': '%02XFFFFFF' % alpha,
                   'precip': '%02XFFFFFF' % min(255, int(alpha * 1.1))}
        # plane[buffer][layer][copy]
        self.plane = []
        for _b in range(2):
            layers = []
            for layer in LAYERS:
                layers.append([xbmcgui.ControlImage(0, 0, 8, 8, '', aspectRatio=0, colorDiffuse=diffuse[layer])
                               if diffuse[layer] else xbmcgui.ControlImage(0, 0, 8, 8, '', aspectRatio=0)
                               for _c in range(MAX_COPIES)])
            self.plane.append(layers)
        self.plane_state = [[[None] * MAX_COPIES for _l in LAYERS] for _b in range(2)]
        self.front = 0            # buffer holding the newest frame
        self.globe_on = False
        self.pending_frames = None  # a frame waiting for the next tick (sliding views)
        self.hide_buffer_later = None
        self.last_step = None
        self.globe_shade = self.image(0, 0, 8, 8, 'globe_shade.png')
        n = s['wind_particles'] if 'wind' in self.layers else 0
        # Every particle costs a few calls into Kodi's GUI per move, and on a Fire TV each call
        # waits for Kodi's render loop: there, use fewer particles and move them less often
        # (Kodi still slides them smoothly in between).
        self.particle_every = 1
        if self.is_android:
            n //= 3
            self.particle_every = 2
        self.particle_ticks = 0
        self.particle_controls = [self.image(0, 0, PARTICLE_PX, PARTICLE_PX, 'particle.png', 'C0FFFFFF')
                                  for _ in range(n)]
        self.particle_state = [None] * n
        self.particles = overlays.Particles(n) if n else None
        self.storm_icons = [self.image(0, 0, STORM_PX, STORM_PX, 'storm.png', 'FFFF9850') for _ in range(MAX_STORMS)]
        self.storm_labels = [self.label(0, 0, 420, 30, font='font10', color='FFFFE0C0') for _ in range(MAX_STORMS)]
        self.iss_icon = self.image(0, 0, ISS_PX, ISS_PX, 'iss.png', 'FFFFFFFF')
        self.iss_label = self.label(0, 0, 200, 30, 'ISS', font='font10', color='FFFFFFFF')
        self.iss_state = None
        self.storm_state = [None] * MAX_STORMS
        # Flights: one control per aircraft up to the cap, chosen afresh with each fetch.
        n = s['max_flights'] if 'flights' in self.layers else 0
        self.flight_icons = [self.image(0, 0, FLIGHT_PX, FLIGHT_PX, 'rot/plane_000.png', 'E0FFFFFF')
                             for _ in range(n)]
        self.flight_state = [None] * n
        self.flight_sel = []
        self.flight_src = None
        self.flight_next = 0.0
        self.fader = self.image(-50, -50, W + 100, H + 100, 'white.png', 'FF000000')
        dim = int(s['dim'] * 255 / 100)
        self.dimmer = self.image(-50, -50, W + 100, H + 100, 'white.png', '%02X000000' % dim)

        # A soft shade along the bottom keeps the status and credits readable over ice.
        self.bottom_shade = self.image(0, H - 110, W, 110, 'shade_bottom.png')
        # Info card, top left.
        self.card_bg = self.image(40, 40, 760, 150, 'white.png', '99000000')
        self.card_accent = self.image(40, 40, 6, 150, 'white.png', 'FF4FC3F7')
        self.clock = self.label(70, 48, 300, 80, font='font45')
        self.date = self.label(300, 62, 480, 40, font='font13', color='FFCFD8DC')
        self.title = self.label(70, 120, 720, 40, font='font13', color='FFE0E0E0')
        self.status = self.label(40, H - 74, W - 80 - LEGEND_W - 40, 30, font='font10', color='D0FFFFFF')
        self.credits = self.label(40, H - 40, W - 80, 30, font='font10', color='A0FFFFFF', align=1)
        self.legend = self.image(W - 40 - LEGEND_W, H - 96, LEGEND_W, 14, 'legend_temp.png', 'E0FFFFFF')
        self.legend_lo = self.label(W - 40 - LEGEND_W, H - 78, 200, 30, '%d°C' % overlays.TEMP_MIN,
                                    font='font10', color='C0FFFFFF')
        self.legend_hi = self.label(W - 240, H - 78, 200, 30, '%d°C' % overlays.TEMP_MAX,
                                    font='font10', color='C0FFFFFF', align=1)
        self.perf = self.label(W - 940, 44, 900, 30, font='font10', color='C0B0FFB0', align=1)

        controls = [self.background]
        for b in range(2):
            for layer in self.plane[b]:
                controls += layer
        controls += [self.globe_shade] + self.particle_controls + self.flight_icons + self.storm_icons
        controls += self.storm_labels
        controls += [self.iss_icon, self.iss_label]
        controls += [self.fader, self.dimmer, self.bottom_shade, self.card_bg, self.card_accent, self.clock, self.date, self.title,
                     self.status, self.credits, self.legend, self.legend_lo, self.legend_hi, self.perf]
        window.addControls(controls)
        hidden = [self.globe_shade, self.legend, self.legend_lo, self.legend_hi] + self.particle_controls
        hidden += self.storm_icons + self.storm_labels + [self.iss_icon, self.iss_label] + self.flight_icons
        for b in range(2):
            for layer in self.plane[b]:
                hidden += layer
        if not s['show_info']:
            hidden += [self.card_bg, self.card_accent, self.clock, self.date, self.title]
        if not s['show_perf']:
            hidden.append(self.perf)
        if dim == 0:
            hidden.append(self.dimmer)
        for c in hidden:
            c.setVisible(False)
        self.fader.setAnimations([anim_fade(0, 0, 0)])
        self.label_text = {}

    def set_label(self, control, text):
        if self.label_text.get(id(control)) != text:
            self.label_text[id(control)] = text
            control.setLabel(text)

    # ------------------------------------------------------------ render thread

    def render_loop(self):
        try:
            self._render_loop()
        except Exception:
            import traceback
            log(traceback.format_exc(), xbmc.LOGERROR)

    def _render_loop(self):
        started = time.time()
        self.world = world_mod.World(self.media, self.store, lambda m: log(m, xbmc.LOGWARNING))
        self.renderer = render.Renderer(self.world, os.path.join(self.profile, 'frames'),
                                        reproject.LutCache(os.path.join(self.profile, 'lut')), self.media,
                                        lambda m: log(m, xbmc.LOGDEBUG))
        for name in self.feeds:
            self._load_feed(name)
        log('world ready in %.1fs' % (time.time() - started))
        base_id = None
        shown = None
        upcoming = None   # the next scene, its lookup tables built ahead while idle
        next_composite = 0.0
        last_spin = 0.0
        while not self.stopped():
            with self.lock:
                ready, self.ready_feeds = self.ready_feeds, set()
                want_scene, self.scene_request = self.scene_request, False
            changed = False
            for name in ready:
                if name == base_id:
                    self.world.load_base(base_id, self.base_options())   # its download finished
                    changed = True
                else:
                    changed = self._load_feed(name) or changed
            for name in list(self.world.overlays):
                if self._too_old(name):
                    self.world.drop_overlay(name)
                    changed = True

            if want_scene:
                scene, base, style_id = upcoming or self.next_scene_spec()
                upcoming = None
                if base != base_id:
                    base_id = base
                    self._ensure_base_feed(base)
                    self.world.load_base(base, self.base_options())
                t = time.time()
                geo = self.renderer.prepare(scene, self.stopped)
                if geo is None:
                    break
                prep = time.time() - t
                mov = motion.Motion(scene.proj.kind, scene.proj.rotatable, self.s['movement'], self.s['speed'],
                                    self.s['direction'] == 0, self.s['pan_pattern'], geo.show_w, geo.show_h, W, H,
                                    float(self.s['center_lon']))
                if scene.proj.kind != 'globe':
                    mov.focus = self.renderer.forward(geo, float(self.s['center_lon']), float(self.s['tilt']),
                                                      mov.rotation(0.0))
                shown = Shown(scene, geo, mov, time.time(), style_id)
                self.world.update_composite(time.time())
                next_composite = time.time() + COMPOSITE_SECONDS
                frames, secs = self._render(shown, shown.rotation)
                self.frame_seconds = secs
                log('scene %s / %s: %dx%d, motion %s, prepared in %.1fs, frame %.2fs'
                    % (scene.proj.id, style_id, geo.show_w, geo.show_h, mov.mode, prep, secs))
                if self.auto_quality and scene.style == render.MAP:
                    self._adapt_quality(secs, mov.mode == 'spin')
                with self.lock:
                    self.posted_scene = (shown, frames)
                    self.posted_frame = None
                self.wake_engine.set()
                continue
            if shown is None:
                self.wake_render.wait(1.0)
                self.wake_render.clear()
                continue

            now = time.time()
            if now >= next_composite:
                # The terminator moves a quarter of a degree a minute: recompose now and then.
                if self.s['daynight']:
                    self.world.update_composite(now)
                    changed = True
                next_composite = now + COMPOSITE_SECONDS
            if shown.motion.mode == 'spin':
                wait = last_spin + max(self.min_interval, self.frame_seconds * 1.1) - now
                with self.lock:
                    busy = self.posted_frame is not None   # the engine hasn't taken the last one
                if wait > 0 or busy:
                    self.wake_render.wait(max(0.03, wait))
                    self.wake_render.clear()
                    continue
                last_spin = time.time()
                # Render for when the frame will be on screen, one render time from now.
                rot = shown.motion.rotation(time.time() + self.frame_seconds - shown.t0)
                frames, secs = self._render(shown, rot)
                self.frame_seconds = self.frame_seconds * 0.7 + secs * 0.3
                with self.lock:
                    self.posted_frame = (id(shown), rot, frames, secs)
                self.wake_engine.set()
            elif changed:
                frames, secs = self._render(shown, shown.rotation)
                self.frame_seconds = secs
                with self.lock:
                    self.posted_frame = (id(shown), shown.rotation, frames, secs)
                self.wake_engine.set()
            elif self.cycling and upcoming is None:
                # Idle with a still or sliding view: build the next scene's tables now, so
                # the next change doesn't wait for them (tens of seconds on a Fire TV).
                upcoming = self.next_scene_spec()
                t = time.time()
                if self.renderer.prepare(upcoming[0], lambda: self.stopped() or self.scene_request) is not None:
                    log('next scene %s prepared ahead in %.1fs' % (upcoming[0].proj.id, time.time() - t))
            else:
                self.wake_render.wait(5.0)
                self.wake_render.clear()

    def _render(self, shown, rot):
        t = time.time()
        geo = shown.geo
        if shown.scene.style == render.MAP:
            frames = self.renderer.render_map(geo, rot, self.layers)
        else:
            frames = self.renderer.render_ascii(geo, rot, self.layers, time.time(), self.s['daynight'],
                                                self.s['lights'], self.s['lights_night_only'])
        return frames, time.time() - t

    def _adapt_quality(self, secs, spinning):
        """Automatic quality: render smaller (Kodi scales up) when frames are slow."""
        budget = 0.6 if spinning else 2.5
        if secs > budget and self.quality > 0.5:
            self.quality = max(0.5, self.quality - 0.25)
            log('rendering is slow (%.1fs): quality now %d%%' % (secs, self.quality * 100))

    def _load_feed(self, name):
        try:
            if self._too_old(name):
                return False
            return self.world.load_feed(name)
        except Exception as error:
            log('could not use %s data: %s' % (name, error), xbmc.LOGWARNING)
            return False

    def _too_old(self, name):
        feed_name = 'weather' if name == 'temp' else name
        if self.max_age is None:
            return False
        meta = self.store.meta(feed_name)
        return meta is not None and time.time() - meta.get('fetched', 0) > self.max_age * 3600

    def _ensure_base_feed(self, base_id):
        for bid, _name, factory, _attr in sources.BASEMAPS:
            if bid == base_id and factory is not None and bid not in self.feeds:
                self.feeds[bid] = factory(self.s)

    # ------------------------------------------------------------ engine thread

    def engine_loop(self):
        try:
            self._engine_loop()
        except Exception:
            import traceback
            log(traceback.format_exc(), xbmc.LOGERROR)
        if self.monitor.abortRequested():
            self.exit()

    def _engine_loop(self):
        next_tick = time.time()
        next_cycle = None
        self.switch_at = None
        self.switch_to = None
        while not self.stopped():
            now = time.time()
            timeout = next_tick - now
            if self.switch_at is not None:
                timeout = min(timeout, self.switch_at - now)
            self.wake_engine.wait(max(0.0, timeout))
            self.wake_engine.clear()
            if self.stopped():
                break
            now = time.time()
            with self.lock:
                posted_scene, self.posted_scene = self.posted_scene, None
                posted_frame, self.posted_frame = self.posted_frame, None
            if posted_scene is not None:
                if self.shown is None or self.s['transition'] == 1:
                    self.show_scene(*posted_scene)
                else:
                    self.fader.setAnimations([anim_fade(0, 100, FADE_MS)])
                    self.switch_to = posted_scene
                    self.switch_at = now + FADE_MS / 1000.0
                next_cycle = now + self.s['cycle_minutes'] * 60.0 if self.cycling else None
            if self.switch_at is not None and now >= self.switch_at:
                self.show_scene(*self.switch_to)
                self.fader.setAnimations([anim_fade(100, 0, FADE_MS)])
                self.switch_at = self.switch_to = None
            if posted_frame is not None and self.shown is not None and posted_frame[0] == id(self.shown):
                self.show_frame(posted_frame[1], posted_frame[2], posted_frame[3])
            if next_cycle is not None and now >= next_cycle and self.switch_at is None:
                next_cycle = None
                with self.lock:
                    self.scene_request = True
                self.wake_render.set()
            if now >= next_tick:
                next_tick = next_tick + TICK if next_tick + TICK > now else now + TICK
                try:
                    self.tick(now)
                except Exception:
                    import traceback
                    log(traceback.format_exc(), xbmc.LOGERROR)

    def tick(self, now):
        started = time.time()
        parts = []
        for name, fn in (('fetch', self.schedule_fetches), ('plane', self.move_plane),
                         ('markers', lambda n: self.update_markers(n, step=True)), ('hud', self.update_hud)):
            if name != 'fetch' and self.shown is None:
                continue
            t = time.time()
            fn(now)
            parts.append((name, time.time() - t))
        self.account(started, now, parts)

    def account(self, started, now, parts):
        """Log, once a minute, how busy the engine tick and the whole Kodi process are."""
        took = time.time() - started
        st = getattr(self, 'acct', None)
        if st is None:
            st = self.acct = {'t': now, 'cpu': time.process_time(), 'ticks': 0, 'sum': 0.0, 'max': 0.0, 'parts': {}}
        st['ticks'] += 1
        for name, secs in parts:
            st['parts'][name] = st['parts'].get(name, 0.0) + secs
        st['sum'] += took
        st['max'] = max(st['max'], took)
        if now - st['t'] >= 60:
            cpu = (time.process_time() - st['cpu']) / (now - st['t']) * 100
            split = ', '.join('%s %.0f' % (k, v / st['ticks'] * 1000) for k, v in st['parts'].items())
            log('last minute: Kodi process CPU %.0f%% of a core, engine tick avg %.0f ms (%s), max %.0f ms'
                % (cpu, st['sum'] / st['ticks'] * 1000, split, st['max'] * 1000))
            self.acct = None

    def schedule_fetches(self, now):
        for name, feed in list(self.feeds.items()):
            if name in self.inflight or not feed.due(self.store, now):
                continue
            self.inflight.add(name)
            self.fetcher.submit(self.fetch, name, feed)

    def fetch(self, name, feed):
        started = time.time()
        ok = feed.run(self.store)
        if feed.unchanged:
            log('%s: unchanged, checked in %.1fs' % (name, time.time() - started))
        else:
            log('%s: %s in %.1fs%s' % (name, 'updated' if ok else 'failed', time.time() - started,
                                        '' if ok else ' (%s)' % feed.error), xbmc.LOGINFO if ok else xbmc.LOGWARNING)
        self.inflight.discard(name)
        if ok:
            with self.lock:
                self.ready_feeds.add(name)
            self.wake_render.set()

    # ------------------------------------------------------------ showing scenes and frames

    def show_scene(self, shown, frames):
        geo = shown.geo
        self.splash.done()
        old = self.shown
        self.shown = shown
        self.frames_shown = 0
        # Reset both buffers to the new size; the newest frame goes in front.
        for b in range(2):
            for li in range(len(LAYERS)):
                for c in range(MAX_COPIES):
                    ctrl = self.plane[b][li][c]
                    ctrl.setWidth(geo.show_w)
                    ctrl.setHeight(geo.show_h)
                    ctrl.setAnimations(self.layer_anims(li, []))
                    ctrl.setVisible(False)
                    self.plane_state[b][li][c] = None
        globe = shown.scene.proj.kind == 'globe' and shown.scene.style == render.MAP
        if globe:
            size_w, size_h = int(geo.show_w * 1.12), int(geo.show_h * 1.12)
            self.globe_shade.setWidth(size_w)
            self.globe_shade.setHeight(size_h)
        self.globe_shade.setVisible(globe)
        self.globe_on = globe
        shown.pos = self.plane_position(shown, time.time())
        self.front = 0
        self.fill_buffer(0, frames, visible=True)
        self.place_buffers(shown.pos, None, 0)
        # Markers start afresh in the new scene: hide what the old one showed, or icons
        # would linger (an ASCII scene draws its storms as characters, not icons).
        for state, groups in ((self.particle_state, [self.particle_controls]),
                              (self.storm_state, [self.storm_icons, self.storm_labels]),
                              (self.flight_state, [self.flight_icons])):
            for i in range(len(state)):
                if state[i] is not None:
                    for controls in groups:
                        controls[i].setVisible(False)
                state[i] = None
        if self.iss_state is not None:
            self.iss_icon.setVisible(False)
            self.iss_label.setVisible(False)
            self.iss_state = None
        self.flight_next = 0.0
        self.update_markers(time.time(), step=True)
        self.update_hud(time.time())
        if old is None:
            log('first scene shown')

    def plane_position(self, shown, now):
        x, y = shown.motion.offset(now - shown.t0)
        return x, y

    def layer_anims(self, li, anims):
        """A layer's animations plus, for the event phases, the alternating pulse."""
        phase = PULSE.get(LAYERS[li])
        if phase and self.s['animate_events']:
            return anims + [('conditional', 'effect=fade start=%d end=%d time=%d pulse=true condition=true'
                             % (phase[0], phase[1], PULSE_MS))]
        return anims

    def fill_buffer(self, b, frames, visible):
        copies = self.shown.copies
        for li, layer in enumerate(LAYERS):
            path = frames.get(layer)
            if layer == 'events2' and not self.s['animate_events']:
                path = None   # still symbols: only the first phase
            for c in range(MAX_COPIES):
                ctrl = self.plane[b][li][c]
                want = path if (path and c < copies) else None
                if want:
                    ctrl.setImage(want, False)
                if (want is not None) != (self.plane_state[b][li][c] is not None) or not visible:
                    ctrl.setVisible(bool(want) and visible)
                self.plane_state[b][li][c] = want

    def wrapped(self, shown, x):
        """For a wrapping map: the left edge of the first copy, in [-show_w, 0)."""
        w = shown.geo.show_w
        return (x % w) - w

    def place_buffers(self, pos, old_pos, ms):
        """Put every plane control at pos (sliding from old_pos over ms when given)."""
        shown = self.shown
        x, y = pos
        if shown.motion.mode == 'scroll':
            base_x = self.wrapped(shown, x)
            old_x = None if old_pos is None else base_x + (old_pos[0] - x)
        else:
            base_x = x
            old_x = None if old_pos is None else old_pos[0]
        ix, iy = int(round(base_x)), int(round(y))
        anims = []
        if old_pos is not None and ms:
            anims = [anim_slide(int(round(old_x)) - ix, int(round(old_pos[1])) - iy, ms)]
        for b in range(2):
            for li in range(len(LAYERS)):
                for c in range(shown.copies):
                    ctrl = self.plane[b][li][c]
                    ctrl.setPosition(ix + c * shown.geo.show_w, iy)
                    if shown.motion.mode != 'spin':
                        ctrl.setAnimations(self.layer_anims(li, anims))
        if self.globe_on:
            gw = int(shown.geo.show_w * 1.12)
            gh = int(shown.geo.show_h * 1.12)
            self.globe_shade.setPosition(ix - (gw - shown.geo.show_w) // 2, iy - (gh - shown.geo.show_h) // 2)

    def show_frame(self, rotation, frames, secs):
        shown = self.shown
        shown.rotation = rotation
        self.frames_shown += 1
        self.fps_window.append(time.time())
        self.fps_window = [t for t in self.fps_window if t > time.time() - 10]
        spin = shown.motion.mode == 'spin'
        fade = spin and self.s['crossfade'] and shown.scene.style == render.MAP
        if not spin:
            if shown.motion.mode in ('pan', 'scroll'):
                self.pending_frames = frames   # swapped in on the next tick, with the slide
            else:
                self.swap_in(frames)
            return
        if not fade:
            self.fill_buffer(self.front, frames, visible=True)
            self.update_markers(time.time())
            return
        # Cross-fade: buffer 1 is drawn above buffer 0. A new frame for buffer 1 fades in;
        # a new frame for buffer 0 goes in behind and buffer 1 fades out to reveal it.
        ms = int(max(150, min(1500, max(self.min_interval, self.frame_seconds) * 1000)))
        if self.front == 0:
            self.fill_buffer(1, frames, visible=True)
            self.fade_buffer(1, 0, 100, ms)
            self.front = 1
        else:
            self.fill_buffer(0, frames, visible=True)
            self.fade_buffer(1, 100, 0, ms)
            self.front = 0
        self.update_markers(time.time())

    def swap_in(self, frames):
        """Show a frame in the other buffer; the old one is hidden a tick later, so there is
        never a gap while Kodi loads the new image."""
        b = 1 - self.front
        self.fill_buffer(b, frames, visible=True)
        self.hide_buffer_later = self.front
        self.front = b

    def fade_buffer(self, b, start, end, ms):
        for li in range(len(LAYERS)):
            for c in range(self.shown.copies):
                if self.plane_state[b][li][c] is not None:
                    self.plane[b][li][c].setAnimations(self.layer_anims(li, [anim_fade(start, end, ms)]))

    def move_plane(self, now):
        shown = self.shown
        hide = self.hide_buffer_later
        if hide is not None:
            self.hide_buffer_later = None
            for li in range(len(LAYERS)):
                for c in range(MAX_COPIES):
                    if self.plane_state[hide][li][c] is not None:
                        self.plane[hide][li][c].setVisible(False)
                        self.plane_state[hide][li][c] = None
        if shown.motion.mode not in ('pan', 'scroll'):
            return
        if self.pending_frames is not None:
            self.swap_in(self.pending_frames)
            self.pending_frames = None
        new = self.plane_position(shown, now + TICK)
        old = shown.pos
        shown.pos = new
        self.place_buffers(new, old, int(TICK * 1000))

    # ------------------------------------------------------------ markers

    def screen_point(self, lon, lat, pos, rotation):
        shown = self.shown
        p = self.renderer.forward(shown.geo, lon, lat, rotation)
        if p is None:
            return None
        x, y = p
        if shown.scene.style != render.MAP:
            if x >= shown.geo.show_w or y >= shown.geo.show_h:
                return None
        px, py = pos
        if shown.motion.mode == 'scroll':
            w = shown.geo.show_w
            sx = self.wrapped(shown, px) + x
            while sx < -20:
                sx += w
            return sx, py + y
        return px + x, py + y

    def update_markers(self, now, step=False):
        """Wind particles and storms. On a tick, particles advance and slide to where the
        map will be at the end of the tick; on a new spin frame only storms follow."""
        shown = self.shown
        if shown is None or self.renderer is None:
            return
        pos = shown.pos or self.plane_position(shown, now)
        ascii_mode = shown.scene.style != render.MAP
        if step:
            self.particle_ticks += 1
            if self.particle_ticks >= self.particle_every or self.last_step is None:
                self.particle_ticks = 0
                seconds = TICK if self.last_step is None else min(6.0, now - self.last_step)
                self.last_step = now
                ppos = pos
                if shown.motion.mode in ('pan', 'scroll') and self.particle_every > 1:
                    # Slide to where the map will be when this longer slide ends.
                    ppos = self.plane_position(shown, now + TICK * self.particle_every)
                self.update_particles(ppos, shown.rotation, ascii_mode, seconds)
        self.update_storms(pos, shown.rotation, ascii_mode)
        if step:
            self.update_iss(now, pos, shown.rotation)
            self.update_flights(now, shown.rotation)

    def update_particles(self, pos, rotation, ascii_mode, seconds):
        weather = self.world.weather if self.world else None
        if self.particles is None or weather is None or ascii_mode:
            for i, c in enumerate(self.particle_controls):
                if self.particle_state[i] is not None:
                    c.setVisible(False)
                    self.particle_state[i] = None
            return
        items = self.particles.step(weather, seconds)
        sliding = self.shown.motion.mode in ('pan', 'scroll', 'spin')
        for i, p in enumerate(items):
            ctrl = self.particle_controls[i]
            pt = self.screen_point(p[0], p[1], pos, rotation)
            old = self.particle_state[i]
            if pt is None or not (-10 <= pt[0] <= W + 10 and -10 <= pt[1] <= H + 10):
                if old is not None:
                    ctrl.setVisible(False)
                    self.particle_state[i] = None
                continue
            x, y = int(pt[0]) - PARTICLE_PX // 2, int(pt[1]) - PARTICLE_PX // 2
            speed = self.particles.speed(weather, p)
            color = 'A0D8F0FF' if speed < 8 else ('C0FFF0A0' if speed < 15 else 'E0FF9070')
            ctrl.setPosition(x, y)
            if old is None or p[3] or abs(old[0] - x) > 90 or abs(old[1] - y) > 90 or not sliding:
                ctrl.setAnimations([anim_fade(0, 100, 600)])
            else:
                ctrl.setAnimations([anim_slide(old[0] - x, old[1] - y, int(TICK * self.particle_every * 1000))])
            if old is None or old[2] != color:
                ctrl.setColorDiffuse(color)
            if old is None:
                ctrl.setVisible(True)
            self.particle_state[i] = (x, y, color)

    def update_iss(self, now, pos, rotation):
        """The ISS, sliding to where it will be at the end of this tick (it covers about a
        quarter of a degree of longitude a second)."""
        orbit = self.world.iss if self.world and 'iss' in self.layers else None
        ll = orbit.position(now + TICK) if orbit else None
        pt = self.screen_point(ll[1], ll[0], pos, rotation) if ll else None
        old = self.iss_state
        if pt is None or not (0 <= pt[0] <= W and 0 <= pt[1] <= H):
            if old is not None:
                self.iss_icon.setVisible(False)
                self.iss_label.setVisible(False)
                self.iss_state = None
            return
        x, y = int(pt[0]) - ISS_PX // 2, int(pt[1]) - ISS_PX // 2
        jump = old is None or abs(old[0] - x) > 300 or abs(old[1] - y) > 300
        anims = [] if jump else [anim_slide(old[0] - x, old[1] - y, int(TICK * 1000))]
        self.iss_icon.setPosition(x, y)
        self.iss_label.setPosition(x + ISS_PX + 2, y + ISS_PX // 2 - 15)
        self.iss_icon.setAnimations(anims)
        self.iss_label.setAnimations(anims)
        if old is None:
            self.iss_icon.setVisible(True)
            self.iss_label.setVisible(True)
        self.iss_state = (x, y)

    def update_flights(self, now, rotation):
        """Aircraft icons, flown on from their last report. On a still map they move every
        few seconds (a pixel or so); on a moving one they slide with it like the particles."""
        if not self.flight_icons or now < self.flight_next:
            return
        shown = self.shown
        moving = shown.motion.mode in ('pan', 'scroll', 'spin')
        step = TICK * self.particle_every if moving else FLIGHT_STATIC_SECONDS
        self.flight_next = now + step
        src = self.world.flights if self.world else []
        if src is not self.flight_src:
            self.flight_src = src
            keep = [ac[flights.ICAO] for ac in self.flight_sel]
            fresh = [ac for ac in src if now - ac[flights.AT] < FLIGHT_MAX_AGE]
            self.flight_sel = flights.select(fresh, len(self.flight_icons), keep)
        # Where the map and the aircraft will be when this step's slide ends.
        until = now + step if moving else now
        pos = self.plane_position(shown, until) if moving else (shown.pos or self.plane_position(shown, now))
        for i, ctrl in enumerate(self.flight_icons):
            old = self.flight_state[i]
            pt = ac = None
            if i < len(self.flight_sel) and until - self.flight_sel[i][flights.AT] < FLIGHT_MAX_AGE:
                ac = self.flight_sel[i]
                lon, lat = flights.position(ac, until)
                pt = self.screen_point(lon, lat, pos, rotation)
            if pt is None or not (-FLIGHT_PX <= pt[0] <= W + FLIGHT_PX and -FLIGHT_PX <= pt[1] <= H + FLIGHT_PX):
                if old is not None:
                    ctrl.setVisible(False)
                    self.flight_state[i] = None
                continue
            # The icon points the way the aircraft moves on screen, which on an interrupted map
            # or the globe need not be its compass track: project a point a little ahead.
            track = flights.heading(ac, lon, lat, until)
            nxt = self.screen_point(*(flights.ahead(lon, lat, track, 50000.0) + (pos, rotation)))
            if nxt is not None and abs(nxt[0] - pt[0]) + abs(nxt[1] - pt[1]) > 0.01:
                track = math.degrees(math.atan2(nxt[0] - pt[0], pt[1] - nxt[1]))
            hd = int(round(track / HEADING_STEP) * HEADING_STEP) % 360
            x, y = int(pt[0]) - FLIGHT_PX // 2, int(pt[1]) - FLIGHT_PX // 2
            color = flights.color(ac)
            state = (x, y, hd, color, ac[flights.ICAO])
            if old == state:
                continue
            same = old is not None and old[4] == state[4]
            if not same or old[2] != hd:
                ctrl.setImage(self.media_path('rot/plane_%03d.png' % hd))
            ctrl.setPosition(x, y)
            if same and moving and abs(old[0] - x) < 200 and abs(old[1] - y) < 200:
                ctrl.setAnimations([anim_slide(old[0] - x, old[1] - y, int(step * 1000))])
            elif not same:
                ctrl.setAnimations([anim_fade(0, 100, 600)])
            if not same or old[3] != color:
                ctrl.setColorDiffuse(color)
            if old is None:
                ctrl.setVisible(True)
            self.flight_state[i] = state

    def update_storms(self, pos, rotation, ascii_mode):
        storms = (self.world.storms if self.world and 'storms' in self.layers and not ascii_mode else [])
        for i in range(MAX_STORMS):
            icon, label = self.storm_icons[i], self.storm_labels[i]
            pt = None
            if i < len(storms):
                st = storms[i]
                pt = self.screen_point(st['lon'], st['lat'], pos, rotation)
            old = self.storm_state[i]
            if pt is None or not (0 <= pt[0] <= W and 0 <= pt[1] <= H):
                if old is not None:
                    icon.setVisible(False)
                    label.setVisible(False)
                    self.storm_state[i] = None
                continue
            st = storms[i]
            x, y = int(pt[0]) - STORM_PX // 2, int(pt[1]) - STORM_PX // 2
            kmh = st.get('wind_kmh') or 0
            text = '%s  %d km/h' % (st.get('name', ''), kmh) if kmh else st.get('name', '')
            color = 'FFFF50C8' if kmh >= 119 else 'FFFFA050'
            if old == (x, y, text):
                continue   # unchanged: every call into Kodi costs a few ms on a Fire TV
            icon.setPosition(x, y)
            label.setPosition(x + STORM_PX + 4, y + STORM_PX // 2 - 15)
            sliding = self.shown.motion.mode in ('pan', 'scroll')
            anims = [anim_slide(old[0] - x, old[1] - y, int(TICK * 1000))] if (old and sliding and
                                                                             abs(old[0] - x) < 200) else []
            icon.setAnimations(anims)
            label.setAnimations(anims)
            if old is None or old[2] != text:
                label.setLabel(text)
                icon.setColorDiffuse(color)
            if old is None:
                icon.setVisible(True)
                label.setVisible(True)
            self.storm_state[i] = (x, y, text)

    # ------------------------------------------------------------ HUD

    def update_hud(self, now):
        s = self.s
        shown = self.shown
        if s['show_info']:
            self.set_label(self.clock, time.strftime('%H:%M'))
            self.set_label(self.date, '%s   UTC %s' % (time.strftime('%a %d %b'), time.strftime('%H:%M', time.gmtime())))
            style_name = dict(config.STYLES).get(shown.style_id, shown.style_id)
            self.set_label(self.title, '%s   ·   %s' % (shown.scene.proj.name, style_name))
        parts = []
        if s['show_status']:
            for name, feed in self.feeds.items():
                if name in sources.BASEMAP_IDS:
                    continue
                meta = self.store.meta(name)
                if meta is None:
                    parts.append('[COLOR FFFF8A80]%s offline[/COLOR]' % feed.label if feed.error
                                 else '%s loading…' % feed.label)
                    continue
                age = now - meta.get('fetched', 0)
                text = '%s %s' % (feed.label, fmt_age(age))
                if age > 2 * feed.refresh:
                    old = self.max_age is not None and age > self.max_age * 3600
                    text = '[COLOR FFFFD180]%s, %s[/COLOR]' % (text, 'hidden' if old else 'not updating')
                parts.append(text)
            if self.world is not None and self.world.base_pending:
                parts.append('Base map loading…')
        self.set_label(self.status, '  ·  '.join(parts))
        temp_visible = ('temp' in self.layers and self.world is not None and 'temp' in self.world.overlays
                        and not (shown.scene.style != render.MAP and shown.scene.ascii.get('mono')))
        show_legend = bool(s['show_legend'] and temp_visible)
        for c in (self.legend, self.legend_lo, self.legend_hi):
            c.setVisible(show_legend)
        if s['show_credits'] and self.world is not None:
            credits = [self.world.base_attribution] + [f.attribution for n, f in self.feeds.items()
                                                       if n not in sources.BASEMAP_IDS]
            self.set_label(self.credits, ' · '.join(c for c in credits if c))
        if s['show_perf']:
            fps = xbmc.getInfoLabel('System.FPS')
            frames = len(self.fps_window) / 10.0
            self.set_label(self.perf, 'Kodi %s fps  ·  frame %.0f ms  ·  %.1f new frames/s  ·  '
                           'quality %d%%  ·  %s' % (fps, self.frame_seconds * 1000, frames, self.quality * 100,
                                                         shown.motion.mode))


def run():
    Screensaver().run()
