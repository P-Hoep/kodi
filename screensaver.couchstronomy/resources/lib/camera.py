"""The TV as a camera: which way it faces, how wide it sees, and where a direction in the
local sky lands on the screen. No Kodi imports.

The camera basis is built in the local ENU frame. Forward points along the TV's azimuth
and tilt. Right is always horizontal (so a level TV keeps the horizon level, even facing
straight up), and up completes the right-handed set. Screen rotation (a TV turned on its
side) and a fine roll correction turn right and up about forward.

Coordinates returned are framebuffer pixels: x right, y down, (0, 0) top left.
"""

import math

from . import astro

PERSPECTIVE, STEREOGRAPHIC, EQUIDISTANT = 0, 1, 2
PROJECTION_NAMES = ('Perspective (rectilinear)', 'Stereographic', 'Angular (equidistant fisheye)')


def fov_from_screen(width_cm, distance_cm):
    """Horizontal field of view (degrees) of a screen of this width seen from this far."""
    return 2.0 * math.degrees(math.atan2(width_cm / 2.0, distance_cm))


class Camera(object):
    def __init__(self, azimuth_deg, tilt_deg, hfov_deg, width, height, rotation_steps=0, roll_deg=0.0,
                 projection=PERSPECTIVE):
        self.azimuth = azimuth_deg % 360.0
        self.tilt = max(-90.0, min(90.0, tilt_deg))
        self.width, self.height = width, height
        self.rotation_steps = rotation_steps % 4
        self.projection = projection
        if projection == PERSPECTIVE:
            hfov_deg = min(hfov_deg, 160.0)
        self.hfov = hfov_deg
        a = math.radians(self.azimuth)
        h = math.radians(self.tilt)
        self.forward = astro.enu(a, h)
        right = (math.cos(a), -math.sin(a), 0.0)
        up = astro.cross(right, self.forward)
        # A TV turned clockwise by rho (as the viewer sees it): its x axis points down-right
        # in the world by rho. Steps of 90 degrees describe a portrait-mounted TV.
        rho = math.radians(90.0 * self.rotation_steps + roll_deg)
        c, s = math.cos(rho), math.sin(rho)
        self.right = tuple(right[k] * c - up[k] * s for k in range(3))
        self.up = tuple(up[k] * c + right[k] * s for k in range(3))
        # The field of view is measured across the TV as it hangs on the wall.
        physical_w = height if self.rotation_steps % 2 else width
        physical_h = width if self.rotation_steps % 2 else height
        half = math.radians(hfov_deg) / 2.0
        if projection == PERSPECTIVE:
            self.f = (physical_w / 2.0) / math.tan(half)
        elif projection == STEREOGRAPHIC:
            self.f = (physical_w / 2.0) / (2.0 * math.tan(half / 2.0))
        else:
            self.f = (physical_w / 2.0) / half
        self.vfov = math.degrees(2.0 * self.inverse_radius(physical_h / 2.0))
        self.cx, self.cy = width / 2.0, height / 2.0
        # Angular radius of the circle through the screen corners: the culling cone.
        self.radius = self.inverse_radius(math.hypot(width, height) / 2.0)
        self.cos_radius = math.cos(min(math.pi, self.radius + math.radians(2.0)))
        self.matrix = (self.right, self.up, self.forward)

    def inverse_radius(self, r_px):
        """Angle from the axis of a point r_px pixels from the centre."""
        if self.projection == PERSPECTIVE:
            return math.atan(r_px / self.f)
        if self.projection == STEREOGRAPHIC:
            return 2.0 * math.atan(r_px / (2.0 * self.f))
        return r_px / self.f

    def to_camera(self, v):
        r, u, f = self.matrix
        return (r[0] * v[0] + r[1] * v[1] + r[2] * v[2],
                u[0] * v[0] + u[1] * v[1] + u[2] * v[2],
                f[0] * v[0] + f[1] * v[1] + f[2] * v[2])

    def project_camera(self, x, y, z):
        """Camera coordinates (need not be unit) -> (sx, sy) or None if not projectable."""
        if self.projection == PERSPECTIVE:
            if z <= 1e-9:
                return None
            k = self.f / z
        else:
            rho = math.sqrt(x * x + y * y)
            if rho < 1e-12:
                return self.cx, self.cy
            theta = math.atan2(rho, z)
            if theta > math.radians(179.0):
                return None
            if self.projection == STEREOGRAPHIC:
                k = 2.0 * self.f * math.tan(theta / 2.0) / rho
            else:
                k = self.f * theta / rho
        return self.cx + x * k, self.cy - y * k

    def project(self, v):
        """ENU direction -> framebuffer (sx, sy), or None behind the camera."""
        return self.project_camera(*self.to_camera(v))

    def on_screen(self, p, margin=0.0):
        return p is not None and -margin <= p[0] < self.width + margin and -margin <= p[1] < self.height + margin

    def unproject(self, sx, sy):
        """Framebuffer pixel -> ENU unit vector."""
        x = sx - self.cx
        y = self.cy - sy
        rho = math.hypot(x, y)
        theta = self.inverse_radius(rho)
        if rho < 1e-12:
            cx, cy, cz = 0.0, 0.0, 1.0
        else:
            st = math.sin(theta)
            cx, cy, cz = x / rho * st, y / rho * st, math.cos(theta)
        r, u, f = self.matrix
        return tuple(r[k] * cx + u[k] * cy + f[k] * cz for k in range(3))

    def pixel_scale(self):
        """Pixels per radian at the centre of the screen."""
        return self.f

    def describe(self):
        return 'facing %s (%.0f°), tilt %+.0f°, field %.0f° × %.0f°' % (
            compass_name(self.azimuth), self.azimuth, self.tilt, self.hfov, self.vfov)


COMPASS = ('N', 'NNE', 'NE', 'ENE', 'E', 'ESE', 'SE', 'SSE', 'S', 'SSW', 'SW', 'WSW', 'W', 'WNW', 'NW', 'NNW')


def compass_name(az_deg):
    return COMPASS[int((az_deg % 360.0) / 22.5 + 0.5) % 16]
