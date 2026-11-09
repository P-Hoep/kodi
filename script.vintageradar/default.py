import sys

import xbmc

from resources.lib import app, setup

if __name__ == '__main__':
    if 'find_location' in sys.argv[1:]:
        setup.find_location()
    else:
        try:
            app.main()
        except Exception:
            import traceback
            xbmc.log(traceback.format_exc(), xbmc.LOGERROR)
            raise
