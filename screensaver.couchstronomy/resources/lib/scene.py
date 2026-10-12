"""From settings and a moment in time to everything on screen. No Kodi imports.

View   - what the settings say: observer, camera, rendering choices (fixed per session).
Model  - the catalogues plus View; build(unix) returns a Scene.
Scene  - screen-space stars, bodies, deep-sky objects, lines, label candidates and the
         numbers the sky-colour layer needs (Sun and Moon altitude, limiting magnitude).

Every object goes through the same chain: catalogue position -> apparent topocentric
direction (astro, bodies) -> refraction -> horizon test -> extinction -> camera.
"""

import math
import os
import time

from . import astro, bodies, camera, catalog, config

DEG = astro.DEG
SKY_DARK_LIMIT = 6.5          # naked-eye limit under a dark, moonless sky
EXTINCTION_K = 0.2            # magnitudes per airmass (clear, sea-level-ish)
LINE_GAP = 10.0               # constellation lines stop short of their stars (px)
PHOTO_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'media', 'messier')
MAX_PHOTOS = 16


def photo_keys():
    """Messier numbers with a bundled photo ('M42', ...)."""
    try:
        return frozenset(n[:-4] for n in os.listdir(PHOTO_DIR) if n.endswith('.png'))
    except OSError:
        return frozenset()


class View(object):
    """Settings resolved into an observer and a camera."""

    def __init__(self, s, width=1920, height=1080):
        self.s = s
        self.width, self.height = width, height
        self.lat = max(-90.0, min(90.0, s['lat'])) * DEG
        self.lon = ((s['lon'] + 180.0) % 360.0 - 180.0) * DEG
        self.elevation = max(-500.0, min(9000.0, s['elevation']))
        az = s['azimuth'] + (s['declination'] if s['heading_type'] == 1 else 0.0)
        if s['fov_mode'] == 1:
            hfov = camera.fov_from_screen(s['screen_cm'], max(1.0, s['distance_cm']))
        else:
            hfov = float(s['hfov'])
        proj = s['projection']
        if proj == 0:
            projection = camera.PERSPECTIVE if hfov <= 120.0 else camera.STEREOGRAPHIC
        else:
            projection = (camera.PERSPECTIVE, camera.STEREOGRAPHIC, camera.EQUIDISTANT)[proj - 1]
        self.camera = camera.Camera(az, s['tilt'], hfov, width, height, s['rotation'], s['roll'], projection)
        self.realistic = s['look'] == 0
        self.photos = s['show_dsos'] and s['messier_photos']
        self.enhance = 0 if self.realistic else 1 + s['enhance']     # 0 none, 1 mild, 2 strong
        self.mag_limit = config.MAG_LIMITS[s['mag_limit']]
        self.clip_horizon = s['horizon'] != 2
        self.refraction = s['refraction']
        self.extinction = s['extinction']
        self.keep_dark = s['daytime'] == 1
        self.light_pollution = s['light_pollution'] / 100.0
        self.labels = s['labels']
        self.time_offset = s['time_offset'] * 3600.0
        self.time_speed = config.TIME_SPEEDS[s['time_speed']]
        self.t0 = time.time()

    def sky_time(self, now=None):
        """The simulated instant: real time, plus the offset, sped up from start if asked."""
        now = time.time() if now is None else now
        if self.time_speed == 1:
            return now + self.time_offset
        return self.t0 + (now - self.t0) * self.time_speed + self.time_offset


class Point(object):
    __slots__ = ('x', 'y', 'mag', 'rgb', 'fade', 'kind', 'key')

    def __init__(self, x, y, mag, rgb, fade, kind, key):
        self.x, self.y, self.mag, self.rgb, self.fade, self.kind, self.key = x, y, mag, rgb, fade, kind, key


class Disk(object):
    """A resolved body: centre, radius in pixels and the lighting in its local frame."""
    __slots__ = ('body', 'x', 'y', 'r', 'sun', 'north', 'mag', 'fade', 'true_r', 'ring')

    def __init__(self, **kw):
        self.ring = None
        for k, v in kw.items():
            setattr(self, k, v)


class Label(object):
    __slots__ = ('text', 'x', 'y', 'gap', 'priority', 'style', 'key', 'placed')

    def __init__(self, text, x, y, gap, priority, style, key=None):
        self.text, self.x, self.y, self.gap = text, x, y, gap
        self.priority, self.style, self.key = priority, style, key
        self.placed = None


class Scene(object):
    def __init__(self, unix, frame):
        self.unix = unix
        self.frame = frame
        self.points = []
        self.disks = []
        self.dsos = []       # (x, y, rx_px, ry_px, intensity, DeepSky)
        self.photos = []     # (key, x, y, size_px, degrees clockwise from up to north, alpha)
        self.photo_keys = set()
        self.lines = []      # (x0, y0, x1, y1)
        self.borders = []
        self.labels = []
        self.spotlight = []  # (key, x, y, title, [detail lines])
        self.bodies = {}
        self.sun_alt = self.moon_alt = -90.0
        self.sun_hor = self.moon_hor = None
        self.moon_illum = 0.0
        self.limit = SKY_DARK_LIMIT
        self.diffuse_visibility = 1.0
        self.stars_considered = 0


def twilight_limit(sun_alt_deg):
    """Naked-eye limiting magnitude allowed by the Sun alone (rough, eye-adapted)."""
    pts = ((-18.0, SKY_DARK_LIMIT), (-15.0, 5.6), (-12.0, 4.6), (-9.0, 3.2), (-6.0, 1.8),
           (-3.0, 0.6), (0.0, -1.0), (5.0, -3.4))
    if sun_alt_deg <= pts[0][0]:
        return pts[0][1]
    for (a0, m0), (a1, m1) in zip(pts, pts[1:]):
        if sun_alt_deg <= a1:
            return m0 + (m1 - m0) * (sun_alt_deg - a0) / (a1 - a0)
    return pts[-1][1]


def airmass_mag(u):
    """Extinction (mag) for an apparent ENU z component u = sin(alt)."""
    h = math.degrees(math.asin(max(-1.0, min(1.0, u))))
    return EXTINCTION_K * (astro.airmass(h * DEG) - 1.0)


class Model(object):
    def __init__(self, view):
        self.view = view
        self.stars = catalog.Stars(catalog.year_of(view.sky_time()))
        self.sky = catalog.Sky()
        self.photo_keys = photo_keys() if view.photos else frozenset()
        self._colors = {}
        self._earth = None    # (jd_tt, state): the Earth's state, reused for a minute

    # ------------------------------------------------------------ helpers

    def frame(self, unix):
        v = self.view
        jd = astro.jd_tt(unix)
        if self._earth is None or abs(self._earth[0] - jd) > 60.0 / 86400.0:
            from . import vsop87
            self._earth = (jd, vsop87.earth_state(jd))
        jd0, (pos, vel) = self._earth
        dt = jd - jd0
        state = (astro.add(pos, astro.scale(vel, dt)), vel)
        return astro.Frame(unix, v.lat, v.lon, v.elevation, earth_state=state)

    def star_color(self, bv):
        key = int(round(bv * 20))
        rgb = self._colors.get(key)
        if rgb is None:
            raw = catalog.bv_to_rgb(key / 20.0)
            mode = self.view.s['star_colours']
            if mode == 2:
                rgb = (255, 255, 255)
            else:
                keep = 0.45 if mode == 0 else 1.0
                rgb = tuple(int(255 - (255 - c) * keep) for c in raw)
                m = max(rgb)
                rgb = tuple(int(c * 255 / m) for c in rgb)
            self._colors[key] = rgb
        return rgb

    def apparent(self, hor):
        """Refraction (when on). Returns the apparent ENU vector."""
        if self.view.refraction and hor[2] > -0.035:
            return astro.refract_enu(hor)
        return hor

    def visible(self, hor):
        return hor[2] >= 0.0 or not self.view.clip_horizon

    # ------------------------------------------------------------ the scene

    def build(self, unix):
        v = self.view
        cam = v.camera
        fr = self.frame(unix)
        sc = Scene(unix, fr)
        bods = bodies.compute(fr)
        sc.bodies = bods
        sun = bods['Sun']
        sc.sun_hor = self.apparent(sun.hor)
        sc.sun_alt = math.degrees(math.asin(sc.sun_hor[2]))
        m = bods['Moon']
        sc.moon_hor = self.apparent(m.hor)
        sc.moon_alt = math.degrees(math.asin(sc.moon_hor[2]))
        sc.moon_illum = m.illum

        # How faint the eye can see right now.
        sky_limit = SKY_DARK_LIMIT - 2.5 * v.light_pollution
        if not v.keep_dark:
            sky_limit = min(sky_limit, twilight_limit(sc.sun_alt))
            if sc.moon_alt > 0:
                sky_limit -= 1.2 * m.illum ** 1.5 * min(1.0, sc.moon_alt / 20.0 + 0.3)
        if v.realistic:
            limit = min(v.mag_limit, sky_limit)
        else:
            limit = v.mag_limit if v.keep_dark or sc.sun_alt < -12 else min(v.mag_limit, sky_limit + 1.5)
        sc.limit = limit
        dark = 1.0 if v.keep_dark else max(0.0, min(1.0, (-sc.sun_alt - 10.0) / 8.0))
        moon_wash = 0.0 if v.keep_dark or sc.moon_alt <= 0 else 0.75 * m.illum ** 1.5
        sc.diffuse_visibility = dark * (1.0 - moon_wash) * (1.0 - 0.8 * v.light_pollution if v.realistic else 1.0)

        self._stars(sc, fr, cam, limit)
        if v.s['show_planets'] or v.s['show_sun_moon']:
            self._bodies(sc, fr, cam, limit)
        if v.s['show_dsos']:
            self._dsos(sc, fr, cam, limit)
            self._thin_photos(sc)
        if v.s['show_lines'] or (v.labels == config.EXPLORER and v.s['constellation_names']) or \
                (v.labels == config.NAMED and v.s['constellation_names']):
            self._constellations(sc, fr, cam)
        if v.s['show_borders']:
            self._borders(sc, fr, cam)
        if v.labels == config.EXPLORER:
            self._compass(sc, cam)
        return sc

    def _stars(self, sc, fr, cam, limit):
        v = self.view
        stars = self.stars
        hor_to_j2000 = astro.transpose(fr.j2000_to_hor)
        axis = astro.mxv(hor_to_j2000, cam.forward)
        idx = stars.in_cone(axis, cam.cos_radius, limit + 0.01)
        sc.stars_considered = len(idx)
        X, Y, Z, MAG, BV = stars.x, stars.y, stars.z, stars.mag, stars.bv
        (m00, m01, m02), (m10, m11, m12), (m20, m21, m22) = fr.j2000_to_hor
        bx, by, bz = fr.beta
        (r0, r1, r2), (u0, u1, u2), (f0, f1, f2) = cam.matrix
        refr, clip, ext = v.refraction, v.clip_horizon, v.extinction
        perspective = cam.projection == camera.PERSPECTIVE
        fpx, cx, cy, w, h = cam.f, cam.cx, cam.cy, cam.width, cam.height
        names = stars.names
        explorer = v.labels == config.EXPLORER
        named = v.labels == config.NAMED
        sqrt, asin, sin, cos, tan = math.sqrt, math.asin, math.sin, math.cos, math.tan
        points = sc.points
        fade_band = 0.6
        for i in idx:
            x, y, z = X[i] + bx, Y[i] + by, Z[i] + bz
            e = m00 * x + m01 * y + m02 * z
            n = m10 * x + m11 * y + m12 * z
            u = m20 * x + m21 * y + m22 * z
            k = 1.0 / sqrt(e * e + n * n + u * u)
            e *= k
            n *= k
            u *= k
            if refr and u > -0.035:
                hd = asin(u) * 57.29577951308232
                rd = 1.02 / tan((hd + 10.3 / (hd + 5.11)) * DEG) / 60.0
                if rd > 0:
                    hz = sqrt(e * e + n * n)
                    if hz > 1e-12:
                        h2 = (hd + rd) * DEG
                        q = cos(h2) / hz
                        e *= q
                        n *= q
                        u = sin(h2)
            if clip and u < 0.0:
                continue
            mag = MAG[i]
            if ext and u > 0.0:
                mag += airmass_mag(u) if u < 0.5 else EXTINCTION_K * (1.0 / u - 1.0)
            if mag > limit:
                continue
            xc = r0 * e + r1 * n + r2 * u
            yc = u0 * e + u1 * n + u2 * u
            zc = f0 * e + f1 * n + f2 * u
            if perspective:
                if zc <= 1e-9:
                    continue
                q = fpx / zc
                sx, sy = cx + xc * q, cy - yc * q
            else:
                p = cam.project_camera(xc, yc, zc)
                if p is None:
                    continue
                sx, sy = p
            if sx < -20 or sy < -20 or sx >= w + 20 or sy >= h + 20:
                continue
            fade = min(1.0, (limit - mag) / fade_band + 0.15)
            points.append(Point(sx, sy, mag, self.star_color(BV[i]), fade, 'star', i))
            info = names.get(i) if (explorer or named) else None
            if info is not None and 0 <= sx < w and 0 <= sy < h:
                text = None
                if info.proper and MAG[i] <= (3.5 if explorer else 2.0):
                    text = info.proper
                elif explorer and info.desig and MAG[i] <= 3.0:
                    text = info.desig
                if text:
                    sc.labels.append(Label(text, sx, sy, 6 + max(0.0, 2.5 - mag) * 2, 50 - mag * 5, 'star', i))
                if explorer and MAG[i] <= 2.6 and info.proper:
                    sc.spotlight.append(('star', i, sx, sy, info.proper, self._star_details(i, info, e, n, u)))

    def _star_details(self, i, info, e, n, u):
        lines = []
        con = self.sky.by_id.get(info.con)
        kind = 'Star'
        if info.spect:
            kind = 'Star, spectral type %s' % info.spect.split()[0]
        lines.append(kind)
        if info.desig or con:
            lines.append('%s%s' % (info.desig + ' · ' if info.desig else '', 'in ' + con.name if con else ''))
        mag = self.stars.mag[i]
        dist = ('%s light years away' % _num(info.dist_ly)) if info.dist_ly else ''
        lines.append('Magnitude %.1f%s' % (mag, ('  ·  ' + dist) if dist else ''))
        if info.var:
            lines.append('Variable star %s' % info.var)
        lines.append(_altaz((e, n, u)))
        return lines

    def _bodies(self, sc, fr, cam, limit):
        v = self.view
        explorer = v.labels == config.EXPLORER
        labelled = v.labels != config.NATURAL
        enhance = v.enhance
        order = []
        if v.s['show_sun_moon']:
            order += ['Sun', 'Moon']
        if v.s['show_planets']:
            order += [p[0] for p in bodies.PLANETS]
        sun_dir = sc.sun_hor
        for name in order:
            b = sc.bodies[name]
            hor = self.apparent(b.hor)
            alt_deg = math.degrees(math.asin(hor[2]))
            if v.clip_horizon and hor[2] < -b.radius:
                continue
            c = cam.to_camera(hor)
            p = cam.project_camera(*c)
            r_true = b.radius * cam.f
            if p is None or not cam.on_screen(p, margin=max(40.0, r_true * 1.2)):
                continue
            mag = b.mag + (airmass_mag(hor[2]) if v.extinction and b.kind != 'sun' and hor[2] > 0 else 0.0)
            if b.kind == 'planet' and mag > limit and v.realistic:
                continue
            fade = 1.0 if b.kind != 'planet' else min(1.0, (limit - mag) / 0.6 + 0.15)
            if b.kind == 'planet' and not v.realistic:
                fade = max(fade, 0.45)   # Enhanced: every planet stays findable, however faint
            r = r_true
            if enhance and b.kind == 'moon':
                r *= (1.6, 2.5)[enhance - 1]
            elif enhance and b.kind == 'planet':
                r = max(r, (2.2, 3.6)[enhance - 1])
            key = name
            if r >= 1.3 or b.kind in ('moon', 'sun'):
                sun_l, north = self._local_lighting(cam, c, b, sun_dir)
                d = Disk(body=b, x=p[0], y=p[1], r=r, sun=sun_l, north=north, mag=mag, fade=fade, true_r=r_true)
                if name == 'Saturn' and b.ring_tilt is not None:
                    d.ring = (b.ring_tilt, self._screen_angle(cam, c, b.pole_hor))
                sc.disks.append(d)
            else:
                sc.points.append(Point(p[0], p[1], mag, b.color, max(0.0, fade), 'planet', key))
            if labelled and name != 'Sun' or (labelled and name == 'Sun' and sc.sun_alt > -1):
                text = name
                if explorer and b.kind == 'planet':
                    text = '%s  %+.1f' % (name, b.mag)
                elif explorer and b.kind == 'moon':
                    text = 'Moon  %d%%' % round(b.illum * 100)
                sc.labels.append(Label(text, p[0], p[1], r + 8, 100 if b.kind != 'planet' else 90, b.kind, name))
            if explorer:
                sc.spotlight.append((b.kind, name, p[0], p[1], name, self._body_details(b, hor, alt_deg)))

    def _local_lighting(self, cam, c, b, sun_dir):
        """Sun direction in the body's screen-aligned local frame (x right, y up, z towards
        the viewer), and the screen angle of the body's north pole."""
        bz = astro.norm(c)
        zl = (-bz[0], -bz[1], -bz[2])
        xr = (1.0, 0.0, 0.0)
        d = astro.dot(xr, zl)
        xl = astro.norm((xr[0] - d * zl[0], xr[1] - d * zl[1], xr[2] - d * zl[2]))
        yl = astro.cross(zl, xl)
        if b.kind == 'sun':
            s = (0.0, 0.0, 1.0)
        else:
            sc_ = cam.to_camera(b.sun_dir)
            s = (astro.dot(sc_, xl), astro.dot(sc_, yl), astro.dot(sc_, zl))
        north = 0.0
        if b.pole_hor is not None:
            pc = cam.to_camera(b.pole_hor)
            north = math.atan2(astro.dot(pc, xl), astro.dot(pc, yl))
        return s, north

    def _screen_angle(self, cam, c, pole_hor):
        bz = astro.norm(c)
        zl = (-bz[0], -bz[1], -bz[2])
        d = zl[0]
        xl = astro.norm((1.0 - d * zl[0], -d * zl[1], -d * zl[2]))
        yl = astro.cross(zl, xl)
        pc = cam.to_camera(pole_hor)
        return math.atan2(astro.dot(pc, xl), astro.dot(pc, yl))

    def _body_details(self, b, hor, alt_deg):
        lines = []
        if b.kind == 'moon':
            lines.append('Moon, %d%% lit (%s)' % (round(b.illum * 100), moon_phase_name(b)))
            lines.append('%s km away' % _num(round(b.dist_km)))
        elif b.kind == 'sun':
            lines.append('The Sun')
            lines.append('%.4f AU away' % b.distance_au)
        else:
            lines.append('Planet, %d%% lit' % round(b.illum * 100) if b.name in ('Mercury', 'Venus', 'Mars')
                         else 'Planet')
            minutes = b.distance_au * 499.004784 / 60.0
            lines.append('%.2f AU away (light takes %s)' % (b.distance_au, _minutes(minutes)))
            lines.append('Magnitude %+.1f  ·  %.1f" across' % (b.mag, 2 * b.radius / astro.ARCSEC))
        lines.append(_altaz(hor))
        return lines

    def _dsos(self, sc, fr, cam, limit):
        v = self.view
        explorer = v.labels == config.EXPLORER
        for d in self.sky.dsos:
            hor = self.apparent(fr.star_to_hor(d.vec))
            if not self.visible(hor):
                continue
            c = cam.to_camera(hor)
            p = cam.project_camera(*c)
            if p is None or not cam.on_screen(p, margin=60):
                continue
            mag = d.mag if d.mag is not None else 12.0
            rx = max(1.0, d.major / 60.0 * DEG * cam.f / 2.0)
            ry = max(1.0, d.minor / 60.0 * DEG * cam.f / 2.0)
            if v.extinction and hor[2] > 0:
                mag += airmass_mag(hor[2])
            # Spread the object's light over its area: a big faint galaxy is a whisper.
            area = max(1.0, d.major * d.minor)          # arcmin^2
            surface = mag + 2.5 * math.log10(area)      # mag per arcmin^2, roughly
            intensity = 10 ** (-0.4 * (surface - 10.5))
            if v.realistic:
                intensity *= sc.diffuse_visibility
            else:
                intensity = intensity ** 0.7 * 1.6
            if d.is_cluster():
                intensity *= 0.35      # their stars are drawn individually
            sc.dsos.append((p[0], p[1], rx, ry, min(0.6, intensity), d))
            daylit = v.realistic and not v.keep_dark and sc.sun_alt > -6
            photo_r = 0.0
            if d.name in self.photo_keys and (v.keep_dark or sc.sun_alt <= -6):
                photo_r = self._photo(sc, fr, cam, d, p, mag)
            if explorer and not daylit and mag <= 9.5 and 0 <= p[0] < cam.width and 0 <= p[1] < cam.height:
                label = d.name if not d.alt else '%s  %s' % (d.name, d.alt)
                sc.labels.append(Label(label, p[0], p[1], max(max(rx, ry) * 0.6, photo_r * 0.55) + 6, 20 - mag,
                                       'dso', d.name))
                details = [d.type_name().capitalize()]
                if d.desig:
                    details.append(d.desig)
                if d.mag is not None:
                    details.append('Magnitude %.1f  ·  %s\' across' % (d.mag, _num(d.major)))
                details.append(_altaz(hor))
                if d.name.startswith('M') and mag <= 7.5:
                    sc.spotlight.append(('dso', d.name, p[0], p[1], d.alt or d.name, details))

    def _thin_photos(self, sc):
        """Brightest first; drop a photo whose centre sits inside a bigger one (M43 in M42,
        M32 and M110 in M31), and keep at most MAX_PHOTOS."""
        kept = []
        for ph in sorted(sc.photos, key=lambda ph: ph[6]):
            if len(kept) >= MAX_PHOTOS:
                break
            if any(k[3] > ph[3] and math.hypot(k[1] - ph[1], k[2] - ph[2]) < k[3] * 0.45 for k in kept):
                continue
            kept.append(ph)
        sc.photos = [ph[:6] for ph in kept]
        sc.photo_keys = set(ph[0] for ph in kept)

    def _photo(self, sc, fr, cam, d, p, mag):
        """A Messier photo at the object, as big as the object (but never tiny), north
        turned to where north is on screen."""
        v = d.vec
        k = v[2]
        t = astro.norm((-k * v[0], -k * v[1], 1.0 - k * v[2]))       # towards the celestial pole
        q = cam.project_camera(*cam.to_camera(self.apparent(fr.star_to_hor(astro.norm(
            (v[0] + 0.01 * t[0], v[1] + 0.01 * t[1], v[2] + 0.01 * t[2]))))))
        angle = math.degrees(math.atan2(q[0] - p[0], p[1] - q[1])) if q else 0.0
        size = d.major / 60.0 * DEG * cam.f * 1.4
        size = max(0.036 * cam.width, min(0.4 * cam.height, size))
        alpha = 0.9 * (sc.diffuse_visibility if self.view.realistic else 1.0)
        if alpha <= 0.05:
            return 0.0
        sc.photos.append((d.name, p[0], p[1], size, angle, alpha, mag))
        sc.photo_keys.add(d.name)
        return size / 2.0

    def _segment(self, cam, a, b):
        """Two apparent ENU unit vectors -> list of screen segments (clipped to the horizon
        and to the front of the camera)."""
        v = self.view
        if v.clip_horizon:
            if a[2] < 0 and b[2] < 0:
                return []
            if a[2] < 0 or b[2] < 0:
                t = a[2] / (a[2] - b[2])
                m = astro.norm(tuple(a[k] + (b[k] - a[k]) * t for k in range(3)))
                m = (m[0], m[1], 0.0)
                a, b = (m, b) if a[2] < 0 else (a, m)
        ca, cb = cam.to_camera(a), cam.to_camera(b)
        near = 1e-3
        if ca[2] < near and cb[2] < near:
            return []
        if cam.projection == camera.PERSPECTIVE:
            if ca[2] < near or cb[2] < near:
                t = (near - ca[2]) / (cb[2] - ca[2])
                m = tuple(ca[k] + (cb[k] - ca[k]) * t for k in range(3))
                ca, cb = (m, cb) if ca[2] < near else (ca, m)
            pa, pb = cam.project_camera(*ca), cam.project_camera(*cb)
            if pa is None or pb is None:
                return []
            return [(pa[0], pa[1], pb[0], pb[1])]
        # Curved projections: subdivide so each piece is under two degrees.
        n = max(1, int(astro.angle(ca, cb) / (2 * DEG)) + 1)
        pts = []
        for i in range(n + 1):
            t = i / float(n)
            pts.append(cam.project_camera(*[ca[k] + (cb[k] - ca[k]) * t for k in range(3)]))
        out = []
        for p0, p1 in zip(pts, pts[1:]):
            if p0 is not None and p1 is not None:
                out.append((p0[0], p0[1], p1[0], p1[1]))
        return out

    def _constellations(self, sc, fr, cam):
        v = self.view
        axis_hor = cam.forward
        cos_view = math.cos(min(math.pi, cam.radius + 2 * DEG))
        hor_to_j2000 = astro.transpose(fr.j2000_to_hor)
        axis = astro.mxv(hor_to_j2000, axis_hor)
        lines_on = v.s['show_lines']
        names_on = v.s['constellation_names'] and v.labels != config.NATURAL
        for con in self.sky.constellations:
            # Skip constellations whose bounding cone misses the view cone.
            sep = math.acos(max(-1.0, min(1.0, astro.dot(axis, con.center))))
            ext = math.acos(max(-1.0, min(1.0, con.cos_extent)))
            if sep - ext > math.acos(cos_view):
                continue
            if lines_on:
                for line in con.lines:
                    pts = [self.apparent(fr.star_to_hor(p)) for p in line]
                    for a, b in zip(pts, pts[1:]):
                        for seg in self._segment(cam, a, b):
                            s2 = _shorten(seg, LINE_GAP)
                            if s2:
                                sc.lines.append(s2)
            if names_on and (v.labels == config.EXPLORER or con.rank == 1):
                hor = self.apparent(fr.star_to_hor(con.label))
                if not self.visible(hor):
                    continue
                p = cam.project(hor)
                if p is not None and 0 <= p[0] < cam.width and 0 <= p[1] < cam.height:
                    sc.labels.append(Label(con.name.upper(), p[0], p[1], 0, 5 - con.rank, 'const', con.id))

    def _borders(self, sc, fr, cam):
        cos_view = math.cos(min(math.pi, cam.radius + 5 * DEG))
        axis = astro.mxv(astro.transpose(fr.j2000_to_hor), cam.forward)
        for line in self.sky.borders:
            for a, b in zip(line, line[1:]):
                if astro.dot(a, axis) < cos_view and astro.dot(b, axis) < cos_view:
                    continue
                pa = self.apparent(fr.star_to_hor(a))
                pb = self.apparent(fr.star_to_hor(b))
                sc.borders.extend(self._segment(cam, pa, pb))

    def _compass(self, sc, cam):
        for i, name in enumerate(camera.COMPASS):
            if i % 2:
                continue
            az = i * 22.5
            p = cam.project(astro.enu(math.radians(az), 0.0))
            if p is not None and 0 <= p[0] < cam.width and 0 <= p[1] < cam.height:
                sc.labels.append(Label(name, p[0], p[1], 0, 200, 'compass', 'compass-' + name))


def _shorten(seg, gap):
    x0, y0, x1, y1 = seg
    dx, dy = x1 - x0, y1 - y0
    d = math.hypot(dx, dy)
    if d <= 2 * gap + 2:
        return None
    k = gap / d
    return (x0 + dx * k, y0 + dy * k, x1 - dx * k, y1 - dy * k)


def _num(x):
    if x is None:
        return ''
    if isinstance(x, float) and x != int(x) and x < 100:
        return '%.1f' % x
    return '{:,}'.format(int(round(x)))


def _minutes(m):
    if m < 60:
        return '%.0f min' % m
    return '%dh %02dm' % (int(m // 60), int(m % 60))


def _altaz(hor):
    az, alt = astro.az_alt(hor)
    return 'Altitude %.1f°  ·  azimuth %.1f° (%s)' % (math.degrees(alt), math.degrees(az),
                                                     camera.compass_name(math.degrees(az)))


def moon_phase_name(m):
    """Waxing or waning from the Moon's elongation sign is not in Body; use illumination
    and the Sun's side instead: the lit limb faces the Sun."""
    k = m.illum
    if k < 0.03:
        return 'new moon'
    if k > 0.97:
        return 'full moon'
    return 'crescent' if k < 0.45 else ('quarter' if k < 0.55 else 'gibbous')


def place_labels(labels, width, height, char_w=11.0, line_h=26.0, avoid=(), max_count=45):
    """Greedy placement, most important first. Each label tries right, left, above and
    below its object; it is dropped if every spot overlaps a placed label or an avoided
    rectangle, or once max_count are placed (a wide field would otherwise be a wall of
    text). Objects never move for a label."""
    rects = list(avoid)
    out = []
    for lab in sorted(labels, key=lambda l: -l.priority):
        if len(out) >= max_count:
            break
        w = len(lab.text) * char_w + 4
        h = line_h
        if lab.style in ('const', 'compass'):
            spots = [(lab.x - w / 2, lab.y - h / 2)]
            if lab.style == 'compass':
                spots = [(lab.x - w / 2, lab.y + 4), (lab.x - w / 2, lab.y - h - 4)]
        else:
            g = lab.gap
            spots = [(lab.x + g, lab.y - h / 2), (lab.x - g - w, lab.y - h / 2),
                     (lab.x - w / 2, lab.y - g - h), (lab.x - w / 2, lab.y + g)]
        for x, y in spots:
            if x < 4 or y < 4 or x + w > width - 4 or y + h > height - 4:
                continue
            r = (x, y, x + w, y + h)
            if any(r[0] < q[2] and q[0] < r[2] and r[1] < q[3] and q[1] < r[3] for q in rects):
                continue
            rects.append(r)
            lab.placed = (x, y, w, h)
            out.append(lab)
            break
    return out
