"""Turns the world into image files for one scene. No Kodi imports.

A Scene is a projection, a rendering style and a size. Preparing it builds (or loads) the
lookup tables; rendering a frame rolls the geographic images to the wanted central
meridian, pushes them through the tables and writes PNGs for Kodi to show."""

import math
import os
import time

from . import ascii, events, landclass, overlays, raster, reproject, sun, world as world_mod

MAP, ASCII_GEO, ASCII_IMAGE = 'map', 'ascii_geo', 'ascii_image'
OVERLAY_ORDER = ('temp', 'clouds', 'precip', 'fires', 'lightning')   # bottom to top over the base map


class Scene(object):
    def __init__(self, proj, style, screen_w, screen_h, zoom=1.0, quality=1.0, tilt=20.0, ascii_opts=None):
        self.proj = proj
        self.style = style
        self.screen_w, self.screen_h = screen_w, screen_h
        self.zoom = zoom
        self.quality = quality
        self.tilt = tilt if proj.kind == 'globe' else 0.0
        self.ascii = ascii_opts or {}
        self.layout = reproject.Layout(proj, screen_w, screen_h, zoom, self.tilt)

    def key(self):
        return (self.proj.id, self.style, self.zoom, self.quality, self.tilt,
                tuple(sorted(self.ascii.items())))


class Geometry(object):
    """Tables and sizes for a prepared scene."""

    def __init__(self, scene):
        self.scene = scene
        lay = scene.layout
        self.disp_w, self.disp_h = lay.disp_w, lay.disp_h
        self.lut = self.olut = self.glut = None
        self.img_w = self.img_h = self.ow = self.oh = 0
        self.cols = self.rows = 0
        self.cell = (0, 0)
        # Size of the rendered image on screen (ASCII drops the part-cell remainder).
        self.show_w, self.show_h = self.disp_w, self.disp_h


class Renderer(object):
    def __init__(self, world, folder, lut_cache, media, log=lambda msg: None):
        self.world = world
        self.folder = folder
        self.cache = lut_cache
        self.media = media
        self.log = log
        self.counter = 0
        self.atlases = {}
        self.palettes = {}
        if not os.path.isdir(folder):
            os.makedirs(folder)
        for name in os.listdir(folder):
            if name.endswith('.png'):
                try:
                    os.remove(os.path.join(folder, name))
                except OSError:
                    pass
        self.recent = []

    # ------------------------------------------------------------ preparation

    def prepare(self, scene, stop=None):
        """-> Geometry, or None if stopped. Slow the first time for each scene size."""
        geo = Geometry(scene)
        lay = scene.layout
        proj = scene.proj
        if scene.style == MAP:
            q = scene.quality
            geo.img_w = max(8, int(round(lay.disp_w * q)))
            geo.img_h = max(8, int(round(lay.disp_h * q)))
            kx = lay.k * geo.img_w / float(lay.disp_w)
            ky = lay.k * geo.img_h / float(lay.disp_h)
            geo.lut = reproject.build(proj, geo.img_w, geo.img_h, kx, ky, world_mod.SW, world_mod.SH,
                                      scene.tilt, self.cache, stop)
            if geo.lut is None:
                return None
            # Weather overlays are smooth fields: half resolution is plenty.
            geo.ow, geo.oh = max(8, geo.img_w // 2), max(8, geo.img_h // 2)
            okx = lay.k * geo.ow / float(lay.disp_w)
            oky = lay.k * geo.oh / float(lay.disp_h)
            geo.olut = reproject.build(proj, geo.ow, geo.oh, okx, oky, world_mod.CW, world_mod.CH,
                                       scene.tilt, self.cache, stop)
            if geo.olut is None:
                return None
        else:
            cw, ch = ascii.CELL_SIZES[scene.ascii.get('density', 1)]
            geo.cell = (cw, ch)
            geo.cols = max(4, int(lay.disp_w // cw))
            geo.rows = max(4, int(lay.disp_h // ch))
            # The grid starts at the map's top-left corner and drops the part-cell remainder.
            geo.show_w, geo.show_h = geo.cols * cw, geo.rows * ch
            # Table at grid resolution: one source sample per character cell.
            geo.glut = reproject.build(proj, geo.cols, geo.rows, lay.k / cw, lay.k / ch, world_mod.CW, world_mod.CH,
                                       scene.tilt, self.cache, stop)
            if geo.glut is None:
                return None
        return geo

    # ------------------------------------------------------------ helpers

    def _out(self, layer, data):
        self.counter += 1
        path = os.path.join(self.folder, '%s_%06d.png' % (layer, self.counter))
        raster.write(path, data)
        self.recent.append(path)
        # Keep the last few frames: Kodi may still be showing or fading them.
        while len(self.recent) > 24:
            old = self.recent.pop(0)
            try:
                os.remove(old)
            except OSError:
                pass
        return path

    def forward(self, geo, lon, lat, rotation):
        """Geographic point -> display pixel inside the map (or None where not shown)."""
        scene = geo.scene
        proj = scene.proj
        local = (lon - rotation + 540.0) % 360.0 - 180.0
        if proj.kind == 'globe':
            p = proj.forward_view(local, lat, 0.0, scene.tilt)
        else:
            p = proj.forward(local, lat)
        if p is None:
            return None
        return scene.layout.plane_to_display(*p)

    # ------------------------------------------------------------ map frames

    def render_map(self, geo, rotation, layers):
        """-> {'base': path, 'temp': path, ...}. rotation: central meridian in degrees."""
        w = self.world
        if w.composite is None:
            w.update_composite(time.time())
        out = {}
        shift = int(round(rotation / 360.0 * world_mod.SW)) % world_mod.SW
        base = raster.roll_words(w.composite, world_mod.SW, world_mod.SH, shift)
        words = reproject.apply(geo.lut, base)
        out['base'] = self._out('base', raster.encode_words(geo.img_w, geo.img_h, words))
        oshift = int(round(rotation / 360.0 * world_mod.CW)) % world_mod.CW
        for name in OVERLAY_ORDER:
            if name not in layers or name not in w.overlays:
                continue
            src = raster.roll_words(w.overlays[name], world_mod.CW, world_mod.CH, oshift)
            out[name] = self._out(name, raster.encode_words(geo.ow, geo.oh, reproject.apply(geo.olut, src)))
        quakes = w.quakes if 'quakes' in layers else []
        volcanoes = w.volcanoes if 'volcanoes' in layers else []
        if quakes or volcanoes:
            # Symbols at their projected positions, in two phases Kodi alternates.
            k = geo.img_w / float(geo.disp_w)
            a, b = events.Canvas(geo.img_w, geo.img_h), events.Canvas(geo.img_w, geo.img_h)

            def to_xy(lon, lat):
                p = self.forward(geo, lon, lat, rotation)
                return None if p is None else (p[0] * k, p[1] * k)
            events.draw_symbols(a, b, k, quakes, volcanoes, to_xy, time.time())
            out['events'] = self._out('events', a.png())
            out['events2'] = self._out('events2', b.png())
        return out

    # ------------------------------------------------------------ ASCII frames

    def palette(self, opts):
        name = opts.get('mono_palette', 'green') if opts.get('mono') else opts.get('palette', 'natural')
        if name not in self.palettes:
            self.palettes[name] = ascii.Palette(name)
        return self.palettes[name]

    def atlas(self, cell):
        if cell not in self.atlases:
            path = os.path.join(self.media, 'glyphs', 'glyphs_%dx%d.png' % cell)
            self.atlases[cell] = ascii.Atlas(path, cell[0], cell[1])
        return self.atlases[cell]

    def render_ascii(self, geo, rotation, layers, t, daynight=True, lights=True, lights_night_only=True):
        scene = geo.scene
        opts = scene.ascii
        w = self.world
        pal = self.palette(opts)
        atlas = self.atlas(geo.cell)
        uni = opts.get('unicode', True)
        image_mode = scene.style == ASCII_IMAGE
        ramp = ascii.RAMPS[opts.get('ramp', 0)]
        show_borders = opts.get('borders', True)
        show_urban = opts.get('urban', True)
        mono = opts.get('mono', False)
        CW, CH = world_mod.CW, world_mod.CH
        sentinel = CW * CH
        shift = int(round(rotation / 360.0 * CW)) % CW
        s = sun.Sun(t)
        # Per-row and per-column parts of the solar altitude, so each cell is two lookups.
        sin_lat = [math.sin(math.radians(90.0 - (v + 0.5) * 180.0 / CH)) for v in range(CH)]
        cos_lat = [math.cos(math.radians(90.0 - (v + 0.5) * 180.0 / CH)) for v in range(CH)]
        cos_dlon = [math.cos(math.radians(-180.0 + (u + 0.5) * 360.0 / CW - s.lon)) for u in range(CW)]
        clouds = w.overlay_rgba.get('clouds') if 'clouds' in layers else None
        precip = w.overlay_rgba.get('precip') if 'precip' in layers else None
        weather = w.weather
        temp_on = 'temp' in layers and weather is not None and not mono
        wind_on = 'wind' in layers and weather is not None
        black = pal.black
        idx = ascii.INDEX
        fire_mask = w.masks.get('fires') if 'fires' in layers else None
        bolt_mask = w.masks.get('lightning') if 'lightning' in layers else None
        flash_a, flash_b = {}, {}   # cell -> (glyph, colour) for the two alternating phases
        classes, lights_small, lines_small = w.classes, w.lights_small, w.lines_small
        cells = []
        cols = geo.cols
        empty = (0, 0, 0)
        for n, gidx in enumerate(geo.glut):
            if gidx == sentinel:
                cells.append(empty)
                continue
            v, u = divmod(gidx, CW)
            u = (u + shift) % CW
            gi = v * CW + u
            daylight = 1.0
            if daynight:
                daylight = sun.daylight(sin_lat[v] * s.sin_dec + cos_lat[v] * s.cos_dec * cos_dlon[u])
            lat = None
            if image_mode:
                rgb = w.sample_color((v * 2) * world_mod.SW + u * 2, daylight)
                if clouds is not None:
                    a = clouds[gi * 4 + 3] / 255.0
                    if a > 0.05:
                        rgb = ascii.mix(rgb, (235, 240, 245), a * (0.35 + 0.65 * daylight))
                glyph, color = ascii.image_cell(rgb, ramp)
                color = ascii.scale(color, 1.25)
            else:
                cls = classes[gi]
                if cls == landclass.URBAN and not show_urban:
                    cls = landclass.PLAINS
                glyph, color = ascii.geographic_cell(cls, gi, uni)
                lit = lights and (lights_small[gi] > 70) and (daylight < 0.5 or not lights_night_only)
                if daynight:
                    color = ascii.scale(color, 0.28 + 0.72 * daylight)
                if lit:
                    glyph = '*' if lights_small[gi] > 170 else '·' if uni else '.'
                    k = 0.6 + 0.4 * lights_small[gi] / 255.0
                    color = ascii.scale((255, 205, 110), k)
                if show_borders and lines_small[gi] & 1 and cls not in landclass.WATER:
                    glyph = '·' if uni else '.'
                    color = ascii.scale((230, 90, 90), 0.4 + 0.6 * daylight)
                if clouds is not None:
                    a = clouds[gi * 4 + 3]
                    if a > 120:
                        glyph = ('▒' if a > 190 else '░') if uni else (':' if a > 190 else '.')
                        color = ascii.scale((230, 235, 240), 0.35 + 0.65 * daylight)
            bg = black
            if precip is not None:
                p = gi * 4
                level = overlays.rain_intensity(precip[p], precip[p + 1], precip[p + 2], precip[p + 3])
                if level:
                    if lat is None:
                        lat = 90.0 - (v + 0.5) * 180.0 / CH
                    cold = weather is not None and weather.temp.sample(-180.0 + (u + 0.5) * 360.0 / CW, lat) < 0
                    if cold:
                        glyph, color = '*', (240, 245, 255)
                    else:
                        glyph = ',;/'[level - 1]
                        color = ((90, 170, 255), (60, 200, 255), (150, 120, 255))[level - 1]
            if temp_on:
                if lat is None:
                    lat = 90.0 - (v + 0.5) * 180.0 / CH
                tc = overlays.temperature_color(weather.temp.sample(-180.0 + (u + 0.5) * 360.0 / CW, lat))
                bg = pal.index(ascii.scale(tc, 0.2))
            if wind_on and (n % cols) % 6 == 3 and (n // cols) % 4 == 2:
                if lat is None:
                    lat = 90.0 - (v + 0.5) * 180.0 / CH
                lon = -180.0 + (u + 0.5) * 360.0 / CW
                uu, vv = weather.wind(lon, lat)
                speed = math.hypot(uu, vv)
                if speed > 3.0:
                    direction = math.degrees(math.atan2(-uu, -vv)) % 360.0  # wind FROM
                    glyph = ascii.arrow(direction, uni)
                    color = (220, 240, 255) if speed < 10 else ((255, 230, 120) if speed < 18 else (255, 120, 90))
            if fire_mask is not None and fire_mask[gi]:
                flash_a[n] = ('\u263c' if uni else '*', (255, 120, 30))
                flash_b[n] = ('*', (255, 210, 60))
            if bolt_mask is not None and bolt_mask[gi]:
                flash_a[n] = ('\u203c' if uni else '!', (255, 255, 190))
                flash_b[n] = ('!', (200, 200, 255))
            cells.append((idx.get(glyph, 0), pal.index(color), bg))
        self._ascii_points(geo, cells, flash_a, flash_b, rotation, pal, uni, layers)
        out = {'base': self._out('ascii', atlas.encode(cells, geo.cols, geo.rows, pal))}
        if flash_a or flash_b:
            for name, flash in (('events', flash_a), ('events2', flash_b)):
                layer = [(0, 0, 0)] * (geo.cols * geo.rows)
                for n, (glyph, color) in flash.items():
                    layer[n] = (idx.get(glyph, 0), pal.index(color), black)
                out[name] = self._out(name, atlas.encode(layer, geo.cols, geo.rows, pal))
        return out

    def _ascii_points(self, geo, cells, flash_a, flash_b, rotation, pal, uni, layers):
        """Storms, volcanoes and earthquakes as characters. Names go in the still frame;
        the symbols themselves go in the two flashing phases."""
        cw, ch = geo.cell
        now = time.time()

        def cell(lon, lat):
            p = self.forward(geo, lon, lat, rotation)
            if p is None:
                return None
            col, row = int(p[0] // cw), int(p[1] // ch)
            if 0 <= col < geo.cols and 0 <= row < geo.rows:
                return row, col
            return None

        labels = []

        def label(row, col, text, color):
            for i, c in enumerate(' ' + text):
                if col + 1 + i >= geo.cols:
                    break
                n = row * geo.cols + col + 1 + i
                cells[n] = (ascii.INDEX.get(c, 0), pal.index(color), pal.black)
                labels.append(n)

        w = self.world
        if 'quakes' in layers:
            for q in w.quakes:
                rc = cell(q['lon'], q['lat'])
                if rc is None:
                    continue
                n = rc[0] * geo.cols + rc[1]
                color = events.quake_color(now - q['time'])
                flash_a[n] = ('\u25ce' if uni else 'O', color)
                flash_b[n] = ('\u25cb' if uni else 'o', ascii.scale(color, 0.6))
                if q['mag'] >= 5.5:
                    label(rc[0], rc[1], 'M%.1f' % q['mag'], color)
        if 'volcanoes' in layers:
            for v in w.volcanoes:
                rc = cell(v['lon'], v['lat'])
                if rc is None:
                    continue
                n = rc[0] * geo.cols + rc[1]
                flash_a[n] = ('\u25b2' if uni else 'A', (240, 60, 30))
                flash_b[n] = ('\u25b2' if uni else 'A', (255, 210, 70))
                if rc[0] > 0:   # smoke above the crater, on and off
                    flash_b[n - geo.cols] = ('\u00b0' if uni else "'", (200, 200, 200))
        if 'storms' in layers:
            for storm in w.storms:
                rc = cell(storm['lon'], storm['lat'])
                if rc is None:
                    continue
                strong = (storm.get('wind_kmh') or 0) >= 119
                color = (255, 80, 200) if strong else (255, 170, 80)
                n = rc[0] * geo.cols + rc[1]
                flash_a[n] = ('@', color)
                flash_b[n] = ('\u00a7' if uni else '&', ascii.scale(color, 0.7))
                cells[n] = (ascii.INDEX['@'], pal.index(color), pal.black)
                label(rc[0], rc[1], storm.get('name', '').upper()[:12], color)
        for n in labels:   # names stay readable: nothing flashes over them
            flash_a.pop(n, None)
            flash_b.pop(n, None)
