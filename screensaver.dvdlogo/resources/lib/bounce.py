"""The logo's motion: a straight line through an endlessly mirrored plane.

The logo's top-left corner lives in a rectangle 0..width by 0..height. Reflecting it at every
wall is the same motion as a straight ray in an unfolded plane that is folded back into the
rectangle with a triangle wave. In that plane a wall bounce is the ray crossing a multiple of
`width` or `height`, and a corner hit is both at once: the ray crossing a lattice point
(i*width, j*height). So aiming at a lattice point is enough to arrive exactly in a corner, and
the small course correction it takes is all a viewer sees.

`aim()` bends the ray by at most a few degrees at a bounce and then the logo really does reach
the corner, after as many bounces as the target is far away. `aim_near_miss()` arms the same
run but starts a short, deliberate swerve half a second before the corner, so the logo looks
certain to make it and then does not.

No Kodi imports; tests/test_dvdlogo.py simulates whole screens.
"""

import math

EPS = 1e-9
CORNER_PX = 0.3          # wall crossings this close together (in pixels travelled) are a corner
MIN_COMPONENT = 0.12     # a corner run never becomes almost horizontal or vertical
TURN_STEPS = 6           # the last-second swerve is a short arc ...
TURN_STEP_SECONDS = 0.07 # ... in this many straight Kodi animations
TURN_DEGREES = (20.0, 34.0)


def fold(u, length):
    """Mirror the unfolded coordinate u back into 0..length."""
    r = u % (2.0 * length)
    return r if r <= length else 2.0 * length - r


def slide_offsets(base, start, end):
    """A Kodi slide's start and end offsets for a leg from `start` to `end`.

    The control stays at `base`; Kodi draws it at base + offset. Moving the control to the
    far end of the leg and then starting the animation is two calls, and a frame rendered
    between them shows the logo at that far end for a flash. Absolute offsets from one fixed
    base need only the animation call, and consecutive legs meet exactly.
    """
    return (int(round(start[0])) - base[0], int(round(start[1])) - base[1],
            int(round(end[0])) - base[0], int(round(end[1])) - base[1])


def _next_multiple(u, length, v):
    """(seconds, coordinate) of the next multiple of `length` strictly ahead along v."""
    if v > 0:
        k = math.floor(u / length + EPS) + 1
    elif v < 0:
        k = math.ceil(u / length - EPS) - 1
    else:
        return float('inf'), u
    target = k * length
    return (target - u) / v, target


def rotate(x, y, radians):
    c, s = math.cos(radians), math.sin(radians)
    return x * c - y * s, x * s + y * c


class Motion(object):
    def __init__(self, width, height, speed, rng):
        self.width = float(width)
        self.height = float(height)
        self.speed = float(speed)
        self.rng = rng
        self.u = [0.0, 0.0]
        self.v = [0.0, 0.0]
        self.target = None       # the lattice point a corner run is heading for
        self.veer_in = None      # seconds of travel until a near miss swerves
        self.turning = 0         # straight animations left in the swerve
        self.turn_direction = 1
        self.turn_angle = 0.0
        self.turn_step = TURN_STEP_SECONDS

    # ------------------------------------------------------------ state

    def start(self, x, y):
        """Begin at a physical position with a diagonal direction."""
        self.u = [float(x), float(y)]
        angle = self.rng.uniform(0.55, 1.05)          # a slope between about 0.6 and 1.7
        if self.rng.random() < 0.5:
            angle = math.pi - angle
        if self.rng.random() < 0.5:
            angle = -angle
        self.v = [self.speed * math.cos(angle), self.speed * math.sin(angle)]

    def point(self):
        """The physical position (the logo's top-left corner)."""
        return fold(self.u[0], self.width), fold(self.u[1], self.height)

    def _signs(self):
        """How the unfolded axis maps to the physical one: +1 or -1 per axis."""
        sx = 1.0 if self.u[0] % (2.0 * self.width) <= self.width else -1.0
        sy = 1.0 if self.u[1] % (2.0 * self.height) <= self.height else -1.0
        return sx, sy

    def physical_velocity(self):
        sx, sy = self._signs()
        return sx * self.v[0], sy * self.v[1]

    def _turn(self, radians):
        """Rotate the physical direction (the unfolded one follows its signs)."""
        sx, sy = self._signs()
        px, py = sx * self.v[0], sy * self.v[1]
        px, py = rotate(px, py, radians)
        self.v = [sx * px, sy * py]

    # ------------------------------------------------------------ running

    def next_leg(self):
        """(seconds, kind) until the next event. kind: wall, corner, veer or turn."""
        if self.veer_in is not None and self.veer_in <= 0.0:
            self._begin_swerve()
        tx, _ = _next_multiple(self.u[0], self.width, self.v[0])
        ty, _ = _next_multiple(self.u[1], self.height, self.v[1])
        if abs(tx - ty) * self.speed <= CORNER_PX:
            dt, kind = max(0.0, min(tx, ty)), 'corner'
        else:
            dt, kind = min(tx, ty), 'wall'
        if self.turning:
            if self.turn_step < dt:
                dt, kind = self.turn_step, 'turn'
        if self.veer_in is not None and self.veer_in < dt:
            dt, kind = max(0.0, self.veer_in), 'veer'
        if dt == float('inf'):
            dt = 1.0                                   # never expected; do not spin
        return dt, kind

    def advance(self, dt, kind):
        """Move for dt seconds and finish the event that ends the leg."""
        if self.veer_in is not None:
            self.veer_in -= dt
        self.u[0] += self.v[0] * dt
        self.u[1] += self.v[1] * dt
        if kind == 'corner':
            # Land exactly on the lattice: floating point should be there already.
            self.u[0] = round(self.u[0] / self.width) * self.width
            self.u[1] = round(self.u[1] / self.height) * self.height
            self.target = None
            self.veer_in = None
        elif kind == 'veer':
            self._begin_swerve()
        elif kind == 'turn':
            self._turn(self.turn_direction * self.turn_angle)
            self.turning -= 1
            if self.turning <= 0:
                self.turning = 0

    # ------------------------------------------------------------ corner hunting

    def _lattice(self, reach):
        """Lattice points (corner images) around the current unfolded position."""
        w, h = self.width, self.height
        k0 = int(math.floor(self.u[0] / w)) - reach
        j0 = int(math.floor(self.u[1] / h)) - reach
        for k in range(k0, k0 + 2 * reach + 2):
            for j in range(j0, j0 + 2 * reach + 2):
                yield k * w, j * h

    def aim(self, tolerance_degrees=12.0, reach=2, max_distance=None):
        """Turn the direction, by at most tolerance_degrees, onto a corner image.

        Returns the lattice point chosen (or None). The bend happens at the bounce the caller
        just finished, where it reads as a bounce rather than a curve.
        """
        if self.turning:
            return None              # a corner run must not start while the swerve is still turning
        tolerance = math.radians(tolerance_degrees)
        if max_distance is None:
            max_distance = 3.0 * math.hypot(self.width, self.height)
        speed = math.hypot(self.v[0], self.v[1]) or 1.0
        ux, uy = self.u
        best = None
        for x, y in self._lattice(reach):
            dx, dy = x - ux, y - uy
            dist = math.hypot(dx, dy)
            if dist < 1.0 or dist > max_distance:
                continue
            if abs(dx) / dist < MIN_COMPONENT or abs(dy) / dist < MIN_COMPONENT:
                continue
            dot = (dx * self.v[0] + dy * self.v[1]) / (dist * speed)
            if dot <= 0.0:
                continue
            angle = math.acos(max(-1.0, min(1.0, dot)))
            if angle > tolerance:
                continue
            if (best is None or angle < best[0] - 0.02
                    or (abs(angle - best[0]) <= 0.02 and dist < best[1])):
                best = (angle, dist, (x, y))
        if best is None:
            return None
        _angle, _dist, (x, y) = best
        dx, dy = x - ux, y - uy
        scale = speed / math.hypot(dx, dy)
        self.v = [dx * scale, dy * scale]
        self.target = (x, y)
        return self.target

    def aim_near_miss(self, lead_seconds, tolerance_degrees=12.0, reach=2, max_distance=None):
        """Aim at a corner but plan to swerve `lead_seconds` before arriving."""
        if self.aim(tolerance_degrees, reach, max_distance) is None:
            return None
        dx, dy = self.target[0] - self.u[0], self.target[1] - self.u[1]
        self.veer_in = max(0.0, math.hypot(dx, dy) / self.speed - lead_seconds)
        return self.target

    def _begin_swerve(self):
        if self.target is None:
            self.veer_in = None
            return
        corner = fold(self.target[0], self.width), fold(self.target[1], self.height)
        here = self.point()
        out = (here[0] - corner[0], here[1] - corner[1])
        pvx, pvy = self.physical_velocity()
        angle = math.radians(self.rng.uniform(*TURN_DEGREES))
        options = (rotate(pvx, pvy, angle), rotate(pvx, pvy, -angle))
        # Turn towards the inside of the screen, away from the corner it was heading for.
        best = max(options, key=lambda p: p[0] * out[0] + p[1] * out[1])
        self.turn_direction = 1 if best is options[0] else -1
        self.turn_angle = angle / TURN_STEPS
        self.turning = TURN_STEPS
        self.turn_step = TURN_STEP_SECONDS
        self.target = None
        self.veer_in = None
