"""The screensaver window and its display loop: Kodi glue only.

The screen is one Sentinel-2 satellite image of the tracked box with a marker for every ship, and
a panel on the right with the clock, the live status, a paged ship list and a photo slideshow. Every
control is created from Python, bottom to top, because the layout only exists in this file.

Three worker threads feed the screen and never touch Kodi:

* the AIS thread (tracker.py) fills the fleet and the ship database,
* the lookup worker (sources.py) fills the profile database with details and photos,
* one photo download at a time (PhotoJob below) keeps the slideshow fed.

The display loop runs on its own thread and only reads snapshots. Any input or the screensaver
being woken stops it and the window closes straight away.
"""

import hashlib
import os
import tempfile
import threading
import time
import traceback

import xbmc
import xbmcaddon
import xbmcgui
import xbmcvfs

from . import ais, config, mapimage, net, sources, store, tracker

W, H = 1920, 1080
MAP_W, MAP_H = config.MAP_WIDTH, config.MAP_HEIGHT
MAP_X, MAP_Y = 0, 0

PANEL_X = MAP_W
PANEL_W = W - MAP_W
X0 = PANEL_X + 44
INNER_W = PANEL_W - 88
INFO_WIDTH = INNER_W            # the detail line may use the full panel width
CLOCK_W = 180

DIVIDER_Y = 178
LIST_HEADER_Y = 196
ROWS = 6
ROW_Y = 234
ROW_H = 68

PHOTO_X = X0
PHOTO_Y = 672
PHOTO_W = INNER_W
PHOTO_H = 288
PHOTO_NAME_Y = 968
PHOTO_SOURCE_Y = 998

CREDIT_W, CREDIT_H = 188, 26
CREDIT_X = PHOTO_X + PHOTO_W - CREDIT_W - 10
CREDIT_Y = PHOTO_Y + PHOTO_H - CREDIT_H - 10

PAGE_SECONDS = 8.0
SHIPS_TICK = 2.0
LOOP_TICK = 0.5
CROSSFADE_MS = 900
PHOTO_MAX_BYTES = 8 * 1024 * 1024
PHOTO_CANDIDATES_MAX = 40
MAX_MARKERS = 90
MARKER = 40

ALIGN = {'left': 0, 'right': 1, 'center': 2}

# One diffuse colour per marker group; the icons themselves are white, so the tint is exact.
PANEL_COLOUR = 'FF070B12'
ACCENT = 'FF8ECAE6'
DIM = 'A6FFFFFF'
FAINT = '8CFFFFFF'
LINE = '22FFFFFF'
BORDER = '38FFFFFF'

# The list has one line for the ship's own details, so the long official navigation phrases
# ("Under way using engine") lose to the country and speed that matter more at a glance.
SHORT_NAV = {
    0: 'Under way', 1: 'At anchor', 2: 'Not under command', 3: 'Restricted',
    4: 'Draught', 5: 'Moored', 6: 'Aground', 7: 'Fishing', 8: 'Sailing',
    11: 'Towing astern', 12: 'Towing alongside', 14: 'AIS-SART',
}

FADE_IN_OUT = [('visible', 'effect=fade start=0 end=100 time=%d' % CROSSFADE_MS),
               ('hidden', 'effect=fade start=100 end=0 time=%d' % CROSSFADE_MS)]


def log(message, level=xbmc.LOGINFO):
    xbmc.log('[%s] %s' % (config.ADDON_ID, message), level)


def localized(addon, sid):
    try:
        text = addon.getLocalizedString(sid)
    except Exception:
        text = ''
    return text or config.STRINGS.get(sid, '')


# -------------------------------------------------------------------------------------------
# Settings
# -------------------------------------------------------------------------------------------
def setting_getters(addon):
    """Typed getters on Kodi 19+, the string getter on anything older."""
    if hasattr(addon, 'getSettingNumber'):
        return {'boolean': addon.getSettingBool,
                'integer': addon.getSettingInt,
                'number': addon.getSettingNumber,
                'string': addon.getSettingString}

    def boolean(sid):
        return addon.getSetting(sid).strip().lower() in ('true', '1', 'yes')

    def integer(sid):
        text = addon.getSetting(sid).strip()
        try:
            return int(float(text))
        except ValueError:
            return 0

    def number(sid):
        text = addon.getSetting(sid).strip()
        try:
            return float(text)
        except ValueError:
            return 0.0

    def string(sid):
        return addon.getSetting(sid)

    return {'boolean': boolean, 'integer': integer, 'number': number, 'string': string}


# -------------------------------------------------------------------------------------------
# Photo files
# -------------------------------------------------------------------------------------------
def photo_extension(url):
    path = url.split('?', 1)[0].lower()
    for extension in ('.png', '.jpg', '.jpeg'):
        if path.endswith(extension):
            return extension
    return '.jpg'


def photo_path(folder, url):
    digest = hashlib.sha1(url.encode('utf-8')).hexdigest()[:16]
    return os.path.join(folder, 'photo_%s%s' % (digest, photo_extension(url)))


class PhotoJob(threading.Thread):
    """Download one photo to the cache. The display thread polls ``done``; it never blocks."""

    def __init__(self, folder, candidate, timeout=25):
        threading.Thread.__init__(self, name='shiptracker-photo')
        self.daemon = True
        self.folder = folder
        self.candidate = candidate
        self.url = candidate['url']
        self.timeout = timeout
        self.path = None
        self.error = None
        self.done = threading.Event()

    def run(self):
        try:
            path = photo_path(self.folder, self.url)
            if os.path.exists(path) and os.path.getsize(path) > 1000:
                self.path = path
                return
            body = net.fetch(self.url, timeout=self.timeout,
                             headers={'Accept': 'image/jpeg,image/png;q=0.9,*/*;q=0.5'},
                             max_bytes=PHOTO_MAX_BYTES)
            if len(body) < 1000:
                raise net.HttpError('%s: image too small' % net.short(self.url), 'http')
            if not os.path.isdir(self.folder):
                os.makedirs(self.folder, exist_ok=True)
            handle, temp = tempfile.mkstemp(prefix='.photo-', suffix='.tmp', dir=self.folder)
            try:
                with os.fdopen(handle, 'wb') as out:
                    out.write(body)
                os.replace(temp, path)
            except Exception:
                try:
                    os.remove(temp)
                except OSError:
                    pass
                raise
            self.path = path
        except Exception as error:
            self.error = error
        finally:
            self.done.set()


class MapJob(threading.Thread):
    """Fetch one area's satellite image without blocking the display thread."""

    def __init__(self, folder, bounds, width, height):
        threading.Thread.__init__(self, name='shiptracker-map')
        self.daemon = True
        self.folder = folder
        self.bounds = tuple(bounds)
        self.width = width
        self.height = height
        self.path = None
        self.error = None
        self.done = threading.Event()

    def run(self):
        try:
            self.path = mapimage.ensure_map(self.folder, self.bounds, self.width, self.height)
        except Exception as error:
            self.error = error
        finally:
            self.done.set()


# -------------------------------------------------------------------------------------------
# Window
# -------------------------------------------------------------------------------------------
class ExitMonitor(xbmc.Monitor):
    """Kodi waking the screensaver is a stop signal even when Python gets no action."""

    def __init__(self, on_wake):
        xbmc.Monitor.__init__(self)
        self.on_wake = on_wake

    def onScreensaverDeactivated(self):
        self.on_wake()


class SaverWindow(xbmcgui.WindowXMLDialog):
    def __init__(self, *args, **kwargs):
        self.app = kwargs['app']

    def onInit(self):
        self.app.attach(self)

    def onAction(self, _action):
        self.app.wake()
        return True


class Saver(object):
    def __init__(self):
        self.addon = xbmcaddon.Addon(config.ADDON_ID)
        self.path = self.addon.getAddonInfo('path')
        self.profile = xbmcvfs.translatePath(self.addon.getAddonInfo('profile'))
        self.photos = os.path.join(self.profile, 'photos')
        self.settings = config.read(setting_getters(self.addon))

        self.areas = config.enabled_areas(self.settings)
        self.area_index = 0
        self.current = self.areas[0] if self.areas else None
        self.box = self.current['box'] if self.current else None
        self.bounds = config.map_bounds(self.box[0], self.box[1], self.box[2], self.box[3],
                                        MAP_W, MAP_H) if self.box is not None else None
        self.area_seconds = config.area_seconds(self.settings)
        self.area_started = time.time()
        self.timeout = config.ship_timeout_seconds(self.settings)
        self.photo_seconds = config.photo_seconds(self.settings)
        self.brightness = config.map_brightness(self.settings)
        self.show_clock = bool(self.settings.get('show_clock', True))
        self.enrich = config.enrich_enabled(self.settings)
        self.debug_on = config.debug_enabled(self.settings)

        self.stop = threading.Event()
        self.monitor = ExitMonitor(self.wake)
        self.window = None
        self.thread = None
        self.started = time.time()

        self.store = None
        self.fleet = ais.Fleet()
        self.enricher = None
        self.tracker = None

        self.controls = None
        self.map_image = None
        self.map_overlay = None
        self.map_job = None
        self.map_attribution = None
        self.center_status = None
        self.markers = []
        self.marker_state = []
        self.marker_icon = []
        self.marker_colour = []

        self.clock_label = None
        self.area_label = None
        self.bbox_label = None
        self.status_label = None
        self.list_header = None
        self.row_names = []
        self.row_infos = []
        self.row_lines = []
        self.row_texts = [None] * ROWS
        self.row_shown = [False] * ROWS

        self.photo_images = []
        self.photo_front = 0
        self.photo_name = None
        self.photo_source = None
        self.photo_showing = None
        self.photo_job = None
        self.photo_ready = None
        self.photo_candidates = []
        self.photo_failed = set()
        self.photo_index = 0
        self.photo_next_at = 0.0
        self.photo_candidates_at = 0.0

        self.ships = []
        self.page = 0
        self.pages = 1
        self.page_started = 0.0
        self.clock_shown = None
        self.ships_at = 0.0
        self.status_at = 0.0
        self.clock_at = 0.0

    # ------------------------------------------------------------------ lifecycle
    def tr(self, sid):
        return localized(self.addon, sid)

    def run(self):
        """show() rather than doModal(): when Kodi itself wakes the screensaver it closes the
        window without telling Python, and doModal() then never returns."""
        window = SaverWindow('screensaver-shiptracker.xml', self.path, 'Default', '1080i', app=self)
        self.window = window
        try:
            window.show()
            started = time.time()
            while not self.stopped():
                if time.time() - started > 2.0 and \
                        not xbmc.getCondVisibility('System.ScreenSaverActive'):
                    break
                self.monitor.waitForAbort(0.2)
        finally:
            self.shutdown()

    def wake(self):
        self.stop.set()

    def stopped(self):
        return self.stop.is_set() or self.monitor.abortRequested()

    def shutdown(self):
        self.stop.set()
        if self.thread is not None:
            self.thread.join(2.5)
        for worker in (self.enricher, self.tracker):
            if worker is not None:
                try:
                    worker.stop()
                except Exception:
                    pass
        for worker in (self.tracker, self.enricher):
            if worker is not None:
                try:
                    worker.join(2.0)
                except Exception:
                    pass
        if self.store is not None:
            try:
                self.store.close()
            except Exception:
                pass
        window, self.window = self.window, None
        if window is not None:
            try:
                window.close()
            except Exception:
                pass
        log('screensaver closed after %.1f s' % (time.time() - self.started))

    def _debug(self, message):
        if self.debug_on:
            log(message, xbmc.LOGDEBUG)

    def _warn(self, message):
        log(message, xbmc.LOGWARNING)

    # ------------------------------------------------------------------ setup
    def _media(self, name):
        return os.path.join(self.path, 'resources', 'skins', 'Default', 'media', name)

    def _open_store(self):
        try:
            if not os.path.isdir(self.profile):
                os.makedirs(self.profile, exist_ok=True)
        except OSError:
            pass
        try:
            return store.Store(os.path.join(self.profile, 'ships.db'))
        except Exception as error:
            self._warn('database unavailable (%s); using memory for this run' % error)
            return store.Store(':memory:')

    def _start_workers(self):
        self.store = self._open_store()
        self.fleet.seed(self.store.load_ships())
        try:
            self.store.prune()
        except Exception:
            pass
        boxes = [area['box'] for area in self.areas]
        if self.enrich and boxes:
            self.enricher = sources.Enricher(self.store, enabled=True,
                                             debug=self._debug if self.debug_on else None)
            self.enricher.start()
        if boxes:
            self.tracker = tracker.Tracker(self.settings.get('api_key', ''), boxes, self.fleet,
                                           self.store, enricher=self.enricher,
                                           debug=self._debug if self.debug_on else None)
            self.tracker.start()

    # ------------------------------------------------------------------ controls
    def attach(self, window):
        if self.controls is not None or self.stopped():
            return

        backdrop = xbmcgui.ControlImage(-20, -20, W + 40, H + 40, self._media('sea.png'),
                                        aspectRatio=0)
        self.map_image = xbmcgui.ControlImage(MAP_X, MAP_Y, MAP_W, MAP_H, '', aspectRatio=0)
        self.map_overlay = xbmcgui.ControlImage(
            MAP_X, MAP_Y, MAP_W, MAP_H, self._media('white.png'), aspectRatio=0,
            colorDiffuse='%02XFFFFFF' % int(round(self.brightness / 100.0 * 255)))
        self.map_overlay.setVisible(False)

        self.markers = []
        for _ in range(MAX_MARKERS):
            marker = xbmcgui.ControlImage(0, 0, MARKER, MARKER, '', aspectRatio=0)
            marker.setVisible(False)
            self.markers.append(marker)
        self.marker_state = [None] * MAX_MARKERS
        self.marker_icon = [None] * MAX_MARKERS
        self.marker_colour = [None] * MAX_MARKERS

        self.ais_credit = xbmcgui.ControlLabel(
            24, 1004, 1360, 24, self.tr(32025), font='font10', textColor='B3FFFFFF')
        self.map_attribution = xbmcgui.ControlLabel(
            24, 1032, 1360, 26, self.tr(32014), font='font10', textColor='B3FFFFFF')
        self.center_status = xbmcgui.ControlLabel(
            0, 476, MAP_W, 90, '', font='font32', textColor='E6FFFFFF',
            alignment=ALIGN['center'])

        panel = xbmcgui.ControlImage(PANEL_X, 0, PANEL_W, H, self._media('white.png'),
                                     aspectRatio=0, colorDiffuse=PANEL_COLOUR)
        accent = xbmcgui.ControlImage(PANEL_X, 0, 3, H, self._media('white.png'),
                                      aspectRatio=0, colorDiffuse='8090CAE6')

        self.clock_label = xbmcgui.ControlLabel(X0 + INNER_W - CLOCK_W, 40, CLOCK_W, 56, '',
                                                font='font27', textColor='E6FFFFFF',
                                                alignment=ALIGN['right'])
        area_text = self.current['name'] if self.current else ''
        self.area_label = xbmcgui.ControlLabel(
            X0, 48, INNER_W - CLOCK_W - 12, 44, self._clip(area_text, 20),
            font='font27', textColor='FFFFFFFF')
        self.bbox_label = xbmcgui.ControlLabel(
            X0, 98, INNER_W, 30, config.box_label(self.box) if self.box else '', font='font12',
            textColor=FAINT)
        self.status_label = xbmcgui.ControlLabel(X0, 134, INNER_W, 32, '', font='font20',
                                                 textColor=ACCENT)

        divider = xbmcgui.ControlImage(X0, DIVIDER_Y, INNER_W, 1, self._media('white.png'),
                                       aspectRatio=0, colorDiffuse=LINE)
        self.list_header = xbmcgui.ControlLabel(X0, LIST_HEADER_Y, INNER_W, 28, '',
                                                font='font18', textColor=FAINT)

        for index in range(ROWS):
            y = ROW_Y + index * ROW_H
            line = xbmcgui.ControlImage(X0, y + 60, INNER_W, 1, self._media('white.png'),
                                        aspectRatio=0, colorDiffuse=LINE)
            name = xbmcgui.ControlLabel(X0, y, INNER_W, 30, '', font='font24',
                                        textColor='FFFFFFFF')
            info = xbmcgui.ControlLabel(X0, y + 30, INNER_W, 24, '', font='font13',
                                        textColor=DIM)
            for control in (line, name, info):
                control.setVisible(False)
            self.row_lines.append(line)
            self.row_names.append(name)
            self.row_infos.append(info)

        frame = xbmcgui.ControlImage(PHOTO_X, PHOTO_Y, PHOTO_W, PHOTO_H,
                                     self._media('photo_placeholder.png'), aspectRatio=0)
        self.photo_images = [
            xbmcgui.ControlImage(PHOTO_X, PHOTO_Y, PHOTO_W, PHOTO_H, '', aspectRatio=1),
            xbmcgui.ControlImage(PHOTO_X, PHOTO_Y, PHOTO_W, PHOTO_H, '', aspectRatio=1)]
        for image in self.photo_images:
            image.setAnimations(FADE_IN_OUT)
            image.setVisible(False)
        border = [
            xbmcgui.ControlImage(PHOTO_X, PHOTO_Y, PHOTO_W, 1, self._media('white.png'),
                                 aspectRatio=0, colorDiffuse=BORDER),
            xbmcgui.ControlImage(PHOTO_X, PHOTO_Y + PHOTO_H - 1, PHOTO_W, 1,
                                 self._media('white.png'), aspectRatio=0, colorDiffuse=BORDER),
            xbmcgui.ControlImage(PHOTO_X, PHOTO_Y, 1, PHOTO_H, self._media('white.png'),
                                 aspectRatio=0, colorDiffuse=BORDER),
            xbmcgui.ControlImage(PHOTO_X + PHOTO_W - 1, PHOTO_Y, 1, PHOTO_H,
                                 self._media('white.png'), aspectRatio=0, colorDiffuse=BORDER)]
        self.photo_name = xbmcgui.ControlLabel(PHOTO_X, PHOTO_NAME_Y, PHOTO_W, 30, '',
                                               font='font20', textColor='FFFFFFFF')
        self.photo_source = xbmcgui.ControlLabel(PHOTO_X, PHOTO_SOURCE_Y, PHOTO_W, 24, '',
                                                 font='font13', textColor=FAINT)
        self.photo_credit_pill = xbmcgui.ControlImage(
            CREDIT_X, CREDIT_Y, CREDIT_W, CREDIT_H, self._media('white.png'),
            aspectRatio=0, colorDiffuse='99000000')
        self.photo_credit = xbmcgui.ControlLabel(
            CREDIT_X, CREDIT_Y + 2, CREDIT_W, CREDIT_H - 4, self.tr(32019),
            font='font12', textColor='D9FFFFFF', alignment=ALIGN['center'])
        self.photo_credit_pill.setVisible(False)
        self.photo_credit.setVisible(False)

        self.controls = ([backdrop, self.map_image, self.map_overlay] + self.markers +
                         [self.ais_credit, self.map_attribution, self.center_status, panel, accent,
                          self.clock_label, self.area_label, self.bbox_label, self.status_label,
                          divider, self.list_header] +
                         self.row_lines + self.row_names + self.row_infos +
                         [frame] + self.photo_images + border +
                         [self.photo_credit_pill, self.photo_credit,
                          self.photo_name, self.photo_source])
        window.addControls(self.controls)

        if not self.show_clock:
            self.clock_label.setVisible(False)
        self._show_placeholder()
        self.photo_next_at = time.time() + 1.0

        self._start_workers()
        self.thread = threading.Thread(target=self._display_loop, name='shiptracker-display')
        self.thread.daemon = True
        self.thread.start()
        self._debug('attached: box %s, %d rows, %d markers'
                    % (self.box, ROWS, MAX_MARKERS))

    # ------------------------------------------------------------------ display loop
    def _display_loop(self):
        try:
            self._display()
        except Exception:
            log(traceback.format_exc(), xbmc.LOGERROR)

    def _display(self):
        self._request_map()
        while not self.stopped():
            now = time.time()
            self._tick(now)
            self.monitor.waitForAbort(LOOP_TICK)

    def _request_map(self):
        """Start fetching the current area's map; the display loop picks it up when ready."""
        if self.map_image is None:
            return
        if self.box is None:
            self.map_job = None
            self.map_image.setVisible(False)
            self.map_overlay.setVisible(False)
            return
        self.bounds = config.map_bounds(self.box[0], self.box[1], self.box[2], self.box[3],
                                        MAP_W, MAP_H)
        self.map_image.setVisible(False)
        self.map_overlay.setVisible(False)
        self.map_job = MapJob(self.profile, self.bounds, MAP_W, MAP_H)
        self.map_job.start()

    def _update_map(self):
        job = self.map_job
        if job is None or not job.done.is_set():
            return
        self.map_job = None
        if self.stopped() or self.map_image is None or job.bounds != self.bounds:
            return
        if job.path:
            try:
                self.map_image.setImage(job.path)
                self.map_image.setVisible(True)
                self.map_overlay.setVisible(self.brightness > 0)
                self.map_attribution.setLabel(self.tr(32014))
                self._debug('map ready: %s' % job.path)
                return
            except Exception:
                log(traceback.format_exc(), xbmc.LOGERROR)
        try:
            self.map_image.setVisible(False)
            self.map_overlay.setVisible(False)
            self.map_attribution.setLabel(self.tr(32017))
        except Exception:
            pass

    def _tick(self, now):
        if self._area_due(now):
            self._next_area(now)
        if now >= self.clock_at:
            self.clock_at = now + 1.0
            self._tick_clock()
        if now >= self.ships_at:
            self.ships_at = now + SHIPS_TICK
            self._refresh_ships(now)
        if now >= self.status_at:
            self.status_at = now + SHIPS_TICK
            self._update_status(now)
        self._update_map()
        self._update_photo(now)

    def _area_due(self, now):
        return len(self.areas) > 1 and now - self.area_started >= self.area_seconds

    def _next_area(self, now):
        self.area_index = (self.area_index + 1) % len(self.areas)
        self._set_area(now)

    def _set_area(self, now):
        """Switch the map, labels, ships and photos to the area at ``area_index``."""
        self.current = self.areas[self.area_index]
        self.box = self.current['box']
        self.bounds = config.map_bounds(self.box[0], self.box[1], self.box[2], self.box[3],
                                        MAP_W, MAP_H)
        self.area_started = now
        self.ships = []
        self.page = 0
        self.pages = 1
        self.page_started = now
        self._update_markers([])
        self._update_list(now)
        self._reset_photos(now)
        self.area_label.setLabel(self._clip(self.current['name'], 20))
        self.bbox_label.setLabel(config.box_label(self.box))
        self._request_map()
        self._debug('area: %s %s' % (self.current['name'], self.box))

    def _tick_clock(self):
        if self.clock_label is None or not self.show_clock:
            return
        try:
            fmt = xbmc.getRegion('time') or '%H:%M'
        except Exception:
            fmt = '%H:%M'
        text = time.strftime(fmt)
        if text != self.clock_shown:
            self.clock_shown = text
            self.clock_label.setLabel(text)

    # ------------------------------------------------------------------ ships
    def _refresh_ships(self, now):
        if self.box is None:
            self.ships = []
        else:
            self.ships = [ship for ship in self.fleet.snapshot(now, self.timeout)
                          if config.in_box(ship, self.box)]
        self._update_markers(self.ships)
        self._update_list(now)

    def _update_markers(self, ships):
        states = []
        for ship in ships[:MAX_MARKERS]:
            try:
                x, y = config.project(ship['lat'], ship['lon'], self.bounds, MAP_W, MAP_H)
            except (KeyError, TypeError, ValueError, ZeroDivisionError):
                continue
            if not (-20.0 <= x <= MAP_W + 20.0 and -20.0 <= y <= MAP_H + 20.0):
                continue
            course = ship.get('heading')
            if course is None:
                course = ship.get('cog')
            states.append((ship.get('mmsi'), config.heading_index(course),
                           config.marker_colour(ship.get('ship_type')),
                           int(round(x - MARKER / 2.0)), int(round(y - MARKER / 2.0))))

        for index, control in enumerate(self.markers):
            state = states[index] if index < len(states) else None
            if state == self.marker_state[index]:
                continue
            self.marker_state[index] = state
            try:
                if state is None:
                    control.setVisible(False)
                    continue
                _mmsi, icon, colour, x, y = state
                if self.marker_icon[index] != icon:
                    self.marker_icon[index] = icon
                    control.setImage(self._media('ship_%02d.png' % icon))
                if self.marker_colour[index] != colour:
                    self.marker_colour[index] = colour
                    control.setColorDiffuse(colour)
                control.setPosition(x, y)
                control.setVisible(True)
            except Exception:
                log(traceback.format_exc(), xbmc.LOGERROR)
                return

    def _update_list(self, now):
        self.pages = max(1, (len(self.ships) + ROWS - 1) // ROWS)
        if self.page >= self.pages:
            self.page = 0
            self.page_started = now
        elif self.pages > 1 and now - self.page_started >= PAGE_SECONDS:
            self.page = (self.page + 1) % self.pages
            self.page_started = now

        start = self.page * ROWS
        page_ships = self.ships[start:start + ROWS]
        if self.ships:
            self.list_header.setVisible(True)
            self.list_header.setLabel(self.tr(32009) % (start + 1, start + len(page_ships),
                                                        len(self.ships)))
        else:
            self.list_header.setVisible(False)

        for index in range(ROWS):
            if index < len(page_ships):
                ship = page_ships[index]
                name = self._clip(ship.get('name') or 'MMSI %s' % ship.get('mmsi'), 34)
                info = self._ship_info(ship)
            else:
                name, info = '', ''
            if self.row_texts[index] != (name, info):
                self.row_texts[index] = (name, info)
                self.row_names[index].setLabel(name)
                self.row_infos[index].setLabel(info)
            visible = index < len(page_ships)
            if self.row_shown[index] != visible:
                self.row_shown[index] = visible
                self.row_lines[index].setVisible(visible)
                self.row_names[index].setVisible(visible)
                self.row_infos[index].setVisible(visible)

    def _ship_info(self, ship):
        parts = []
        country = config.mid_country(ship.get('mmsi'))
        if country:
            parts.append(country)
        ship_type = config.ship_type_text(ship.get('ship_type'))
        if ship_type:
            parts.append(ship_type)
        sog = ship.get('sog')
        if sog is not None:
            parts.append('%.1f kn' % sog)
        voyage = None
        destination = ship.get('destination')
        if destination:
            candidate = 'to %s' % destination
            if self._width(' · '.join(parts + [candidate])) <= INFO_WIDTH:
                voyage = candidate
        if voyage is None:
            try:
                status = int(ship.get('nav_status'))
            except (TypeError, ValueError):
                status = None
            voyage = SHORT_NAV.get(status) or config.nav_status_text(status)
        if voyage:
            parts.append(voyage)
        length = ship.get('length')
        if length:
            parts.append('%d m' % int(round(length)))
        age = ship.get('age') or 0
        if age > 600:
            parts.append(self.tr(32016) % self._duration(age))
        return self._fit(parts) or self.tr(32013)

    def _fit(self, parts):
        """Join whole parts while their estimated width fits; a long part is dropped, not cut.

        Character counts lie: 'Canada · Cargo · 0.0 kn · Moored' and 'United States · 0.0 kn ·
        Moored' are both 32 characters, but the first is wider and ran past the row. Widths are
        crude per-glyph estimates calibrated against font13 at 1080p.
        """
        chosen, size = [], 0
        for part in parts:
            part = str(part)
            cost = self._width(part) + (self._width(' · ') if chosen else 0)
            if size + cost > INFO_WIDTH:
                continue
            chosen.append(part)
            size += cost
        return ' · '.join(chosen)

    @staticmethod
    def _width(text):
        """Approximate pixel width at font13, a little generous to leave a right margin."""
        total = 0
        for char in str(text):
            if char == ' ':
                total += 8
            elif char.isupper():
                total += 22
            elif char.isdigit():
                total += 17
            elif char in 'iljtfr.,;:\'"!|·-()[]':
                total += 9
            else:
                total += 17
        return total

    # ------------------------------------------------------------------ status
    def _update_status(self, now):
        if not self.areas:
            panel = self.tr(32022)
            self.status_label.setLabel(self.tr(32024))
            if self.center_status is not None:
                self.center_status.setLabel(panel)
                self.center_status.setVisible(True)
            return
        snapshot = self.tracker.snapshot() if self.tracker is not None else {
            'state': 'idle', 'messages': 0, 'last_message_at': 0.0}
        state = snapshot.get('state')
        count = len(self.ships)

        if state == 'no_key':
            panel = self.tr(32021)
        elif state in ('connecting', 'idle'):
            panel = self.tr(32000)
        elif state == 'error':
            panel = self.tr(32004)
        elif snapshot.get('last_message_at') and \
                now - snapshot['last_message_at'] > 180:
            panel = self.tr(32005)
        elif not snapshot.get('messages'):
            panel = self.tr(32002)
        else:
            panel = '● ' + self.tr(32006) + '  ·  ' + self._count_text(count)
        self.status_label.setLabel(self._clip(panel, 70))

        if count:
            center = ''
        elif self.map_job is not None:
            center = self.tr(32023)
        elif state == 'no_key':
            center = self.tr(32001)
        elif state == 'error':
            center = self.tr(32004)
        elif state in ('connecting', 'idle'):
            center = self.tr(32000)
        elif not snapshot.get('messages'):
            center = self.tr(32002)
        else:
            center = self.tr(32003)
        if self.center_status is not None:
            self.center_status.setLabel(center)
            self.center_status.setVisible(bool(center))

    def _count_text(self, count):
        return (self.tr(32007) if count == 1 else self.tr(32008)) % count

    # ------------------------------------------------------------------ photos
    def _reset_photos(self, now):
        """Forget the previous area's candidates and clear the frame for the new one."""
        self.photo_candidates = []
        self.photo_candidates_at = 0.0
        self.photo_index = 0
        self.photo_ready = None
        self.photo_job = None
        self.photo_showing = None
        self._show_placeholder()
        self.photo_next_at = now + 1.0

    def _update_photo(self, now):
        if self.photo_name is None:
            return
        if now - self.photo_candidates_at >= 10.0:
            self.photo_candidates_at = now
            self._rebuild_candidates()

        if not self.photo_candidates:
            self._show_placeholder()
            self.photo_next_at = now + 10.0
            return
        if self.photo_showing == 'placeholder':
            self.photo_source.setLabel(self.tr(32018))

        if self.photo_job is not None and self.photo_job.done.is_set():
            job, self.photo_job = self.photo_job, None
            if job.path:
                self.photo_ready = (job.candidate, job.path)
            else:
                self.photo_failed.add(job.candidate['url'])
                self._debug('photo failed: %s (%s)' % (job.candidate['url'], job.error))

        if self.photo_ready is not None and now >= self.photo_next_at:
            candidate, path = self.photo_ready
            self.photo_ready = None
            self._show_photo(candidate, path)
            self.photo_next_at = now + self.photo_seconds

        if self.photo_job is None and self.photo_ready is None:
            self._start_photo_job(now)

    def _rebuild_candidates(self):
        self.photo_candidates = []
        if not self.enrich or self.enricher is None:
            return
        seen = set()
        for ship in self.ships:
            profile = self.enricher.profile(ship.get('mmsi'))
            if not profile:
                continue
            name = (ship.get('name') or profile.get('name')
                    or 'MMSI %s' % ship.get('mmsi'))
            for photo in profile.get('photos') or []:
                url = photo.get('thumb') or photo.get('url')
                if not url or url in seen:
                    continue
                seen.add(url)
                self.photo_candidates.append({'url': url, 'name': name, 'profile': profile})
                if len(self.photo_candidates) >= PHOTO_CANDIDATES_MAX:
                    return

    def _start_photo_job(self, now):
        candidate = self._next_candidate()
        if candidate is None:
            self.photo_next_at = now + 15.0
            if self.photo_candidates and \
                    all(item['url'] in self.photo_failed for item in self.photo_candidates):
                self.photo_failed.clear()
                self.photo_next_at = now + 60.0
            return
        self.photo_job = PhotoJob(self.photos, candidate)
        self.photo_job.start()

    def _next_candidate(self):
        total = len(self.photo_candidates)
        for _ in range(total):
            candidate = self.photo_candidates[self.photo_index % total]
            self.photo_index = (self.photo_index + 1) % total
            if candidate['url'] in self.photo_failed:
                continue
            if candidate['url'] == self.photo_showing:
                continue
            if self.photo_ready is not None and candidate['url'] == self.photo_ready[0]['url']:
                continue
            return candidate
        return None

    def _show_photo(self, candidate, path):
        slot = 1 - self.photo_front
        coming, going = self.photo_images[slot], self.photo_images[self.photo_front]
        coming.setImage(path)
        coming.setVisible(True)
        going.setVisible(False)
        self.photo_front = slot
        self.photo_showing = candidate['url']
        self.photo_name.setLabel(self._clip(candidate.get('name'), 30))
        self.photo_source.setLabel(self._photo_caption(candidate.get('profile')))
        self.photo_credit_pill.setVisible(True)
        self.photo_credit.setVisible(True)
        self._debug('photo: %s' % candidate.get('name'))

    def _show_placeholder(self):
        if self.photo_showing == 'placeholder':
            return
        slot = 1 - self.photo_front
        coming, going = self.photo_images[slot], self.photo_images[self.photo_front]
        coming.setImage(self._media('photo_placeholder.png'))
        coming.setVisible(True)
        going.setVisible(False)
        self.photo_front = slot
        self.photo_showing = 'placeholder'
        self.photo_name.setLabel('')
        self.photo_source.setLabel(self.tr(32010))
        self.photo_credit_pill.setVisible(False)
        self.photo_credit.setVisible(False)

    def _photo_caption(self, profile):
        profile = profile or {}
        bits = []
        for key in ('owner', 'operator', 'builder'):
            value = profile.get(key)
            if isinstance(value, (list, tuple)):
                value = value[0] if value else None
            if value:
                value = str(value)
                for long, short in ((' Company', ' Co.'), (' Corporation', ' Corp.'),
                                    (' Incorporated', ' Inc.')):
                    value = value.replace(long, short)
                bits.append(value)
                break
        year = profile.get('built_year')
        if year:
            bits.append(str(year))
        if not bits:
            vessel_class = profile.get('vessel_class')
            if isinstance(vessel_class, (list, tuple)):
                vessel_class = vessel_class[0] if vessel_class else None
            if vessel_class:
                bits.append(str(vessel_class))
        return self._clip(' · '.join(bits), 26) if bits else ''

    # ------------------------------------------------------------------ text helpers
    def _clip(self, text, limit):
        text = '' if text is None else ' '.join(str(text).split())
        if len(text) <= limit:
            return text
        return text[:max(0, limit - 1)] + '…'

    def _duration(self, seconds):
        seconds = int(max(0, seconds))
        if seconds < 90:
            return '%d s' % seconds
        minutes = (seconds + 30) // 60
        if minutes < 90:
            return '%d min' % minutes
        hours, rest = divmod(minutes, 60)
        return '%d h %d min' % (hours, rest) if rest else '%d h' % hours


# -------------------------------------------------------------------------------------------
# Entry points
# -------------------------------------------------------------------------------------------
def clear_cache():
    """Delete the ship database, the maps and the photo cache; the next run refills them."""
    addon = xbmcaddon.Addon(config.ADDON_ID)
    profile = xbmcvfs.translatePath(addon.getAddonInfo('profile'))
    removed = 0
    for name in ('ships.db', 'ships.db-wal', 'ships.db-shm'):
        try:
            os.remove(os.path.join(profile, name))
            removed += 1
        except OSError:
            pass
    removed += mapimage.clear(profile)
    photos = os.path.join(profile, 'photos')
    try:
        names = os.listdir(photos)
    except OSError:
        names = []
    for name in names:
        if name.startswith('photo_'):
            try:
                os.remove(os.path.join(photos, name))
                removed += 1
            except OSError:
                pass
    log('cleared %d cached files' % removed)
    try:
        xbmcgui.Dialog().notification(config.ADDON_NAME, localized(addon, 32012), time=5000)
    except Exception:
        pass


def run():
    try:
        Saver().run()
    except Exception:
        log(traceback.format_exc(), xbmc.LOGERROR)
