"""Generate the Alien Life screensaver's settings.xml and strings.po from one table, so the Kodi
settings and screensaver.alienlife/src/ScreensaverAlienLife.cpp agree on option indices.

Run (writes both add-ons):
  python3 tools/make_settings_alienlife.py

The 32-bit Android build defaults to the small world.
"""

import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

from make_settings import write  # noqa: E402

B = lambda sid, label, default, **kw: dict(id=sid, type='boolean', label=label, default=default, **kw)
I = lambda sid, label, default, lo, hi, step=1, **kw: dict(
    id=sid, type='slider', label=label, default=default, min=lo, max=hi, step=step, **kw)
O = lambda sid, label, default, options, **kw: dict(
    id=sid, type='options', label=label, default=default, options=options, **kw)

# Index order is read by LoadSettings() in ScreensaverAlienLife.cpp: WORLDS is 0 = random, then
# alien::WorldKind + 1; COLOURS is ColourMode; PACE is Pace; STYLES is Style; VIEWS is ViewMode;
# QUALITY is Quality.
WORLDS = ['A different world each time', 'Grazers', 'Grazers and hunters',
          'Primordial soup (random genomes)', 'Ecosystem (every design: hunters, puffers, viruses)']
ROCKS = ['None', 'A few', 'Many']
STYLES = ['Organic (soft shaded bodies and bloom, as in ALIEN)', 'Classic (glowing cells and lines)']
VIEWS = ['The whole world', 'Closer, touring the busiest places', 'Close-up, following one creature after another']
QUALITY = ['Automatic (half resolution on Android)', 'Full resolution', 'Half resolution (weak GPUs)']
DETAIL = ['Small (up to 3,500 cells, for TV sticks)', 'Medium (up to 7,000 cells)',
          'Large (up to 14,000 cells)']
MUTATION = ['Off', 'Low', 'Normal', 'High']
COLOURS = ['Genome colour (as in ALIEN)', 'Cell type', 'Lineage', 'Energy']
TRAILS = ['Off', 'Short', 'Medium', 'Long']
PACE = ['Normal (60 steps a second)', 'Fast (120 steps a second)', 'Slow (30 steps a second)']
THREADS = ['Automatic (one per core, up to 4)', '1', '2', '3', '4']


def categories(low_power):
    return [
        ('World', [
            O('world', 'World', 0, WORLDS),
            O('detail', 'World size', 0 if low_power else 1, DETAIL),
            I('energy', 'Energy in the world (%)', 100, 50, 200, 10),
            O('mutation', 'Mutation rate', 2, MUTATION),
            I('sources', 'Radiation sources', 3, 1, 5),
            O('rocks', 'Rocks', 1, ROCKS),
            I('muscle', 'Muscle strength (%)', 100, 50, 200, 10),
            I('world_minutes', 'New world every (minutes, 0 = never)', 20, 0, 120, 5),
        ]),
        ('Look', [
            O('style', 'Look', 0, STYLES),
            O('view', 'Camera', 1, VIEWS),
            O('colour', 'Colour the cells by', 0, COLOURS),
            I('cell_size', 'Cell size (%)', 100, 50, 200, 10),
            B('glow', 'Glow (bloom)', True),
            B('connections', 'Show the connections between cells', True),
            B('particles', 'Show the energy particles', True),
            B('source_glow', 'Show the radiation sources', True),
            B('events', 'Show attacks, injections, grabs, detonations and births', True),
            O('trails', 'Motion trails', 0, TRAILS),
            I('dim', 'Dim the picture (%)', 0, 0, 80, 10),
        ]),
        ('Performance', [
            O('quality', 'Picture resolution (organic look)', 0, QUALITY),
            O('pace', 'Speed', 0, PACE),
            O('threads', 'Simulation threads', 0, THREADS),
        ]),
    ]


if __name__ == '__main__':
    for addon_id, name, low in (('screensaver.alienlife', 'Alien Life (OpenGL)', False),
                                ('screensaver.alienlife.armv7',
                                 'Alien Life (OpenGL, 32-bit Android)', True)):
        root = os.path.normpath(os.path.join(HERE, '..', addon_id))
        os.makedirs(os.path.join(root, 'resources'), exist_ok=True)
        write(root, addon_id, name, categories(low), 'tools/make_settings_alienlife.py')
