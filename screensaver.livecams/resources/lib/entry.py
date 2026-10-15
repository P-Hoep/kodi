"""Entry point. With no argument Kodi is starting the screensaver; settings buttons pass an
action name.

Kodi wakes a screensaver as soon as anything starts playing and then stops its script, so
the screensaver itself never plays a camera: it starts session.py as an ordinary script and
returns. If the user's own media is loaded (paused video, or music), it stays a plain
screensaver showing only a clock, and never touches the player.
"""

import os

import xbmc
import xbmcaddon

from . import config, controller


def main(args):
    action = args[0] if args else ''
    if action:
        from . import setup
        setup.run(action)
        return
    controller.restore_mute()
    if controller.session_alive():
        # Our session is still up (between cameras, or in clock mode after the idle cut-off);
        # Kodi's screensaver timer fired again. The session's window is already on top.
        return
    if xbmc.Player().isPlaying():
        controller.log("the user's own media is loaded: clock only, no camera")
        controller.run_clock()
        return
    path = xbmcaddon.Addon(config.ADDON_ID).getAddonInfo('path')
    xbmc.executebuiltin('RunScript(%s)' % os.path.join(path, 'session.py'))
