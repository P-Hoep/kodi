"""Generate the Cellular Automata Lite screensaver's settings.xml and strings.po from one table.

Lite is the Cellular Automata screensaver without the clock: no font, no clock texture, no mask in
the update shader and no overlay pass. It is aimed at weak devices (32-bit ARM boxes), so its
shaders are generated at start with the chosen rule, wrap, colour mode, view, background, shape,
glow and screen effect compiled in, and the scene is drawn at no more than twice the grid (and no
more than 1080p) and scaled up, rather than shading every output pixel.

It shares the rule, start, colour, view and camera lists with the Cellular Automata add-on, so the
two cannot disagree about what option 7 means. It adds one list of its own: how large the scene is
drawn before it is scaled up. Run:
python3 tools/make_settings_automata_lite.py
"""

import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
SRC = os.path.normpath(os.path.join(HERE, '..', 'screensaver.sandclock'))
sys.path.insert(0, SRC)
sys.path.insert(0, HERE)

from make_settings import write  # noqa: E402
from make_settings_automata import (BACKGROUNDS, CAMERAS, GRID_COLS, MODES, RESTARTS, RULES, SCREEN_FX,  # noqa: E402
                                    SHAPES, SPEEDS, STARTS, VIEWS, cells_text)

from resources.lib import config  # noqa: E402

ADDON_ID = 'screensaver.automata.lite.armv7'
ROOT = os.path.normpath(os.path.join(HERE, '..', ADDON_ID))

# Order matches automata::Settings::draw (automata_lite_app.cpp): 0 auto, 1..4 caps, 5 full screen.
DRAWS = ['Automatic (up to 1080p, and never more than twice the cells)',
         'Up to 1080p (sharpest)',
         'Up to 720p',
         'Up to 540p',
         'Up to 360p (softest, fastest)',
         'Full screen (every output pixel, the heaviest)']


def categories():
    O, S, B, C = config.O, config.S, config.B, config.C
    custom = len(RULES)
    return [
        ('Rules', [
            O('rule', 'Rule', 0, [r[0] for r in RULES] + ['Custom (type it below)']),
            dict(id='custom_rule', type='string', label='Custom rule (B3/S23, or B2/S/C3 with 3 states)',
                 default='B3/S23', visible=('rule', str(custom))),
            B('wrap', 'Wrap around the edges (a torus)', True),
        ]),
        ('Size and speed', [
            # Lite defaults to a quarter of the original's cells: this is the version for boxes
            # that cannot manage the full board.
            O('grid', 'Cells on the screen', 3, [cells_text(c) for c in GRID_COLS]),
            O('speed', 'Generations per second', 5,
              ['%d' % s for s in SPEEDS] + ['Maximum (as many as the device can do)']),
            S('sparks', 'Random sparks (births per generation per million cells)', 0, 0, 1000, 10),
            # The biggest speed lever on a weak GPU: the cost of a frame follows this, not the
            # screen. "Automatic" is the right answer unless the picture looks too soft.
            O('draw', 'Draw the scene at', 0, DRAWS),
        ]),
        ('Start', [
            O('start', 'Starting pattern', 0, STARTS),
            S('density', 'Soup density (% of cells alive)', 30, 5, 60, 5),
            B('auto_restart', 'Start over when it dies out or settles', True),
            O('restart_every', 'Start over every', 4,
              ['Never'] + ['%d minutes' % m if m > 1 else '1 minute' for m in RESTARTS[1:]]),
        ]),
        ('Colours', [
            O('colour_mode', 'Colour', 0, MODES),
            O('palette', 'Palette', 0, config.PALETTE_NAMES),
            C('colour', 'Colour of the cells', 'FFFFB347', visible=('colour_mode', '3')),
            C('background', 'Background', 'FF000000'),
            S('cycle', 'Colour cycling speed', 25, 0, 100, 5),
            S('age_span', 'Colour by age over (generations)', 96, 8, 255, 8),
            S('trail', 'Trails (how long dead cells glow, %)', 60, 0, 95, 5),
            O('shape', 'Cell shape (when cells are 4 px or bigger)', 0, SHAPES),
            O('background_style', 'Background', 0, BACKGROUNDS),
            S('glow', 'Glow around cells (flat and blocks views; costs speed)', 0, 0, 100, 10),
            O('screen_fx', 'Screen effect', 0, SCREEN_FX),
            S('dim', 'Dim (%)', 0, 0, 80, 10),
        ]),
        ('Camera and 3D', [
            O('view', 'View', 0, VIEWS),
            O('camera', 'Camera', 0, CAMERAS),
            S('camera_speed', 'Camera speed', 30, 5, 100, 5),
            S('zoom', 'Deepest zoom (x)', 4, 1, 16, 1),
        ]),
    ]


if __name__ == '__main__':
    os.makedirs(os.path.join(ROOT, 'resources'), exist_ok=True)
    write(ROOT, ADDON_ID, 'Cellular Automata Lite', categories(), 'tools/make_settings_automata_lite.py')
