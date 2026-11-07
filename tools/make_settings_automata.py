"""Generate the Cellular Automata screensaver's settings.xml, strings.po and its C++ tables
(screensaver.sandclock.gl/src/automata_tables.hpp) from one table, so the Kodi settings and the
code cannot disagree about what option 7 means.

Run: python3 tools/make_settings_automata.py
"""

import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
SRC = os.path.normpath(os.path.join(HERE, '..', 'screensaver.sandclock'))
GL = os.path.normpath(os.path.join(HERE, '..', 'screensaver.sandclock.gl'))
ADDON_ID = 'screensaver.automata.armv7'
ROOT = os.path.normpath(os.path.join(HERE, '..', ADDON_ID))
sys.path.insert(0, SRC)
sys.path.insert(0, HERE)

from make_settings import write  # noqa: E402
from resources.lib import config  # noqa: E402

# Life-like rules as Bx/Sy, with an optional /Cn for n states (Generations: a cell that fails
# to survive fades through n-2 more states before it is dead).
RULES = [
    ("Conway's Life", 'B3/S23'),
    ('HighLife', 'B36/S23'),
    ('Day & Night', 'B3678/S34678'),
    ('Seeds', 'B2/S'),
    ('Maze', 'B3/S12345'),
    ('Mazectric', 'B3/S1234'),
    ('Replicator', 'B1357/S1357'),
    ('Diamoeba', 'B35678/S5678'),
    ('Anneal', 'B4678/S35678'),
    ('2x2', 'B36/S125'),
    ('Coagulations', 'B378/S235678'),
    ('Life without death', 'B3/S012345678'),
    ("Brian's Brain (3 states)", 'B2/S/C3'),
    ('Star Wars (4 states)', 'B2/S345/C4'),
    ('Frogs (3 states)', 'B34/S12/C3'),
    ('Bloomerang (24 states)', 'B234/S345/C24'),
    ('Fireworks (21 states)', 'B13/S2/C21'),
    ('Life with fading ghosts (B3/S23, 8 states)', 'B3/S23/C8'),
]
GRID_COLS = [160, 320, 480, 640, 960, 1280, 1920, 2560, 3840]   # rows = cols * 9 / 16
SPEEDS = [1, 2, 5, 10, 15, 30, 60, 120, 240, 480, 960]           # generations per second; then Maximum
RESTARTS = [0, 1, 2, 5, 10, 30, 60]                              # minutes; 0 = never
STARTS = ['Random soup', 'Sparse soup', 'Clusters', 'Kaleidoscope soup (4-way mirror)', 'Centre blob',
          'R-pentomino', 'Acorn', 'Gosper glider guns', 'Glider swarm', 'Soup and guns']
MODES = ['Age (palette gradient)', 'Position (flowing palette)', 'Time (whole screen cycles)', 'One colour',
         'Rainbow', 'Fire (white hot when born, embers as they age)', 'Neighbours (crowded cells change colour)',
         'Rainbow ghosts (trails change colour as they fade)', 'Plasma (a moving colour field)']
CLOCKS = ['Off', 'On top', 'On top, and the digits burst into life at each change', 'Cut out of the cells',
          'Made of living cells (the cells grow from the digits)']
VIEWS = ['Flat', 'Raised blocks (lit, with shadows)', 'Landscape (flying over it)', 'Tunnel (flying through it)',
         'Globe (a spinning planet)']
CAMERAS = ['Still', 'Drift', 'Zoom in and out', 'Fly through (drift, zoom and turn)']
BACKGROUNDS = ['Solid', 'Gradient', 'Plasma']
SCREEN_FX = ['None', 'Vignette', 'CRT (scanlines and vignette)']
SHAPES = ['Square', 'Rounded', 'Dots']


def cells_text(cols):
    n = cols * (cols * 9 // 16)
    if n >= 1000000:
        text = '%.1f million cells' % (n / 1e6)
    else:
        text = '%d thousand cells' % round(n / 1000.0)
    if cols >= 3840:
        text += ', insane'
    return '%d x %d (%s)' % (cols, cols * 9 // 16, text)


def categories():
    O, S, B, C = config.O, config.S, config.B, config.C
    custom = len(RULES)
    return [
        ('Clock', [
            O('clock', 'Clock in the middle', 1, CLOCKS),
            O('clock_font', 'Font', 0, [f[0] for f in config.FONTS], visible=('clock', '!', '0')),
            O('clock_weight', 'Weight', 2, config.WEIGHTS, visible=('clock', '!', '0')),
            B('seconds', 'Show seconds', True, visible=('clock', '!', '0')),
            O('hours', 'Hours', 0, ['24 hour (17:52)', '12 hour (5:52)'], visible=('clock', '!', '0')),
            S('clock_size', 'Clock width (% of the screen)', 50, 20, 90, 5, visible=('clock', '!', '0')),
            O('clock_colour_mode', 'Clock colour', 0, ['White', 'Follows the palette', 'One colour'],
              visible=('clock', '!', '0')),
            C('clock_colour', 'Colour of the clock', 'FFFFFFFF', visible=('clock_colour_mode', '2')),
            S('clock_opacity', 'Clock opacity (%)', 85, 10, 100, 5, visible=('clock', '!', '0')),
        ]),
        ('Rules', [
            O('rule', 'Rule', 0, [r[0] for r in RULES] + ['Custom (type it below)']),
            dict(id='custom_rule', type='string', label='Custom rule (B3/S23, or B2/S/C3 with 3 states)',
                 default='B3/S23', visible=('rule', str(custom))),
            B('wrap', 'Wrap around the edges (a torus)', True),
        ]),
        ('Size and speed', [
            O('grid', 'Cells on the screen', 4, [cells_text(c) for c in GRID_COLS]),
            O('speed', 'Generations per second', 5,
              ['%d' % s for s in SPEEDS] + ['Maximum (as many as the device can do)']),
            S('sparks', 'Random sparks (births per generation per million cells)', 0, 0, 1000, 10),
        ]),
        ('Start', [
            O('start', 'Starting pattern', 0, STARTS),
            S('density', 'Soup density (% of cells alive)', 30, 5, 60, 5),
            B('auto_restart', 'Start over when it dies out or settles', True),
            O('restart_every', 'Start over every', 4, ['Never'] + ['%d minutes' % m if m > 1 else '1 minute' for m in RESTARTS[1:]]),
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


def write_tables(path):
    cols = ', '.join(str(c) for c in GRID_COLS)
    speeds = ', '.join(str(s) for s in SPEEDS) + ', -1'
    restarts = ', '.join(str(r) for r in RESTARTS)
    rules = ',\n'.join('    {"%s", "%s"}' % (n.replace('"', ''), r) for n, r in RULES)
    pal = ',\n'.join('    {%s}' % ', '.join('0x' + c for c in colours) for _name, colours in config.PALETTES)
    with open(path, 'w') as f:
        f.write('''// Generated by tools/make_settings_automata.py; edit the table there.
#pragma once
#include <cstdint>

namespace sandclock {
namespace automata {

struct RuleDef { const char* name; const char* rule; };
constexpr RuleDef RULES[] = {
%s
};
constexpr int RULE_COUNT = %d;                 // the Custom rule is index RULE_COUNT
constexpr int GRID_COLS[] = {%s};              // rows = cols * 9 / 16
constexpr int GRID_COUNT = %d;
constexpr int SPEED_GPS[] = {%s};              // generations per second; -1 = maximum
constexpr int SPEED_COUNT = %d;
constexpr int RESTART_MINUTES[] = {%s};        // 0 = never
constexpr int RESTART_COUNT = %d;
constexpr int START_COUNT = %d;
constexpr int MODE_COUNT = %d;
constexpr int CLOCK_COUNT = %d;
constexpr int VIEW_COUNT = %d;
constexpr int CAMERA_COUNT = %d;
constexpr uint32_t PALETTE[][7] = {
%s
};
constexpr int PALETTE_COUNT = %d;

}  // namespace automata
}  // namespace sandclock
''' % (rules, len(RULES), cols, len(GRID_COLS), speeds, len(SPEEDS) + 1, restarts, len(RESTARTS), len(STARTS),
       len(MODES), len(CLOCKS), len(VIEWS), len(CAMERAS), pal, len(config.PALETTES)))


if __name__ == '__main__':
    os.makedirs(os.path.join(ROOT, 'resources'), exist_ok=True)
    write(ROOT, ADDON_ID, 'Cellular Automata', categories(), 'tools/make_settings_automata.py')
    write_tables(os.path.join(GL, 'src', 'automata_tables.hpp'))
