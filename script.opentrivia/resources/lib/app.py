"""The app: start screen -> quiz round -> results, driven by remote, mouse or touch.

Every answer is a real Kodi button, so focus + Select, a mouse click and a tap all arrive as
onClick. The whole flow lives inside one WindowXMLDialog (ui.Screen) whose logic runs on a
worker thread; opening the settings dialog from there, reloading and carrying on is safe.
"""

import random
import time
import traceback

import xbmc

from opentrivia import APP_ID, config, database, kodi, quiz, theme, ui
from opentrivia.ui import Closed, Screen, View

NEXT, RESUME, END, SETTINGS, QUIT = 'next', 'resume', 'end', 'settings', 'quit'


def clicked(event, *ids):
    return bool(event) and event[0] == 'click' and (not ids or event[1] in ids)


def is_back(event):
    return bool(event) and event[0] == 'action' and event[1] in ui.BACK_ACTIONS


class App(object):
    def __init__(self):
        self.rng = random.Random()
        self.settings = kodi.read_settings(APP_ID)
        self.source = None
        self.total = 0
        self.screen = None

    def palette(self):
        return theme.resolve(self.settings, kodi.now())

    # ------------------------------------------------------------ flow

    def run(self):
        Screen.open('opentrivia.xml', self.logic, palette=self.palette())

    def logic(self, screen):
        self.screen = screen
        view = View(screen, app=True, settings=self.settings)
        view.dim(self.dim_colour())
        if not self.load_source(view):
            return
        while True:
            if self.start_screen(view) != 'start':
                return
            while True:
                action = self.play(view)
                if action == 'again':
                    continue
                if action == SETTINGS:
                    self.settings_screen(view)
                    break
                if action == 'start':
                    break
                return

    # ------------------------------------------------------------ settings and data

    def dim_colour(self):
        value = self.settings.get('dim', 0)
        return '%02X000000' % int(round(value * 2.55)) if value else ''

    def summary(self):
        chosen = config.selected_categories(self.settings)
        return kodi.tr(32052) % (config.number(len(chosen)), config.number(self.total))

    def round_summary(self, round_):
        """The line under 'Round complete': the shape of the round that just ended."""
        return kodi.tr(32059) % round_.length if round_.length else kodi.tr(32060)

    def refresh_source(self):
        if self.source is not None:
            self.source.close()
            self.source = None
        self.source = database.Questions(kodi.db_path(), config.selected_categories(self.settings),
                                         self.rng)
        self.total = self.source.total()

    def load_source(self, view):
        try:
            self.refresh_source()
            return True
        except Exception:
            kodi.log(traceback.format_exc(), xbmc.LOGERROR)
            self.database_error(view)
            return False

    def database_error(self, view):
        view.message(kodi.tr(32018), '%s %s' % (kodi.tr(32036), kodi.tr(32037)), kodi.tr(32034))
        while True:
            event = self.wait()
            if clicked(event, 150) or is_back(event):
                return

    def settings_screen(self, view=None):
        kodi.open_settings(APP_ID)
        self.settings = kodi.read_settings(APP_ID)
        if self.screen is not None:
            self.screen.apply_theme(self.palette())
        if view is not None:
            view.settings = self.settings
            view.dim(self.dim_colour())

    # ------------------------------------------------------------ start and results

    def start_screen(self, view):
        while True:
            view.start(self.summary())
            event = self.wait()
            if clicked(event, 101):
                return 'start'
            if clicked(event, 102):
                self.settings_screen(view)
                continue
            if clicked(event, 103) or is_back(event):
                return 'quit'

    def results(self, view, round_):
        view.results(round_, self.round_summary(round_))
        while True:
            event = self.wait()
            if clicked(event, 111):
                return 'again'
            if clicked(event, 112):
                return SETTINGS
            if clicked(event, 113) or is_back(event):
                return 'quit'

    # ------------------------------------------------------------ a round

    def play(self, view):
        try:
            self.refresh_source()
        except Exception:
            kodi.log(traceback.format_exc(), xbmc.LOGERROR)
            self.database_error(view)
            return 'start'
        round_ = quiz.Round(self.source, config.session_length(self.settings), self.rng)
        while True:
            item = round_.next_question()
            if item is None:
                break
            view.question(item, round_.asked, round_.length, self.settings)
            view.status(round_)
            ended = False
            while True:
                picked = self.answer(view, round_)
                if picked is QUIT:
                    return 'quit'
                if picked is END:
                    ended = True
                    break
                if picked is SETTINGS:
                    # Settings opened from the pause sheet: show the same question again.
                    self.settings_screen(view)
                    view.question(item, round_.asked, round_.length, self.settings)
                    view.status(round_)
                    continue
                break
            if ended:
                break
            correct = round_.answer(picked)
            view.reveal(item.correct, picked)
            view.status(round_)
            if round_.done:
                break
            action = self.after_answer(view, correct)
            if action == QUIT:
                return 'quit'
            if action == END:
                break
            if action == SETTINGS:
                self.settings_screen(view)
                # The answered question's card is still up; continue with the next one.
        return self.results(view, round_)

    def answer(self, view, round_):
        """Wait for an option. Back opens the pause sheet. Returns a choice index or a command."""
        while True:
            event = self.wait()
            ids = view.option_ids()
            if clicked(event, *ids):
                return ids.index(event[1])
            if is_back(event):
                action = self.pause(view)
                if action == RESUME:
                    view.question(round_.question, round_.asked, round_.length, self.settings)
                    view.status(round_)
                elif action == END:
                    return END
                elif action == SETTINGS:
                    return SETTINGS
                else:
                    return QUIT

    def after_answer(self, view, correct):
        """After the reveal: advance on a timer (auto) or on Next/Select. Back pauses."""
        s = self.settings
        seconds = 0
        if s.get('auto_advance', True):
            seconds = (s.get('advance_correct_ms', 1000) if correct
                       else s.get('advance_wrong_ms', 2500)) / 1000.0
        end = time.time() + seconds if seconds else None
        ids = view.option_ids()
        while True:
            timeout = 3600 if end is None else max(0.01, end - time.time())
            event = self.wait(timeout)
            if clicked(event, 141, *ids):
                return NEXT
            if is_back(event):
                action = self.pause(view)
                if action == SETTINGS:
                    return SETTINGS
                if action == END:
                    return END
                if action == QUIT:
                    return QUIT
                # Resume: the answer has been recorded, so carry on to the next question.
                return NEXT
            if event is None or (end is not None and time.time() >= end):
                return NEXT

    def pause(self, view):
        view.pause(True)
        try:
            while True:
                event = self.wait()
                if clicked(event, 301) or is_back(event):
                    return RESUME
                if clicked(event, 302):
                    return END
                if clicked(event, 303):
                    return SETTINGS
                if clicked(event, 304):
                    return QUIT
        finally:
            view.pause(False)

    def wait(self, timeout=3600):
        return self.screen.wait(timeout)


def main(args):
    try:
        App().run()
    except Closed:
        pass
