"""The screensaver: a hands-free loop over the chosen categories. A question, a countdown, the
answer revealed, a pause, then the next question. Any key, click or the screensaver being woken
closes it straight away.

It uses the library's shared window and database. Questions come from the same shuffled block
reads as the app (one query per 600 questions), never one query per question.
"""

import random
import threading
import time
import traceback

import xbmc

from opentrivia import SCREENSAVER_ID, config, database, kodi, theme, ui
from opentrivia.ui import Closed, Screen, View

RETRY_SECONDS = 300


class ExitMonitor(xbmc.Monitor):
    def __init__(self, on_wake):
        xbmc.Monitor.__init__(self)
        self.on_wake = on_wake

    def onScreensaverDeactivated(self):
        self.on_wake()


class Saver(object):
    def __init__(self):
        self.settings = kodi.read_settings(SCREENSAVER_ID)
        self.rng = random.Random()
        self.stop = threading.Event()
        self.monitor = ExitMonitor(self.wake)
        self.screen = None
        self.started = time.time()

    def palette(self):
        return theme.resolve(self.settings, kodi.now())

    # ------------------------------------------------------------ lifecycle

    def run(self):
        """show() and wait here rather than doModal(): when Kodi itself wakes the screensaver
        (a RunScript, a screenshot, a notification) it closes the window without telling Python,
        and doModal() then never returns, so Kodi kills the script. Waiting in a loop that also
        watches System.ScreenSaverActive always ends."""
        screen = Screen.spawn('opentrivia.xml', self.logic, on_input=self.on_input,
                              palette=self.palette())
        self.screen = screen
        try:
            started = time.time()
            while not self.stopped():
                if time.time() - started > 2.0 and not xbmc.getCondVisibility('System.ScreenSaverActive'):
                    break
                self.monitor.waitForAbort(0.2)
        finally:
            self.stop.set()
            screen.shutdown()
            if screen.thread is not None:
                screen.thread.join(2.0)
            kodi.debug('screensaver closed after %.1f s' % (time.time() - self.started))

    def wake(self):
        self.stop.set()

    def on_input(self, _action_id):
        """Any key, click, touch or mouse move: close now (on Kodi's UI thread)."""
        self.wake()
        return True

    def stopped(self):
        return self.stop.is_set() or self.monitor.abortRequested()

    # ------------------------------------------------------------ the show

    def dim_colour(self):
        value = self.settings.get('dim', 0)
        return '%02X000000' % int(round(value * 2.55)) if value else ''

    def logic(self, screen):
        self.screen = screen
        if self.stopped():
            return
        view = View(screen, app=False, settings=self.settings)
        view.dim(self.dim_colour())
        try:
            source = database.Questions(kodi.db_path(), config.selected_categories(self.settings),
                                        self.rng)
        except Exception:
            kodi.log(traceback.format_exc(), xbmc.LOGERROR)
            view.message(kodi.tr(32018), '%s %s' % (kodi.tr(32036), kodi.tr(32037)))
            while True:
                screen.wait(3600)

        s = self.settings
        question_seconds = s.get('question_seconds', 10)
        reveal_seconds = s.get('reveal_seconds', 6)
        show_timer = s.get('show_timer', True)
        dim_after = s.get('dim_after_minutes', 0) * 60
        number = 0
        while True:
            # Theme (Auto switches at the day/night boundaries) and dimming at question bounds.
            screen.apply_theme(self.palette())
            if dim_after and time.time() - self.started > dim_after:
                view.dim(self.dim_colour())
            try:
                item = source.next()
            except RuntimeError:
                kodi.log('no questions match the chosen categories')
                view.message(kodi.tr(32018), kodi.tr(32019))
                screen.sleep(RETRY_SECONDS)
                continue
            number += 1
            view.question(item, number, None, s)
            if show_timer:
                screen.prop('timer', question_seconds)
            screen.sleep(question_seconds)
            screen.prop('timer', '')
            view.reveal(item.correct, None)
            screen.sleep(reveal_seconds)
            view.hide()
            screen.sleep(0.3)


def main(args):
    try:
        Saver().run()
    except Closed:
        pass
