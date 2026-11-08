"""Render the demo GIF for DVD Logo with Pillow, frame by frame.

  python3 tools/make_dvdlogo_gif.py release/gifs/dvd-logo.gif

The frames are drawn from the add-on's own bounce.Motion, so the corner hit and the
last-second veer in the clip are exactly what Kodi runs: the same fold, the same aim, the same
six-step swerve. Only the Kodi window itself is not involved. Needs Pillow.
"""

import math
import os
import random
import sys

from PIL import Image

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.normpath(os.path.join(HERE, '..', 'screensaver.dvdlogo'))
sys.path.insert(0, ROOT)

from resources.lib import bounce, config  # noqa: E402

FPS = 20                # 10 px of travel per frame at 200 px/s, then downscaled with the logo
SECONDS = 22.0          # seed 101: a corner hit at 6.2 s, then a near miss at 20.9 s
OUT_W, OUT_H = 800, 450
VEER_LEAD = 0.5
MAX_RUN = 1100.0           # keep the demo's corner runs short: a corner within about 5 seconds
WHITE = (255, 255, 255)
HIT_COLOUR = (64, 224, 255)


def plan(seed=101, width=config.W, height=config.H):
    """The legs the logo runs, with a corner hit first and a near miss after it.

    Returns (legs, hits, veers); each leg is (start, end, before, after).
    """
    s = config.defaults()
    logo_w, logo_h = config.logo_pixels(s)
    field_w, field_h = width - logo_w, height - logo_h
    rng = random.Random(seed)
    motion = bounce.Motion(field_w, field_h, config.speed_pixels(s), rng)
    while True:
        x, y = rng.uniform(0, field_w), rng.uniform(0, field_h)
        motion.start(x, y)
        first = motion.physical_velocity()
        if min(abs(first[0]), abs(first[1])) > 0.35 * motion.speed:
            break

    legs, hits, veers = [], [], []
    now = 0.0
    phase = 'hit'              # aim at a corner; then fake one after it lands
    next_try = 1.0
    while now < SECONDS:
        dt, kind = motion.next_leg()
        before = motion.point()
        motion.advance(dt, kind)
        after = motion.point()
        legs.append((now, now + dt, before, after))
        now += dt
        if kind == 'corner':
            hits.append((now, after))
            motion.target = None
            phase = 'miss'
            next_try = now + 1.0
        elif kind == 'veer':
            veers.append((now, after))
        elif kind == 'wall' and motion.target is None and not motion.turning and now >= next_try:
            target = (motion.aim_near_miss(VEER_LEAD, max_distance=MAX_RUN) if phase == 'miss'
                      else motion.aim(max_distance=MAX_RUN))
            if target is not None:
                next_try = float('inf')     # one trick per phase; the next one is set by the event
    return legs, hits, veers


def position_at(legs, t):
    for start, end, before, after in legs:
        if start <= t <= end:
            u = 0.0 if end == start else (t - start) / (end - start)
            return (before[0] + (after[0] - before[0]) * u,
                    before[1] + (after[1] - before[1]) * u)
    return legs[-1][3]


def build(out_path):
    legs, hits, veers = plan()
    if not hits:
        sys.exit('no corner hit in %.0f s; raise SECONDS' % SECONDS)
    if not veers:
        sys.exit('no veer in %.0f s; raise SECONDS' % SECONDS)

    s = config.defaults()
    logo_w, logo_h = config.logo_pixels(s)
    logo = Image.open(os.path.join(ROOT, 'resources', 'media', 'dvd.png')).convert('RGBA')
    logo = logo.resize((logo_w, logo_h), Image.LANCZOS)
    hit_at = hits[0][0]

    frames, colours = [], []
    for i in range(int(SECONDS * FPS)):
        now = i / float(FPS)
        colour = HIT_COLOUR if now >= hit_at else WHITE
        colours.append(colour)
        frame = Image.new('RGB', (config.W, config.H), (0, 0, 0))
        x, y = position_at(legs, now)
        tint = Image.new('RGBA', logo.size, colour + (255,))
        tint.putalpha(logo.getchannel('A'))
        frame.paste(tint, (int(round(x)), int(round(y))), tint)
        frames.append(frame.resize((OUT_W, OUT_H), Image.LANCZOS))

    # One palette for every frame: black plus each colour's alpha ramp. Without this each
    # frame carries its own palette and viewers flash between them.
    ramp = list(range(0, 256, 17))
    palette = [(0, 0, 0)]
    for colour in (WHITE, HIT_COLOUR):
        for v in ramp:
            palette.append(tuple(int(c * v / 255.0) for c in colour))
    palette += [(0, 0, 0)] * (256 - len(palette))
    pal_img = Image.new('P', (1, 1))
    pal_img.putpalette([c for rgb in palette for c in rgb])

    indexed = [frame.quantize(palette=pal_img, dither=Image.NONE) for frame in frames]
    indexed[0].save(out_path, save_all=True, append_images=indexed[1:],
                    duration=int(round(1000.0 / FPS)), loop=0, optimize=True, disposal=1)
    print('wrote %s: %d frames at %d fps, corner hit at %.2f s, veer at %.2f s, %.0f KB' % (
        out_path, len(indexed), FPS, hit_at, veers[0][0], os.path.getsize(out_path) / 1024.0))


if __name__ == '__main__':
    build(sys.argv[1] if len(sys.argv) > 1 else 'dvdlogo.gif')
