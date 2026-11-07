"""The screensaver window: the clock as glyph images, crumbling into grains of sand that Kodi
animates, onto a pile that sinks slowly through the floor.

Python only plans; Kodi moves everything. When a digit crumbles, each of its grains gets an
image control with a chain of 'Conditional' slide animations (wait, fall, slide down the side
of the pile, sink with it), all keyed to one Home window property for the batch, which Python
sets at the planned start time. Landed sand is merged every REBUILD seconds into strips (runs
of same-coloured grains in a column, one image each) that sink at the pile's speed with one
long slide animation; strips that have not changed keep running, so a rebuild only touches the
top of the pile. The sinking speed changes in steps, from the first rebuild after every grain
in the air has landed, so that sand already falling still lands where it was planned to.
"""

import datetime
import math
import os
import random
import threading
import time

import xbmc
import xbmcaddon
import xbmcgui

from . import config, sand

ADDON_ID = config.ADDON_ID
PROP = 'sandclock.'
TICK = 0.02
REBUILD = 1.5           # s between merges of landed sand into strips
LEAD_MARGIN = 0.12      # s between planning a crumble or rebuild and starting it
GRAIN_POOL_MAX = 5000
STRIP_POOL = 3000
INFLOW_SECONDS = 20.0   # how far back the sinking speed looks at how much sand fell
STATUS_SECONDS = 60.0
STRIP_NAMES = 48        # Home properties that start strip generations, reused round robin
BATCH_NAMES = 12
STRIP_OVERLAP = 2       # px a strip reaches down over the one below, hiding seams
VARIANTS = 4            # grain texture variants (tools/make_sandclock_media.py)
LOOKS = ['sand', None, 'beads']


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


def cond(name):
    return 'String.IsEqual(Window(Home).Property(%s%s),1)' % (PROP, name)


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


class Names(object):
    """Round-robin Home properties with a count of the controls that still need each one."""

    def __init__(self, prefix, count, home):
        self.prefix, self.count, self.home = prefix, count, home
        self.users = [0] * count
        self.next = 0

    def take(self):
        for _ in range(self.count):
            k = self.next
            self.next = (self.next + 1) % self.count
            if self.users[k] == 0:
                return k
        return None

    def name(self, k):
        return '%s%d' % (self.prefix, k)

    def start(self, k):
        self.home.setProperty(PROP + self.name(k), '1')

    def release(self, k, n=1):
        self.users[k] -= n
        if self.users[k] <= 0:
            self.users[k] = 0
            self.home.clearProperty(PROP + self.name(k))

    def clear_all(self):
        for k in range(self.count):
            self.home.clearProperty(PROP + self.name(k))


class Screensaver(object):
    def __init__(self):
        addon = xbmcaddon.Addon(ADDON_ID)
        self.path = addon.getAddonInfo('path')
        self.media = os.path.join(self.path, 'resources', 'media')
        self.s = s = read_settings(addon)
        self.folder = config.FONTS[s['font']][1]
        self.font = sand.Font.load(os.path.join(self.media, 'fonts', 'fonts.json'), self.folder, s['weight'])
        self.g = sand.grain_px(s, self.font)
        self.grid = sand.Grid(self.g)
        self.rng = random.Random()
        self.home = xbmcgui.Window(10000)
        self.stop = threading.Event()
        self.monitor = ExitMonitor(self.exit)
        self.window = None
        self.dialog_id = None
        self.thread = None
        self.batches = Names('b', BATCH_NAMES, self.home)
        self.gens = Names('s', STRIP_NAMES, self.home)

    # ------------------------------------------------------------ lifecycle

    def run(self):
        """show() and wait here rather than doModal(): when Kodi itself wakes the screensaver
        (a RunScript, a screenshot) it closes the window without telling Python, doModal()
        then never returns and Kodi kills the script after 5 seconds. Waiting in a loop that
        also watches System.ScreenSaverActive always ends."""
        self.window = SaverWindow('screensaver-sandclock.xml', self.path, 'Default', '1080i', app=self)
        try:
            self.window.show()
            started = time.time()
            while not self.stopped():
                if time.time() - started > 2.0 and not xbmc.getCondVisibility('System.ScreenSaverActive'):
                    break
                self.monitor.waitForAbort(0.2)
        finally:
            self.stop.set()
            self.close_window()
            if self.thread:
                self.thread.join(2.0)
            self.batches.clear_all()
            self.gens.clear_all()
            for key in ('bg', 'demo'):
                self.home.clearProperty(PROP + key)
            log('closed')
            del self.window
            del self.monitor

    def attach(self, window):
        s, g = self.s, self.g
        self.home.setProperty(PROP + 'bg', self.dimmed(s['background'], datetime.datetime.now()))
        look = LOOKS[s['grain_look']]
        self.look = look
        white = os.path.join(self.media, 'white.png')
        # Bottom to top: pile strips, falling grains, the clock.
        self.strip_free = [self.image(white, g, g) for _ in range(STRIP_POOL)]
        per_crumble = sum(len(sand.grains(self.font, ch, box, self.grid))
                          for ch, box in zip(sand.widest_text(s), sand.layout(s, self.font, sand.widest_text(s))))
        # Grains live from their crumble until the rebuild after they land: about three crumbles'
        # worth when the whole clock crumbles; one digit at a time needs far fewer (if a big
        # change such as midnight runs short, it just drops fewer grains).
        n_grains = min(GRAIN_POOL_MAX, int(per_crumble * (3.2 if s['crumble'] == 1 else 1.3)) + 200)
        self.grain_free = []
        for i in range(n_grains):
            tex = white if look is None else os.path.join(self.media, 'grains', look, '1_%d.png' % (i % VARIANTS))
            self.grain_free.append(self.image(tex, g, g))
        self.glyphs = [self.image(white, 10, 10) for _ in range(len(sand.widest_text(s)))]
        window.addControls(self.strip_free + self.grain_free + self.glyphs)
        for c in self.strip_free + self.grain_free + self.glyphs:
            c.setVisible(False)
        log('grain %d px, %d grains per whole clock, pools %d grains, %d strips' % (
            g, per_crumble, n_grains, STRIP_POOL))
        self.thread = threading.Thread(target=self.clock_loop, name='sandclock')
        self.thread.daemon = True
        self.thread.start()

    def image(self, path, w, h):
        return xbmcgui.ControlImage(-100, -100, w, h, path, aspectRatio=0)

    def exit(self):
        """Called from Kodi callbacks (a key, or the screensaver being woken)."""
        self.stop.set()      # run() notices and closes the window

    def close_window(self):
        """Close the window without waiting for Kodi's main thread. Window.close() waits for
        the main thread while holding Python's lock; if the main thread wants that lock at the
        same moment (it does when it stops this script because a screensaver is being started
        again), both wait forever and Kodi freezes. Dialog.Close is only posted to the main
        thread (and does nothing if Kodi already closed the window)."""
        if self.dialog_id:
            xbmc.executebuiltin('Dialog.Close(%d,true)' % self.dialog_id)
            self.monitor.waitForAbort(0.3)
        elif self.window:
            self.window.close()      # before onInit: nothing is running yet

    def stopped(self):
        return self.stop.is_set() or self.monitor.abortRequested()

    def wait_until(self, t):
        while not self.stopped():
            left = t - time.time()
            if left <= 0:
                return True
            self.stop.wait(min(left, 0.05))
        return False

    # ------------------------------------------------------------ time and colour

    def clock_time(self):
        """Seconds since midnight on the clock: the real time, or the test hook's (Home
        property sandclock.demo = HH:MM:SS, which then runs on from there)."""
        real = time.time()
        demo = self.home.getProperty(PROP + 'demo')
        if demo != self.demo_text:
            self.demo_text = demo
            self.demo_offset = 0.0
            if demo:
                try:
                    parts = [int(p) for p in demo.split(':')] + [0, 0]
                    now = datetime.datetime.now()
                    today = now.replace(hour=0, minute=0, second=0, microsecond=0)
                    shown = today + datetime.timedelta(hours=parts[0], minutes=parts[1], seconds=parts[2])
                    self.demo_offset = (shown - now).total_seconds()
                except (ValueError, IndexError):
                    pass
        local = datetime.datetime.now()
        midnight = local.replace(hour=0, minute=0, second=0, microsecond=0)
        return (local - midnight).total_seconds() + self.demo_offset, real

    def text_at(self, seconds):
        t = int(seconds) % 86400
        return sand.time_text(self.s, t // 3600, t // 60 % 60, t % 60)

    def when(self, seconds):
        t = int(seconds) % 86400
        return datetime.datetime.now().replace(hour=t // 3600, minute=t // 60 % 60, second=t % 60)

    def dimmed(self, colour, now):
        return sand.scale(colour, sand.dim_factor(self.s, now))

    def colours_for(self, seconds, text, changed):
        """The colour of each character of the clock from `seconds` on."""
        s, now = self.s, self.when(seconds)
        mode = s['colour_mode']
        if mode == config.COLOUR_ONE:
            out = [s['colour']] * len(text)
        elif mode == config.COLOUR_RAINBOW:
            out = [sand.rainbow(seconds)] * len(text)
        elif mode == config.COLOUR_EVERY_CHANGE:
            self.last_colour = sand.pick(sand.palette(s, now), self.last_colour, self.rng)
            out = [self.last_colour] * len(text)
        else:
            out = []
            for i in range(len(text)):
                if i in changed or i >= len(self.colours):
                    self.last_colour = sand.pick(sand.palette(s, now), self.last_colour, self.rng)
                    out.append(self.last_colour)
                else:
                    out.append(self.colours[i])
        return [self.dimmed(c, now) for c in out]

    # ------------------------------------------------------------ the loop

    def clock_loop(self):
        try:
            self._clock_loop()
        except Exception:
            import traceback
            log('clock thread failed:\n' + traceback.format_exc(), xbmc.LOGERROR)
        finally:
            # However the loop ended (a key, Kodi stopping the script to start a screensaver
            # again, an error), the window must close or doModal() never returns and Kodi waits
            # for this script until it gives up on it.
            if not self.stop.is_set():
                self.stop.set()
            self.close_window()

    def _clock_loop(self):
        s = self.s
        self.demo_text, self.demo_offset = None, 0.0
        self.last_colour = None
        self.text, self.boxes, self.colours = '', [], []
        self.flights = []              # [(land time, control, batch name)]
        self.strips = {}               # (col, row, length, colour) -> (control, generation name)
        self.inflow = []               # [(time, grains dropped)]
        self.next_status = time.time() + 15
        interval = 1 if s['seconds'] else 60
        lead = sand.lead(s)
        start = self.started = time.time()
        self.pile = sand.Pile(self.grid, self.rng, start)
        self.target = sand.pile_target(s, self.font, self.g)
        clock, real = self.clock_time()
        self.show(clock, sand.drift(s, 0))
        boundary = (int(clock) // interval + 1) * interval
        crumbled = None
        next_rebuild = real + REBUILD
        log('started: font %s, grain %d px, pile target %d px' % (self.folder, self.g, self.target))
        while not self.stopped():
            clock, real = self.clock_time()
            if abs(boundary - clock) > 2 * interval:          # the demo hook jumped the clock
                boundary = (int(clock) // interval + 1) * interval
                self.show(clock, sand.drift(s, real - start))
            if crumbled != boundary and clock >= boundary - lead:
                crumbled = boundary
                self.crumble(boundary, real + (boundary - lead - clock) + LEAD_MARGIN)
            if clock >= boundary:
                self.show(boundary, sand.drift(s, real - start))
                boundary += interval
            if real >= next_rebuild:
                self.rebuild(next_rebuild + LEAD_MARGIN)
                next_rebuild += REBUILD
            self.stop.wait(TICK)

    def show(self, seconds, offset):
        """Put up the clock as it is at `seconds`."""
        text = self.text_at(seconds)
        boxes = sand.layout(self.s, self.font, text, offset)
        same_layout = len(text) == len(self.text)
        changed = set(i for i, ch in enumerate(text) if not same_layout or ch != self.text[i])
        colours = self.colours_for(seconds, text, changed)
        for i, glyph in enumerate(self.glyphs):
            if i >= len(text):
                glyph.setVisible(False)
                continue
            x, y, w, h = boxes[i]
            name = 'colon' if text[i] == ':' else text[i]
            glyph.setImage(os.path.join(self.media, 'fonts', self.folder, '%d%s.png' % (self.s['weight'], name)), False)
            glyph.setPosition(int(round(x)), int(round(y)))
            glyph.setWidth(int(round(w)))
            glyph.setHeight(int(round(h)))
            glyph.setColorDiffuse(colours[i])
            glyph.setVisible(True)
        self.text, self.boxes, self.colours = text, boxes, colours

    # ------------------------------------------------------------ crumbling

    def crumble(self, boundary, t0):
        """Turn the characters that are about to change into falling grains, starting at t0."""
        s = self.s
        new = self.text_at(boundary)
        whole = s['crumble'] == 1 or len(new) != len(self.text)
        slots = [i for i, ch in enumerate(self.text) if whole or ch != new[i]]
        k = self.batches.take()
        if k is None or not slots:
            return
        gravity, spread = sand.GRAVITY[s['gravity']], sand.SPREAD[s['speed']]
        flights = []
        for i in slots:
            cells = sand.grains(self.font, self.text[i], self.boxes[i], self.grid)
            free = len(self.grain_free) - len(flights)
            if len(cells) > free:                   # out of controls: drop fewer grains
                cells = self.rng.sample(cells, max(0, free))
            flights += self.pile.drop(cells, self.colours[i], t0, gravity, spread)
        name = self.batches.name(k)
        c = cond(name)
        for f in flights:
            ctl = self.grain_free.pop()
            ctl.setPosition(int(f.x), int(round(f.y)))
            ctl.setColorDiffuse(f.colour)
            ctl.setAnimations(self.grain_animations(f, t0, c))
            ctl.setVisibleCondition(c)
            ctl.setVisible(True)
            self.flights.append((t0 + f.land_ms / 1000.0, ctl, k))
        self.batches.users[k] += len(flights)
        self.inflow.append((t0, len(flights)))
        if not self.wait_until(t0):
            return
        if flights:
            self.batches.start(k)
        for i in slots:
            self.glyphs[i].setVisible(False)

    def grain_animations(self, f, t0, c):
        anims = [('Conditional', 'effect=slide end=0,%d delay=%d time=%d tween=quadratic easing=in condition=%s'
                  % (int(round(f.fall_px)), f.delay, max(1, f.fall_ms), c))]
        if f.scatter_px:
            anims.append(('Conditional', 'effect=slide end=%d,0 delay=%d time=%d tween=sine easing=out condition=%s'
                          % (f.scatter_px, f.delay, max(1, f.fall_ms), c)))
        if f.slide_ms:
            anims.append(('Conditional', 'effect=slide end=%d,%d delay=%d time=%d condition=%s'
                          % (f.dx, int(round(f.dy)), f.delay + f.fall_ms, f.slide_ms, c)))
        speed = self.pile.speed_at(t0 + f.land_ms / 1000.0 + 0.001)
        if speed > 0:
            dist = sand.H - f.land_y + self.g
            anims.append(('Conditional', 'effect=slide end=0,%d delay=%d time=%d condition=%s'
                          % (int(dist), f.land_ms, int(1000 * dist / speed), c)))
        return anims

    # ------------------------------------------------------------ the pile

    def rebuild(self, t):
        """At time t, show the landed sand as strips and hide the grains that landed."""
        pile = self.pile
        full = pile.change is not None and t >= pile.change[0] - 0.05
        if full:
            pile.commit(pile.change[0])
        pile.prune(t)
        speed = pile.speed
        wanted = {}
        for col in list(pile.cells):
            for row, n, colour in pile.strips(col, t):
                if pile.cell_y(row + n - 1, t) < sand.H:
                    wanted[(col, row, n, colour)] = True
        keep = {} if full else dict((key, v) for key, v in self.strips.items() if key in wanted)
        drop = [v for key, v in self.strips.items() if key not in keep]
        new = [key for key in wanted if key not in keep]
        gen = self.gens.take() if new else None
        if new and gen is None:
            log('out of strip generations', xbmc.LOGWARNING)
            return
        if len(new) > len(self.strip_free) + len(drop):
            new = new[:len(self.strip_free) + len(drop)]
            log('out of strip controls', xbmc.LOGWARNING)
        fresh = {}
        free = list(self.strip_free)
        spare = [ctl for ctl, _gen in drop]
        c = cond(self.gens.name(gen)) if gen is not None else None
        pending = []
        for key in new:
            col, row, n, colour = key
            ctl = free.pop() if free else spare.pop()
            y = pile.cell_y(row + n - 1, t)
            pending.append((ctl, key, y))
        reused = set(id(ctl) for ctl, _k, _y in pending)
        for ctl, key, y in pending:
            col, row, n, colour = key
            ctl.setPosition(self.grid.x(col), int(round(y)))
            ctl.setHeight(n * self.g + STRIP_OVERLAP)
            if self.look:
                ctl.setImage(os.path.join(self.media, 'grains', self.look, '%d_%d.png' % (n, col % VARIANTS)), False)
            ctl.setColorDiffuse(colour)
            if speed > 0:
                dist = sand.H - y + self.g
                ctl.setAnimations([('Conditional', 'effect=slide end=0,%d time=%d condition=%s'
                                    % (int(dist), int(1000 * dist / speed), c))])
            else:
                ctl.setAnimations([])
            ctl.setVisibleCondition(c)
            ctl.setVisible(True)
            fresh[key] = (ctl, gen)
        if gen is not None:
            self.gens.users[gen] += len(fresh)
        if not self.wait_until(t):
            return
        if gen is not None:
            self.gens.start(gen)
        # Old strips and landed grains go once the new strips are up.
        for ctl, g in drop:
            if id(ctl) not in reused:
                ctl.setVisible(False)
            self.gens.release(g)
        self.strip_free = free + [ctl for ctl in spare if id(ctl) not in reused]
        keep.update(fresh)
        self.strips = keep
        landed = [fl for fl in self.flights if fl[0] <= t]
        self.flights = [fl for fl in self.flights if fl[0] > t]
        for _t, ctl, k in landed:
            ctl.setVisible(False)
            self.grain_free.append(ctl)
            self.batches.release(k)
        # Sink faster when the pile is too tall, slower when it is low; from a few rebuilds on.
        self.inflow = [(when, n) for when, n in self.inflow if when > t - INFLOW_SECONDS]
        rate = sum(n for _w, n in self.inflow) * self.g * self.g / min(INFLOW_SECONDS, max(1.0, t - self.started))
        height = pile.height_px(t)
        speed = sand.sink_speed(rate, height, self.target, pile.footprint(t))
        if t >= self.next_status:
            self.next_status = t + STATUS_SECONDS
            log('pile %d/%d px, sinking %d px/s, %d strips, %d grains falling' % (
                height, self.target, pile.speed, len(self.strips), len(self.flights)))
        if pile.change is None and sand.speed_changed(speed, pile.speed):
            # From the first rebuild after the last grain in the air has landed.
            last = max([fl[0] for fl in self.flights] + [t])
            pile.schedule(t + REBUILD * max(1, int(math.ceil((last - t) / REBUILD))), speed)


def run():
    Screensaver().run()
