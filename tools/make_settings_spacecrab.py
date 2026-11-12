"""Generate the Space Crab screensaver's settings.xml and strings.po from one table, so the Kodi
settings and screensaver.spacecrab/src/ScreensaverSpaceCrab.cpp agree on option indices.

Run:
  python3 tools/make_settings_spacecrab.py
  python3 tools/make_settings_spacecrab.py screensaver.spacecrab.armv7 \
      'Space Crab (OpenGL, 32-bit Android)' low

The optional third argument 'low' makes the 32-bit build default to low detail.
"""

import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ADDON_ID = sys.argv[1] if len(sys.argv) > 1 else 'screensaver.spacecrab'
NAME = sys.argv[2] if len(sys.argv) > 2 else 'Space Crab (OpenGL)'
LOW_POWER = len(sys.argv) > 3 and sys.argv[3] == 'low'
ROOT = os.path.normpath(os.path.join(HERE, '..', ADDON_ID))
sys.path.insert(0, HERE)

from make_settings import write  # noqa: E402

B = lambda sid, label, default, **kw: dict(id=sid, type='boolean', label=label, default=default, **kw)
I = lambda sid, label, default, lo, hi, step=1, **kw: dict(
    id=sid, type='slider', label=label, default=default, min=lo, max=hi, step=step, **kw)
O = lambda sid, label, default, options, **kw: dict(
    id=sid, type='options', label=label, default=default, options=options, **kw)

# Index order is read by LoadSettings() in ScreensaverSpaceCrab.cpp (the enums there).
ANIM_STYLES = ['Steady walk', 'Scuttle and rest (varies)', 'Back and forth']
MOVEMENTS = ['Float in place', 'Wander around the screen', 'Scuttle across space']
TUMBLES = ['Gentle sway', 'Slowly turning', 'Tumbling head over heels', 'Still (facing the camera)']
LENSES = ['Wide', 'Normal', 'Telephoto']
BACKGROUNDS = ['Black', 'Deep blue', 'Nebula']
STAR_MOTIONS = ['Still', 'Slow drift', 'Warp speed (rushing past)']
LIGHTS = ['Warm sunlight', 'Cool starlight', 'Dramatic rim light', 'Colour cycling']
DETAILS = ['Low (weak boxes, Fire TV)', 'High']


def categories():
    return [
        ('Crab', [
            I('crabs', 'Number of crabs', 1, 1, 12),
            I('anim_speed', 'Animation speed (%)', 100, 0, 300, 10),
            O('anim_style', 'Animation', 1, ANIM_STYLES),
            O('movement', 'Movement', 0, MOVEMENTS),
            O('tumble', 'Rotation', 0, TUMBLES),
            I('bob', 'Floating bob (%)', 100, 0, 200, 10),
        ]),
        ('Camera', [
            I('zoom', 'Zoom (%)', 100, 25, 400, 5),
            I('auto_zoom', 'Slow push in and out (%)', 30, 0, 100, 10),
            I('orbit', 'Orbit speed (degrees per second, negative = other way)', 5, -30, 30),
            I('height', 'Camera height (degrees above the crab)', 15, -80, 80, 5),
            O('lens', 'Lens', 1, LENSES),
            B('sway', 'Gentle handheld drift', True),
        ]),
        ('Space', [
            O('background', 'Background', 2, BACKGROUNDS),
            B('stars', 'Stars', True),
            I('star_density', 'Star density (%)', 100, 10, 300, 10, visible='stars'),
            O('star_motion', 'Star motion', 1, STAR_MOTIONS, visible='stars'),
            O('light', 'Lighting', 0, LIGHTS),
        ]),
        ('Performance', [
            O('detail', 'Detail', 0 if LOW_POWER else 1, DETAILS),
            I('dim', 'Dim the picture (%)', 0, 0, 80, 10),
        ]),
    ]


if __name__ == '__main__':
    os.makedirs(os.path.join(ROOT, 'resources'), exist_ok=True)
    write(ROOT, ADDON_ID, NAME, categories(), 'tools/make_settings_spacecrab.py')
