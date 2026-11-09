"""The Vintage Radar app's main loop.

The window and its controls live in ui.py; this file owns the aircraft model, the background
feed, the text-update cadence, input handling and the settings reload. Everything here runs on
Kodi's Python thread: Screen's callbacks only queue events, so no xbmcgui call is ever made
from another thread.
"""

import os
import shutil
import time

import xbmc
import xbmcaddon

from . import config, fontdraw, net, radar_core, radar_feed, ui

ADDON_ID = 'script.vintageradar'
XML = 'script-vintageradar-main.xml'
GROUPS = ('clock', 'header', 'footer', 'list', 'detail', 'labels', 'bar', 'overlay')
INTERVALS = {'clock': 1.0, 'header': 2.0, 'footer': 3.0, 'list': 3.0, 'detail': 2.0,
             'labels': 2.5, 'bar': 0.5, 'overlay': 2.0}

ACTION_MOVE_LEFT = 1
ACTION_MOVE_RIGHT = 2
ACTION_PAGE_UP = 5
ACTION_PAGE_DOWN = 6
ACTION_SELECT = 7
ACTION_PREVIOUS_MENU = 10
ACTION_STOP = 13
ACTION_NAV_BACK = 92
ACTION_MOUSE_RIGHT_CLICK = 101
ACTION_CONTEXT_MENU = 117


def _log(message, level=xbmc.LOGINFO):
    xbmc.log('Vintage Radar: ' + message, level)


def _signature(settings):
    return (settings.location_name, settings.lat, settings.lon, settings.range_km,
            settings.units, settings.refresh_seconds, settings.show_ground,
            settings.min_altitude, settings.sweep_seconds, settings.show_labels,
            settings.label_detail, settings.show_history, settings.max_contacts,
            settings.show_panel, settings.detail_seconds, settings.list_seconds,
            settings.theme, settings.crt, settings.dim, settings.quality)


def _network_signature(settings):
    return (round(settings.lat, 5), round(settings.lon, 5), settings.range_km,
            settings.refresh_seconds)


def _temp_dir():
    try:
        root = xbmc.translatePath('special://temp')
    except Exception:
        root = os.path.join(os.path.expanduser('~'), '.kodi', 'temp')
    base = os.path.join(root, 'vintageradar')
    # One directory per session: two windows (or two Kodi runs) must not overwrite each
    # other's text images, and image names only need to be unique within one renderer.
    path = os.path.join(base, '%d-%d' % (os.getpid(), int(time.time() * 1000)))
    try:
        now = time.time()
        for name in os.listdir(base):
            full = os.path.join(base, name)
            if os.path.isdir(full) and now - os.path.getmtime(full) > 86400.0:
                shutil.rmtree(full, ignore_errors=True)
    except OSError:
        pass
    return path


class App(object):
    def __init__(self, addon, settings, renderer, screen):
        self.addon = addon
        self.settings = settings
        self.renderer = renderer
        self.screen = screen
        self.model = radar_core.Model(settings)
        self.model.set_page_rows(ui.PAGE_ROWS)
        self.pump = None
        self.stop = False
        self.next_times = dict((group, 0.0) for group in GROUPS)
        self.next_settings = 0.0
        self.next_focus = 0.0
        self.last_error = ''
        self.last_error_log = 0.0

    # ---- lifecycle -------------------------------------------------------------------------

    def run(self):
        monitor = xbmc.Monitor()
        scene = self.screen.scene
        if scene is None:
            _log('window did not initialise', xbmc.LOGERROR)
            return
        now = time.monotonic()
        self.model.reset_clock(now)
        scene.apply_settings(self.settings)
        for group in GROUPS:
            self.next_times[group] = 0.0
        self.pump = radar_feed.FeedPump(self.settings, net.fetch)
        self.pump.start()
        _log('started at %.4f, %.4f, range %d km' % (
            self.settings.lat, self.settings.lon, self.settings.range_km))

        while not self.stop:
            if monitor.abortRequested():
                break
            now = time.monotonic()
            for kind, value in self.screen.drain():
                self._event(kind, value, now)
            self._take_feed(now)
            self.model.update(now)
            scene.update_contacts(self.model, now)
            self._update_text(scene, now)
            self._check_settings(now)
            self._check_overlay(scene, now)
            self._check_focus(scene, now)
            if self.stop:
                break
            xbmc.sleep(80)

    def close(self):
        self.stop = True
        if self.pump is not None:
            self.pump.stop()
            self.pump = None

    # ---- feed ------------------------------------------------------------------------------

    def _take_feed(self, now):
        result = self.pump.take() if self.pump is not None else None
        if result is None:
            return
        feed, error = result
        if feed is not None:
            if self.model.feed_error:
                _log('feed recovered')
            self.model.apply_feed(feed, now)
            self.last_error = ''
            return
        self.model.apply_error(error, now)
        if error != self.last_error or now - self.last_error_log > 120.0:
            self.last_error = error
            self.last_error_log = now
            _log(error, xbmc.LOGWARNING)

    def _restart_pump(self):
        if self.pump is not None:
            self.pump.stop()
        self.pump = radar_feed.FeedPump(self.settings, net.fetch)
        self.pump.start()

    # ---- text cadence ----------------------------------------------------------------------

    def _update_text(self, scene, now):
        due = [group for group in GROUPS if now >= self.next_times[group]]
        if not due:
            return
        group = min(due, key=lambda name: self.next_times[name])
        try:
            scene.update_group(group, self.model, now)
        except Exception as error:
            _log('text group %s failed: %s' % (group, error), xbmc.LOGERROR)
        self.next_times[group] = now + INTERVALS[group]

    def _refresh(self):
        for group in GROUPS:
            self.next_times[group] = 0.0

    # ---- input -----------------------------------------------------------------------------

    def _event(self, kind, value, now):
        if kind == 'click':
            self._click(value, now)
        elif kind == 'action':
            self._action(value, now)

    def _click(self, control_id, now):
        scene = self.screen.scene
        role = scene.click_roles.get(control_id)
        if role is None:
            return
        if role[0] == 'overlay_close':
            self._close_overlay(scene)
        elif role[0] == 'anchor':
            contact = self.model.spotlight()
            if contact is not None:
                self._open(contact.ac.hex, now)
        elif role[0] == 'blip':
            slot = role[1]
            if slot < len(self.model.order):
                contact = self.model.contacts[self.model.order[slot]]
                self._open(contact.ac.hex, now)
        elif role[0] == 'row':
            position = self.model.page * ui.PAGE_ROWS + role[1]
            if position < len(self.model.order):
                contact = self.model.contacts[self.model.order[position]]
                self._open(contact.ac.hex, now)
        self._reset_focus(scene)

    def _open(self, hex_value, now):
        scene = self.screen.scene
        if self.model.pin(hex_value):
            scene.show_overlay(self.model, now)
            self._refresh()

    def _close_overlay(self, scene):
        scene.hide_overlay()
        # Closing the card hands the spotlight back to the rotating card.
        self.model.unpin()
        self._refresh()

    def _action(self, action_id, now):
        scene = self.screen.scene
        if action_id in (ACTION_PREVIOUS_MENU, ACTION_NAV_BACK, ACTION_MOUSE_RIGHT_CLICK,
                         ACTION_STOP):
            if scene.overlay_open:
                self._close_overlay(scene)
            else:
                self.stop = True
            return
        if action_id == ACTION_CONTEXT_MENU:
            xbmc.executebuiltin('Addon.OpenSettings(%s)' % ADDON_ID)
            self.next_settings = 0.0
            return
        if action_id == ACTION_SELECT:
            contact = self.model.spotlight()
            if contact is not None and not scene.overlay_open:
                self._open(contact.ac.hex, now)
            return
        if action_id in (ACTION_MOVE_LEFT, ACTION_MOVE_RIGHT):
            self.model.step_spotlight(-1 if action_id == ACTION_MOVE_LEFT else 1)
            if scene.overlay_open:
                scene.update_group('overlay', self.model, now)
            self._refresh()
            self._reset_focus(scene)
            return
        if action_id in (ACTION_PAGE_UP, ACTION_PAGE_DOWN):
            if scene.overlay_open:
                return
            step = -1 if action_id == ACTION_PAGE_UP else 1
            self.model.set_page(self.model.page + step)
            self._refresh()
            self._reset_focus(scene)

    def _reset_focus(self, scene):
        try:
            scene.window.setFocusId(scene.close_id if scene.overlay_open else scene.anchor_id)
        except Exception:
            pass
        self.next_focus = time.monotonic() + 0.5

    def _check_focus(self, scene, now):
        if now < self.next_focus:
            return
        self.next_focus = now + 0.7
        wanted = scene.close_id if scene.overlay_open else scene.anchor_id
        try:
            if self.screen.getFocusId() != wanted:
                self.screen.setFocusId(wanted)
        except Exception:
            pass

    # ---- settings and overlay --------------------------------------------------------------

    def _check_settings(self, now):
        if now < self.next_settings:
            return
        self.next_settings = now + 2.0
        try:
            fresh = config.read(ADDON_ID, self.addon)
        except Exception as error:
            _log('could not read settings: %s' % error, xbmc.LOGWARNING)
            return
        if _signature(fresh) == _signature(self.settings):
            return

        old = self.settings
        self.settings = fresh
        network = _network_signature(old) != _network_signature(fresh)
        if network:
            # The scope has moved; do not keep contacts from the old place and range.
            self.model.contacts = []
            self.model.order = []
            self.model.spotlight_hex = ''
            self.model.pinned = False
            self.model.page = 0
            self.model.has_feed = False
            self.model.feed_received_at = -1.0
            self.model.feed_error = ''
            self.model.feed_source = ''
        if fresh.sweep_seconds != old.sweep_seconds:
            self.model.reset_sweep(now)
        self.model.set_settings(fresh)
        self.model.set_page_rows(ui.PAGE_ROWS)
        if network:
            self._restart_pump()
        scene = self.screen.scene
        scene.apply_settings(fresh)
        if scene.overlay_open:
            scene.update_group('overlay', self.model, now)
        self._refresh()

    def _check_overlay(self, scene, now):
        if not scene.overlay_open:
            return
        if self.model.spotlight() is None or self.model.spotlight_position() < 0:
            self._close_overlay(scene)


def main():
    addon = xbmcaddon.Addon(ADDON_ID)
    settings = config.read(ADDON_ID, addon)
    media = os.path.join(addon.getAddonInfo('path'), 'resources', 'media')
    renderer = fontdraw.Renderer(media, _temp_dir())
    screen = ui.Screen(XML, addon.getAddonInfo('path'))
    app = App(addon, settings, renderer, screen)
    screen.builder = lambda window: ui.Scene(window, media, renderer, app.model, settings)

    xbmc.executebuiltin('InhibitScreensaver(true)')
    try:
        screen.show()
        deadline = time.time() + 5.0
        while screen.scene is None and time.time() < deadline:
            xbmc.sleep(50)
        app.run()
    finally:
        app.close()
        try:
            screen.close()
        except Exception:
            pass
        xbmc.executebuiltin('InhibitScreensaver(false)')
