"""The window base shared by both front-ends, and the card presenter.

Screen: a WindowXMLDialog from the library's skin folder. doModal() runs on the add-on's
main thread; onInit starts the front-end's logic on a worker thread, and onAction / onClick
put events on a queue that the logic reads with wait(). This is the pattern the repo's other
add-ons use, and it keeps Kodi's input callbacks instant.

CardView: shows a Plan (flashcard or multiple choice) by setting window properties that
sheetcards-card.xml reads. All motion is XML animation triggered by those properties.
"""

import queue
import random
import threading
import traceback

import xbmc
import xbmcgui

from .. import kodi, theme
from . import fonts

# Kodi action ids
ACTION_SELECT = 7
ACTION_PREVIOUS_MENU = 10
ACTION_SHOW_INFO = 11
ACTION_NAV_BACK = 92
ACTION_MOUSE_RIGHT_CLICK = 101
ACTION_MOUSE_MOVE = 107
ACTION_REMOTE_1 = 59
ACTION_REMOTE_4 = 62
BACK_ACTIONS = (ACTION_PREVIOUS_MENU, ACTION_NAV_BACK, ACTION_MOUSE_RIGHT_CLICK)

OPTION_IDS = {'grid': (201, 202, 203, 204), 'stack': (211, 212, 213, 214)}

FLIP_MS = 180
ENTER_MS = 260
LEAVE_MS = 200


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
        self.monitor = xbmc.Monitor()

    @classmethod
    def open(cls, xml, logic, on_input=None, palette=None, props=None):
        """Show xml, run logic(screen) on a worker thread, return what it returned."""
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

    # ------------------------------------------------------------ Kodi callbacks

    def onInit(self):
        if self.started:
            return
        self.started = True
        thread = threading.Thread(target=self._run, name='sheetcards-ui')
        thread.daemon = True
        thread.start()

    def _run(self):
        try:
            self.result = self.logic(self)
        except Closed:
            pass
        except Exception:
            kodi.log(traceback.format_exc(), xbmc.LOGERROR)
        finally:
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
            self.close()

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

    def drain(self):
        while not self.events.empty():
            try:
                self.events.get_nowait()
            except queue.Empty:
                break

    def prop(self, key, value):
        self.setProperty('sc.' + key, '' if value is None else str(value))

    def apply_theme(self, palette):
        for key in theme.PROPERTIES:
            self.prop(key, palette.get(key, ''))

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

    def set_strings(self, mapping):
        for key, sid in mapping.items():
            self.prop(key, kodi.tr(sid))


CARD_STRINGS = {'t.missed': 32022, 't.got': 32023, 't.score': 32024, 't.streak': 32025, 't.paused': 32026,
                't.resume': 32027, 't.end': 32028, 't.quit': 32029}


class CardView(object):
    """Puts one card on the card window and runs its animations."""

    def __init__(self, screen, app, rng=None):
        self.screen = screen
        self.app = app
        self.rng = rng or random.Random()
        self.plan = None
        self.stage = None
        screen.prop('app', '1' if app else '')
        screen.set_strings(CARD_STRINGS)
        try:
            self.stage = screen.getControl(100)
            self.home = self.stage.getPosition()
        except RuntimeError:
            self.home = (0, 0)

    def clear_card(self):
        p = self.screen.prop
        for key in ('flip', 'answered', 'timer', 'hint', 'pulse', 'info'):
            p(key, '')
        for i in range(1, 5):
            p('s%d' % i, '')
            p('o%d' % i, '')

    def leave(self):
        if self.screen.getProperty('sc.shown'):
            self.screen.prop('shown', '')
            self.screen.sleep(LEAVE_MS / 1000.0 + 0.04)
        self.clear_card()

    def drift(self, box=24):
        if self.stage is not None:
            self.stage.setPosition(int(self.home[0] + self.rng.randint(-box, box)),
                                   int(self.home[1] + self.rng.randint(-box, box)))

    def show(self, plan, chip='', drift=False):
        """Lay out a card (hidden), then let it enter."""
        self.leave()
        self.plan = plan
        p = self.screen.prop
        p('chip', chip)
        p('prompt', plan.prompt)
        p('qsize', fonts.bucket(plan.prompt))
        p('reveal', plan.reveal)
        p('rsize', fonts.bucket(plan.reveal))
        p('kicker', (kodi.tr(32059) if plan.side == 'q' else kodi.tr(32058)).upper())
        p('side', 'front')
        if plan.kind == 'choice':
            p('layout', 'stack' if plan.stacked else 'grid')
            p('n', len(plan.options))
            for i, text in enumerate(plan.options):
                p('o%d' % (i + 1), text)
            p('view', 'choice')
        else:
            p('view', 'flash')
            if self.app:
                p('hint', kodi.tr(32042))
        if drift:
            self.drift()
        p('shown', '1')
        self.screen.sleep(ENTER_MS / 1000.0)

    def option_ids(self):
        return OPTION_IDS['stack' if self.plan.stacked else 'grid'][:len(self.plan.options)]

    def flip(self):
        """Front -> back: squash to zero width, swap sides, grow back (XML Conditional)."""
        p = self.screen.prop
        p('hint', '')
        p('flip', '1')
        self.screen.sleep(FLIP_MS / 1000.0 + 0.02)
        p('side', 'back')
        p('kicker', (kodi.tr(32058) if self.plan.side == 'q' else kodi.tr(32059)).upper())
        p('flip', '')
        self.screen.sleep(FLIP_MS / 1000.0)

    def reveal_choice(self, picked=None):
        """Correct option green; a wrong pick red; with no pick (screensaver) the rest fade."""
        for i in range(len(self.plan.options)):
            state = ''
            if i == self.plan.correct:
                state = 'good'
            elif picked is not None and i == picked:
                state = 'bad'
            elif picked is None:
                state = 'dim'
            self.screen.prop('s%d' % (i + 1), state)

    def message(self, title, body='', button='', button2=''):
        self.leave()
        p = self.screen.prop
        p('msg.title', title)
        p('msg.body', body)
        p('msg.button', button)
        p('msg.button2', button2)
        p('view', 'message')
        p('shown', '1')
        self.screen.sleep(ENTER_MS / 1000.0)
        if button:
            self.screen.focus(152 if button2 else 150)
