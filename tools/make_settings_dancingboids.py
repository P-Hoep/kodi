"""Generate the Dancing Boids screensaver's settings.xml and strings.po from one table, so the Kodi
settings and screensaver.dancingboids/src/ScreensaverDancingBoids.cpp agree on option indices.

Run (writes both add-ons):
  python3 tools/make_settings_dancingboids.py

The 32-bit Android build gets lighter defaults (fewer boids, fewer neighbours per boid).
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

# Index order is read by LoadSettings() in ScreensaverDancingBoids.cpp (the enums there).
EDGES = ['Turn back at the edges', 'Wrap around']
BACKGROUNDS = ['Black', 'Dusk sky (dark starlings)']
COLOURS = ['Original blues', 'One colour per flock', 'By heading (rainbow)', 'By speed',
           'Random colours']
SHAPES = ['Triangles', 'Slim darts', 'Dots']
TRAILS = ['Off', 'Short', 'Medium', 'Long']
THREADS = ['Automatic (one per core, up to 4)', '1', '2', '3', '4']


def categories(low_power):
    return [
        ('Flock', [
            I('boids', 'Number of boids', 1500 if low_power else 3000, 100, 10000, 100),
            I('flocks', 'Number of flocks (each keeps to its own kind)', 1, 1, 4),
            I('speed', 'Speed (%)', 100, 25, 250, 5),
            I('vision', 'How far a boid sees', 55, 20, 120, 5),
            I('separation', 'Separation: keep apart (%)', 100, 0, 300, 10),
            I('alignment', 'Alignment: fly the same way (%)', 100, 0, 300, 10),
            I('cohesion', 'Cohesion: stay together (%)', 100, 0, 300, 10),
            O('edges', 'Screen edges', 0, EDGES),
            I('lead', 'Dance around a wandering point (%, 0 = off)', 25, 0, 100, 5),
            I('predators', 'Hawks chasing the flock', 1, 0, 4),
            I('round_seconds', 'New flock every (seconds, 0 = never)', 90, 0, 600, 10),
            B('vary', 'Vary the behaviour with each new flock', True),
        ]),
        ('Look', [
            O('background', 'Background', 0, BACKGROUNDS),
            O('colour', 'Colours', 0, COLOURS, visible=('background', 0)),
            O('shape', 'Boid shape', 0, SHAPES),
            I('size', 'Boid size (%)', 100, 50, 300, 10),
            B('glow', 'Glow (additive light)', False, visible=('background', 0)),
            O('trails', 'Motion trails', 0, TRAILS, visible=('background', 0)),
            I('dim', 'Dim the picture (%)', 0, 0, 80, 10),
        ]),
        ('Performance', [
            I('steps_per_second', 'Simulation steps per second', 60, 30, 120, 10),
            O('threads', 'Simulation threads', 0, THREADS),
            I('neighbours', 'Neighbours each boid listens to', 24 if low_power else 32, 8, 64, 4),
        ]),
    ]


if __name__ == '__main__':
    for addon_id, name, low in (('screensaver.dancingboids', 'Dancing Boids (OpenGL)', False),
                                ('screensaver.dancingboids.armv7',
                                 'Dancing Boids (OpenGL, 32-bit Android)', True)):
        root = os.path.normpath(os.path.join(HERE, '..', addon_id))
        os.makedirs(os.path.join(root, 'resources'), exist_ok=True)
        write(root, addon_id, name, categories(low), 'tools/make_settings_dancingboids.py')
