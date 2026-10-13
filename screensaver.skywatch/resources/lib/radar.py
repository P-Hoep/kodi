"""Radar feeds: plan the past + future frames for one view, download them into the frame
store, and keep a manifest. No Kodi imports.

Every frame's files have a deterministic path (frames/<source>/<view key>/<frame key>_<n>.png)
so the background service can pre-warm frames the screensaver later finds on disk. The
fallback chain picks, for past and for future, the first source that covers the view and is
not backing off (Rainbow -> HRRR -> past only). manifest.json is rewritten atomically after
each change, for anything outside this process that wants to read the frame list.
"""

import json
import math
import os
import threading
import time

from . import cache, geo, net, raster
from .sources import gibs as gibs_mod
from .sources.hrrr import HRRR
from .sources.iem import IEM
from .sources.librewxr import LibreWXR
from .sources.rainbow import Rainbow
from .sources.rainviewer import RainViewer

RESOLUTION = {'low': (640, 360), 'balanced': (960, 540), 'high': (1920, 1080)}
MAX_FRAMES = {'low': 24, 'balanced': 36, 'high': 36}


class Chains(object):
    """The source objects for one session, shared by every feed (so run and snapshot
    lookups are cached once)."""

    def __init__(self, settings):
        s = settings
        precip_type = s.get('color_scheme', 0) == 1
        blue = s.get('color_scheme', 0) == 2
        self.iem = IEM()
        self.rainviewer = RainViewer(blue)
        self.hrrr = HRRR(precip_type)
        self.libre = LibreWXR(s['librewxr_url'], blue) if s.get('librewxr_url') else None
        key = s.get('rainbow_key') or ''
        self.rainbow = Rainbow(key, s.get('rainbow_cap', 27) * 1000) if key else None
        self.gibs = gibs_mod.GIBS()
        self.future_mode = s.get('future_source', 0)

    def past(self):
        out = []
        if self.libre:
            out.append(self.libre)
        return out + [self.iem, self.rainviewer]

    def future(self, allow_rainbow=True):
        mode = self.future_mode
        out = []
        if mode == 4:
            return out
        if mode in (0, 2) and self.rainbow and allow_rainbow:
            out.append(self.rainbow)
        if mode == 3 and self.libre:
            out.append(self.libre)
        if mode in (0, 1, 2, 3):
            out.append(self.hrrr)
        return out


class Feed(object):
    """Past and future frames for one view."""

    def __init__(self, name, view, chains, root, size, budget, log, past_minutes, future_minutes,
                 max_frames=36, past_step=300, future_step=None, allow_rainbow=True):
        self.name = name
        self.view = view
        self.chains = chains
        self.root = root
        self.size = size
        self.budget = budget
        self.log = log
        self.past_minutes = past_minutes
        self.future_minutes = future_minutes
        self.max_frames = max_frames
        self.past_step = past_step
        self.future_step = future_step
        self.allow_rainbow = allow_rainbow
        self.lock = threading.Lock()
        self.inflight = set()
        self.failed = {}
        self.plan = []
        self.planned_at = 0.0
        self.version = 0
        self.ready = []
        self.past_source = self.future_source = None
        self.future_state = 'off'
        self.rainbow_at = 0.0

    # ------------------------------------------------------------ planning

    def _choose(self, chain):
        for src in chain:
            if src.covers(self.view.lat, self.view.lon) and self.budget.ready(src.id):
                return src
        return None

    def make_plan(self):
        v = self.view
        past_src = self._choose(self.chains.past()) if self.past_minutes else None
        future_chain = self.chains.future(self.allow_rainbow) if self.future_minutes else []
        future_src = self._choose(future_chain)
        frames = []
        if past_src is not None:
            try:
                if isinstance(past_src, IEM):
                    frames += past_src.frames(v, 'past', self.past_minutes, self.size, self.past_step)
                else:
                    frames += past_src.frames(v, 'past', self.past_minutes, self.size)
            except Exception as error:
                self.log('%s: %s frames failed: %s' % (self.name, past_src.id, error))
        future = []
        if future_src is not None:
            if isinstance(future_src, Rainbow) and not self._rainbow_allowed(future_src):
                future_src = self._choose([s for s in future_chain if not isinstance(s, Rainbow)])
            try:
                if isinstance(future_src, HRRR):
                    future = future_src.frames(v, 'future', self.future_minutes, self.size,
                                               self.future_step or 900)
                elif future_src is not None:
                    future = future_src.frames(v, 'future', self.future_minutes, self.size)
            except Exception as error:
                self.log('%s: %s frames failed: %s' % (self.name, future_src.id, error))
        # Keep within the frame budget: future frames first, then every nth past frame.
        room = max(4, self.max_frames - len(future)) if frames else 0
        future = future[:self.max_frames - min(room, len(frames))]
        if len(frames) > room:
            stride = int(math.ceil(len(frames) / float(room)))
            frames = frames[::-1][::stride][::-1]
        for f in frames:
            f['source'] = past_src.id
        for f in future:
            f['source'] = future_src.id
            f['model'] = getattr(future_src, 'model', False)
        self.past_source, self.future_source = past_src, future_src
        with self.lock:
            self.plan = frames + future
            self.planned_at = time.time()
        return self.plan

    def _rainbow_allowed(self, src):
        """Refresh the nowcast at most hourly and only while the month's tiles allow it."""
        planned = [f for f in self.plan if f.get('source') == src.id]
        if planned and time.time() - self.rainbow_at < src.refresh:
            return True     # keep the frames we already paid for
        cost = len(self.view.tiles_at(max(0, self.view.zoom - 1))) * (self.future_minutes * 60 // 1200)
        if not self.budget.allows(src.id, cost, src.quota):
            self.log('%s: Rainbow.ai monthly allowance nearly used; using HRRR' % self.name)
            return False
        self.rainbow_at = time.time()
        return True

    # ------------------------------------------------------------ files

    def part_path(self, frame, n):
        folder = os.path.join(self.root, frame['source'], self.view.key() + '_%dx%d' % self.size)
        return os.path.join(folder, '%s_%d.png' % (frame['key'], n))

    def frame_ready(self, frame):
        return all(os.path.exists(self.part_path(frame, n)) for n in range(len(frame['parts'])))

    def update(self, submit, stop=None):
        """Re-plan when due and queue downloads of missing parts via submit(fn, *args)."""
        due = 60 if not self.plan else 150
        if time.time() - self.planned_at > due:
            self.make_plan()
        with self.lock:
            plan = list(self.plan)
        for frame in plan:
            if stop is not None and stop.is_set():
                return
            for n, part in enumerate(frame['parts']):
                path = self.part_path(frame, n)
                key = (frame['key'], n)
                if key in self.inflight or os.path.exists(path):
                    continue
                if time.time() - self.failed.get(key, 0) < 90:
                    continue
                self.inflight.add(key)
                submit(self._download, frame, n, part[0], path, key)
        self._refresh_ready(plan)

    def _download(self, frame, n, url, path, key):
        src = frame['source']
        try:
            if not self.budget.ready(src):
                return
            body = net.fetch_image(url, timeout=10)
            self.budget.count(src)
            cache.write_atomic(path, body)
            self.budget.ok(src)
            with self.lock:
                self._refresh_ready(self.plan)
        except net.HttpError as error:
            self.failed[key] = time.time()
            if error.status == 429 or (error.status or 0) >= 500:
                delay = self.budget.failed(src, error.status, str(error))
                self.log('%s: %s backing off %d s (%s)' % (self.name, src, delay, error))
                self.planned_at = 0   # re-plan: the chain may fall back to another source
            else:
                self.log('%s: frame %s failed: %s' % (self.name, frame['key'], error))
        finally:
            self.inflight.discard(key)

    def _refresh_ready(self, plan):
        ready = []
        for frame in plan:
            if self.frame_ready(frame):
                ready.append(dict(frame, files=[(self.part_path(frame, n),) + tuple(p[1:])
                                                for n, p in enumerate(frame['parts'])]))
        keys = [f['key'] for f in ready]
        if keys != [f['key'] for f in self.ready]:
            self.ready = ready
            self.version += 1
            self._write_manifest(plan)
        futures = [f for f in plan if f['kind'] == 'future']
        if not futures:
            self.future_state = 'off' if not self.future_minutes else 'pending'
        else:
            self.future_state = 'ok' if any(f['kind'] == 'future' for f in ready) else 'pending'

    def _write_manifest(self, plan):
        try:
            folder = os.path.join(self.root, 'manifests')
            body = json.dumps({'feed': self.name, 'view': self.view.key(), 'updated': time.time(),
                               'future': self.future_state,
                               'frames': [{'t': f['t'], 'kind': f['kind'], 'key': f['key'], 'run': f.get('run'),
                                           'source': f['source'], 'files': f['files']} for f in self.ready]})
            cache.write_atomic(os.path.join(folder, '%s.json' % self.name), body)
        except Exception as error:
            self.log('manifest: %s' % error)

    def prune(self):
        """Delete this feed's files that are no longer planned (expired past frames, old runs)."""
        with self.lock:
            keep = set()
            for frame in self.plan:
                for n in range(len(frame['parts'])):
                    keep.add(self.part_path(frame, n))
        folders = set(os.path.dirname(p) for p in keep)
        for folder in folders:
            try:
                names = os.listdir(folder)
            except OSError:
                continue
            for name in names:
                full = os.path.join(folder, name)
                if full not in keep and time.time() - os.path.getmtime(full) > 600:
                    try:
                        os.remove(full)
                    except OSError:
                        pass


# ---------------------------------------------------------------- overlays

def warning_overlay(view, polygons, path, width=4):
    """Draw warning polygon outlines for the view into a full-size transparent PNG."""
    canvas = raster.Canvas(view.width, view.height)
    for poly in polygons:
        for ring in poly['rings']:
            pts = [view.screen_xy(lat, lon) for lon, lat in ring]
            if not any(-200 <= x <= view.width + 200 and -200 <= y <= view.height + 200 for x, y in pts):
                continue
            # A dark halo under the colour keeps outlines readable over any radar colour.
            for a, b in zip(pts, pts[1:] + pts[:1]):
                canvas.line(a[0], a[1], b[0], b[1], 'A0000000', width + 3)
            for a, b in zip(pts, pts[1:] + pts[:1]):
                canvas.line(a[0], a[1], b[0], b[1], poly['color'], width)
    cache.write_atomic(path, canvas.png())
    return path


def upwind_center(lat, lon, wind_from_deg, view_km):
    """Move the map centre a quarter of the view towards where the weather comes from."""
    if wind_from_deg is None:
        return lat, lon
    sector = round(wind_from_deg / 45.0) * 45 % 360   # quantised so the view stays put
    return geo.offset_point(lat, lon, sector, view_km * 0.22)
