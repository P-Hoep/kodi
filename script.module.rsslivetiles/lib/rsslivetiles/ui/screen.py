"""The window base shared by both front-ends.

doModal() runs on the add-on's main thread; onInit starts the front-end's logic on a worker
thread, and onAction / onClick put events on a queue that the logic reads with wait(). This is
the pattern the repo's other add-ons use, and it keeps Kodi's input callbacks instant.

The program uses a full WindowXML (so a video enclosure can play fullscreen over it); the
screensaver a WindowXMLDialog.
"""

import queue
import threading
import traceback

import xbmc
import xbmcgui

from .. import kodi

ACTION_LEFT, ACTION_RIGHT, ACTION_UP, ACTION_DOWN = 1, 2, 3, 4
ACTION_PAGE_UP, ACTION_PAGE_DOWN = 5, 6
ACTION_SELECT = 7
ACTION_PREVIOUS_MENU = 10
ACTION_SHOW_INFO = 11
ACTION_CONTEXT_MENU = 117
ACTION_NAV_BACK = 92
ACTION_MOUSE_RIGHT_CLICK = 101
ACTION_MENU = 163
ACTION_SCROLL_UP, ACTION_SCROLL_DOWN = 111, 112
ACTION_MOUSE_WHEEL_UP, ACTION_MOUSE_WHEEL_DOWN = 104, 105
ACTION_MOUSE_MOVE = 107
ACTION_PLAYER_PLAY = 79
BACK_ACTIONS = (ACTION_PREVIOUS_MENU, ACTION_NAV_BACK, ACTION_MOUSE_RIGHT_CLICK)
MENU_ACTIONS = (ACTION_CONTEXT_MENU, ACTION_MENU)
NOISE = (ACTION_MOUSE_MOVE, 0)


class Closed(Exception):
    """The window closed (or Kodi is shutting down) while the logic was waiting."""


class _Base(object):
    def _setup(self):
        self.events = queue.Queue()
        self.started = False
        self.closed = threading.Event()
        self.logic = None
        self.result = None
        self.on_input = None          # screensaver: called on the UI thread for instant exit
        self.monitor = xbmc.Monitor()

    @classmethod
    def open(cls, xml, logic, on_input=None, props=None):
        """Show xml, run logic(screen) on a worker thread, return what it returned."""
        screen = cls(xml, kodi.library_path(), 'Default', '1080i')
        screen.logic = logic
        screen.on_input = on_input
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
        thread = threading.Thread(target=self._run, name='rsslivetiles-ui')
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
        if aid in NOISE:
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

    def post(self, event):
        """Events from other threads (feed refreshes)."""
        self.events.put(event)

    def wait(self, seconds):
        """The next event within seconds, or None. Raises Closed when the window closed."""
        remaining = seconds
        while True:
            if self.closed.is_set() or self.monitor.abortRequested():
                raise Closed()
            step = min(0.05, max(0.0, remaining))
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
            if self.closed.is_set() or self.monitor.waitForAbort(min(0.05, end)):
                raise Closed()
            end -= 0.05

    def prop(self, key, value):
        self.setProperty(key, '' if value is None else str(value))

    def props(self, mapping):
        for key, value in mapping.items():
            self.setProperty(key, '' if value is None else str(value))

    def control(self, cid):
        try:
            return self.getControl(cid)
        except RuntimeError:
            return None


class AppScreen(_Base, xbmcgui.WindowXML):
    def __init__(self, *args, **kwargs):
        self._setup()


class SaverScreen(_Base, xbmcgui.WindowXMLDialog):
    def __init__(self, *args, **kwargs):
        self._setup()
