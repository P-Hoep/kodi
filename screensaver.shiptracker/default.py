import sys

from resources.lib import ui

if __name__ == '__main__':
    if 'clear_cache' in sys.argv:
        ui.clear_cache()
    else:
        ui.run()
