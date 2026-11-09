"""Vintage Radar: the interactive front-end.

All the scope code lives in script.module.vintageradar; this add-on adds the window loop, the
remote handling and the contact sheet, which are part of the shared session and Scene.
"""

import time

import xbmc
import xbmcaddon

from vintageradar import APP_ID, SKIN, config, fontdraw, session, ui


def main():
    addon = xbmcaddon.Addon(APP_ID)
    settings = config.read(APP_ID, addon)
    media, library_path = session.media_path()
    renderer = fontdraw.Renderer(media, session.temp_dir())
    screen = ui.Screen(SKIN, library_path)
    app = session.App(addon, settings, renderer, screen, addon_id=APP_ID)
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
