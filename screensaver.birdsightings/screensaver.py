# -*- coding: utf-8 -*-
"""Local Bird Sightings: a living mosaic of recent iNaturalist bird photos."""
import math
import os
import random
import sys
import threading
import time
import traceback

import xbmc
import xbmcaddon
import xbmcgui

ADDON = xbmcaddon.Addon()
ADDON_ID = ADDON.getAddonInfo("id")
ADDON_PATH = ADDON.getAddonInfo("path")
sys.path.insert(0, os.path.join(ADDON_PATH, "resources", "lib"))

import birdsdata  # noqa: E402
import gridlayout  # noqa: E402

WHITE = os.path.join(ADDON_PATH, "resources", "skins", "default", "media", "white.png")

# Font names come from the active skin; font12/13/14 exist in Estuary and most others.
FONT_SMALL, FONT_BODY, FONT_TITLE = "font12", "font13", "font14"

ALIGN_RIGHT = getattr(xbmcgui, "ALIGN_RIGHT", 1)
ALIGN_CENTER_X = getattr(xbmcgui, "ALIGN_CENTER_X", 2)
ALIGN_CENTER_Y = getattr(xbmcgui, "ALIGN_CENTER_Y", 4)
ALIGN_TRUNC = getattr(xbmcgui, "ALIGN_TRUNCATED", 8)

GOLD = "0xFFF2B544"
TEXT = "0xFFFFFFFF"
GREY = "0xFFB8C0C8"
HEADER_BG = "0xFF0B1A1F"


def log(msg, level=xbmc.LOGINFO):
    xbmc.log("[%s] %s" % (ADDON_ID, msg), level)


def _setting(addon, key, default, kind="str"):
    try:
        if kind == "bool":
            return addon.getSettingBool(key)
        if kind == "int":
            return addon.getSettingInt(key)
        if kind == "float":
            return float(str(addon.getSetting(key)).strip().replace(",", "."))
        value = addon.getSetting(key)
        return value if value else default
    except Exception:
        return default


def _clamp(v, lo, hi):
    return max(lo, min(hi, v))


def load_config():
    a = xbmcaddon.Addon()
    return {
        "lat": _setting(a, "latitude", 44.9778, "float"),
        "lng": _setting(a, "longitude", -93.2650, "float"),
        "radius": _clamp(_setting(a, "radius", 20, "int"), 1, 200),
        "place": _setting(a, "location_name", "your area"),
        "days": _clamp(_setting(a, "days", 3, "int"), 1, 30),
        "max_obs": _clamp(_setting(a, "max_obs", 100, "int"), 1, 200),
        "research": _setting(a, "research_only", False, "bool"),
        "no_captive": _setting(a, "no_captive", True, "bool"),
        "open_license": _setting(a, "open_license", False, "bool"),
        "refresh_min": _clamp(_setting(a, "refresh_min", 30, "int"), 5, 180),
        "cols": _clamp(_setting(a, "cols", 7, "int"), 4, 12),
        "flip": _clamp(_setting(a, "flip", 2, "int"), 1, 10),
        "spot_every": _clamp(_setting(a, "spot_every", 30, "int"), 0, 180),
        "spot_secs": _clamp(_setting(a, "spot_secs", 12, "int"), 5, 40),
        "miles": _setting(a, "units", 0, "int") == 1,
    }


class Tile(object):
    def __init__(self, size):
        self.size = size
        self.a = self.b = self.strip = self.label = None
        self.sighting = None
        self.busy = False


class ExitMonitor(xbmc.Monitor):
    def __init__(self, callback):
        xbmc.Monitor.__init__(self)
        self._callback = callback

    def onScreensaverDeactivated(self):
        self._callback()


class Screensaver(xbmcgui.WindowXMLDialog):
    def __init__(self, *args, **kwargs):
        self.exit_requested = False
        self.monitor = None
        self.cfg = {}
        self.W = self.H = 0
        self.sightings = []
        self.species_counts = {}
        self.queue = []
        self.tiles = []
        self.jobs = []
        self.sp = {}
        self.hdr = {}
        self.status = None
        self.built = False
        self.fetching = False
        self.pending = None
        self.spot_active = False
        self.next_spot = 0.0
        self.recent_spot = []

    # ---------------------------------------------------------------- lifecycle
    def onInit(self):
        self.monitor = ExitMonitor(self._request_exit)
        try:
            self._run()
        except Exception:
            log("Screensaver crashed:\n" + traceback.format_exc(), xbmc.LOGERROR)
        finally:
            self.close()

    def onAction(self, action):
        self._request_exit()

    def _request_exit(self):
        self.exit_requested = True

    # ------------------------------------------------------------------ main loop
    def _run(self):
        self.W, self.H = self.getWidth(), self.getHeight()
        self.cfg = load_config()
        self.status = xbmcgui.ControlLabel(
            0, int(self.H / 2) - 50, self.W, 100, "Listening for birds...",
            font=FONT_TITLE, textColor=GOLD, alignment=ALIGN_CENTER_X | ALIGN_CENTER_Y)
        self.addControl(self.status)

        now = time.time()
        next_refresh = now + self.cfg["refresh_min"] * 60
        next_flip = now + 1.0
        next_clock = now + 20
        self.next_spot = now + max(8, self.cfg["spot_every"] // 2)
        self._fetch_async()

        while not self.exit_requested and not self.monitor.abortRequested():
            now = time.time()

            if self.pending is not None:
                result, self.pending, self.fetching = self.pending, None, False
                self._apply(result)
                if not self.sightings:
                    next_refresh = now + 60  # retry sooner while we have nothing

            if now >= next_refresh and not self.fetching:
                self._fetch_async()
                next_refresh = now + self.cfg["refresh_min"] * 60

            if self.built:
                if now >= next_flip and not self.spot_active:
                    free = [t for t in self.tiles if not t.busy]
                    if free:
                        self.jobs.append((now, self._flip_job(random.choice(free))))
                    next_flip = now + self.cfg["flip"] * random.uniform(0.5, 1.2)
                if (self.cfg["spot_every"] > 0 and not self.spot_active
                        and now >= self.next_spot and self.sightings):
                    self.jobs.append((now, self._spotlight_job()))
                if now >= next_clock:
                    self._update_header()
                    next_clock = now + 20

            alive = []
            for ready, gen in self.jobs:
                if now < ready:
                    alive.append((ready, gen))
                    continue
                try:
                    alive.append((now + next(gen), gen))
                except StopIteration:
                    pass
            self.jobs = alive

            if self.monitor.waitForAbort(0.05):
                break

        for _, gen in self.jobs:
            gen.close()

    # ---------------------------------------------------------------------- data
    def _fetch_async(self):
        self.fetching = True
        cfg = self.cfg

        def work():
            try:
                self.pending = birdsdata.fetch_sightings(
                    cfg["lat"], cfg["lng"], cfg["radius"], cfg["days"], cfg["max_obs"],
                    cfg["research"], cfg["no_captive"], cfg["open_license"])
            except Exception as exc:
                log("Fetch failed: %s" % exc, xbmc.LOGWARNING)
                self.pending = {"error": str(exc)}

        t = threading.Thread(target=work)
        t.daemon = True
        t.start()

    def _apply(self, result):
        if "error" in result:
            if not self.built and self.status:
                self.status.setLabel("Couldn't reach iNaturalist - retrying...")
            return
        sightings = result["sightings"]
        if not sightings:
            if not self.built and self.status:
                self.status.setLabel(
                    "No bird photos within %d km of %s in the last %d days.[CR]"
                    "Try a wider radius or more days in the add-on settings." %
                    (self.cfg["radius"], self.cfg["place"], self.cfg["days"]))
            return
        self.sightings = sightings
        self.species_counts = result["species_counts"]
        self.queue = []
        if not self.built:
            self._build_all()
        else:
            self._update_header()

    def _next(self):
        shown = set(t.sighting.id for t in self.tiles if t.sighting)
        allow_dupes = len(self.sightings) <= len(self.tiles)
        for _ in range(len(self.sightings) + 1):
            if not self.queue:
                self.queue = self.sightings[:]
                random.shuffle(self.queue)
            s = self.queue.pop()
            if allow_dupes or s.id not in shown:
                return s
        return random.choice(self.sightings)

    # --------------------------------------------------------------- UI building
    def _build_all(self):
        if self.status:
            self.removeControl(self.status)
            self.status = None
        self.top = int(self.H * 0.065)
        self._build_grid()      # z-order = add order: grid < header < spotlight
        self._build_header()
        self._build_spotlight()
        self.built = True
        self._update_header()
        self.jobs.append((time.time(), self._reveal_job()))

    def _build_grid(self):
        W, H, top = self.W, self.H, self.top
        n = len(self.sightings)
        area_h = float(H - top)
        cols = max(3, min(self.cfg["cols"], int(math.ceil(math.sqrt(n * W / area_h)))))
        rows = max(2, int(round(cols * area_h / W)))
        max_big = max(1, cols // 3) if n >= 12 else 0
        cells = gridlayout.make_layout(cols, rows, max_big)
        cw, ch = W / float(cols), area_h / rows
        gap = 3
        fade = [("Visible", "effect=fade start=0 end=100 time=400")]
        pop = fade + [("Visible", "effect=zoom start=88 end=100 center=auto time=550 tween=back easing=out")]
        controls = []
        for c, r, size in cells:
            x, y = int(c * cw) + gap, top + int(r * ch) + gap
            w, h = int(cw * size) - 2 * gap, int(ch * size) - 2 * gap
            strip_h = int(H * (0.042 if size == 1 else 0.055))
            t = Tile(size)
            t.a = xbmcgui.ControlImage(x, y, w, h, "", aspectRatio=1)
            t.b = xbmcgui.ControlImage(x, y, w, h, "", aspectRatio=1)
            t.strip = xbmcgui.ControlImage(x, y + h - strip_h, w, strip_h, WHITE, colorDiffuse="0xB0000000")
            t.label = xbmcgui.ControlLabel(
                x + 10, y + h - strip_h, w - 20, strip_h, "",
                font=FONT_SMALL if size == 1 else FONT_BODY, textColor=TEXT,
                alignment=ALIGN_CENTER_Y | ALIGN_TRUNC)
            controls += [t.a, t.b, t.strip, t.label]
            self.tiles.append(t)
        self.addControls(controls)
        for t in self.tiles:
            for ctl in (t.a, t.b, t.strip, t.label):
                ctl.setVisible(False)
            t.a.setAnimations(pop)
            t.b.setAnimations(pop)
            t.strip.setAnimations(fade)
            t.label.setAnimations(fade)

    def _build_header(self):
        W, top = self.W, self.top
        bar = xbmcgui.ControlImage(0, 0, W, top, WHITE, colorDiffuse=HEADER_BG)
        title = xbmcgui.ControlLabel(30, 0, int(W * 0.45), top, "", font=FONT_BODY,
                                     textColor=GOLD, alignment=ALIGN_CENTER_Y | ALIGN_TRUNC)
        stats = xbmcgui.ControlLabel(int(W * 0.42), 0, int(W * 0.58) - 30, top, "",
                                     font=FONT_SMALL, textColor=GREY,
                                     alignment=ALIGN_RIGHT | ALIGN_CENTER_Y)
        self.addControls([bar, title, stats])
        self.hdr = {"title": title, "stats": stats}

    def _update_header(self):
        cfg = self.cfg
        rad = ("%d mi" % round(cfg["radius"] * 0.621371)) if cfg["miles"] else ("%d km" % cfg["radius"])
        days = cfg["days"]
        clock = time.strftime("%I:%M %p").lstrip("0")
        self.hdr["title"].setLabel("BIRDS NEAR %s" % cfg["place"].upper())
        self.hdr["stats"].setLabel(
            "%d sightings  \u00b7  %d species  \u00b7  last %s  \u00b7  within %s  \u00b7  %s" % (
                len(self.sightings), len(self.species_counts),
                "day" if days == 1 else "%d days" % days, rad, clock))

    def _build_spotlight(self):
        W, H = self.W, self.H
        px, pw = int(W * 0.67), int(W * 0.28)
        ms = self.cfg["spot_secs"] * 1000
        sp = {
            "dim": xbmcgui.ControlImage(0, 0, W, H, WHITE, colorDiffuse="0xEE000000"),
            "bg": xbmcgui.ControlImage(0, 0, W, H, "", aspectRatio=1, colorDiffuse="0x44FFFFFF"),
            "photo": xbmcgui.ControlImage(int(W * 0.05), int(H * 0.10), int(W * 0.58), int(H * 0.80), "", aspectRatio=2),
            "kicker": xbmcgui.ControlLabel(px, int(H * 0.22), pw, 40, "", font=FONT_BODY, textColor=GOLD,
                                           alignment=ALIGN_TRUNC),
            "name": xbmcgui.ControlTextBox(px, int(H * 0.28), pw, int(H * 0.20), font=FONT_TITLE, textColor=TEXT),
            "sci": xbmcgui.ControlLabel(px, int(H * 0.47), pw, 40, "", font=FONT_BODY, textColor=GREY,
                                        alignment=ALIGN_TRUNC),
            "rule": xbmcgui.ControlImage(px, int(H * 0.54), int(pw * 0.3), 4, WHITE, colorDiffuse=GOLD),
            "details": xbmcgui.ControlTextBox(px, int(H * 0.57), pw, int(H * 0.22), font=FONT_BODY, textColor=TEXT),
            "count": xbmcgui.ControlLabel(px, int(H * 0.80), pw, 40, "", font=FONT_SMALL, textColor=GREY,
                                          alignment=ALIGN_TRUNC),
            "credit": xbmcgui.ControlLabel(int(W * 0.05), int(H * 0.925), int(W * 0.9), 36, "",
                                           font=FONT_SMALL, textColor=GREY, alignment=ALIGN_TRUNC),
        }
        self.sp_order = ["dim", "bg", "photo", "rule", "kicker", "name", "sci", "details", "count", "credit"]
        self.addControls([sp[k] for k in self.sp_order])
        out = ("Hidden", "effect=fade start=100 end=0 time=450")
        for k in self.sp_order:
            sp[k].setVisible(False)
            anims = [out, ("Visible", "effect=fade start=0 end=100 time=600")]
            if k in ("kicker", "name", "sci", "rule", "details", "count"):
                anims.append(("Visible", "effect=slide start=80,0 end=0,0 time=700 delay=250 tween=cubic easing=out"))
            if k == "photo":
                anims.append(("Visible", "effect=zoom start=100 end=106 center=auto time=%d tween=sine easing=inout" % ms))
            if k == "bg":
                anims.append(("Visible", "effect=zoom start=100 end=115 center=auto time=%d tween=sine easing=inout" % ms))
            sp[k].setAnimations(anims)
        self.sp = sp

    # ----------------------------------------------------------------- animation jobs
    def _caption(self, s):
        ago = s.ago(short=True)
        return "%s  \u00b7  %s" % (s.common, ago) if ago else s.common

    def _tile_url(self, tile, s):
        return s.url_large if tile.size > 1 else s.url_medium

    def _reveal_job(self):
        order = self.tiles[:]
        random.shuffle(order)
        for t in order:
            s = self._next()
            t.sighting = s
            t.a.setImage(self._tile_url(t, s))
            t.label.setLabel(self._caption(s))
            for ctl in (t.a, t.strip, t.label):
                ctl.setVisible(True)
            yield 0.07

    def _flip_job(self, tile):
        tile.busy = True
        try:
            s = self._next()
            url = self._tile_url(tile, s)
            tile.b.setImage(url)          # preload while hidden
            yield 1.0
            tile.label.setLabel(self._caption(s))
            tile.b.setVisible(True)       # pop-in over the old photo
            tile.sighting = s
            yield 1.0
            tile.a.setImage(url)          # underlay now matches, then drop the overlay
            yield 0.4
            tile.b.setVisible(False)
        finally:
            tile.busy = False

    def _pick_spotlight(self):
        pool = self.sightings
        if random.random() < 0.5:
            pool = sorted(pool, key=lambda s: s.sort_key, reverse=True)[:15]
        fresh = [s for s in pool if s.id not in self.recent_spot] or pool
        s = random.choice(fresh)
        self.recent_spot.append(s.id)
        del self.recent_spot[:-12]
        return s

    def _spotlight_job(self):
        self.spot_active = True
        try:
            s = self._pick_spotlight()
            sp = self.sp
            ago = s.ago()
            sp["kicker"].setLabel(("SPOTTED %s" % ago.upper()) if ago else "SIGHTING")
            sp["name"].setText(s.common)
            sp["sci"].setLabel(s.sci)
            lines = [x for x in (s.place, s.distance_text(self.cfg["miles"]),
                                 ("Observed by %s" % s.user) if s.user else "") if x]
            if s.quality == "research":
                lines.append("Community-verified ID")
            sp["details"].setText("\n".join(lines))
            n = self.species_counts.get(s.taxon_id, 1)
            days = self.cfg["days"]
            window = "today" if days == 1 else "in the last %d days" % days
            sp["count"].setLabel("Reported %d times %s" % (n, window) if n > 1
                                 else "Reported once %s" % window)
            sp["credit"].setLabel("Photo: %s   \u00b7   via iNaturalist" % s.attribution)
            sp["bg"].setImage(s.url_large)
            sp["photo"].setImage(s.url_large)
            yield 1.3                     # let the big photo load
            for k in self.sp_order:
                sp[k].setVisible(True)
            yield self.cfg["spot_secs"]
            for k in self.sp_order:
                sp[k].setVisible(False)
            yield 0.8
        finally:
            self.spot_active = False
            self.next_spot = time.time() + self.cfg["spot_every"]


def main():
    win = Screensaver("screensaver-birds.xml", ADDON_PATH, "default", "1080i")
    win.doModal()
    del win


if __name__ == "__main__":
    main()
