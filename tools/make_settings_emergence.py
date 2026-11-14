"""Generate the Emergence screensaver's settings.xml and strings.po from one table, so the Kodi
settings and screensaver.emergence/src/ScreensaverEmergence.cpp agree on option indices.

Run (writes both add-ons):
  python3 tools/make_settings_emergence.py

Emergence runs Physarum v2, Dancing Boids and Particle Life v2 in one world, alone or coupled. The
32-bit Android build starts at the Low detail level (sized for a Fire TV stick).
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

# Index orders are read by LoadSettings() in ScreensaverEmergence.cpp: SceneChoice then the Scene
# enum of World.h, kSceneMinutes, Mode, BoidColour, Shape, LifePalette, Pace; the slime presets
# and palettes are physarum::kPresets / kPalettes (PhysarumPresets.h), index + 1.
SCENES = ['Rotate through all seven scenes', 'Rotate through the combinations',
          'Rotate through the three on their own',
          'Slime mould (Physarum alone)', 'Murmuration (the flock alone)', 'Particle life (alone)',
          'Slime highways (the flock lays scent, the slime grows along it)',
          'Cell garden (the particle cells feed the slime)',
          'Reef (the flock swims round the particle cells)',
          'Ecosystem (all three together)']
MINUTES = ['1 minute', '2 minutes', '3 minutes', '5 minutes', '10 minutes', '20 minutes', '30 minutes']
SLIME_PRESETS = ['A different one each scene', 'Transport network', 'Fine web', 'Double-veined cells',
                 'Coarse veins', 'Honeycomb', 'Labyrinth', 'Worms', 'Spots and comets', 'Foam',
                 'Long threads', 'Restless']
MODES = ['Palette', 'Neon (white-hot cores)', 'Fire']
PALETTES = ['A different one each scene', 'Neon', 'Desert sand', 'Ocean', 'Sunset', 'Candy', 'Forest',
            'Ice', 'Greyscale']
BOID_COLOURS = ['Automatic (blue alone, pale over the slime)', "The original's blues", 'One colour per flock',
                'By heading (rainbow)', 'Pale silver']
SHAPES = ['Triangles', 'Darts', 'Dots']
LIFE_RULES = ['Random rules', "The original app's saved models", 'Either, at random']
LIFE_PALETTES = ['Classic', 'Neon', 'Pastel', 'Rainbow', 'Random hues each scene']
TRAILS = ['Off', 'Short', 'Medium', 'Long']
DETAIL = ['Low (TV sticks: 80-150 thousand slime agents, 900-1,500 boids)',
          'Medium (150-250 thousand agents, 1,500-3,000 boids)',
          'High (300-500 thousand agents, 2,500-5,000 boids)']
PACES = ['Normal (60 steps a second)', 'Fast (120 steps a second)', 'Slow (30 steps a second, half the CPU)']
THREADS = ['Automatic (one per core but one, up to 4)', '1', '2', '3', '4']


def categories(low_power):
    return [
        ('Scenes', [
            O('scene', 'Scenes', 0, SCENES),
            O('scene_minutes', 'Change scene every', 2, MINUTES),
            I('coupling', 'How strongly they feel each other (%)', 100, 25, 300, 25),
        ]),
        ('Slime', [
            O('slime_preset', 'Behaviour', 0, SLIME_PRESETS),
            O('colour_mode', 'Colour', 0, MODES),
            O('palette', 'Palette', 0, PALETTES),
            I('cycle', 'Colour cycling speed', 20, 0, 100, 5),
            I('brightness', 'Brightness (%)', 100, 30, 300, 10),
        ]),
        ('Flock', [
            I('flocks', 'Flocks (each keeps to its own kind)', 1, 1, 4),
            I('hawks', 'Hawks (in Murmuration and Reef)', 1, 0, 4),
            B('vary', 'A different temperament for each scene', True),
            O('boid_colour', 'Colour', 0, BOID_COLOURS),
            O('shape', 'Shape', 0, SHAPES),
            I('boid_size', 'Size (%)', 100, 30, 300, 10),
        ]),
        ('Particles', [
            O('life_rules', 'Rules', 2, LIFE_RULES),
            I('life_colours', 'Most colours for random rules', 5, 2, 8),
            O('life_palette', 'Palette', 0, LIFE_PALETTES),
            I('point_size', 'Particle size', 3, 1, 8),
            B('glow', 'Glow (additive light)', False),
        ]),
        ('Look', [
            O('trails', 'Motion trails (scenes without slime)', 0, TRAILS),
            I('dim', 'Dim (%)', 0, 0, 80, 10),
        ]),
        ('Performance', [
            O('detail', 'Detail', 0 if low_power else 1, DETAIL),
            O('pace', 'Speed', 0, PACES),
            O('threads', 'Simulation threads', 0, THREADS),
        ]),
    ]


if __name__ == '__main__':
    for addon_id, name, low in (('screensaver.emergence', 'Emergence (OpenGL)', False),
                                ('screensaver.emergence.armv7', 'Emergence (OpenGL, 32-bit Android)', True)):
        root = os.path.normpath(os.path.join(HERE, '..', addon_id))
        os.makedirs(os.path.join(root, 'resources'), exist_ok=True)
        write(root, addon_id, name, categories(low), 'tools/make_settings_emergence.py')
