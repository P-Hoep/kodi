"""The screensaver window: an AI plays Tetris on a playfield that fills the screen.

Kodi controls do the drawing. There are 360 block images, one per board cell, each positioned
once and tinted with the piece colour; a piece moving or locking only touches the handful of
cells that changed. The active piece and its landing ghost are four more images, moved one cell
at a time, so Python wakes about 20-50 times a second only while a piece is falling.

The AI and the board live in ai.py, board.py, game.py and pieces.py, which have no Kodi imports
and are tested offline. This module is the window, the clock, the HUD and the play loop.
"""

import os
import random
import threading
import time
import traceback

import xbmc
import xbmcaddon
import xbmcgui

from . import ai, board, clockface, config, game, pieces

ADDON_ID = config.ADDON_ID

PANEL_X, PANEL_Y, PANEL_W, PANEL_H = 28, 24, 420, 286
NEXT_X, NEXT_Y, NEXT_W, NEXT_H = config.W - 28 - 330, 24, 330, 220
PREVIEW_SCALE = 0.58
GAME_OVER_SECONDS = 1.6

CAPTION = 'FF8FA0B8'
VALUE = 'FFF5F7FB'
CLOCK = 'FFFFFFFF'


def log(message, level=xbmc.LOGINFO):
    xbmc.log('[%s] %s' % (ADDON_ID, message), level)


def read_settings(addon):
    try:
        st = addon.getSettings()   # Kodi 20+
        getters = {'boolean': st.getBool, 'integer': st.getInt, 'string': st.getString}
    except AttributeError:
        getters = {'boolean': addon.getSettingBool, 'integer': addon.getSettingInt,
                   'string': addon.getSetting}
    return config.read(getters)


class ExitMonitor(xbmc.Monitor):
    def __init__(self, on_exit):
        xbmc.Monitor.__init__(self)
        self.on_exit = on_exit

    def onScreensaverDeactivated(self):
        self.on_exit()


class SaverWindow(xbmcgui.WindowXMLDialog):
    def __init__(self, *args, **kwargs):
        self.app = kwargs['app']
        self.built = False

    def onInit(self):
        if not self.built:
            self.built = True
            self.app.dialog_id = xbmcgui.getCurrentWindowDialogId()
            self.app.attach(self)

    def onAction(self, action):
        self.app.exit()


class Screensaver(object):
    def __init__(self):
        addon = xbmcaddon.Addon(ADDON_ID)
        self.path = addon.getAddonInfo('path')
        self.media = os.path.join(self.path, 'resources', 'media')
        self.s = read_settings(addon)
        self.colours = config.piece_colours(self.s)
        self.colours[board.FIXED] = self.s['clock_colour']
        self.clock_key = None
        self.rng = random.Random()
        self.game = game.Game(board.Board(config.COLS, config.ROWS), self.rng, self.s['start_level'])
        self.stop = threading.Event()
        self.monitor = ExitMonitor(self.exit)
        self.window = None
        self.dialog_id = 0
        self.thread = None
        self.best = 0

        self.cells = []
        self.shown = [None] * (config.COLS * config.ROWS)
        self.clock = None
        self.active = []
        self.ghost = []
        self.next_blocks = []
        self.active_shape = ()
        self.preview_cell = (1, 1)

    # ------------------------------------------------------------ lifecycle

    def run(self):
        """show() and wait here rather than doModal(): when Kodi itself wakes the screensaver
        (a RunScript, a screenshot) it closes the window without telling Python, doModal()
        then never returns and Kodi kills the script after 5 seconds. Waiting in a loop that
        also watches System.ScreenSaverActive always ends."""
        self.window = SaverWindow('screensaver-tetris.xml', self.path, 'Default', '1080i', app=self)
        try:
            self.window.show()
            started = time.time()
            last_minute = None
            while not self.stopped():
                if time.time() - started > 2.0 and not xbmc.getCondVisibility('System.ScreenSaverActive'):
                    break
                if (self.s['show_clock'] and self.s['clock_style'] == config.CLOCK_TEXT
                        and self.clock is not None):
                    now = time.localtime()
                    if now.tm_min != last_minute:
                        last_minute = now.tm_min
                        self.set_label(self.clock, config.clock_text(now, self.s['clock_24h']))
                self.monitor.waitForAbort(0.2)
        finally:
            self.stop.set()
            self.close_window()
            if self.thread:
                self.thread.join(2.0)
            log('closed after %d pieces, best %d' % (self.game.pieces, self.best))
            del self.window
            del self.monitor

    def attach(self, window):
        s = self.s
        block = os.path.join(self.media, 'block.png')
        controls = []

        self.background = self.image(-60, -60, config.W + 120, config.H + 120, 'white.png',
                                     s['background'])
        controls.append(self.background)
        controls.append(self.image(0, 0, config.W, config.H, 'vignette.png'))

        left, top, width, height = config.board_rect(s)
        self.grid = self.image(left, top, width, height, 'grid.png')
        self.grid.setVisible(s['show_grid'])
        controls.append(self.grid)

        cell_w, cell_h = config.cell_rect(s, 0, 0)[2:]
        for y in range(config.ROWS):
            for x in range(config.COLS):
                cell = self.image(*config.cell_rect(s, x, y), 'block.png')
                cell.setVisible(False)
                self.cells.append(cell)
                controls.append(cell)

        self.active = [self.image(0, 0, cell_w, cell_h, 'block.png') for _ in range(4)]
        self.ghost = [self.image(0, 0, cell_w, cell_h, 'block.png') for _ in range(4)]
        for cell in self.active + self.ghost:
            cell.setVisible(False)
        controls.extend(self.ghost)
        controls.extend(self.active)

        self.stats_panel = self.image(PANEL_X, PANEL_Y, PANEL_W, PANEL_H, 'panel.png',
                                      config.hud_colour(s))
        self.clock_panel = self.image(PANEL_X, PANEL_Y, 330, 92, 'panel.png',
                                      config.hud_colour(s))
        self.next_panel = self.image(NEXT_X, NEXT_Y, NEXT_W, NEXT_H, 'panel.png',
                                     config.hud_colour(s))
        self.gameover_panel = self.image(config.W // 2 - 260, config.H // 2 - 80, 520, 150,
                                         'panel.png', 'CC000000')
        controls.extend([self.stats_panel, self.clock_panel, self.next_panel, self.gameover_panel])

        self.clock = self.label(52, 38, 352, 64, '', 'font45', CLOCK)
        self.score_caption = self.label(52, 118, 352, 28, 'SCORE', 'font13', CAPTION)
        self.score_value = self.label(52, 142, 352, 46, '0', 'font30', VALUE)
        self.lines_caption = self.label(52, 198, 90, 26, 'LINES', 'font13', CAPTION)
        self.lines_value = self.label(52, 220, 90, 36, '0', 'font20', VALUE)
        self.level_caption = self.label(172, 198, 90, 26, 'LEVEL', 'font13', CAPTION)
        self.level_value = self.label(172, 220, 90, 36, '1', 'font20', VALUE)
        self.best_caption = self.label(286, 198, 120, 26, 'BEST', 'font13', CAPTION)
        self.best_value = self.label(286, 220, 120, 36, '0', 'font20', VALUE)
        self.next_caption = self.label(NEXT_X + 24, NEXT_Y + 18, NEXT_W - 48, 28, 'NEXT',
                                       'font13', CAPTION)
        self.gameover_label = self.label(config.W // 2 - 260, config.H // 2 - 84, 520, 150,
                                         'GAME OVER', 'font45', 'FFFF6B6B', align=2)
        controls.extend([self.clock, self.score_caption, self.score_value, self.lines_caption,
                         self.lines_value, self.level_caption, self.level_value,
                         self.best_caption, self.best_value, self.next_caption,
                         self.gameover_label])

        preview_w = max(1, int(round(cell_w * PREVIEW_SCALE)))
        preview_h = max(1, int(round(cell_h * PREVIEW_SCALE)))
        self.preview_cell = (preview_w, preview_h)
        self.next_blocks = [self.image(0, 0, preview_w, preview_h, 'block.png') for _ in range(4)]
        for block_control in self.next_blocks:
            block_control.setVisible(False)
        controls.extend(self.next_blocks)

        self.stats_panel.setVisible(s['show_hud'])
        for label in (self.score_caption, self.score_value, self.lines_caption, self.lines_value,
                      self.level_caption, self.level_value, self.best_caption, self.best_value):
            label.setVisible(s['show_hud'])
        self.next_panel.setVisible(s['show_next'])
        self.next_caption.setVisible(s['show_next'])
        text_clock = s['show_clock'] and s['clock_style'] == config.CLOCK_TEXT
        self.clock.setVisible(text_clock)
        self.clock_panel.setVisible(text_clock and not s['show_hud'])
        self.gameover_panel.setVisible(False)
        self.gameover_label.setVisible(False)
        window.addControls(controls)

        self.set_label(self.clock, config.clock_text(time.localtime(), s['clock_24h']))
        self.update_hud()
        self.draw_next(self.game.next)
        self.update_block_clock()
        self.draw_board()
        log('%d x %d board, %.0f%% block size, skill %s, speed %d%%, scheme %d' % (
            config.COLS, config.ROWS, s['block_size'], config.SKILLS[s['skill']], s['speed'],
            s['scheme']))
        self.thread = threading.Thread(target=self.play_loop, name='tetris-ai')
        self.thread.daemon = True
        self.thread.start()

    def close_window(self):
        """Close without waiting for Kodi's main thread (see the DVD Logo screensaver): Window.close()
        can deadlock while Kodi is shutting this script down."""
        if self.dialog_id:
            xbmc.executebuiltin('Dialog.Close(%d,true)' % self.dialog_id)
            self.monitor.waitForAbort(0.3)
        elif self.window:
            self.window.close()

    def stopped(self):
        return self.stop.is_set() or self.monitor.abortRequested()

    def exit(self):
        self.stop.set()

    def wait(self, seconds):
        deadline = time.time() + seconds
        while not self.stopped():
            left = deadline - time.time()
            if left <= 0:
                return True
            self.stop.wait(min(left, 0.03))
        return False

    # ------------------------------------------------------------ controls

    def image(self, x, y, w, h, name, colour=None):
        path = os.path.join(self.media, name)
        if colour:
            return xbmcgui.ControlImage(x, y, w, h, path, aspectRatio=0, colorDiffuse=colour)
        return xbmcgui.ControlImage(x, y, w, h, path, aspectRatio=0)

    def label(self, x, y, w, h, text, font, colour, align=0):
        return xbmcgui.ControlLabel(x, y, w, h, text, font=font, textColor=colour, alignment=align)

    @staticmethod
    def set_label(control, text):
        if control.getLabel() != text:
            control.setLabel(text)

    def update_hud(self):
        self.best = max(self.best, self.game.score)
        self.set_label(self.score_value, format(self.game.score, ','))
        self.set_label(self.lines_value, str(self.game.lines))
        self.set_label(self.level_value, str(self.game.level))
        self.set_label(self.best_value, format(self.best, ','))

    # ------------------------------------------------------------ drawing

    def draw_board(self):
        letters = self.game.board.letters
        shown = self.shown
        for y in range(config.ROWS):
            row = letters[y]
            for x in range(config.COLS):
                index = y * config.COLS + x
                letter = row[x]
                want = self.colours[letter] if letter else None
                if want == shown[index]:
                    continue
                control = self.cells[index]
                if want is None:
                    control.setVisible(False)
                else:
                    control.setColorDiffuse(want)
                    control.setVisible(True)
                shown[index] = want

    def move_active(self, x, y):
        for control, (dx, dy) in zip(self.active, self.active_shape):
            left, top = config.cell_rect(self.s, x + dx, y + dy)[:2]
            control.setPosition(left, top)

    def show_active(self, shape, x, y, colour):
        self.active_shape = shape
        for control in self.active:
            control.setColorDiffuse(colour)
            control.setVisible(True)
        self.move_active(x, y)

    def hide_active(self):
        for control in self.active:
            control.setVisible(False)

    def show_ghost(self, shape, x, y, colour):
        if not self.s['ghost']:
            self.hide_ghost()
            return
        ghost = config.ghost_colour(colour)
        for control, (dx, dy) in zip(self.ghost, shape):
            left, top = config.cell_rect(self.s, x + dx, y + dy)[:2]
            control.setPosition(left, top)
            control.setColorDiffuse(ghost)
            control.setVisible(True)

    def hide_ghost(self):
        for control in self.ghost:
            control.setVisible(False)

    def draw_next(self, letter):
        shape = pieces.ROTATIONS[letter][0]
        pw, ph = self.preview_cell
        width = pieces.width(shape) * pw
        height = pieces.height(shape) * ph
        left = NEXT_X + (NEXT_W - width) // 2
        top = NEXT_Y + 62 + (NEXT_H - 62 - height) // 2
        for control, (dx, dy) in zip(self.next_blocks, shape):
            control.setPosition(left + dx * pw, top + dy * ph)
            control.setColorDiffuse(self.colours[letter])
            control.setVisible(self.s['show_next'])

    def flash_rows(self, rows):
        indexes = [y * config.COLS + x for y in rows for x in range(config.COLS)]
        letters = self.game.board.letters
        for _pulse in range(2):
            for index in indexes:
                self.cells[index].setColorDiffuse('FFFFFFFF')
            if not self.wait(0.07):
                return
            for index in indexes:
                y, x = divmod(index, config.COLS)
                self.cells[index].setColorDiffuse(self.colours[letters[y][x]])
            if not self.wait(0.05):
                return

    # ------------------------------------------------------------ the game

    def play_loop(self):
        try:
            while not self.stopped():
                self.play_one()
        except Exception:
            log('game loop failed:\n' + traceback.format_exc(), xbmc.LOGERROR)
            self.stop.set()

    def update_block_clock(self):
        """Put the block clock on the board, once a minute. If locked pieces are in the way,
        keep the old digits and try again after the next piece locks."""
        if not self.s['show_clock'] or self.s['clock_style'] != config.CLOCK_BLOCKS:
            return
        now = time.localtime()
        key = (now.tm_hour, now.tm_min)
        if key == self.clock_key:
            return
        cells = clockface.cells(now, self.s['clock_24h'])
        if not self.game.board.can_set_fixed(cells):
            return
        self.game.board.set_fixed(cells)
        self.clock_key = key
        self.draw_board()

    def play_one(self):
        self.update_block_clock()
        game = self.game
        letter = game.take()
        self.draw_next(game.next)
        placement = ai.choose(game.board, letter, self.rng, self.s['skill'])
        if placement is None:
            self.game_over()
            return

        shape = pieces.ROTATIONS[letter][placement.rotation]
        masks = pieces.masks(shape)
        colour = self.colours[letter]
        width = pieces.width(shape)
        spawn_x = max(0, min(config.COLS - width, config.COLS // 2 - width // 2))
        if not game.board.fits(masks, spawn_x, 0):
            spawn_x = placement.x

        self.show_active(shape, spawn_x, 0, colour)
        self.show_ghost(shape, placement.x, placement.y, colour)
        think, move_delay, drop_delay = game.delays(self.s)
        if not self.wait(think):
            return

        x = spawn_x
        while x != placement.x and not self.stopped():
            step = 1 if placement.x > x else -1
            if not game.board.fits(masks, x + step, 0):
                x = placement.x
                break
            x += step
            self.move_active(x, 0)
            if not self.wait(move_delay):
                return
        if x != placement.x:
            x = placement.x
            self.move_active(x, 0)

        y = 0
        while y < placement.y and not self.stopped():
            y += 1
            self.move_active(x, y)
            if not self.wait(drop_delay):
                return

        self.hide_active()
        self.hide_ghost()
        game.board.place(letter, shape, placement.x, placement.y)
        self.draw_board()
        full = game.board.full_rows()
        if full:
            self.flash_rows(full)
            if self.stopped():
                return
            game.board.remove_rows(full)
            self.draw_board()
        game.lock(len(full))
        self.update_hud()

    def game_over(self):
        self.best = max(self.best, self.game.score)
        self.update_hud()
        self.hide_active()
        self.hide_ghost()
        self.gameover_panel.setVisible(True)
        self.gameover_label.setVisible(True)
        self.wait(GAME_OVER_SECONDS)
        self.gameover_panel.setVisible(False)
        self.gameover_label.setVisible(False)
        self.game.reset()
        self.draw_board()
        self.draw_next(self.game.next)
        self.update_hud()


def run():
    Screensaver().run()
