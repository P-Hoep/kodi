"""Generate the Endless World (OpenGL) screensaver's settings.xml and strings.po from one table,
so the Kodi settings and screensaver.infworld.gl/src/kodi_infworld.cpp cannot disagree about what
option 2 means.

Run: python3 tools/make_settings_infworld.py
     python3 tools/make_settings_infworld.py screensaver.infworld.gl.armv7 'Endless World (OpenGL, 32-bit Android)'
"""

import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ADDON_ID = sys.argv[1] if len(sys.argv) > 1 else 'screensaver.infworld.gl'
NAME = sys.argv[2] if len(sys.argv) > 2 else 'Endless World (OpenGL)'
ROOT = os.path.normpath(os.path.join(HERE, '..', ADDON_ID))
sys.path.insert(0, HERE)

from make_settings import write  # noqa: E402

B = lambda sid, label, default, **kw: dict(id=sid, type='boolean', label=label, default=default, **kw)
I = lambda sid, label, default, lo, hi, step=1, **kw: dict(
    id=sid, type='slider', label=label, default=default, min=lo, max=hi, step=step, **kw)
O = lambda sid, label, default, options, **kw: dict(
    id=sid, type='options', label=label, default=default, options=options, **kw)

CATEGORIES = [
    ('World', [
        I('seed', 'Seed (0 = a new world each start)', 0, 0, 999),
        I('range', 'How far to draw (chunks per ring, higher = more world, slower)', 6, 3, 9),
        O('detail', 'Terrain and tree detail', 1, ['Low', 'Medium', 'High']),
        O('trees', 'Trees', 2, ['None', 'Sparse', 'Normal', 'Lush']),
    ]),
    ('Camera', [
        O('mode', 'Flight', 0, ['Glide (a slow, wandering flight)',
                                'Circle (a slow, steady turn)',
                                'Drift (very slow, calm)']),
        I('speed', 'Speed (world units per second)', 45, 10, 200, 5),
        I('height', 'Height above the ground (metres)', 90, 20, 400, 10),
        B('wander', 'Look around as it flies', True),
    ]),
    ('Scene', [
        B('water', 'Draw the sea and lakes', True),
    ]),
    ('Display', [
        I('dim', 'Dim the picture (%)', 0, 0, 80, 10),
        O('draw_res', 'Render resolution', 0, ['Automatic (up to 1440p)',
                                               'Full (the screen size)',
                                               'Up to 1080p',
                                               'Up to 720p',
                                               'Up to 540p (light)']),
        B('adaptive', 'Lower the detail when the frame rate drops', True),
    ]),
]


if __name__ == '__main__':
    write(ROOT, ADDON_ID, NAME, CATEGORIES, 'tools/make_settings_infworld.py')
