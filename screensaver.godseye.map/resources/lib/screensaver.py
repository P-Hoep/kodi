"""The screensaver: a live map of one configured place, refreshed in the background."""

import math
import os
import threading
import time

import xbmc
import xbmcaddon
import xbmcgui
import xbmcvfs

from . import clouds, geo, layers, looks, motion, tiles, weather
from .workers import Workers

ADDON_ID = 'screensaver.godseye.map'
W, H = 1920, 1080
DECLUTTER_CELL = 64                 # px; first pass draws at most one marker per cell
LABEL_CELL_W, LABEL_CELL_H = 200, 44
LABEL_CHAR_PX = 12                  # rough width of one font10 character
LABEL_GAP_PX = 2                    # extra per character when checking for overlaps
MAX_LABELS = 30
TICK = 1.0                          # seconds between motion updates; Kodi animates in between
SELECT_SECONDS = 4.0                # how often the set of drawn markers is re-chosen
TILE_CHECK_SECONDS = 5.0            # how often tiles are re-checked when nothing signalled a change
NO_SLIDE = [('conditional', 'effect=slide start=0,0 end=0,0 time=0 condition=true')]
DRIFT_PX, DRIFT_PERIOD = 48, 900.0  # burn-in protection: a slow 48 px circle every 15 min

BOOLS = ['layer_flights', 'layer_military', 'layer_satellites', 'layer_radar', 'layer_clouds',
         'layer_lightning', 'layer_quakes', 'layer_cyclones', 'layer_traffic', 'layer_incidents',
         'layer_rail', 'layer_transit', 'show_info',
         'show_labels', 'drift', 'show_weather', 'show_moon', 'show_home']
INTS = {'zoom': 16, 'basemap': 1, 'flight_refresh': 20, 'satellite_group': 1, 'overlay_opacity': 70,
        'quake_period': 0, 'quake_min_mag': 1, 'traffic_refresh': 600, 'max_markers': 150, 'dim': 0,
        'units': 0, 'look': 0}
CLOUDS_MAX_ZOOM = 10   # closer in, satellite infrared pixels are bigger than the view
CLOUDS_REFRESH = 600   # GOES updates every 5 min, the global mosaic hourly
WEATHER_REFRESH = 900   # seconds; Open-Meteo is keyless and asks for fair use
WEATHER_RETRY = 120
NUMBERS = {'lat': 44.9031331, 'lon': -93.3096136}
STRINGS = ['location_name', 'tomtom_key', 'transit_custom_url']
# Personal home-use key; the TomTom API key setting overrides it.
BUILTIN_TOMTOM_KEY = 'MtpWoLIzfM2z8gDDl0zBoewiwtvJ5quj'

MARKER_LAYERS = [('flights', 'Flights'), ('military', 'Military'), ('satellites', 'Satellites'),
                 ('quakes', 'Quakes'), ('cyclones', 'Storms'), ('transit', 'Transit')]
ICONS = {'plane': 'plane.png', 'circle': 'circle.png', 'storm': 'storm.png', 'bus': 'bus.png',
         'satellite': 'satellite.png', 'vehicle': 'vehicle.png'}
ROTATING = ('plane', 'bus')
BADGES = ('bus',)  # detailed icons tinted with the look's badge colour (stays readable in black-hot)
HOME_PX = 96
HOME_COLOR = 'FFFFD54F'
# Layers drawn one refresh behind, gliding between reported positions (see motion.py).
GLIDE_LAYERS = ('transit',)
GLIDE_SLACK = 3.0  # seconds added to the glide so a slow fetch doesn't leave vehicles paused
# Rotating markers swap between pre-drawn images (media/rot/<icon>_<heading>.png, one per
# HEADING_STEP degrees, from tools/make_media.py) instead of using Kodi's rotate animation:
# that animation pivots on where a control was when it was set, so moving markers drift.
HEADING_STEP = 5
# Rotated plane images are padded so wingtips survive rotation, so they're drawn that much
# larger; bus images already include the orbiting chevron.
ROT_PAD = {'plane': 1.125, 'bus': 1.0}


def log(message, level=xbmc.LOGINFO):
    xbmc.log('[%s] %s' % (ADDON_ID, message), level)


def read_settings(addon):
    s = {}
    for key in BOOLS:
        try:
            s[key] = addon.getSettingBool(key)
        except Exception:
            s[key] = False
    for key, default in INTS.items():
        try:
            s[key] = addon.getSettingInt(key)
        except Exception:
            s[key] = default
    for key, default in NUMBERS.items():
        try:
            s[key] = addon.getSettingNumber(key)
        except Exception:
            s[key] = default
    for key in STRINGS:
        s[key] = addon.getSettingString(key) or ''
    s['tomtom_key'] = s['tomtom_key'].strip() or BUILTIN_TOMTOM_KEY
    return s


class ExitMonitor(xbmc.Monitor):
    def __init__(self, on_exit):
        xbmc.Monitor.__init__(self)
        self.on_exit = on_exit

    def onScreensaverDeactivated(self):
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
        # Any key ends a screensaver; Kodi also sends onScreensaverDeactivated.
        self.app.exit()


class Screensaver(object):
    def __init__(self):
        self.addon = xbmcaddon.Addon(ADDON_ID)
        self.path = self.addon.getAddonInfo('path')
        self.profile = xbmcvfs.translatePath(self.addon.getAddonInfo('profile'))
        if not os.path.isdir(self.profile):
            os.makedirs(self.profile)
        self.media = os.path.join(self.path, 'resources', 'media')
        for name in os.listdir(self.profile):
            if name.startswith('clouds_') and name.endswith('.png'):  # left by an earlier run
                try:
                    os.remove(os.path.join(self.profile, name))
                except OSError:
                    pass
        self.settings = read_settings(self.addon)
        self.settings['_cache_dir'] = self.profile
        s = self.settings
        self.home = geo.Viewport(s['lat'], s['lon'], int(geo.clamp(s['zoom'], 2, 17)), W, H)

        self.layers = []
        for cls in layers.LAYER_CLASSES:
            if s.get('layer_' + cls.id):
                self.layers.append(cls(s))
        self.data = {}
        self.data_version = 0
        self.glider = motion.Glider()
        self.selected = []
        self.selected_version = -1
        self.labelled = set()
        self.counts_on_screen = {}
        self.next_select = 0.0
        self.tiles_dirty = True
        self.next_tile_check = 0.0
        self.slot_of = {}
        self.label_text = {}
        self.errors = {}
        self.fetched = {}
        self.inflight = set()
        self.lock = threading.Lock()
        self.wake = threading.Event()
        self.stop = threading.Event()
        self.monitor = ExitMonitor(self.exit)
        self.window = None
        self.engine = None
        self.fetcher = Workers(3, 'fetch', lambda e: log('fetch error: %s' % e, xbmc.LOGWARNING))
        self.cache = tiles.TileCache(os.path.join(self.profile, 'tiles'), self.tile_ready,
                                     lambda msg: log(msg, xbmc.LOGDEBUG))

        self.look = looks.by_index(s['look'])
        if self.look.recolor:
            # Recolouring needs palette PNG tiles, which only the OpenStreetMap base map has.
            basemap = [tiles.recolored(tiles.OSM, self.look)]
        else:
            basemap = tiles.BASEMAPS[int(geo.clamp(s['basemap'], 0, len(tiles.BASEMAPS) - 1))][1]
        self.sources = [(src, 255) for src in basemap] + tiles.overlays(s)
        self.base_count = len(basemap)
        self.show_clouds = bool(s['layer_clouds']) and self.home.zoom <= CLOUDS_MAX_ZOOM
        self.clouds_at = 0.0
        self.clouds_pending = None
        self.clouds_shown = None
        self.clouds_file = None
        self.grain_frame = 0

    # ------------------------------------------------------------ lifecycle

    def run(self):
        self.window = SaverWindow('screensaver-godseye-map.xml', self.path, 'Default', '1080i', app=self)
        try:
            self.window.doModal()
        finally:
            self.stop.set()
            self.wake.set()
            if self.engine:
                self.engine.join(3)
            self.cache.shutdown()
            self.fetcher.shutdown()
            del self.window
            del self.monitor

    def attach(self, window):
        self.build_controls(window)
        self.engine = threading.Thread(target=self.engine_loop, name='godseye-engine')
        self.engine.daemon = True
        self.engine.start()
        pruner = threading.Thread(target=self.cache.prune, name='godseye-prune')
        pruner.daemon = True
        pruner.start()

    def exit(self):
        if not self.stop.is_set():
            self.stop.set()
            self.wake.set()
            if self.window:
                self.window.close()

    # ------------------------------------------------------------ controls

    def media_path(self, name):
        return os.path.join(self.media, name)

    def image(self, x, y, w, h, name='', diffuse=None, aspect=0):
        path = self.media_path(name) if name else ''
        if diffuse:
            return xbmcgui.ControlImage(x, y, w, h, path, aspectRatio=aspect, colorDiffuse=diffuse)
        return xbmcgui.ControlImage(x, y, w, h, path, aspectRatio=aspect)

    def label(self, x, y, w, h, text='', font='font13', color='FFFFFFFF', align=0):
        return xbmcgui.ControlLabel(x, y, w, h, text, font=font, textColor=color, alignment=align)

    def build_controls(self, window):
        s = self.settings
        n = self.home.max_tiles()
        self.pools = []
        tint = (self.look.tile_tint or 'FFFFFFFF')[2:]
        for src, alpha in self.sources:
            diffuse = '%02X%s' % (alpha, tint) if alpha < 255 or self.look.tile_tint else None
            pool = [xbmcgui.ControlImage(0, 0, geo.TILE, geo.TILE, '', colorDiffuse=diffuse) if diffuse
                    else xbmcgui.ControlImage(0, 0, geo.TILE, geo.TILE, '') for _ in range(n)]
            self.pools.append(pool)
        self.pool_state = [[None] * n for _ in self.pools]
        # Infrared clouds: one image stretched over the view, between base map and overlays.
        self.cloud_image = None
        if self.show_clouds:
            alpha = int(geo.clamp(s['overlay_opacity'], 0, 100) * 255 / 100)
            self.cloud_image = xbmcgui.ControlImage(0, 0, W, H, '', aspectRatio=0,
                                                    colorDiffuse='%02X%s' % (alpha, tint))
        dim = int(geo.clamp(s['dim'], 0, 90) * 255 / 100)
        self.dimmer = self.image(-100, -100, W + 200, H + 200, 'white.png', '%02X000000' % dim)

        m = int(geo.clamp(s['max_markers'], 20, 300)) if self.layers else 0
        self.markers = [self.image(0, 0, 32, 32, 'plane.png') for _ in range(m)]
        self.label_bgs = [self.image(0, 0, 10, 30, 'white.png', 'B0000000') for _ in range(m)]
        self.labels = [self.label(0, 0, 420, 30, font='font10') for _ in range(m)]
        self.marker_state = [None] * m
        self.free_slots = list(range(m - 1, -1, -1))
        self.label_state = [None] * m

        # Home icon: a white sticker border under a house tinted for the look.
        self.home_controls = []
        if s['show_home']:
            self.home_back = self.image(0, 0, HOME_PX, HOME_PX, 'home_back.png')
            self.home_front = self.image(0, 0, HOME_PX, HOME_PX, 'home_front.png',
                                         self.look.badge_color or HOME_COLOR)
            self.home_controls = [self.home_back, self.home_front]
        self.home_shown = None

        # Sensor-look overlays, over the map and markers but under the cards.
        lk = self.look
        self.look_controls = []
        self.grain = None
        if lk.vignette:
            self.look_controls.append(self.image(0, 0, W, H, 'look/vignette.png', '%02X000000' % lk.vignette))
        if lk.scanlines:
            self.look_controls.append(self.image(0, 0, W, H, 'look/scanlines.png', '%02X000000' % lk.scanlines))
        if lk.grain:
            self.grain = self.image(0, 0, W, H, 'look/grain_0.png', '%02X%s' % (lk.grain, tint))
            self.look_controls.append(self.grain)

        # Info card, top left.
        self.card_bg = self.image(40, 40, 820, 196, 'white.png', 'B8000000')
        self.card_accent = self.image(40, 40, 6, 196, 'white.png', 'FF69F0AE')
        self.clock = self.label(70, 52, 780, 80, font='font45')
        self.place = self.label(70, 128, 780, 44, font='font13', color='FFE0E0E0')
        self.counts = self.label(70, 176, 780, 44, font='font10', color='FFB0BEC5')

        self.credits = self.label(W - 1240, H - 34, 1220, 30, font='font10', color='B0FFFFFF', align=1)

        # Weather card, top right: a weather section and/or a moon section.
        wx, ww = W - 40 - 640, 640
        weather_h = 200 if s['show_weather'] else 0
        moon_h = 128 if s['show_moon'] else 0
        self.wcard = []
        self.wx_labels = {}
        self.moon_image = self.moon_name = self.moon_next = None
        if weather_h or moon_h:
            self.wcard += [self.image(wx, 40, ww, weather_h + moon_h, 'white.png', 'B8000000'),
                           self.image(wx + ww - 6, 40, 6, weather_h + moon_h, 'white.png', 'FF4FC3F7')]
        if weather_h:
            self.wx_labels = {
                # Initial text goes in the constructor: setLabel on a control that isn't in a
                # window yet is delivered to id-0 labels of the active window (Kodi's home).
                'temp': self.label(wx + 30, 52, 240, 80, '--', font='font45'),
                'condition': self.label(wx + 250, 74, ww - 280, 44, 'Loading weather...', font='font13',
                                        color='FFE0E0E0'),
                'feels_hi_lo': self.label(wx + 30, 132, ww - 60, 34, font='font10', color='FFCFD8DC'),
                'wind_humidity': self.label(wx + 30, 162, ww - 60, 34, font='font10', color='FFCFD8DC'),
                'sun': self.label(wx + 30, 192, ww - 60, 34, font='font10', color='FFCFD8DC'),
            }
            self.wcard += list(self.wx_labels.values())
        if moon_h:
            top = 40 + weather_h
            if weather_h:
                self.wcard.append(self.image(wx + 30, top, ww - 60, 2, 'white.png', '30FFFFFF'))
            self.moon_image = xbmcgui.ControlImage(wx + 30, top + 16, 96, 96, '')
            self.moon_name = self.label(wx + 146, top + 26, ww - 180, 44, font='font13', color='FFE0E0E0')
            self.moon_next = self.label(wx + 146, top + 70, ww - 180, 34, font='font10', color='FFCFD8DC')
            self.wcard += [self.moon_image, self.moon_name, self.moon_next]
        self.weather = None
        self.weather_at = 0.0
        self.weather_shown = None
        self.moon_shown = None

        controls = []
        for i, pool in enumerate(self.pools):
            if i == self.base_count and self.cloud_image is not None:
                controls.append(self.cloud_image)
            controls += pool
        if self.cloud_image is not None and self.base_count >= len(self.pools):
            controls.append(self.cloud_image)
        controls += [self.dimmer] + self.label_bgs + self.labels + self.markers + self.home_controls
        controls += self.look_controls
        controls += [self.card_bg, self.card_accent, self.clock, self.place, self.counts, self.credits]
        controls += self.wcard
        window.addControls(controls)
        hidden = self.label_bgs + self.labels + self.markers
        if self.cloud_image is not None:
            hidden.append(self.cloud_image)
        for pool in self.pools:
            hidden += pool
        if not s['show_info']:
            hidden += [self.card_bg, self.card_accent, self.clock, self.place, self.counts]
        if dim == 0:
            hidden.append(self.dimmer)
        for c in hidden:
            c.setVisible(False)

    # ------------------------------------------------------------ engine
    #
    # Motion: Python wakes on a steady TICK, works out where every marker will be one tick
    # from now, moves its control there and gives it a slide animation starting from where
    # it is drawn now. Kodi then plays the slide at the display's frame rate, so markers
    # move continuously instead of hopping on every Python update. Expensive work (choosing
    # which markers to show, checking tiles on disk) runs only when something changed.

    def engine_loop(self):
        next_tick = time.time()
        while not self.stop.is_set() and not self.monitor.abortRequested():
            self.wake.wait(max(0.0, next_tick - time.time()))
            self.wake.clear()
            if self.stop.is_set():
                break
            now = time.time()
            if now < next_tick - 0.02:
                continue  # woken by a download; it is picked up on the next tick
            next_tick = next_tick + TICK if next_tick + TICK > now else now + TICK
            try:
                view = self.current_view(now)
                self.schedule_fetches(view)
                self.render(view, now)
            except Exception:
                import traceback
                log(traceback.format_exc(), xbmc.LOGERROR)
        if self.monitor.abortRequested():
            self.exit()

    def current_view(self, now=None):
        view = geo.Viewport(self.home.lat, self.home.lon, self.home.zoom, W, H)
        if self.settings['drift']:
            now = time.time() if now is None else now
            phase = 2 * math.pi * (now % DRIFT_PERIOD) / DRIFT_PERIOD
            view.pan(DRIFT_PX * math.cos(phase), DRIFT_PX * math.sin(phase))
        return view

    def interval(self, layer):
        return self.settings['flight_refresh'] if layer.id == 'flights' else layer.interval

    def schedule_fetches(self, view):
        now = time.time()
        if self.show_clouds and 'clouds' not in self.inflight and now >= self.clouds_at:
            self.inflight.add('clouds')
            self.fetcher.submit(self.fetch_clouds)
        if self.settings['show_weather'] and 'weather' not in self.inflight and now >= self.weather_at:
            self.inflight.add('weather')
            self.fetcher.submit(self.fetch_weather)
        for layer in self.layers:
            if layer.id in self.inflight or view.zoom < layer.min_zoom:
                continue
            last = self.fetched.get(layer.id)
            if last is None or now - last >= self.interval(layer):
                self.inflight.add(layer.id)
                # Fetch for the undrifted view so drift never triggers refetches.
                self.fetcher.submit(self.fetch_layer, layer, self.home)

    def fetch_clouds(self):
        try:
            data, rect = clouds.fetch(self.home)  # undrifted view; drift is applied when drawn
            path = os.path.join(self.profile, 'clouds_%d.png' % int(time.time()))
            with open(path, 'wb') as handle:
                handle.write(data)
            self.clouds_pending = (path, rect)
            self.clouds_at = time.time() + CLOUDS_REFRESH
        except Exception as error:
            self.clouds_at = time.time() + WEATHER_RETRY
            log('clouds failed: %s' % error, xbmc.LOGWARNING)
        finally:
            self.inflight.discard('clouds')

    def render_clouds(self, view):
        if self.cloud_image is None:
            return
        pending, self.clouds_pending = self.clouds_pending, None
        if pending:
            path, rect = pending
            self.cloud_image.setImage(path, False)
            self.cloud_image.setWidth(rect[2])
            self.cloud_image.setHeight(rect[3])
            if self.clouds_file is None:
                self.cloud_image.setVisible(True)
            elif self.clouds_file != path:
                try:
                    os.remove(self.clouds_file)
                except OSError:
                    pass
            self.clouds_file = path
            self.clouds_rect = rect
            self.clouds_shown = None
        if self.clouds_file is None:
            return
        hx, hy = self.home.origin
        vx, vy = view.origin
        pos = (int(round(self.clouds_rect[0] + hx - vx)), int(round(self.clouds_rect[1] + hy - vy)))
        if pos != self.clouds_shown:
            self.cloud_image.setPosition(*pos)
            self.clouds_shown = pos

    def fetch_weather(self):
        s = self.settings
        try:
            self.weather = weather.fetch(s['lat'], s['lon'], imperial=s['units'] == 0)
            self.weather_at = time.time() + WEATHER_REFRESH
        except Exception as error:
            self.weather_at = time.time() + WEATHER_RETRY
            log('weather failed: %s' % error, xbmc.LOGWARNING)
        finally:
            self.inflight.discard('weather')

    def render_weather(self):
        current = self.weather
        if self.wx_labels and current is not None and current is not self.weather_shown:
            for key, control in self.wx_labels.items():
                control.setLabel(current[key])
            self.weather_shown = current
        if self.moon_image is not None:
            m = weather.moon()
            shown = (m['frame'], m['text'], m['upcoming'])
            if shown != self.moon_shown:
                self.moon_image.setImage(self.media_path(os.path.join('moon', 'moon_%02d.png' % m['frame'])))
                self.moon_name.setLabel(m['text'])
                self.moon_next.setLabel(m['upcoming'])
                self.moon_shown = shown

    def fetch_layer(self, layer, view):
        started = time.time()
        try:
            items = layer.fetch(view)
            with self.lock:
                if layer.id in GLIDE_LAYERS:
                    self.glider.update(items, time.time(), self.interval(layer) + GLIDE_SLACK)
                self.data[layer.id] = items
                self.data_version += 1
                self.errors.pop(layer.id, None)
                self.fetched[layer.id] = started
            log('%s: %d items in %.1fs' % (layer.id, len(items), time.time() - started), xbmc.LOGDEBUG)
        except Exception as error:
            with self.lock:
                self.errors[layer.id] = str(error)
                self.data_version += 1
                self.fetched[layer.id] = started - self.interval(layer) + 30  # retry in 30 s
            log('%s failed: %s' % (layer.id, error), xbmc.LOGWARNING)
        finally:
            self.inflight.discard(layer.id)

    def tile_ready(self, *_args):
        self.tiles_dirty = True

    # ------------------------------------------------------------ render

    def render(self, view, now):
        if self.tiles_dirty or self.settings['drift'] or now >= self.next_tile_check:
            self.tiles_dirty = False
            self.next_tile_check = now + TILE_CHECK_SECONDS
            self.render_tiles(view)
        if self.data_version != self.selected_version or now >= self.next_select:
            self.select(view, now)
        # Targets one tick ahead; the slide animation covers the time in between.
        target = now + TICK
        entries = []
        for item in self.selected:
            x, y = view.screen_xy(*self.position(item, target))
            entries.append((item, x, y))
        self.render_markers(entries)
        self.render_clouds(view)
        self.render_info(view)
        self.render_weather()
        self.render_home(view)
        if self.grain is not None:
            self.grain_frame = (self.grain_frame + 1) % 4
            self.grain.setImage(self.media_path('look/grain_%d.png' % self.grain_frame))

    def position(self, item, when):
        if item.layer in GLIDE_LAYERS:
            return self.glider.position(item, when)
        return item.position_at(when)

    def select(self, view, now):
        """Choose which markers to draw and which get labels (every few seconds, or when
        new data arrives), and count what is on screen for the info card."""
        with self.lock:
            self.selected_version = self.data_version
            items = []
            for layer in self.layers:
                if view.zoom >= layer.min_zoom:
                    items.extend(self.data.get(layer.id) or [])
        self.next_select = now + SELECT_SECONDS
        visible = self.on_screen(view, items, now)
        chosen = self.budget(visible, len(self.markers))
        self.selected = [v[0] for v in chosen]
        self.labelled = self.choose_labels(chosen)
        counts = {}
        for item, _x, _y, _d in visible:
            counts[item.layer] = counts.get(item.layer, 0) + 1
        self.counts_on_screen = counts

    def render_tiles(self, view):
        plans = [view.tiles_at(src.max_zoom) for src, _alpha in self.sources]
        wanted = set()
        for (src, _alpha), plan in zip(self.sources, plans):
            for z, tx, ty, _sx, _sy, _size in plan:
                wanted.add((src.id, z, tx, ty))
        self.cache.want(wanted)
        for p, ((src, _alpha), plan) in enumerate(zip(self.sources, plans)):
            pool, state = self.pools[p], self.pool_state[p]
            for slot, ctrl in enumerate(pool):
                target = None
                if slot < len(plan):
                    z, tx, ty, sx, sy, size = plan[slot]
                    path = self.cache.ensure(src, z, tx, ty)
                    if path:
                        target = (path, sx, sy, size)
                old = state[slot]
                if target == old:
                    continue
                if target is None:
                    ctrl.setVisible(False)
                else:
                    if old is None or old[0] != target[0]:
                        ctrl.setImage(target[0], False)
                    if old is None or old[3] != target[3]:
                        ctrl.setWidth(target[3])
                        ctrl.setHeight(target[3])
                    if old is None or old[1:3] != target[1:3]:
                        ctrl.setPosition(target[1], target[2])
                    if old is None:
                        ctrl.setVisible(True)
                state[slot] = target

    def on_screen(self, view, items, when):
        cx, cy = W / 2.0, H / 2.0
        out = []
        for item in items:
            x, y = view.screen_xy(*self.position(item, when))
            if view.contains(x, y, 40):
                out.append((item, x, y, (x - cx) ** 2 + (y - cy) ** 2))
        return out

    def budget(self, visible, limit):
        """Share the marker limit between layers and spread markers over the screen.

        Pass 1 takes at most one marker per grid cell, layers taking turns; pass 2 fills
        what is left of the limit in the same order."""
        groups = {}
        for v in visible:
            groups.setdefault(v[0].layer, []).append(v)
        for group in groups.values():
            group.sort(key=lambda v: (-v[0].priority, v[3]))
        out, taken, used = [], set(), set()
        for spread in (True, False):
            cursors = dict((lid, 0) for lid in groups)
            active = list(groups)
            while len(out) < limit and active:
                for lid in list(active):
                    group, i = groups[lid], cursors[lid]
                    while i < len(group):
                        v = group[i]
                        i += 1
                        if id(v) in taken:
                            continue
                        cell = (int(v[1] // DECLUTTER_CELL), int(v[2] // DECLUTTER_CELL))
                        if spread and cell in used:
                            continue
                        used.add(cell)
                        taken.add(id(v))
                        out.append(v)
                        break
                    cursors[lid] = i
                    if i >= len(group):
                        active.remove(lid)
                    if len(out) >= limit:
                        break
        return out

    def choose_labels(self, chosen):
        labelled = set()
        if not self.settings['show_labels']:
            return labelled
        claimed = set()
        for item, x, y, _d in sorted(chosen, key=lambda v: (-v[0].priority, v[3])):
            if not item.label:
                continue
            left = x + item.size / 2 + 4
            cells = set((int(cx // LABEL_CELL_W), int(y // LABEL_CELL_H))
                        for cx in (left, left + (LABEL_CHAR_PX + LABEL_GAP_PX) * len(item.label) + 16))
            if cells & claimed:
                continue
            claimed |= cells
            labelled.add(item.uid)
            if len(labelled) >= MAX_LABELS:
                break
        return labelled

    def render_markers(self, entries):
        # Each item keeps its control for as long as it is shown, so a control never jumps
        # from one aircraft or bus to another.
        wanted = set(item.uid for item, _x, _y in entries)
        for uid in [u for u in self.slot_of if u not in wanted]:
            self.free_slots.append(self.slot_of.pop(uid))
        assigned = [None] * len(self.markers)
        for entry in entries:
            uid = entry[0].uid
            slot = self.slot_of.get(uid)
            if slot is None:
                if not self.free_slots:
                    continue
                slot = self.free_slots.pop()
                self.slot_of[uid] = slot
            assigned[slot] = entry
        for k, ctrl in enumerate(self.markers):
            entry = assigned[k]
            mark = text = None
            if entry is not None:
                item, x, y = entry
                heading = None
                size = item.size
                if item.icon in ROTATING and item.heading is not None:
                    heading = int(round(item.heading / float(HEADING_STEP)) * HEADING_STEP) % 360
                    size = int(round(item.size * ROT_PAD.get(item.icon, 1.0)))
                if item.icon in BADGES:
                    color = self.look.badge_color or item.color
                else:
                    color = self.look.marker_color or item.color
                mark = (item.uid, item.icon, size, color, heading,
                        int(round(x - size / 2.0)), int(round(y - size / 2.0)))
                if item.uid in self.labelled:
                    text = (item.uid, item.label, int(x + item.size / 2 + 4), int(y - 15))
            self.apply_marker(k, ctrl, mark)
            self.apply_label(k, text)

    @staticmethod
    def slide(dx, dy):
        return [('conditional', 'effect=slide start=%d,%d end=0,0 time=%d condition=true'
                 % (dx, dy, int(TICK * 1000)))]

    def apply_marker(self, k, ctrl, mark):
        old = self.marker_state[k]
        if mark == old:
            return
        if mark is None:
            ctrl.setVisible(False)
            self.marker_state[k] = None
            return
        uid, icon, size, color, heading, x, y = mark
        same = old is not None and old[0] == uid
        if not same or old[1] != icon or old[4] != heading:
            if heading is None:
                ctrl.setImage(self.media_path(ICONS[icon]))
            else:
                ctrl.setImage(self.media_path(os.path.join('rot', '%s_%03d.png' % (icon, heading))))
        if not same or old[2] != size:
            ctrl.setWidth(size)
            ctrl.setHeight(size)
        if not same or old[3] != color:
            ctrl.setColorDiffuse(color)
        if not same:
            ctrl.setPosition(x, y)
            ctrl.setAnimations(NO_SLIDE)  # a newly shown item appears in place
        elif old[5:7] != (x, y):
            ctrl.setPosition(x, y)
            ctrl.setAnimations(self.slide(old[5] - x, old[6] - y))
        if old is None:
            ctrl.setVisible(True)
        self.marker_state[k] = mark

    def apply_label(self, k, text):
        old = self.label_state[k]
        if text == old:
            return
        bg, label = self.label_bgs[k], self.labels[k]
        if text is None:
            bg.setVisible(False)
            label.setVisible(False)
            self.label_state[k] = None
            return
        uid, value, x, y = text
        same = old is not None and old[0] == uid
        if not same or old[1] != value:
            label.setLabel(value)
            bg.setWidth(LABEL_CHAR_PX * len(value) + 16)
        bg.setPosition(x, y)
        label.setPosition(x + 8, y - 1)
        animations = self.slide(old[2] - x, old[3] - y) if same else NO_SLIDE
        bg.setAnimations(animations)
        label.setAnimations(animations)
        if old is None:
            bg.setVisible(True)
            label.setVisible(True)
        self.label_state[k] = text

    def render_home(self, view):
        if not self.home_controls:
            return
        x, y = view.screen_xy(self.home.lat, self.home.lon)
        pos = (int(round(x - HOME_PX / 2.0)), int(round(y - HOME_PX / 2.0)))
        if pos != self.home_shown:
            old = self.home_shown
            for control in self.home_controls:
                control.setPosition(*pos)
                if old is not None:
                    control.setAnimations(self.slide(old[0] - pos[0], old[1] - pos[1]))
            self.home_shown = pos

    def set_label(self, control, text):
        """setLabel only when the text changed (each call costs a trip into Kodi's GUI)."""
        if self.label_text.get(id(control)) != text:
            self.label_text[id(control)] = text
            control.setLabel(text)

    def render_info(self, view):
        s = self.settings
        if s['show_info']:
            self.set_label(self.clock, time.strftime('%H:%M'))
            place = s['location_name'] or '%.3f, %.3f' % (view.lat, view.lon)
            self.set_label(self.place, '%s   ·   %s' % (place, time.strftime('%a %d %b')))
            counts = self.counts_on_screen
            with self.lock:
                errors = dict(self.errors)
                have = set(self.data)
            parts = []
            active = set(l.id for l in self.layers)
            for lid, name in MARKER_LAYERS:
                if lid not in active:
                    continue
                layer = next(l for l in self.layers if l.id == lid)
                if view.zoom < layer.min_zoom:
                    continue
                if lid in errors and lid not in have:
                    parts.append('[COLOR FFFF8A80]%s offline[/COLOR]' % name)
                elif lid in have and (self.data[lid] or lid not in ('transit',)):
                    parts.append('%s %d' % (name, counts.get(lid, 0)))
            if (s['layer_traffic'] or s['layer_incidents']) and not s['tomtom_key'].strip():
                parts.append('[COLOR FFFFD180]Traffic needs key[/COLOR]')
            self.set_label(self.counts, '  ·  '.join(parts))
        credits = []
        for src, _alpha in self.sources:
            credits.append(src.attribution)
        for layer in self.layers:
            credits.append(layer.attribution)
        seen = []
        for c in credits:
            if c not in seen:
                seen.append(c)
        self.set_label(self.credits, ' · '.join(seen))


def run():
    Screensaver().run()
