"""The screensaver window: map pages with frame stacks, pooled panel pages, the overlay.

Kodi draws controls in the order they were added and Python can't reorder them, so every
control is created once at start, bottom to top: map pages, two panel pages (so one can
crossfade into the other), the overlay, then the splash. Radar frames are
pre-loaded images in a fixed stack of slots; playback only toggles visibility, so textures
load once and the loop stays smooth on a Raspberry Pi.

Threads: the data thread runs the hub and the radar feeds (network and file work only, no
GUI calls); the player thread advances frames, switches scenes and updates the overlay.
"""

import os
import threading
import time
import traceback

import xbmc
import xbmcaddon
import xbmcgui
import xbmcvfs

from . import budget as budget_mod
from . import cache, config, geo, hub as hub_mod, net, player, radar, scenes, splash, units
from .scenes.common import Context
from .sources import basemap, gibs as gibs_mod
from .sources import nws as nws_mod
from .workers import Workers

ADDON_ID = config.ADDON_ID
W, H = 1920, 1080
FONTS = {'xs': 'font10', 'sm': 'font13', 'md': 'font37', 'lg': 'font45', 'xl': 'font60'}
ALIGN = {'left': 0, 'right': 1, 'center': 2}
# Labels per (font, alignment) and images in each panel page.
POOL = {('xs', 'left'): 60, ('xs', 'center'): 60, ('xs', 'right'): 40, ('sm', 'left'): 40,
        ('sm', 'center'): 30, ('sm', 'right'): 12, ('md', 'left'): 16, ('md', 'center'): 20, ('md', 'right'): 4,
        ('lg', 'left'): 12, ('lg', 'center'): 20, ('lg', 'right'): 4, ('xl', 'left'): 6, ('xl', 'center'): 8,
        ('xl', 'right'): 2}
IMAGES = 140
FADE_MS = 700
FRAME_FADE_MS = 120
TICK = 0.05
ACCENT = 'FF4FC3F7'
NOW_COLOR = 'FFFFFFFF'
PAST_COLOR = 'FF4FC3F7'
FUTURE_COLOR = 'FFCE93D8'
PENDING_COLOR = 'FF5A6472'


def log(message, level=xbmc.LOGINFO):
    xbmc.log('[%s] %s' % (ADDON_ID, message), level)


def debug(message):
    log(message, xbmc.LOGDEBUG)


def read_settings(addon):
    return config.read({'boolean': addon.getSettingBool, 'integer': addon.getSettingInt,
                        'number': addon.getSettingNumber, 'string': addon.getSetting})


def detect_profile(s):
    choice = s.get('profile', 0)
    if choice:
        return ['', 'low', 'balanced', 'high'][choice]
    # Kodi on Android also reports System.Platform.Linux.RaspberryPi, so check Android first.
    if xbmc.getCondVisibility('System.Platform.Android'):
        return 'balanced'
    if xbmc.getCondVisibility('System.Platform.Linux.RaspberryPi'):
        return 'low'
    res = xbmc.getInfoLabel('System.ScreenResolution') or ''
    if '3840' in res or '2160' in res:
        return 'high'
    return 'balanced'


def transition_anims(mode, ms=FADE_MS):
    if mode == 2:
        return []
    if mode == 1:
        return [('visible', 'effect=slide start=1920,0 end=0,0 time=%d tween=cubic easing=out' % ms),
                ('hidden', 'effect=slide start=0,0 end=-1920,0 time=%d tween=cubic easing=in' % ms)]
    return [('visible', 'effect=fade start=0 end=100 time=%d' % ms),
            ('hidden', 'effect=fade start=100 end=0 time=%d' % ms)]


def rotate_anim(degrees):
    # Kodi rotates counter-clockwise for positive angles; compass bearings go clockwise.
    return ('conditional', 'effect=rotate end=%d center=auto time=0 condition=true' % (-degrees))


class ExitMonitor(xbmc.Monitor):
    def __init__(self, app):
        xbmc.Monitor.__init__(self)
        self.app = app

    def onScreensaverDeactivated(self):
        if not self.app.as_script:
            # Kodi stops a Python screensaver about 5 s after waking it. In interactive mode
            # SkyWatch reopens straight away as an ordinary script window, which Kodi leaves alone.
            self.app.relaunch = bool(self.app.settings.get('interactive'))
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
        self.app.on_action(action)


# ---------------------------------------------------------------- pages

class Page(object):
    """A set of controls shown and hidden together."""

    def __init__(self, app):
        self.app = app
        self.controls = []
        self.shown = False

    def set_anims(self, anims):
        for c in self.controls:
            c.setAnimations(anims)


class MapPage(Page):
    def __init__(self, app, spec, feed, base, labels, capacity):
        Page.__init__(self, app)
        self.spec = spec
        self.feed = feed
        self.base_src, self.label_src = base, labels
        self.view = spec.view
        s = app.settings
        n = self.view.max_tiles()
        media = app.media_path
        self.bg_tiles = [xbmcgui.ControlImage(0, 0, 256, 256, '') for _ in range(n)]
        self.sat = xbmcgui.ControlImage(0, 0, W, H, '', aspectRatio=0) if spec.satellite else None
        alpha = int((spec.radar_alpha or s.get('radar_opacity', 75)) * 255 / 100)
        self.radar_diffuse = '%02XFFFFFF' % alpha
        self.slots = [[xbmcgui.ControlImage(0, 0, W, H, '', aspectRatio=0, colorDiffuse=self.radar_diffuse)
                       for _ in range(capacity)] for _ in range(feed.max_frames)]
        self.slot_frame = [None] * len(self.slots)       # frame key loaded in each slot
        self.slot_parts = [0] * len(self.slots)
        self.warn = xbmcgui.ControlImage(0, 0, W, H, '', aspectRatio=0) if spec.warnings else None
        self.label_tiles = [xbmcgui.ControlImage(0, 0, 256, 256, '') for _ in range(n)] \
            if s.get('labels_above', True) and labels is not None else []
        self.pin = xbmcgui.ControlImage(0, 0, 64, 64, media('pin.png'), colorDiffuse='FFFFFFFF')
        self.top_fade = xbmcgui.ControlImage(0, 0, W, 300, media('fade.png'), aspectRatio=0, colorDiffuse='D0000000')
        self.bottom_fade = xbmcgui.ControlImage(0, H - 200, W, 200, media('fade_up.png'), aspectRatio=0,
                                                colorDiffuse='D0000000')
        self.accent = xbmcgui.ControlImage(96, 66, 8, 64, media('white.png'), colorDiffuse=ACCENT)
        self.title = xbmcgui.ControlLabel(126, 58, 1100, 70, scenes.TITLES.get(spec.id, ''), font=FONTS['xl'])
        self.subtitle = xbmcgui.ControlLabel(128, 136, 980, 40, '', font=FONTS['sm'], textColor='FFC9D4E0')
        # Timeline: PAST / NOW / FUTURE with a cursor at the frame shown.
        self.tl_x, self.tl_y, self.tl_w = 96, 1012, 700
        self.track = xbmcgui.ControlImage(self.tl_x, self.tl_y, self.tl_w, 10, media('pill.png'),
                                          colorDiffuse='40FFFFFF')
        self.past_bar = xbmcgui.ControlImage(self.tl_x, self.tl_y, 10, 10, media('pill.png'), colorDiffuse=PAST_COLOR)
        self.future_bar = xbmcgui.ControlImage(self.tl_x, self.tl_y, 10, 10, media('pill.png'),
                                               colorDiffuse=FUTURE_COLOR)
        self.now_tick = xbmcgui.ControlImage(self.tl_x, self.tl_y - 10, 4, 30, media('white.png'),
                                             colorDiffuse=NOW_COLOR)
        self.cursor = xbmcgui.ControlImage(self.tl_x, self.tl_y - 9, 28, 28, media('dot.png'), colorDiffuse='FFFFFFFF')
        self.lbl_past = xbmcgui.ControlLabel(self.tl_x, self.tl_y - 44, 200, 30, 'PAST', font=FONTS['xs'],
                                             textColor='C0FFFFFF')
        self.lbl_now = xbmcgui.ControlLabel(self.tl_x, self.tl_y - 44, 120, 30, 'NOW', font=FONTS['xs'],
                                            textColor='FFFFFFFF', alignment=ALIGN['center'])
        self.lbl_future = xbmcgui.ControlLabel(self.tl_x + self.tl_w - 400, self.tl_y - 44, 400, 30, 'FUTURE',
                                               font=FONTS['xs'], textColor='C0FFFFFF', alignment=ALIGN['right'])
        self.frame_time = xbmcgui.ControlLabel(self.tl_x + self.tl_w + 30, self.tl_y - 30, 560, 50, '',
                                               font=FONTS['md'])
        # Legend, bottom right.
        legend = 'legend_ptype.png' if s.get('color_scheme') == 1 and spec.future else 'legend_dbz.png'
        self.legend = xbmcgui.ControlImage(W - 96 - 420, 1004, 420, 18, media(legend), aspectRatio=0)
        if legend == 'legend_dbz.png':
            text = ['5', '25', '45', '65 dBZ']
        else:
            text = ['Rain', 'Snow', 'Freezing', 'Ice']
        self.legend_labels = [xbmcgui.ControlLabel(W - 96 - 420 + k * 140 - 10, 968, 200, 30, t, font=FONTS['xs'],
                                                   textColor='C0FFFFFF') for k, t in enumerate(text)]
        show_legend = s.get('ov_legend', True)
        frames = [c for slot in self.slots for c in slot]
        self.frame_controls = frames
        self.chrome = [self.top_fade, self.bottom_fade, self.accent, self.title, self.subtitle, self.track,
                       self.past_bar, self.future_bar, self.now_tick, self.cursor, self.lbl_past, self.lbl_now,
                       self.lbl_future, self.frame_time]
        if show_legend:
            self.chrome += [self.legend] + self.legend_labels
        self.controls = (self.bg_tiles + ([self.sat] if self.sat else []) + frames + ([self.warn] if self.warn else [])
                         + self.label_tiles + [self.pin] + self.chrome)
        self.static = [c for c in self.controls if c not in frames]
        self.tile_state = {}
        self.frames = []            # ready frames in playback order: (frame dict, slot)
        self.index = 0
        self.next_step = 0.0
        self.feed_version = -1
        self.visible_slot = None
        self.sat_path = self.warn_path = None
        self.paused = False
        self.timeline_state = None

    # ------------------------------------------------------------ setup

    def after_add(self, anims, smooth):
        for c in self.controls:
            c.setVisible(False)
        self.page_anims = anims
        for c in self.static:
            c.setAnimations(anims)
        frame_anims = [('visible', 'effect=fade start=0 end=100 time=%d' % FRAME_FADE_MS),
                       ('hidden', 'effect=fade start=100 end=0 time=%d' % FRAME_FADE_MS)] if smooth else []
        for c in self.frame_controls:
            c.setAnimations(frame_anims)
        x, y = self.view.screen_xy(self.app.settings['lat'], self.app.settings['lon'])
        self.pin_visible = 0 <= x <= W and 0 <= y <= H
        self.pin.setPosition(int(x - 32), int(y - 32))

    def retarget(self, spec, feed):
        """Interactive zoom: the same controls for a new view."""
        self.spec, self.feed, self.view = spec, feed, spec.view
        self.tile_state = {}
        self.slot_frame = [None] * len(self.slots)
        self.frames = []
        self.feed_version = -1
        for slot in self.slots:
            for c in slot:
                c.setVisible(False)
        for c in self.bg_tiles + self.label_tiles:
            c.setVisible(False)
        x, y = self.view.screen_xy(self.app.settings['lat'], self.app.settings['lon'])
        self.pin_visible = 0 <= x <= W and 0 <= y <= H
        self.pin.setPosition(int(x - 32), int(y - 32))
        self.refresh_tiles()
        self.sync_frames(force=True)
        self.show()

    def refresh_tiles(self):
        """Point tile controls at tiles that are on disk; returns the share of base tiles drawn."""
        drawn = wanted = 0
        for src, pool in ((self.base_src, self.bg_tiles), (self.label_src, self.label_tiles)):
            if not pool or src is None:
                continue
            plan = self.view.tiles_at(src.max_zoom)
            for k, ctrl in enumerate(pool):
                target = None
                if k < len(plan):
                    z, tx, ty, sx, sy, size = plan[k]
                    path = self.app.tiles.ensure(src, z, tx, ty)
                    if path:
                        target = (path, sx, sy, size)
                    if src is self.base_src:
                        wanted += 1
                key = (id(pool), k)
                old = self.tile_state.get(key)
                if target == old:
                    if target and src is self.base_src:
                        drawn += 1
                    continue
                if target is None:
                    ctrl.setVisible(False)
                else:
                    ctrl.setImage(target[0], False)
                    ctrl.setPosition(target[1], target[2])
                    ctrl.setWidth(target[3])
                    ctrl.setHeight(target[3])
                    if self.shown:
                        ctrl.setVisible(True)
                    if src is self.base_src:
                        drawn += 1
                self.tile_state[key] = target
        return drawn / float(wanted or 1)

    def set_overlay_images(self):
        if self.sat is not None and self.app.sat_file.get(self.spec.id) and \
                self.app.sat_file[self.spec.id] != self.sat_path:
            self.sat_path = self.app.sat_file[self.spec.id]
            self.sat.setImage(self.sat_path, False)
            if self.shown:
                self.sat.setVisible(True)
        if self.warn is not None and self.app.warn_file.get(self.spec.id) != self.warn_path:
            self.warn_path = self.app.warn_file.get(self.spec.id)
            if self.warn_path:
                self.warn.setImage(self.warn_path, False)
            if self.shown:
                self.warn.setVisible(bool(self.warn_path))

    # ------------------------------------------------------------ frames

    def sync_frames(self, force=False):
        """Load new frames into free slots. Called at the NOW pause (or when nothing plays),
        so a texture is never swapped mid-loop."""
        if self.feed.version == self.feed_version and not force:
            return
        self.feed_version = self.feed.version
        ready = self.feed.ready[-len(self.slots):]
        keys = [f['key'] for f in ready]
        keep = dict((self.slot_frame[i], i) for i in range(len(self.slots)) if self.slot_frame[i] in keys)
        free = [i for i in range(len(self.slots)) if self.slot_frame[i] not in keys]
        order = []
        for f in ready:
            slot = keep.get(f['key'])
            if slot is None:
                if not free:
                    continue
                slot = free.pop(0)
                self._load(slot, f)
            order.append((f, slot))
        for i in free:
            if self.slot_frame[i] is not None and i != self.visible_slot:
                for c in self.slots[i]:
                    c.setVisible(False)
                self.slot_frame[i] = None
        current = self.frames[self.index][0]['key'] if self.frames and self.index < len(self.frames) else None
        self.frames = order
        self.index = next((k for k, (f, _s) in enumerate(order) if f['key'] == current), self.now_index())
        self.timeline_state = None

    def _load(self, slot, frame):
        controls = self.slots[slot]
        files = frame['files']
        for k, c in enumerate(controls):
            if k < len(files):
                path, x, y, w, h = files[k]
                c.setImage(path, False)
                c.setPosition(int(x), int(y))
                c.setWidth(int(w))
                c.setHeight(int(h))
            else:
                c.setVisible(False)
        self.slot_frame[slot] = frame['key']
        self.slot_parts[slot] = min(len(files), len(controls))

    def now_index(self):
        past = [k for k, (f, _s) in enumerate(self.frames) if f['kind'] == 'past']
        return past[-1] if past else 0

    def show_slot(self, slot):
        if slot == self.visible_slot:
            return
        if slot is not None:
            for c in self.slots[slot][:self.slot_parts[slot]]:
                c.setVisible(True)
        if self.visible_slot is not None:
            for c in self.slots[self.visible_slot]:
                c.setVisible(False)
        self.visible_slot = slot

    def tick(self, now):
        """Advance the loop: frame rate from settings, pause on NOW, longer pause at the end."""
        if not self.frames or self.paused:
            if not self.frames:
                self.sync_frames()
            return
        if now < self.next_step:
            return
        fps = max(1.0, self.app.settings.get('fps', 5) * self.spec.fps_factor)
        k = self.index
        frame, slot = self.frames[k]
        self.show_slot(slot)
        self.update_timeline(frame)
        hold = 1.0 / fps
        if k == self.now_index() and self.app.settings.get('now_pause', 15):
            hold = max(hold, self.app.settings['now_pause'] / 10.0)
        if k == len(self.frames) - 1:
            hold = max(hold, 1.2)
        self.next_step = now + hold
        self.index = k + 1
        if self.index >= len(self.frames):
            self.index = 0
        if k == self.now_index():
            self.sync_frames()

    def update_timeline(self, frame):
        frames = [f for f, _s in self.frames]
        if not frames:
            return
        t0 = frames[0]['t']
        future_state = self.feed.future_state
        future_end = frames[-1]['t']
        if future_state == 'pending':
            future_end = max(future_end, time.time() + self.spec.future * 60)
        span = max(1.0, future_end - t0)
        now_frame = frames[self.now_index()]
        nx = self.tl_x + self.tl_w * (now_frame['t'] - t0) / span
        state = (t0, future_end, now_frame['key'], future_state)
        if state != self.timeline_state:
            self.timeline_state = state
            self.past_bar.setWidth(max(10, int(nx - self.tl_x)))
            has_future = self.spec.future > 0
            self.future_bar.setPosition(int(nx), self.tl_y)
            self.future_bar.setWidth(max(10, int(self.tl_x + self.tl_w - nx)))
            self.future_bar.setColorDiffuse(FUTURE_COLOR if future_state == 'ok' else PENDING_COLOR)
            self.future_bar.setVisible(self.shown and has_future)
            self.now_tick.setPosition(int(nx) - 2, self.tl_y - 10)
            self.lbl_now.setPosition(int(nx) - 60, self.tl_y - 44)
            self.lbl_future.setLabel('' if not has_future else
                                     ('FUTURE' if future_state == 'ok' else 'FUTURE · model update pending'))
            self.lbl_past.setLabel('PAST' if self.spec.past else '')
            if not self.spec.past:
                self.lbl_now.setLabel('')
        x = self.tl_x + self.tl_w * (frame['t'] - t0) / span
        self.cursor.setPosition(int(x) - 14, self.tl_y - 9)
        u = self.app.units
        when = u.clock(frame['t'])
        if frame['kind'] == 'future':
            ahead = int(round((frame['t'] - time.time()) / 60.0))
            rel = '+%d h %02d min' % (ahead // 60, ahead % 60) if ahead >= 60 else '+%d min' % max(0, ahead)
            tag = '[COLOR FFFFB74D]MODEL[/COLOR]' if frame.get('model') else '[COLOR FFCE93D8]NOWCAST[/COLOR]'
            self.frame_time.setLabel('%s   %s   %s' % (when, rel, tag))
        else:
            ago = int(round((time.time() - frame['t']) / 60.0))
            self.frame_time.setLabel('%s   [COLOR B0FFFFFF]%d min ago[/COLOR]' % (when, ago) if ago > 2 else
                                     '%s   [COLOR B0FFFFFF]latest[/COLOR]' % when)
        self.subtitle.setLabel(self.app.subtitle_for(self.spec, frame))

    # ------------------------------------------------------------ show / hide

    def show(self):
        self.shown = True
        self.refresh_tiles()
        self.set_overlay_images()
        self.sync_frames(force=True)
        for k, c in enumerate(self.bg_tiles):
            c.setVisible(self.tile_state.get((id(self.bg_tiles), k)) is not None)
        for k, c in enumerate(self.label_tiles):
            c.setVisible(self.tile_state.get((id(self.label_tiles), k)) is not None)
        if self.sat is not None:
            self.sat.setVisible(bool(self.sat_path))
        if self.warn is not None:
            self.warn.setVisible(bool(self.warn_path))
        self.pin.setVisible(self.pin_visible)
        self.timeline_state = None
        for c in self.chrome:
            c.setVisible(True)
        self.future_bar.setVisible(self.spec.future > 0)
        self.index = 0 if self.spec.past == 0 else max(0, self.now_index() - max(0, len(self.frames) // 2))
        self.next_step = 0.0
        self.visible_slot = None

    def hide(self):
        self.shown = False
        for c in self.static:
            c.setVisible(False)
        self.show_slot(None)


class PanelPage(Page):
    """Pooled labels and images that any panel scene's Layout is mapped onto."""

    def __init__(self, app):
        Page.__init__(self, app)
        media = app.media_path
        self.bg = xbmcgui.ControlImage(0, 0, W, H, media('bg.jpg'), aspectRatio=0)
        self.images = [xbmcgui.ControlImage(0, 0, 10, 10, '') for _ in range(IMAGES)]
        self.labels = {}
        for (font, align), n in POOL.items():
            self.labels[(font, align)] = [xbmcgui.ControlLabel(0, 0, 10, 10, '', font=FONTS[font],
                                                               alignment=ALIGN[align]) for _ in range(n)]
        self.textbox = xbmcgui.ControlTextBox(96, 200, 1728, 800, font=FONTS['md'], textColor='FFE6EBF0')
        self.controls = [self.bg] + self.images + [c for pool in self.labels.values() for c in pool] + [self.textbox]
        self.used = []
        self.scene = None
        self.rotated = set()

    def after_add(self, anims):
        self.anims = anims
        for c in self.controls:
            c.setVisible(False)
            c.setAnimations(anims)

    def apply(self, lay):
        """Map the layout onto the pools; leaves everything hidden until show()."""
        media = self.app.media_path
        used = [self.bg]
        self.bg.setImage(media(lay.background))
        img_i = 0
        lbl_i = dict((k, 0) for k in self.labels)
        dropped = 0
        for item in lay.items:
            if item[0] == 'image':
                _k, x, y, w, h, path, color, aspect, rotate = item
                if img_i >= len(self.images) or w <= 0 or h <= 0:
                    dropped += 1
                    continue
                c = self.images[img_i]
                img_i += 1
                c.setImage(path if os.path.isabs(path) else media(path))
                c.setPosition(x, y)
                c.setWidth(w)
                c.setHeight(h)
                c.setColorDiffuse(color or 'FFFFFFFF')
                if rotate or id(c) in self.rotated:
                    c.setAnimations(self.anims + ([rotate_anim(rotate)] if rotate else []))
                    if rotate:
                        self.rotated.add(id(c))
                    else:
                        self.rotated.discard(id(c))
                used.append(c)
            else:
                _k, x, y, w, h, text, font, align, color = item
                key = (font, align)
                pool = self.labels.get(key)
                if pool is None or lbl_i[key] >= len(pool):
                    dropped += 1
                    continue
                c = pool[lbl_i[key]]
                lbl_i[key] += 1
                c.setPosition(x, y)
                c.setWidth(w)
                c.setHeight(h)
                c.setLabel('[COLOR %s]%s[/COLOR]' % (color, text) if color else text)
                used.append(c)
        if lay.textbox:
            x, y, w, h, text = lay.textbox
            self.textbox.setPosition(x, y)
            self.textbox.setWidth(w)
            self.textbox.setHeight(h)
            self.textbox.setText(text)
            self.textbox.autoScroll(6000, 2500, 5000)
            used.append(self.textbox)
        if dropped:
            log('%s: %d items did not fit the control pools' % (lay.title, dropped), xbmc.LOGWARNING)
        self.pending = used

    def show(self):
        self.shown = True
        for c in self.used:
            if c not in self.pending:
                c.setVisible(False)
        for c in self.pending:
            c.setVisible(True)
        self.used = self.pending

    def hide(self):
        self.shown = False
        for c in self.used:
            c.setVisible(False)


class Overlay(object):
    """Clock, date, location, data age, mini conditions, alert banner, attribution, debug."""

    def __init__(self, app):
        s = app.settings
        media = app.media_path
        self.app = app
        self.clock = xbmcgui.ControlLabel(1100, 56, 724, 74, '', font=FONTS['xl'], alignment=ALIGN['right'])
        self.info = xbmcgui.ControlLabel(824, 132, 1000, 40, '', font=FONTS['sm'], textColor='FFC9D4E0',
                                         alignment=ALIGN['right'])
        self.chip_icon = xbmcgui.ControlImage(0, 58, 72, 72, '')
        self.chip_temp = xbmcgui.ControlLabel(0, 56, 200, 74, '', font=FONTS['xl'], alignment=ALIGN['right'])
        self.banner = xbmcgui.ControlImage(0, 0, W, 52, media('white.png'), colorDiffuse='F0C62828')
        self.banner_text = xbmcgui.ControlLabel(96, 8, 1728, 40, '', font=FONTS['sm'])
        self.credits = xbmcgui.ControlLabel(96, 1046, 1728, 30, '', font=FONTS['xs'], textColor='70FFFFFF',
                                            alignment=ALIGN['center'])
        self.debug = xbmcgui.ControlLabel(20, 900, 900, 150, '', font=FONTS['xs'], textColor='FF69F0AE')
        self.controls = [self.chip_icon, self.chip_temp, self.clock, self.info, self.banner, self.banner_text,
                         self.credits, self.debug]
        self.state = {}
        self.chip_on = False
        self.s = s

    def after_add(self):
        for c in self.controls:
            c.setVisible(False)
        fade = [('visible', 'effect=fade time=400'), ('hidden', 'effect=fade time=400')]
        for c in (self.chip_icon, self.chip_temp, self.banner, self.banner_text):
            c.setAnimations(fade)
        s = self.s
        self.clock.setVisible(bool(s.get('ov_clock', True)))
        self.info.setVisible(True)
        self.credits.setVisible(bool(s.get('ov_credits', True)))
        self.debug.setVisible(bool(s.get('debug')))

    def set(self, control, key, text):
        if self.state.get(key) != text:
            self.state[key] = text
            control.setLabel(text)

    def update(self, scene, alerts, chip, info, credits, debug_text, shift=(0, 0)):
        s = self.s
        u = self.app.units
        if s.get('ov_clock', True):
            self.set(self.clock, 'clock', u.clock(time.time()))
            show_clock = scene != 'ambient'
            if self.state.get('clock_on') != show_clock:
                self.state['clock_on'] = show_clock
                self.clock.setVisible(show_clock)
        self.set(self.info, 'info', info)
        self.set(self.credits, 'credits', credits)
        if s.get('debug'):
            self.set(self.debug, 'debug', debug_text)
        # Mini conditions chip, left of the clock, on scenes that don't show conditions.
        want_chip = bool(chip) and s.get('ov_chip', True) and scene not in ('current', 'ambient', 'alert')
        if want_chip:
            icon_path, temp = chip
            clock_on = s.get('ov_clock', True) and scene != 'ambient'
            clock_w = 40 + 30 * len(self.state.get('clock', '')) if clock_on else 0
            x = 1824 - clock_w     # right edge of the temperature
            if self.state.get('chip') != (icon_path, temp, x):
                self.state['chip'] = (icon_path, temp, x)
                self.chip_temp.setLabel(temp)
                self.chip_temp.setPosition(x - 200, 56)
                self.chip_icon.setImage(self.app.media_path(icon_path))
                self.chip_icon.setPosition(x - 34 * len(temp) - 84, 58)
        if want_chip != self.chip_on:
            self.chip_on = want_chip
            self.chip_icon.setVisible(want_chip)
            self.chip_temp.setVisible(want_chip)
        # Alert banner.
        text = ''
        color = None
        if alerts:
            a = alerts[0]
            until = (' until %s' % u.clock(a['ends'])) if a.get('ends') else ''
            text = '[B]%s[/B]%s   ·   %s' % (a['event'].upper(), until, (a.get('area') or '')[:90])
            color = 'F0C62828' if a['level'] >= 3 else 'F0E08A00'
            if len(alerts) > 1:
                text += '   (+%d more)' % (len(alerts) - 1)
        if self.state.get('banner') != (text, color):
            self.state['banner'] = (text, color)
            self.banner_text.setLabel(text)
            if color:
                self.banner.setColorDiffuse(color)
            self.banner.setVisible(bool(text))
            self.banner_text.setVisible(bool(text))
        if self.state.get('shift') != shift:
            self.state['shift'] = shift
            dx, dy = shift
            self.clock.setPosition(1100 + dx, 56 + dy)
            self.info.setPosition(824 + dx, 132 + dy)
            self.credits.setPosition(96 + dx, 1046 + dy)


# ---------------------------------------------------------------- the app

INTERACTIVE_IDLE = 600   # an interactive window closes after 10 minutes without input


class App(object):
    def __init__(self, as_script=False):
        self.as_script = as_script
        self.relaunch = False
        self.last_input = time.time()
        self.addon = xbmcaddon.Addon(ADDON_ID)
        self.path = self.addon.getAddonInfo('path')
        self.media = os.path.join(self.path, 'resources', 'media')
        self.profile = xbmcvfs.translatePath(self.addon.getAddonInfo('profile'))
        if not os.path.isdir(self.profile):
            os.makedirs(self.profile)
        self.settings = s = read_settings(self.addon)
        self.units = units.Units(s)
        self.perf = detect_profile(s)
        net.set_contact(s.get('nws_email'))
        self.store = cache.JsonCache(os.path.join(self.profile, 'data.db'))
        self.budget = budget_mod.Budget(self.store)
        self.hub = hub_mod.Hub(s, self.store, self.budget, debug)
        self.place = s.get('location_name') or ('%.2f, %.2f' % (s['lat'], s['lon']))
        self.playlist = player.Playlist(s)
        self.stop = threading.Event()
        self.lock = threading.Lock()
        pool = 2 if self.perf == 'low' else 4
        self.data_pool = Workers(pool, 'sw-data', lambda e: log('data job: %s' % e, xbmc.LOGWARNING))
        self.radar_pool = Workers(pool, 'sw-radar', lambda e: log('radar job: %s' % e, xbmc.LOGWARNING))
        self.tiles = cache.TileStore(os.path.join(self.profile, 'tiles'), log=debug,
                                     counter=lambda sid: self.budget.count(sid))
        self.chains = radar.Chains(s)
        fc = self.hub.get('forecast')
        self.wind_from = self._steering_wind(fc)
        self.zoom = s['zoom']
        self.specs = scenes.map_specs(s, self.wind_from)
        self.feeds = {}
        self._feed_cache = {}
        size = radar.RESOLUTION[self.perf]
        for sid, spec in self.specs.items():
            self.feeds[sid] = self.make_feed(spec)
        self.size = size
        self.window = None
        self.splash = None
        self.monitor = ExitMonitor(self)
        self.sat_file = {}
        self.warn_file = {}
        self.thumb = None
        self.current = None
        self.current_page = None
        self.scene_end = 0.0
        self.started = time.time()
        self.offline_since = None
        self.frames_shown = 0
        self.last = {}

    # ------------------------------------------------------------ setup

    def media_path(self, name):
        return name if os.path.isabs(name) else os.path.join(self.media, name)

    def _steering_wind(self, fc):
        hourly = (fc or {}).get('hourly') or {}
        now = time.time()
        for t, d in zip(hourly.get('time') or [], hourly.get('wind_direction_850hPa') or []):
            if t >= now - 3600 and d is not None:
                return d
        return ((fc or {}).get('current') or {}).get('wind_direction_10m')

    def make_feed(self, spec):
        key = (spec.view.key(), spec.past, spec.future, spec.future_step, spec.past_step, spec.allow_rainbow)
        feed = self._feed_cache.get(key)
        if feed is None:
            feed = radar.Feed(spec.id, spec.view, self.chains, os.path.join(self.profile, 'frames'),
                              radar.RESOLUTION[self.perf], self.budget, debug, spec.past, spec.future,
                              radar.MAX_FRAMES[self.perf], spec.past_step, spec.future_step, spec.allow_rainbow)
            self._feed_cache[key] = feed
        return feed

    def capacity(self, spec):
        """Controls per frame slot: 1 for whole-view WMS images, more for tile sources."""
        v = spec.view
        n = 1
        wms_past = geo.inside(v.lat, v.lon, geo.IEM_NEXRAD) and not self.chains.libre
        if spec.past and not wms_past:
            n = max(n, v.max_tiles(self.chains.libre.max_zoom if self.chains.libre else 7))
        if spec.future and spec.allow_rainbow and self.chains.rainbow:
            n = max(n, v.max_tiles(max(0, v.zoom - 1)))
        if spec.future and self.chains.future_mode == 3 and self.chains.libre:
            n = max(n, v.max_tiles(self.chains.libre.max_zoom))
        return n

    def run(self):
        self.window = SaverWindow('screensaver-skywatch.xml', self.path, 'Default', '1080i', app=self)
        try:
            self.window.doModal()
        finally:
            self.shutdown()
        if self.relaunch:
            xbmc.executebuiltin('RunScript(%s,interactive)' % os.path.join(self.path, 'default.py'))

    def shutdown(self):
        self.stop.set()
        if self.splash:
            self.splash.close()
        deadline = time.time() + 1.5   # Kodi kills a screensaver that takes over 5 s to stop
        for t in getattr(self, 'threads', []):
            t.join(max(0.05, deadline - time.time()))
        self.data_pool.shutdown()
        self.radar_pool.shutdown()
        self.tiles.shutdown()
        try:
            self.budget.save()
        except Exception:
            pass
        xbmcgui.Window(10000).clearProperty('skywatch.active')
        del self.window
        del self.monitor

    def attach(self, window):
        started = time.time()
        s = self.settings
        anims = transition_anims(s.get('transition', 0))
        base, labels = basemap.layers(s.get('basemap', 0), retina=self.perf == 'high', key=s.get('map_key', ''))
        self.base_src, self.label_src = base, labels
        self.map_pages = {}
        for sid, spec in self.specs.items():
            self.map_pages[sid] = MapPage(self, spec, self.feeds[sid], base, labels, self.capacity(spec))
        self.panels = [PanelPage(self), PanelPage(self)]
        self.overlay = Overlay(self)
        # Dialog windows don't paint their XML background, so a black backdrop goes first.
        self.backdrop = xbmcgui.ControlImage(-20, -20, W + 40, H + 40, self.media_path('white.png'),
                                             colorDiffuse='FF05080D')
        controls = [self.backdrop]
        for page in self.map_pages.values():
            controls += page.controls
        for page in self.panels:
            controls += page.controls
        controls += self.overlay.controls
        window.addControls(controls)
        for page in self.map_pages.values():
            page.after_add(anims, s.get('smooth', True))
        for page in self.panels:
            page.after_add(anims)
        self.overlay.after_add()
        self.splash = splash.Splash(window, self.media, ACCENT, 12.0, log)
        xbmcgui.Window(10000).setProperty('skywatch.active', 'true')
        log('built %d controls in %.2f s (profile %s, scenes %s)' % (len(controls), time.time() - started, self.perf,
                                                                      ', '.join(self.specs)))
        self.threads = [threading.Thread(target=self.guard(self.data_loop), name='skywatch-data'),
                        threading.Thread(target=self.guard(self.player_loop), name='skywatch-player')]
        for t in self.threads:
            t.daemon = True
            t.start()

    def guard(self, fn):
        def run():
            try:
                fn()
            except Exception:
                log(traceback.format_exc(), xbmc.LOGERROR)
        return run

    def exit(self):
        if not self.stop.is_set():
            self.stop.set()
            if self.window:
                self.window.close()

    # ------------------------------------------------------------ input

    def on_action(self, action):
        if not self.as_script:
            self.relaunch = bool(self.settings.get('interactive'))
            self.exit()
            return
        self.last_input = time.time()
        aid = action.getId()
        if aid in (xbmcgui.ACTION_NAV_BACK, xbmcgui.ACTION_PREVIOUS_MENU, xbmcgui.ACTION_STOP):
            self.exit()
        elif aid in (xbmcgui.ACTION_MOVE_LEFT, xbmcgui.ACTION_MOVE_RIGHT):
            self.pending_skip = -1 if aid == xbmcgui.ACTION_MOVE_LEFT else 1
        elif aid in (xbmcgui.ACTION_MOVE_UP, xbmcgui.ACTION_MOVE_DOWN):
            self.pending_zoom = 1 if aid == xbmcgui.ACTION_MOVE_UP else -1
        elif aid in (xbmcgui.ACTION_SELECT_ITEM, xbmcgui.ACTION_PAUSE, xbmcgui.ACTION_PLAYER_PLAY):
            page = self.current_page
            if isinstance(page, MapPage):
                page.paused = not page.paused
            self.paused = not getattr(self, 'paused', False)

    # ------------------------------------------------------------ data thread

    def data_loop(self):
        last_prune = last_save = time.time()
        last_evict = 0.0
        while not self.stop.is_set():
            try:
                self.hub.run_due(self.data_pool.submit)
                for feed in set(self.feeds.values()):
                    feed.update(self.radar_pool.submit, self.stop)
                now = time.time()
                if 'satellite' in self.specs and now - self.last.get('sat', 0) > 600:
                    self.last['sat'] = now
                    self.data_pool.submit(self.fetch_satellite)
                if 'regional' in self.specs and self.specs['regional'].warnings and \
                        now - self.last.get('warn', 0) > 300:
                    self.last['warn'] = now
                    self.data_pool.submit(self.fetch_warnings)
                if self.settings.get('scene_ambient', 0) and now - self.last.get('thumb', 0) > 300:
                    self.last['thumb'] = now
                    self.data_pool.submit(self.fetch_thumb)
                if now - last_prune > 1800:
                    last_prune = now
                    for feed in set(self.feeds.values()):
                        feed.prune()
                    cache.remove_older(os.path.join(self.profile, 'thumbs'), 3 * 3600,
                                       keep=set(p for p in (self.thumb or ()) if p))
                if now - last_evict > 3600:
                    last_evict = now
                    cache.evict(self.profile, self.settings.get('cache_mb', 500) * 1024 * 1024, debug)
                if now - last_save > 300:
                    last_save = now
                    self.budget.save()
            except Exception:
                log(traceback.format_exc(), xbmc.LOGERROR)
            self.stop.wait(2.0)

    def fetch_satellite(self):
        spec = self.specs['satellite']
        src = self.chains.gibs
        if not src.covers(spec.view.lat, spec.view.lon):
            return
        size = radar.RESOLUTION[self.perf]
        for age in (30, 50, 80):
            url, t, day, _parts = src.image(spec.view, size, age)
            path = os.path.join(self.profile, 'frames', 'gibs', '%s_%d.%s' % (spec.view.key(), t,
                                                                              'jpg' if day else 'png'))
            try:
                if not os.path.exists(path):
                    body = net.fetch_image(url, timeout=20)
                    if len(body) < 2000:
                        continue   # an empty image: not processed yet
                    cache.write_atomic(path, body)
                    self.budget.count('gibs')
                self.sat_file['satellite'] = path
                self.sat_time = t
                return
            except net.HttpError as error:
                debug('satellite: %s' % error)

    def fetch_warnings(self):
        spec = self.specs['regional']
        try:
            polys = nws_mod.warning_polygons(spec.view.bbox())
            self.budget.count('nws')
        except net.HttpError as error:
            debug('warnings: %s' % error)
            return
        if not polys:
            self.warn_file['regional'] = None
            return
        stamp = int(time.time())
        path = os.path.join(self.profile, 'frames', 'warnings', 'regional_%d.png' % stamp)
        radar.warning_overlay(spec.view, polys, path)
        old = self.warn_file.get('regional')
        self.warn_file['regional'] = path
        self.warn_events = sorted(set(p['event'] for p in polys))
        if old and old != path:
            threading.Timer(30, lambda: os.path.exists(old) and os.remove(old)).start()

    def fetch_thumb(self):
        s = self.settings
        v = geo.Viewport(s['lat'], s['lon'], max(3, self.zoom - 3), 480, 270)
        folder = os.path.join(self.profile, 'thumbs')
        base = os.path.join(folder, 'base_%s.png' % v.key())
        try:
            if not os.path.exists(base):
                x0, y0, x1, y1 = v.bbox3857()
                cache.write_atomic(base, net.fetch_image(basemap.ESRI_DARK_EXPORT % (x0, y0, x1, y1, 480, 270)))
            radar_path = None
            feed = self.feeds.get('local') or self.feeds.get('regional')
            if feed and feed.past_source is not None and feed.past_source.id == 'iem':
                t = feed.past_source.latest()
                radar_path = os.path.join(folder, 'radar_%s_%d.png' % (v.key(), t))
                if not os.path.exists(radar_path):
                    url = feed.past_source.frames(v, 'past', 0, (480, 270))[-1]['parts'][0][0]
                    cache.write_atomic(radar_path, net.fetch_image(url))
            self.thumb = (base, radar_path)
        except Exception as error:
            debug('thumbnail: %s' % error)

    # ------------------------------------------------------------ player thread

    def player_loop(self):
        splash_done = False
        last_overlay = 0.0
        last_tiles = 0.0
        self.pending_skip = 0
        self.pending_zoom = 0
        while not self.stop.is_set():
            now = time.time()
            try:
                if self.pending_zoom:
                    self.change_zoom(self.pending_zoom)
                    self.pending_zoom = 0
                if self.pending_skip:
                    step, self.pending_skip = self.pending_skip, 0
                    self.switch(step)
                elif self.current is None or (now >= self.scene_end and not getattr(self, 'paused', False)):
                    if self.ready_to_start(now):
                        self.switch(1)
                page = self.current_page
                if isinstance(page, MapPage):
                    page.tick(now)
                    if now - last_tiles > 3:
                        last_tiles = now
                        share = page.refresh_tiles()
                        page.set_overlay_images()
                        if not splash_done and (share > 0.85 or now - self.started > 10):
                            splash_done = True
                            self.splash.done()
                elif page is not None and not splash_done:
                    splash_done = True
                    self.splash.done()
                if now - last_overlay >= 1.0:
                    last_overlay = now
                    self.update_overlay(now)
                    if self.as_script and now - self.last_input > INTERACTIVE_IDLE:
                        self.exit()
            except Exception:
                log(traceback.format_exc(), xbmc.LOGERROR)
            self.stop.wait(TICK)

    def ready_to_start(self, now):
        """On the first scene, wait (up to 12 s) for the first radar frames or forecast."""
        if self.current is not None:
            return True
        if now - self.started > 12:
            return True
        first = self.playlist.base_order()[:1]
        if first and first[0] in self.feeds:
            return len(self.feeds[first[0]].ready) >= 3 and \
                self.map_pages[first[0]].refresh_tiles() > 0.6
        return self.hub.get('forecast') is not None

    def available(self, sid):
        return scenes.available(sid, self.hub, self.settings, time.time(), self.feeds, self.hub.alerts())

    def switch(self, step):
        now = time.time()
        alerts = [a for a in self.hub.alerts() if a['level'] >= 3]
        if step > 0:
            sid = self.playlist.next(self.available, bool(alerts))
        else:
            sid = self.playlist.skip(self.available, -1, bool(alerts))
        if sid is None:
            sid = 'ambient'
        old = self.current_page
        if sid in self.map_pages:
            page = self.map_pages[sid]
        else:
            page = self.panels[1] if old is self.panels[0] else self.panels[0]
            ctx = Context(self.settings, self.units, self.hub, self.profile, self.place, now)
            ctx.thumb = self.thumb
            try:
                lay = scenes.build_panel(sid, ctx, self.hub.alerts())
            except Exception:
                log('scene %s failed:\n%s' % (sid, traceback.format_exc()), xbmc.LOGERROR)
                self.scene_end = now + 2
                return
            if self.settings.get('oled'):
                lay = lay.shifted(*self.oled_shift(now))
            page.apply(lay)
        if old is not None and old is not page:
            old.hide()
        page.show()
        self.current, self.current_page = sid, page
        self.scene_end = now + self.playlist.duration(sid)
        if sid == 'ambient':
            # Rebuild on the minute so the big clock never lags.
            self.scene_end = min(self.scene_end, (int(now // 60) + 1) * 60 + 0.2)
        debug('scene %s for %d s' % (sid, self.playlist.duration(sid)))

    def change_zoom(self, delta):
        if 'local' not in self.specs:
            return
        z = int(geo.clamp(self.zoom + delta, 4, 12))
        if z == self.zoom:
            return
        self.zoom = z
        spec = scenes.map_specs(dict(self.settings, scene_local=1), self.wind_from, z)['local']
        feed = self.make_feed(spec)
        self.specs['local'], self.feeds['local'] = spec, feed
        self.map_pages['local'].retarget(spec, feed)
        if self.current != 'local':
            self.playlist.order = []
            self.current = None

    def oled_shift(self, now):
        """A slow 12 px wander every 3 minutes, plus moving the layout by a whole step hourly."""
        step = int(now // 180)
        return ((step * 7) % 25 - 12, (step * 5) % 17 - 8)

    def subtitle_for(self, spec, frame):
        parts = [self.place]
        if spec.id == 'future':
            from .scenes.conditions import first_rain
            t = first_rain(self.hub.get('forecast'), time.time())
            parts.append('Precipitation reaches you around %s' % self.units.clock(t) if t else
                         'No precipitation reaching you in the next 18 h')
            return '  ·  '.join(parts)
        elif spec.id == 'regional' and getattr(self, 'warn_events', None) and self.warn_file.get('regional'):
            parts.append(', '.join(self.warn_events[:3]))
        elif spec.id == 'satellite':
            parts.append('GOES GeoColor' if self.sat_file.get('satellite', '').endswith('.jpg') else 'GOES infrared')
        src = frame.get('source')
        if frame['kind'] == 'future' and frame.get('run'):
            parts.append('%s run %s' % ('HRRR' if src == 'hrrr' else src.capitalize(),
                                        time.strftime('%H:%MZ', time.gmtime(frame['run']))))
        return '  ·  '.join(parts)

    def update_overlay(self, now):
        s = self.settings
        u = self.units
        fc = self.hub.get('forecast')
        age = self.hub.forecast_age()
        bits = []
        if s.get('ov_date', True):
            bits.append(time.strftime('%a %b ', time.localtime(now)) + str(time.localtime(now).tm_mday))
        if s.get('ov_location', True):
            bits.append(self.place)
        if s.get('ov_age', True) and age is not None:
            if age > 3600:
                bits.append('[COLOR FFFFB74D]offline, data from %s[/COLOR]' % u.clock(now - age))
            else:
                bits.append('updated %s' % units.ago(age))
        chip = None
        if fc and fc.get('current'):
            c = fc['current']
            from .scenes.common import icon
            chip = (icon(c.get('weather_code'), bool(c.get('is_day', 1))), u.temp(c.get('temperature_2m')))
        alerts = self.hub.alerts()
        credits = self.credits()
        dbg = ''
        if s.get('debug'):
            feeds = ', '.join('%s %d/%d' % (sid, len(f.ready), len(f.plan)) for sid, f in self.feeds.items())
            status = ', '.join('%s:%s' % (k, v[0]) for k, v in sorted(self.budget.summary().items()))
            dbg = 'scene %s · profile %s · tiles %d hit / %d miss\n%s\n%s' % (
                self.current, self.perf, self.tiles.hits, self.tiles.misses, feeds, status)
        shift = self.oled_shift(now) if s.get('oled') else (0, 0)
        self.overlay.update(self.current, alerts, chip, '   ·   '.join(bits), credits, dbg, shift)

    def credits(self):
        sid = self.current
        out = []
        if sid in self.map_pages:
            out.append(self.base_src.attribution)
            feed = self.feeds.get(sid)
            if feed and feed.past_source is not None:
                out.append(feed.past_source.attribution)
            if feed and feed.future_source is not None and self.map_pages[sid].spec.future:
                out.append(feed.future_source.attribution)
            if sid == 'satellite':
                out.append(gibs_mod.GIBS.attribution)
            if sid == 'regional' and self.warn_file.get('regional'):
                out.append('Warnings: NWS')
        else:
            out.append('Weather data by Open-Meteo.com')
            if sid in ('climate', 'year'):
                out.append('ERA5 reanalysis (Copernicus)')
            if sid in ('daily', 'discussion', 'alert') and self.hub.us:
                out.append('NWS')
            if sid in ('marine', 'fishing') and self.hub.get('tides'):
                out.append('NOAA CO-OPS')
            if sid == 'fishing' and self.hub.get('gauge'):
                out.append('USGS')
            if sid in ('sunmoon',):
                out = ['Computed on this device']
            if sid == 'ambient' and self.thumb:
                out = ['Esri', 'IEM / NWS NEXRAD']
        return '  ·  '.join(out)


def run(interactive=False):
    App(as_script=interactive).run()


def clear_cache():
    addon = xbmcaddon.Addon(ADDON_ID)
    profile = xbmcvfs.translatePath(addon.getAddonInfo('profile'))
    import shutil
    for name in ('tiles', 'frames', 'charts', 'thumbs'):
        shutil.rmtree(os.path.join(profile, name), ignore_errors=True)
    try:
        os.remove(os.path.join(profile, 'data.db'))
    except OSError:
        pass
    xbmcgui.Dialog().notification(config.ADDON_NAME, 'Cache cleared', os.path.join(addon.getAddonInfo('path'),
                                                                                   'icon.png'), 3000)

