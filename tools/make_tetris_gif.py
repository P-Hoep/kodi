"""Render the demo GIF for Tetris AI with Pillow, frame by frame.

  python3 tools/make_tetris_gif.py release/gifs/tetris.gif

The frames come from the add-on's own ai, board, game and pieces and its block, grid, panel
and vignette images, so the pieces, the AI's choices, the scoring and the look are exactly
what Kodi runs. Only the Kodi window itself is not involved. Needs Pillow.

The clip starts partway into a game (seed 16, after 28 pieces) so that three lines clear
within the next eight pieces, and the clock is frozen at the time of the screenshot it was
matched to.
"""

import os
import random
import sys
import time

from PIL import Image, ImageChops, ImageDraw, ImageFont

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.normpath(os.path.join(HERE, '..', 'screensaver.tetris'))
sys.path.insert(0, ROOT)

from resources.lib import ai, board, clockface, config, game, pieces  # noqa: E402

OUT_W, OUT_H = 960, 540
SCALE = OUT_W / float(config.W)
FPS = 15
SEED = 16
START_PIECE = 29          # pieces 1-28 are played before the clip starts
CLIP_PIECES = 8
CLOCK = '11:17 AM'        # frozen: a demo should look the same every time it is rendered
CLOCK_TIME = time.struct_time((2026, 11, 8, 11, 17, 0, 6, 312, 0))

# The Kodi window's own layout, from resources/lib/screensaver.py.
PANEL_X, PANEL_Y, PANEL_W, PANEL_H = 28, 24, 420, 286
NEXT_X, NEXT_Y, NEXT_W, NEXT_H = config.W - 28 - 330, 24, 330, 220
PREVIEW_SCALE = 0.58
GHOST_ALPHA = 0x50

CAPTION = (0x8F, 0xA0, 0xB8)
VALUE = (0xF5, 0xF7, 0xFB)
WHITE = (0xFF, 0xFF, 0xFF)

FONT_PATHS = ['/Applications/Kodi.app/Contents/Resources/Kodi/media/Fonts/arial.ttf',
              '/usr/share/kodi/media/Fonts/arial.ttf',
              '/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf']


def font(size):
    for path in FONT_PATHS:
        if os.path.exists(path):
            return ImageFont.truetype(path, size)
    return ImageFont.load_default()


def rgb(argb):
    """'FF00F0F0' -> (0, 240, 240)."""
    return int(argb[2:4], 16), int(argb[4:6], 16), int(argb[6:8], 16)


def at(value):
    return int(round(value * SCALE))


class Renderer(object):
    def __init__(self, s):
        self.s = s
        self.colours = config.piece_colours(s)
        media = os.path.join(ROOT, 'resources', 'media')
        self.cell_w, self.cell_h = at(config.cell_rect(s, 0, 0)[2]), at(config.cell_rect(s, 0, 0)[3])

        block = self.open(os.path.join(media, 'block.png'), (self.cell_w, self.cell_h))
        self.blocks = dict((p, self.tint(block, rgb(c) + (255,))) for p, c in self.colours.items())
        self.blocks[board.FIXED] = self.tint(block, rgb(s['clock_colour']) + (255,))
        self.bare = self.tint(block, WHITE + (255,))
        self.ghosts = dict((p, self.fade(self.blocks[p], GHOST_ALPHA))
                           for p in self.colours)

        self.grid = self.open(os.path.join(media, 'grid.png'), (OUT_W, OUT_H))
        self.vignette = self.open(os.path.join(media, 'vignette.png'), (OUT_W, OUT_H))

        self.base = Image.new('RGB', (OUT_W, OUT_H), rgb(s['background']))
        self.base.paste(self.vignette, (0, 0), self.vignette)
        self.base.paste(self.grid, (0, 0), self.grid)

        hud = '%02X000000' % int(round(s['hud_opacity'] * 2.55))
        panel = Image.open(os.path.join(media, 'panel.png')).convert('RGBA')
        self.stats_panel = self.panel(panel, PANEL_W, PANEL_H, hud)
        self.next_panel = self.panel(panel, NEXT_W, NEXT_H, hud)

        self.preview_cell = (at(config.cell_rect(s, 0, 0)[2] * PREVIEW_SCALE),
                             at(config.cell_rect(s, 0, 0)[3] * PREVIEW_SCALE))
        small = block.resize(self.preview_cell, Image.LANCZOS)
        self.preview = dict((p, self.tint(small, rgb(c) + (255,))) for p, c in self.colours.items())

        self.clock_font = font(max(7, at(45)))
        self.score_font = font(max(7, at(30)))
        self.caption_font = font(max(7, at(13)))
        self.value_font = font(max(7, at(20)))
        self.panels_x, self.panels_y = at(PANEL_X), at(PANEL_Y)
        self.next_x, self.next_y = at(NEXT_X), at(NEXT_Y)
        self.hud_caption = CAPTION
        self.hud_value = VALUE

    @staticmethod
    def open(path, size):
        return Image.open(path).convert('RGBA').resize(size, Image.LANCZOS)

    @staticmethod
    def tint(sprite, colour):
        return ImageChops.multiply(sprite, Image.new('RGBA', sprite.size, colour))

    @staticmethod
    def fade(sprite, alpha):
        out = sprite.copy()
        out.putalpha(sprite.getchannel('A').point(lambda v: v * alpha // 255))
        return out

    def panel(self, sprite, w, h, hud):
        tinted = self.tint(sprite.resize((at(w), at(h)), Image.LANCZOS), rgb(hud) + (int(hud[:2], 16),))
        return tinted

    def render(self, letters, active, ghost, score, lines, level, best, next_letter,
               flash_rows=()):
        """One frame. active and ghost are (letter, shape, x, y) or None."""
        frame = self.base.copy()
        cw, ch = self.cell_w, self.cell_h
        for y, row in enumerate(letters):
            for x, letter in enumerate(row):
                if not letter:
                    continue
                sprite = self.bare if y in flash_rows else self.blocks[letter]
                frame.paste(sprite, (x * cw, y * ch), sprite)
        if ghost is not None:
            letter, shape, gx, gy = ghost
            for dx, dy in shape:
                frame.paste(self.ghosts[letter], ((gx + dx) * cw, (gy + dy) * ch),
                            self.ghosts[letter])
        if active is not None:
            letter, shape, ax, ay = active
            for dx, dy in shape:
                frame.paste(self.blocks[letter], ((ax + dx) * cw, (ay + dy) * ch),
                            self.blocks[letter])
        frame.paste(self.hud(score, lines, level, best, next_letter), (0, 0), self.hud(
            score, lines, level, best, next_letter))
        return frame

    def hud(self, score, lines, level, best, next_letter):
        layer = Image.new('RGBA', (OUT_W, OUT_H), (0, 0, 0, 0))
        if self.s['show_hud']:
            layer.paste(self.stats_panel, (self.panels_x, self.panels_y), self.stats_panel)
            layer.paste(self.next_panel, (self.next_x, self.next_y), self.next_panel)
        draw = ImageDraw.Draw(layer)
        if self.s['show_clock'] and self.s['clock_style'] == config.CLOCK_TEXT:
            self.text(draw, at(52), at(38), CLOCK, self.clock_font, WHITE)
        if self.s['show_hud']:
            self.text(draw, at(52), at(118), 'SCORE', self.caption_font, self.hud_caption)
            self.text(draw, at(52), at(142), format(score, ','), self.score_font, self.hud_value)
            self.text(draw, at(52), at(198), 'LINES', self.caption_font, self.hud_caption)
            self.text(draw, at(52), at(220), str(lines), self.value_font, self.hud_value)
            self.text(draw, at(172), at(198), 'LEVEL', self.caption_font, self.hud_caption)
            self.text(draw, at(172), at(220), str(level), self.value_font, self.hud_value)
            self.text(draw, at(286), at(198), 'BEST', self.caption_font, self.hud_caption)
            self.text(draw, at(286), at(220), format(best, ','), self.value_font, self.hud_value)
        if self.s['show_next']:
            self.text(draw, at(NEXT_X + 24), at(NEXT_Y + 18), 'NEXT', self.caption_font,
                      self.hud_caption)
            shape = pieces.ROTATIONS[next_letter][0]
            pw, ph = self.preview_cell
            width = pieces.width(shape) * pw
            height = pieces.height(shape) * ph
            left = self.next_x + (at(NEXT_W) - width) // 2
            top = self.next_y + at(62) + (at(NEXT_H) - at(62) - height) // 2
            sprite = self.preview[next_letter]
            for dx, dy in shape:
                layer.paste(sprite, (left + dx * pw, top + dy * ph), sprite)
        return layer

    @staticmethod
    def text(draw, x, y, value, face, colour):
        draw.text((x, y), value, font=face, fill=colour + (255,))


def play(renderer, seed=SEED, start_piece=START_PIECE, count=CLIP_PIECES):
    s = renderer.s
    b = board.Board(config.COLS, config.ROWS)
    b.set_fixed(clockface.cells(CLOCK_TIME, s['clock_24h']))
    rng = random.Random(seed)
    g = game.Game(b, rng, 1)
    frames = []

    def shoot(active=None, ghost=None, flash_rows=()):
        frames.append(renderer.render(b.letters, active, ghost, g.score, g.lines, g.level,
                                      max(g.score, best), g.next, flash_rows).copy())

    best = 0
    for n in range(1, start_piece):
        letter = g.take()
        placement = ai.choose(b, letter, rng, 0)
        shape = pieces.ROTATIONS[letter][placement.rotation]
        b.place(letter, shape, placement.x, placement.y)
        g.lock(b.remove_rows(b.full_rows()))

    for _n in range(count):
        letter = g.take()
        placement = ai.choose(b, letter, rng, 0)
        if placement is None:
            break
        shape = pieces.ROTATIONS[letter][placement.rotation]
        masks = pieces.masks(shape)
        width = pieces.width(shape)
        spawn_x = max(0, min(config.COLS - width, config.COLS // 2 - width // 2))
        if not b.fits(masks, spawn_x, 0):
            spawn_x = placement.x
        ghost = (letter, shape, placement.x, placement.y)

        shoot((letter, shape, spawn_x, 0), ghost)
        shoot((letter, shape, spawn_x, 0), ghost)       # a moment of thought
        x = spawn_x
        while x != placement.x:
            step = 1 if placement.x > x else -1
            if not b.fits(masks, x + step, 0):
                x = placement.x
                shoot((letter, shape, x, 0), ghost)
                break
            x += step
            shoot((letter, shape, x, 0), ghost)
        y = 0
        while y < placement.y:
            y += 1
            shoot((letter, shape, x, y), ghost)
        b.place(letter, shape, placement.x, placement.y)
        full = b.full_rows()
        if full:
            for _pulse in range(2):
                shoot(flash_rows=full)
                shoot()
            b.remove_rows(full)
        g.lock(len(full))
        best = max(best, g.score)
        shoot()
        shoot()
    return frames


def build(out_path):
    s = config.defaults()
    s['clock_style'] = config.CLOCK_BLOCKS      # the demo shows the clock on the playfield
    renderer = Renderer(s)
    # One shared palette for every frame, so players do not flash between palettes.
    sample = renderer.render([('IOTSZJL#' * 3)[:config.COLS]] * config.ROWS,
                             ('T', pieces.ROTATIONS['T'][0], 8, 8), None, 1234, 7, 3, 1234, 'O',
                             flash_rows=(0,))
    palette = sample.quantize(colors=256)
    frames = play(renderer)
    indexed = [frame.quantize(palette=palette, dither=Image.NONE) for frame in frames]
    indexed[0].save(out_path, save_all=True, append_images=indexed[1:],
                    duration=int(round(1000.0 / FPS)), loop=0, optimize=True, disposal=1)
    print('wrote %s: %d frames at %d fps, %.1f s, %.0f KB' % (
        out_path, len(indexed), FPS, len(indexed) / float(FPS),
        os.path.getsize(out_path) / 1024.0))


if __name__ == '__main__':
    build(sys.argv[1] if len(sys.argv) > 1 else 'tetris.gif')
