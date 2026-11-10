"""Entry point for Kodi's screensaver launcher, and for the Clear cache settings button."""

import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
if HERE not in sys.path:
    sys.path.insert(0, HERE)


def main():
    args = [arg for arg in sys.argv[1:] if not arg.startswith('addon=')]
    try:
        from resources.lib import ui
        if 'clear_cache' in args:
            ui.clear_cache()
        else:
            ui.run()
    except Exception:
        import traceback
        import xbmc
        xbmc.log('[screensaver.hackernews] %s' % traceback.format_exc(), xbmc.LOGERROR)


if __name__ == '__main__':
    main()
