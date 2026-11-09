"""The shared window and its presenter, used by the app and the screensaver.

Screen is a WindowXMLDialog from the library's skin. doModal() (the app) or show() (the
screensaver) runs on the add-on's main thread; onInit starts the front-end's logic on a worker
thread, and onAction / onClick put events on a queue the logic reads with wait(). That keeps
Kodi's input callbacks instant and lets every front-end live in one XML file.

View sets the window properties opentrivia.xml reads: the view, the question and its font
bucket, the answer states and the theme colours. All motion is XML animation triggered by those
properties; Python never moves controls in a loop.
"""

import queue
import threading
import traceback

import xbmc
import xbmcgui

from . import config, kodi, quiz, theme

# Kodi action ids
ACTION_SELECT = 7
ACTION_PREVIOUS_MENU = 10
ACTION_NAV_BACK = 92
ACTION_MOUSE_RIGHT_CLICK = 101
ACTION_MOUSE_MOVE = 107
BACK_ACTIONS = (ACTION_PREVIOUS_MENU, ACTION_NAV_BACK, ACTION_MOUSE_RIGHT_CLICK)

OPTION_IDS = {'duo': (221, 222), 'stack': (211, 212, 213, 214), 'grid': (201, 202, 203, 204)}
ENTER_MS = 240
LEAVE_MS = 200

# Static wording is set once from the library's strings.po; see config.VIEW_STRINGS.
VIEW_STRINGS = config.VIEW_STRINGS


class Closed(Exception):
    """The window closed (or Kodi is shutting down) while the logic was waiting."""


class Screen(xbmcgui.WindowXMLDialog):
    def __init__(self, *args, **kwargs):
        self.events = queue.Queue()
        self.started = False
        self.closed = threading.Event()
        self.logic = None
        self.result = None
        self.on_input = None          # screensaver: called on the UI thread for instant exit
        self.close_on_finish = True   # the screensaver closes its own window from the main loop
        self.dialog_id = 0
        self.monitor = xbmc.Monitor()
        self.thread = None

    # ------------------------------------------------------------ opening

    @classmethod
    def open(cls, xml, logic, on_input=None, palette=None, props=None):
        """Show xml modally, run logic(screen) on a worker thread, return what it returned."""
        screen = cls(xml, kodi.library_path(), 'Default', '1080i')
        screen.logic = logic
        screen.on_input = on_input
        if palette:
            screen.apply_theme(palette)
        for key, value in (props or {}).items():
            screen.prop(key, value)
        try:
            screen.doModal()
        finally:
            screen.closed.set()
        result = screen.result
        del screen
        return result

    @classmethod
    def spawn(cls, xml, logic, on_input=None, palette=None, props=None):
        """Show xml without blocking (the screensaver). Returns the screen; the caller closes it."""
        screen = cls(xml, kodi.library_path(), 'Default', '1080i')
        screen.logic = logic
        screen.on_input = on_input
        screen.close_on_finish = False
        if palette:
            screen.apply_theme(palette)
        for key, value in (props or {}).items():
            screen.prop(key, value)
        screen.show()
        return screen

    # ------------------------------------------------------------ Kodi callbacks

    def onInit(self):
        if self.started:
            return
        self.started = True
        self.dialog_id = xbmcgui.getCurrentWindowDialogId()
        thread = threading.Thread(target=self._run, name='opentrivia-ui')
        thread.daemon = True
        self.thread = thread
        thread.start()

    def _run(self):
        try:
            self.result = self.logic(self)
        except Closed:
            pass
        except Exception:
            kodi.log(traceback.format_exc(), xbmc.LOGERROR)
        finally:
            if self.close_on_finish:
                self.finish()

    def onAction(self, action):
        aid = action.getId()
        if self.on_input and self.on_input(aid):
            return
        self.events.put(('action', aid))

    def onClick(self, control_id):
        self.events.put(('click', control_id))

    def finish(self, result=None):
        if result is not None:
            self.result = result
        if not self.closed.is_set():
            self.closed.set()
            try:
                self.close()
            except RuntimeError:
                pass

    def shutdown(self):
        """Close from the screensaver's main loop. Dialog.Close is posted to Kodi's main thread
        and does nothing if Kodi has already closed the window; self.close() would wait on the
        main thread and can deadlock if Kodi is restarting the screensaver."""
        self.closed.set()
        if self.dialog_id:
            xbmc.executebuiltin('Dialog.Close(%d,true)' % self.dialog_id)
        else:
            try:
                self.close()
            except RuntimeError:
                pass

    # ------------------------------------------------------------ logic helpers

    def wait(self, seconds):
        """The next event within seconds, or None. Raises Closed when the window closed."""
        remaining = seconds
        while True:
            if self.closed.is_set() or self.monitor.abortRequested():
                raise Closed()
            step = min(0.1, max(0.0, remaining))
            try:
                return self.events.get(timeout=step) if step > 0 else self.events.get_nowait()
            except queue.Empty:
                pass
            remaining -= step
            if remaining <= 0:
                return None

    def sleep(self, seconds):
        """Wait without consuming events."""
        end = seconds
        while end > 0:
            if self.closed.is_set() or self.monitor.waitForAbort(min(0.1, end)):
                raise Closed()
            end -= 0.1

    def prop(self, key, value):
        self.setProperty('ot.' + key, '' if value is None else str(value))

    def apply_theme(self, palette):
        for key in theme.PROPERTIES:
            self.prop(key, palette.get(key, ''))

    def set_strings(self, mapping):
        for key, sid in mapping.items():
            self.prop(key, kodi.tr(sid))

    def focus(self, control_id, settle=0.06):
        """Visibility comes from properties, which Kodi applies on its next frame."""
        for _ in range(10):
            xbmc.sleep(int(settle * 1000))
            try:
                self.setFocusId(control_id)
                if self.getFocusId() == control_id:
                    return True
            except RuntimeError:
                pass
        return False


class View(object):
    """Puts one screenful on the shared window by setting ot.* properties."""

    def __init__(self, screen, app=False, settings=None):
        self.screen = screen
        self.app = app
        self.settings = settings or {}
        self.layout = 'grid'
        self.n = 0
        screen.prop('app', '1' if app else '')
        screen.prop('clock', '1' if not app and self.settings.get('show_clock', True) else '')
        screen.prop('paused', '')
        screen.set_strings(VIEW_STRINGS)

    # ------------------------------------------------------------ views

    def start(self, summary, hint=''):
        self.clear()
        p = self.screen.prop
        p('view', 'start')
        p('summary', summary)
        p('hint', hint)
        p('tagline', kodi.tr(32001))
        p('title', kodi.tr(32000))
        self.screen.sleep(0.05)
        self.screen.focus(101)

    def question(self, item, number, total=None, settings=None):
        s = settings or self.settings
        self.settings = s
        self.clear()
        layout = quiz.layout(s, item.choices)
        self.layout, self.n = layout, len(item.choices)
        p = self.screen.prop
        p('view', 'quiz')
        p('q', item.question)
        p('qsize', quiz.question_bucket(item.question, s.get('text_size', 100)))
        p('osize', quiz.option_bucket(max(item.choices, key=len), s.get('text_size', 100)))
        p('layout', layout)
        p('n', self.n)
        p('letters', '1' if s.get('show_letters', True) else '')
        category = config.category_title(item.category)
        # The app's top bar has the chip; the screensaver's card kicker carries the category
        # instead, so the same word never appears twice.
        p('chip', category if (self.app and s.get('show_category', True)) else '')
        if self.app and s.get('show_number', True):
            label = kodi.tr(32023) % (number, total) if total else kodi.tr(32024) % number
        else:
            label = category if s.get('show_category', True) else kodi.tr(32051)
        p('kicker', label.upper())
        p('progress', self._progress(number, total) if self.app else '')
        p('hint', kodi.tr(32011) if self.app else '')
        for i, text in enumerate(item.choices):
            p('o%d' % (i + 1), text)
        for i in range(self.n, 4):
            p('o%d' % (i + 1), '')
        self.screen.sleep(ENTER_MS / 1000.0)
        if self.app:
            self.focus_option()

    def reveal(self, correct, picked):
        p = self.screen.prop
        for i in range(self.n):
            p('s%d' % (i + 1), 'good' if i == correct else ('bad' if i == picked else 'dim'))
        right = picked is None or picked == correct
        p('result', 'good' if right else 'bad')
        p('feedback', kodi.tr(32013) if right else kodi.tr(32014))
        if self.app and picked is not None:
            self.screen.sleep(0.05)
            self.screen.focus(141)

    def status(self, round_):
        p = self.screen.prop
        p('score_text', '%s %d' % (kodi.tr(32025), round_.score))
        p('streak_text', '%s %d' % (kodi.tr(32026), round_.streak) if round_.asked else '')
        if round_.length:
            p('progress', self._progress(round_.asked, round_.length) if self.app else '')

    def results(self, round_, summary):
        self.clear()
        p = self.screen.prop
        p('view', 'results')
        p('summary', summary)
        p('r.score', '%d / %d' % (round_.score, round_.asked))
        p('r.accuracy', kodi.tr(32008) % int(round(round_.accuracy)))
        p('r.best', str(round_.best))
        p('r.counts', '%s  ·  %s' % (kodi.tr(32029) % round_.score,
                                     kodi.tr(32030) % (round_.asked - round_.score)))
        self.screen.sleep(0.05)
        self.screen.focus(111)

    def message(self, title, body, button=''):
        self.clear()
        p = self.screen.prop
        p('view', 'message')
        p('msg.title', title)
        p('msg.body', body)
        p('msg.button', button)
        if button:
            self.screen.sleep(0.05)
            self.screen.focus(150)

    def pause(self, on):
        self.screen.prop('paused', '1' if on else '')
        if on:
            self.screen.sleep(0.05)
            self.screen.focus(301)

    def dim(self, colour):
        self.screen.prop('dim', colour)

    def hide(self):
        self.clear()

    # ------------------------------------------------------------ helpers

    def clear(self):
        p = self.screen.prop
        for key in ('q', 'qsize', 'osize', 'layout', 'kicker', 'chip', 'timer', 'result',
                    'feedback', 'hint', 'progress', 'score_text', 'streak_text', 'summary',
                    'msg.title', 'msg.body', 'msg.button'):
            p(key, '')
        p('n', 0)
        p('view', '')
        for i in range(1, 5):
            p('o%d' % i, '')
            p('s%d' % i, '')

    def option_ids(self):
        return OPTION_IDS[self.layout][:self.n]

    def focus_option(self):
        ids = self.option_ids()
        if ids:
            self.screen.focus(ids[0])

    def _progress(self, number, total):
        """The top bar's compact '1 / 20'; the card's kicker carries the full wording."""
        return kodi.tr(32007) % (number, total) if total else ''


def colour_with_alpha(colour, alpha):
    """'FFE2B96A' + 0x40 -> '40E2B96A'."""
    return '%02X%s' % (max(0, min(255, int(alpha))), colour[2:])
