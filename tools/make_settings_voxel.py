"""Generate the Cellular Automata 3D screensaver's settings.xml and strings.po, and its C++ tables
(screensaver.sandclock.gl/src/voxel_tables.hpp) from one table.

Cellular Automata 3D is the three-dimensional sibling of the Cellular Automata screensaver: an
N x N x N grid of voxels running Life-like rules on all 26 neighbours, stored in 2D textures (for
OpenGL ES 2.0) and ray-marched into a rotating 3D view. There is no clock. It shares the colour
palettes, the speed list and the restart list with the 2D add-ons, so an index means the same
thing everywhere; the rules, cube sizes, starts, colour modes and draw caps are its own.

Run: python3 tools/make_settings_voxel.py
"""

import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
SRC = os.path.normpath(os.path.join(HERE, '..', 'screensaver.sandclock'))
GL = os.path.normpath(os.path.join(HERE, '..', 'screensaver.sandclock.gl'))
ADDON_ID = 'screensaver.automata3d.armv7'
ROOT = os.path.normpath(os.path.join(HERE, '..', ADDON_ID))
sys.path.insert(0, SRC)
sys.path.insert(0, HERE)

from make_settings import write  # noqa: E402
from make_settings_automata import RESTARTS, SPEEDS  # noqa: E402

from resources.lib import config  # noqa: E402

# 3D Life-like rules: birth and survival counts among the 26 neighbours of a voxel. The names are
# ours; the rules were picked by simulating random soups and keeping the ones that stay alive and
# keep changing (instead of freezing or boiling away).
RULES = [
    ("Bays' Life (B4/S45)", 'B4/S45'),
    ('Frost (B6,7/S3,4)', 'B6,7/S3,4'),
    ('Coral (B6,7/S5,6)', 'B6,7/S5,6'),
    ('Clouds (B5/S5,6,7)', 'B5/S5,6,7'),
    ('Growth (B5/S4,5,6,7)', 'B5/S4,5,6,7'),
    ('Crystal (B4/S4,5,6)', 'B4/S4,5,6'),
    ('Sprawl (B3/S5,6,7,8)', 'B3/S5,6,7,8'),
    ('Reef (B7,8/S5,6,7,8)', 'B7,8/S5,6,7,8'),
]
GRIDS = [24, 32, 40, 48, 56, 64]          # the cube's edge, so n^3 cells
STARTS = ['Random soup', 'Sparse soup', 'Clusters', 'Centre sphere of soup', 'Hollow sphere', 'Lattice',
          'Random walkers', 'Cube frame', 'Crystal seed']
MODES = ['Age (palette gradient)', 'Position (flowing palette)', 'Time (whole screen cycles)', 'One colour',
         'Rainbow', 'Fire (white hot when born, embers as they age)',
         'Neighbours (crowded cells change colour)', 'Plasma (a moving colour field)']
CAMERAS = ['Still', 'Orbit (slowly circles)', 'Tumble (circles and rocks)', 'Zoom in and out',
           'Inside (drift through the cube)', 'Inside (tumble)']
DRAWS = ['Automatic (up to 360p; the 3D view is the expensive part)', 'Up to 1080p (sharpest, heavy)',
         'Up to 720p', 'Up to 540p', 'Up to 360p', 'Up to 270p (fastest)', 'Full screen (every output pixel)']
BACKGROUNDS = ['Solid', 'Gradient', 'Plasma']
SCREEN_FX = ['None', 'Vignette', 'CRT (scanlines and vignette)']

# A preset is a whole look: rule, cube, starting pattern, colours, glow, screen effect, camera.
# Speed, draw resolution, sparks, restart timers and camera speed stay the user's own settings, so
# a preset can never make a weak device stutter. "Rotate" shows them in a shuffled order.
PRESET_DEFAULTS = dict(rule=0, wrap=True, grid=2, start=2, density=22, colour_mode=1, palette=2,
                       colour=0xFFB347, background_style=0, glow=0, screen_fx=0, dim=0,
                       camera=1, zoom=4, infinite=False)
PRESETS = [
    ("Bays' Ocean", dict(rule=0, grid=2, start=2, density=22, colour_mode=1, palette=2,
                         background_style=1, glow=25, camera=1, zoom=4)),
    ('Orchid Bloom', dict(rule=0, grid=2, start=2, density=25, colour_mode=0, palette=4,
                          glow=40, screen_fx=1, camera=2, zoom=3)),
    ('Ice Crystal', dict(rule=5, grid=3, start=2, density=22, colour_mode=0, palette=6,
                         background_style=1, glow=35, camera=0, zoom=4)),
    ('Neon Reef', dict(rule=7, grid=2, start=0, density=35, colour_mode=6, palette=0,
                       background_style=1, glow=40, camera=2, zoom=3)),
    ('Deep Space', dict(rule=1, grid=2, start=0, density=22, colour_mode=4, palette=0,
                        background_style=2, glow=15, dim=10, camera=1, zoom=2)),
    ('Inside the Torus', dict(rule=7, grid=5, start=0, density=10, colour_mode=4, palette=0,
                              glow=35, camera=4, zoom=4, infinite=True)),
    ('Monolith', dict(rule=4, grid=2, start=2, density=22, colour_mode=3, palette=7,
                      colour=0xFFFFFF, background_style=1, camera=3, zoom=3)),
    ('Candy Cloud', dict(rule=2, grid=2, start=0, density=30, colour_mode=7, palette=5,
                         background_style=1, glow=35, camera=1, zoom=5)),
    ('Sandstorm', dict(rule=3, grid=3, start=0, density=22, colour_mode=0, palette=1,
                       background_style=2, glow=20, camera=2, zoom=3)),
]
ROTATE_SECONDS = [15, 30, 60, 120, 300]


def preset_all(p):
    d = dict(PRESET_DEFAULTS)
    d.update(p)
    return d


def cells_text(n):
    total = n ** 3
    if total >= 1000000:
        text = '%.1f million cells' % (total / 1e6)
    else:
        text = '%d thousand cells' % round(total / 1000.0)
    return '%d x %d x %d (%s)' % (n, n, n, text)


def categories():
    O, S, B, C = config.O, config.S, config.B, config.C
    custom = len(RULES)
    rotating = len(PRESETS) + 1
    return [
        ('Presets', [
            O('preset', 'Preset (sets the rule, cube, colours and camera below)', 0,
              ['Custom (use the settings below)'] + [p[0] for p in PRESETS] +
              ['Rotate through the presets']),
            O('rotate_time', 'Change preset every', 1,
              ['%d seconds' % s if s < 60 else '%d minute%s' % (s // 60, '' if s == 60 else 's')
               for s in ROTATE_SECONDS], visible=('preset', str(rotating))),
        ]),
        ('Rules', [
            O('rule', 'Rule', 0, [r[0] for r in RULES] + ['Custom (type it below)']),
            dict(id='custom_rule', type='string', label='Custom rule (B4/S45, or B6,7/S3,4)',
                 default='B6,7/S3,4', visible=('rule', str(custom))),
            B('wrap', 'Wrap around the edges (a torus)', True),
            B('infinite', 'Endless cube (repeat it for ever; best with an inside camera)', False,
              visible='wrap'),
        ]),
        ('Size and speed', [
            O('grid', 'Cells in the cube', 2, [cells_text(n) for n in GRIDS]),
            O('speed', 'Generations per second', 4,
              ['%d' % s for s in SPEEDS] + ['Maximum (as many as the device can do)']),
            S('sparks', 'Random sparks (births per generation per million cells)', 0, 0, 1000, 10),
            # The raymarch is the expensive part on a weak GPU, far more than the simulation. Lower
            # this first if the picture stutters.
            O('draw', 'Draw the 3D scene at', 0, DRAWS),
        ]),
        ('Start', [
            O('start', 'Starting pattern', 0, STARTS),
            S('density', 'Soup density (% of cells alive)', 22, 5, 60, 5),
            B('auto_restart', 'Start over when it dies out or settles', True),
            O('restart_every', 'Start over every', 4,
              ['Never'] + ['%d minutes' % m if m > 1 else '1 minute' for m in RESTARTS[1:]]),
        ]),
        ('Colours', [
            O('colour_mode', 'Colour', 1, MODES),
            O('palette', 'Palette', 2, config.PALETTE_NAMES),
            C('colour', 'Colour of the cells', 'FFFFB347', visible=('colour_mode', '3')),
            C('background', 'Background', 'FF000000'),
            S('cycle', 'Colour cycling speed', 25, 0, 100, 5),
            S('age_span', 'Colour by age over (generations)', 64, 8, 255, 8),
            O('background_style', 'Background style', 0, BACKGROUNDS),
            S('glow', 'Glow on exposed cells (costs speed)', 0, 0, 100, 10),
            O('screen_fx', 'Screen effect', 0, SCREEN_FX),
            S('dim', 'Dim (%)', 0, 0, 80, 10),
        ]),
        ('Camera', [
            O('camera', 'Camera', 1, CAMERAS),
            S('camera_speed', 'Camera speed', 25, 5, 100, 5),
            S('zoom', 'Closeness (x)', 4, 1, 8, 1),
        ]),
    ]


def write_tables(path):
    speeds = ', '.join(str(s) for s in SPEEDS) + ', -1'
    restarts = ', '.join(str(r) for r in RESTARTS)
    rules = ',\n'.join('    {"%s", "%s"}' % (n.replace('"', ''), r) for n, r in RULES)
    grids = ', '.join(str(n) for n in GRIDS)
    presets = ',\n'.join(
        '    {"%s", %d, %s, %d, %d, %d, %d, %d, 0x%06Xu, %d, %d, %d, %d, %d, %d, %s}' % (
            name.replace('"', '\\"'), v['rule'], 'true' if v['wrap'] else 'false', v['grid'],
            v['start'], v['density'], v['colour_mode'], v['palette'], v['colour'],
            v['background_style'], v['glow'], v['screen_fx'], v['dim'], v['camera'], v['zoom'],
            'true' if v['infinite'] else 'false')
        for name, p in PRESETS for v in [preset_all(p)])
    with open(path, 'w') as f:
        f.write('''// Generated by tools/make_settings_voxel.py; edit the table there.
#pragma once

namespace sandclock {
namespace voxel {

struct RuleDef3D { const char* name; const char* rule; };
constexpr RuleDef3D VOXEL_RULES[] = {
%s
};
constexpr int VOXEL_RULE_COUNT = %d;           // the Custom rule is index VOXEL_RULE_COUNT
constexpr int VOXEL_GRIDS[] = {%s};           // the cube's edge
constexpr int VOXEL_GRID_COUNT = %d;
constexpr int VOXEL_START_COUNT = %d;
constexpr int VOXEL_MODE_COUNT = %d;
constexpr int VOXEL_CAMERA_COUNT = %d;
constexpr int VOXEL_DRAW_COUNT = %d;
constexpr int VOXEL_PRESET_COUNT = %d;         // the Custom and Rotate entries follow them
constexpr int VOXEL_ROTATE_SECONDS[] = {%s};
constexpr int VOXEL_ROTATE_COUNT = %d;

// A whole look. Fields, in order: name, rule, wrap, grid, start, density, colour_mode, palette,
// colour, background_style, glow, screen_fx, dim, camera, zoom, infinite.
struct PresetDef3D {
    const char* name;
    int rule; bool wrap; int grid; int start; int density; int colour_mode; int palette;
    unsigned colour; int background_style; int glow; int screen_fx; int dim; int camera; int zoom;
    bool infinite;
};
constexpr PresetDef3D VOXEL_PRESETS[] = {
%s
};

}  // namespace voxel
}  // namespace sandclock
''' % (rules, len(RULES), grids, len(GRIDS), len(STARTS), len(MODES), len(CAMERAS), len(DRAWS),
       len(PRESETS), ', '.join(str(s) for s in ROTATE_SECONDS), len(ROTATE_SECONDS), presets))


if __name__ == '__main__':
    os.makedirs(os.path.join(ROOT, 'resources'), exist_ok=True)
    write(ROOT, ADDON_ID, 'Cellular Automata 3D', categories(), 'tools/make_settings_voxel.py')
    write_tables(os.path.join(GL, 'src', 'voxel_tables.hpp'))
