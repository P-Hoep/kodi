"""Generate the Growing Plant (OpenGL) screensaver's settings.xml and strings.po from one table,
so the Kodi settings and screensaver.plant.gl/src/kodi_plant.cpp cannot disagree about what
option 2 means.

Run: python3 tools/make_settings_plant_gl.py
     python3 tools/make_settings_plant_gl.py screensaver.plant.gl.armv7 'Growing Plant (OpenGL, 32-bit Android)'
"""

import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ADDON_ID = sys.argv[1] if len(sys.argv) > 1 else 'screensaver.plant.gl'
NAME = sys.argv[2] if len(sys.argv) > 2 else 'Growing Plant (OpenGL)'
ROOT = os.path.normpath(os.path.join(HERE, '..', ADDON_ID))
sys.path.insert(0, HERE)

from make_settings import write  # noqa: E402

B = lambda sid, label, default, **kw: dict(id=sid, type='boolean', label=label, default=default, **kw)
I = lambda sid, label, default, lo, hi, step=1, **kw: dict(
    id=sid, type='slider', label=label, default=default, min=lo, max=hi, step=step, **kw)
O = lambda sid, label, default, options, **kw: dict(
    id=sid, type='options', label=label, default=default, options=options, **kw)

CATEGORIES = [
    ('Plant', [
        O('preset', 'Plant', 0, ['Automatic (a different plant every cycle)',
                                 'Tree',
                                 'Bush',
                                 'Fern / vine',
                                 'Fan-leaf plant',
                                 'L-system pattern']),
        I('seed', 'Seed (0 = a new plant each start)', 0, 0, 999),
        O('leaf_density', 'Leaf density', 1, ['Sparse', 'Normal', 'Lush']),
        O('growth_speed', 'How long a plant takes to grow', 1,
          ['Slow (36 s)', 'Normal (25 s)', 'Fast (17 s)', 'Very fast (11 s)']),
        I('hold_seconds', 'How long to hold the finished plant (seconds)', 14, 0, 60, 2),
    ]),
    ('Camera', [
        O('motion', 'Camera movement', 0, ['Automatic (changes every cycle)',
                                           'Orbit (a steady circle)',
                                           'Sway (a hand-held drift)',
                                           'Spiral (rise while circling)',
                                           'Crane (climb from the soil to above the crown)',
                                           'Still (one angle per cycle)']),
        I('camera_speed', 'Camera speed (%)', 100, 10, 200, 5),
        O('framing', 'Framing', 0, ['Normal', 'Close', 'Wide']),
    ]),
    ('Scene', [
        O('background', 'Background', 0, ['Automatic (changes every cycle)',
                                          'Dawn',
                                          'Meadow',
                                          'Dusk',
                                          'Night',
                                          'Studio',
                                          'Aurora']),
        B('ground', 'Draw the ground and the contact shadow', True),
        B('particles', 'Drifting pollen', True),
    ]),
    ('Display', [
        O('quality', 'Detail', 1, ['Low (for slow boxes)', 'Normal', 'High']),
        I('dim', 'Dim the picture (%)', 0, 0, 80, 10),
    ]),
]


if __name__ == '__main__':
    write(ROOT, ADDON_ID, NAME, CATEGORIES, 'tools/make_settings_plant_gl.py')
