"""The map projections. No Kodi imports.

Every flat projection is described as a triangle mesh: vertices carry a position on the
projection plane (x right, y up) and the geographic point (lon, lat) they show. The
rasteriser in reproject.py fills each triangle from the equirectangular source images, so
one code path draws continuous, interrupted (lobed) and polyhedral (unfolded) maps, and a
lobe or face boundary can never leak imagery from the wrong side of a cut. The globe is
drawn by an exact per-pixel inverse instead.

forward(lon, lat) gives the plane position of one point (or None where the projection
does not show it); markers and wind particles use it to line up with the raster.
"""

import cmath
import math

D2R = math.pi / 180.0
R2D = 180.0 / math.pi
HALF_PI = math.pi / 2


# ---------------------------------------------------------------- raw projections (radians)

def equirectangular(lam, phi):
    return lam, phi


def mercator(lam, phi):
    return lam, math.log(math.tan(math.pi / 4 + phi / 2))


def gall_peters(lam, phi):
    k = math.cos(45 * D2R)
    return lam * k, math.sin(phi) / k


def lambert_cea(lam, phi):
    return lam, math.sin(phi)


def sinusoidal(lam, phi):
    return lam * math.cos(phi), phi


def _mollweide_theta(phi):
    if abs(abs(phi) - HALF_PI) < 1e-9:
        return math.copysign(HALF_PI, phi)
    target = math.pi * math.sin(phi)
    theta = phi
    for _ in range(30):
        f = 2 * theta + math.sin(2 * theta) - target
        d = 2 + 2 * math.cos(2 * theta)
        if d == 0:
            break
        step = f / d
        theta -= step
        if abs(step) < 1e-12:
            break
    return theta


def mollweide(lam, phi):
    theta = _mollweide_theta(phi)
    return 2 * math.sqrt(2) / math.pi * lam * math.cos(theta), math.sqrt(2) * math.sin(theta)


def _homolosine_latitude():
    """Latitude where sinusoidal and Mollweide parallels have the same length (40.7368 deg)."""
    lo, hi = 0.5, 0.9
    for _ in range(60):
        mid = (lo + hi) / 2
        diff = math.cos(mid) - 2 * math.sqrt(2) / math.pi * math.cos(_mollweide_theta(mid))
        if diff > 0:
            lo = mid
        else:
            hi = mid
    return (lo + hi) / 2


HOMOLOSINE_PHI = _homolosine_latitude()
HOMOLOSINE_DY = mollweide(0, HOMOLOSINE_PHI)[1] - HOMOLOSINE_PHI


def homolosine(lam, phi):
    if abs(phi) <= HOMOLOSINE_PHI:
        return sinusoidal(lam, phi)
    x, y = mollweide(lam, phi)
    return x, y - math.copysign(HOMOLOSINE_DY, phi)


def sinu_mollweide(lam, phi):
    """Philbrick's Sinu-Mollweide: Mollweide north of 40.7 S, sinusoidal south of it."""
    if phi > -HOMOLOSINE_PHI:
        x, y = mollweide(lam, phi)
        return x, y - HOMOLOSINE_DY
    return sinusoidal(lam, phi)


ROBINSON = [  # latitude 0, 5, ... 90: (parallel length, distance from the equator)
    (1.0000, 0.0000), (0.9986, 0.0620), (0.9954, 0.1240), (0.9900, 0.1860), (0.9822, 0.2480),
    (0.9730, 0.3100), (0.9600, 0.3720), (0.9427, 0.4340), (0.9216, 0.4958), (0.8962, 0.5571),
    (0.8679, 0.6176), (0.8350, 0.6769), (0.7986, 0.7346), (0.7597, 0.7903), (0.7186, 0.8435),
    (0.6732, 0.8936), (0.6213, 0.9394), (0.5722, 0.9761), (0.5322, 1.0000)]


def robinson(lam, phi):
    a = min(abs(phi) * R2D / 5.0, 17.999999)
    i = int(a)
    f = a - i
    x0, y0 = ROBINSON[i]
    x1, y1 = ROBINSON[i + 1]
    px = x0 + (x1 - x0) * f
    py = y0 + (y1 - y0) * f
    return 0.8487 * px * lam, math.copysign(1.3523 * py, phi)


def equal_earth(lam, phi):
    a1, a2, a3, a4 = 1.340264, -0.081106, 0.000893, 0.003796
    theta = math.asin(math.sqrt(3) / 2 * math.sin(phi))
    t2 = theta * theta
    t6 = t2 * t2 * t2
    x = 2 * math.sqrt(3) * lam * math.cos(theta) / (3 * (9 * a4 * t6 * t2 + 7 * a3 * t6 + 3 * a2 * t2 + a1))
    y = theta * (a1 + a2 * t2 + t6 * (a3 + a4 * t2))
    return x, y


WINKEL_COS_PHI1 = 2 / math.pi


def winkel_tripel(lam, phi):
    alpha = math.acos(max(-1.0, min(1.0, math.cos(phi) * math.cos(lam / 2))))
    sinc = math.sin(alpha) / alpha if alpha > 1e-12 else 1.0
    x = (lam * WINKEL_COS_PHI1 + 2 * math.cos(phi) * math.sin(lam / 2) / sinc) / 2
    y = (phi + math.sin(phi) / sinc) / 2
    return x, y


# ---------------------------------------------------------------- base class

class Projection(object):
    kind = 'flat'          # 'cylindrical' (wraps east-west), 'flat' or 'globe'
    interrupted = False    # lobes/faces fixed to geography: never re-centre by rolling
    rotatable = True       # the central meridian can move (re-render with rolled sources)
    step = 2.0             # mesh spacing in degrees for graticule meshes

    def __init__(self, pid, name):
        self.id = pid
        self.name = name
        self._mesh = None
        self._bounds = None

    def mesh(self):
        """-> (vertices [(x, y, lon, lat)], triangles [(i, j, k)])."""
        if self._mesh is None:
            self._mesh = self.build_mesh()
        return self._mesh

    def bounds(self):
        if self._bounds is None:
            verts = self.mesh()[0]
            xs = [v[0] for v in verts]
            ys = [v[1] for v in verts]
            self._bounds = (min(xs), min(ys), max(xs), max(ys))
        return self._bounds

    def forward(self, lon, lat):
        raise NotImplementedError


class Graticule(Projection):
    """A raw projection meshed on a lon/lat grid, optionally split into lobes.

    lobes: (lon0, lon1, lat0, lat1, central lon) in degrees; lon1 may exceed 180 for a
    lobe that straddles the antimeridian."""

    def __init__(self, pid, name, raw, kind='flat', lobes=None, lat_limit=90.0, step=2.0, rotatable=True):
        Projection.__init__(self, pid, name)
        self.raw = raw
        self.kind = kind
        self.lobes = lobes or [(-180.0, 180.0, -lat_limit, lat_limit, 0.0)]
        self.interrupted = lobes is not None and len(lobes) > 1
        self.rotatable = rotatable and not self.interrupted
        self.lat_limit = lat_limit
        self.step = step

    def project(self, lon, lat, lobe):
        lonc = lobe[4]
        x, y = self.raw((lon - lonc) * D2R, lat * D2R)
        if lonc:
            x += self.raw(lonc * D2R, 0.0)[0]
        return x, y

    def build_mesh(self):
        verts, tris = [], []
        for lobe in self.lobes:
            lon0, lon1, lat0, lat1 = lobe[:4]
            nx = max(1, int(math.ceil((lon1 - lon0) / self.step)))
            ny = max(1, int(math.ceil((lat1 - lat0) / self.step)))
            base = len(verts)
            for j in range(ny + 1):
                lat = lat0 + (lat1 - lat0) * j / float(ny)
                for i in range(nx + 1):
                    lon = lon0 + (lon1 - lon0) * i / float(nx)
                    x, y = self.project(lon, lat, lobe)
                    verts.append((x, y, lon, lat))
            for j in range(ny):
                for i in range(nx):
                    a = base + j * (nx + 1) + i
                    b, c, d = a + 1, a + nx + 1, a + nx + 2
                    tris.append((a, b, d))
                    tris.append((a, d, c))
        return verts, tris

    def forward(self, lon, lat):
        if abs(lat) > self.lat_limit:
            return None
        for lobe in self.lobes:
            lon0, lon1, lat0, lat1 = lobe[:4]
            if not (lat0 <= lat <= lat1):
                continue
            for l in (lon, lon + 360.0, lon - 360.0):
                if lon0 <= l <= lon1:
                    return self.project(l, lat, lobe)
        return None


# ---------------------------------------------------------------- Peirce quincuncial

def _tanh_sinh(h=1.0 / 8, kmax=24):
    nodes = []
    for k in range(-kmax, kmax + 1):
        t = k * h
        u = HALF_PI * math.sinh(t)
        x = math.tanh(u)
        w = h * HALF_PI * math.cosh(t) / math.cosh(u) ** 2
        if abs(x) < 1.0:  # nodes that round to an endpoint would hit the singularity
            nodes.append(((x + 1) / 2, w / 2))  # mapped to [0, 1]
    return nodes


_TS_NODES = _tanh_sinh()


def _square_map(z):
    """Conformal map of the unit disk onto a square: f(z) = integral from 0 to z of
    dt / sqrt(1 + t^4). Corners where z^4 = -1; tanh-sinh copes with the corner singularity."""
    if z == 0:
        return 0j
    z4 = z ** 4
    total = 0j
    for s, w in _TS_NODES:
        total += w / cmath.sqrt(1 + z4 * s ** 4)
    return z * total


PEIRCE_A = _square_map(1.0).real   # half side of the inner (northern) square, about 0.927
PEIRCE_SHIFT = 25.0                # puts the southern cuts on meridians 20, 110, 160 W, 70 W
PEIRCE_TURN = cmath.exp(1j * 225 * D2R)


class Peirce(Graticule):
    """Peirce quincuncial: the northern hemisphere conformally in a central square, the
    southern hemisphere folded out into the four corners. A square map."""

    def __init__(self):
        lobes = [(-180.0, 180.0, 0.0, 90.0, None)]
        for k in range(4):
            a0 = -45 + 90 * k - PEIRCE_SHIFT
            lobes.append((a0, a0 + 90.0, -90.0, 0.0, k))
        Graticule.__init__(self, 'peirce', 'Peirce quincuncial', None, lobes=lobes, step=2.0)
        self.interrupted = True
        self.rotatable = False

    def project(self, lon, lat, lobe):
        r = math.tan((90.0 - lat) * D2R / 2)
        arg = (lon + PEIRCE_SHIFT) * D2R
        if lobe[4] is None or r <= 1.0:
            w = _square_map(cmath.rect(min(r, 1.0), arg))
        else:
            w0 = _square_map(cmath.rect(1.0 / r, arg))
            a = PEIRCE_A
            k = lobe[4]
            if k == 0:
                w = 2 * a - w0.conjugate()
            elif k == 1:
                w = w0.conjugate() + 2j * a
            elif k == 2:
                w = -2 * a - w0.conjugate()
            else:
                w = w0.conjugate() - 2j * a
        w *= PEIRCE_TURN
        return w.real, w.imag


# ---------------------------------------------------------------- polyhedral (unfolded) maps

def unit(lon, lat):
    lo, la = lon * D2R, lat * D2R
    return (math.cos(la) * math.cos(lo), math.cos(la) * math.sin(lo), math.sin(la))


def lonlat(p):
    x, y, z = p
    return math.atan2(y, x) * R2D, math.asin(max(-1.0, min(1.0, z))) * R2D


def _inverse3(a, b, c):
    """Inverse of the 3x3 matrix with columns a, b, c."""
    m = [[a[0], b[0], c[0]], [a[1], b[1], c[1]], [a[2], b[2], c[2]]]
    det = (m[0][0] * (m[1][1] * m[2][2] - m[1][2] * m[2][1])
           - m[0][1] * (m[1][0] * m[2][2] - m[1][2] * m[2][0])
           + m[0][2] * (m[1][0] * m[2][1] - m[1][1] * m[2][0]))
    inv = [[0.0] * 3 for _ in range(3)]
    for i in range(3):
        for j in range(3):
            r = [k for k in range(3) if k != j]
            s = [k for k in range(3) if k != i]
            minor = m[r[0]][s[0]] * m[r[1]][s[1]] - m[r[0]][s[1]] * m[r[1]][s[0]]
            inv[i][j] = (-1) ** (i + j) * minor / det
    return inv


class Polyhedral(Projection):
    """Each face of a polyhedron (a spherical triangle) mapped onto a triangle of an
    unfolded net. faces: [((A, B, C) unit vectors, (a, b, c) net points)]."""

    subdivide = 16

    def __init__(self, pid, name, faces):
        Projection.__init__(self, pid, name)
        self.faces = faces
        self.inverses = [_inverse3(*f[0]) for f in faces]
        self.interrupted = True
        self.rotatable = False

    def to_sphere(self, face, b):
        """Barycentric point on a face -> unit vector (gnomonic: straight through the centre)."""
        (A, B, C), _net = self.faces[face]
        p = [b[0] * A[i] + b[1] * B[i] + b[2] * C[i] for i in range(3)]
        n = math.sqrt(p[0] * p[0] + p[1] * p[1] + p[2] * p[2])
        return (p[0] / n, p[1] / n, p[2] / n)

    def to_face(self, face, p):
        """Unit vector -> barycentric coordinates on a face (None when not on it)."""
        inv = self.inverses[face]
        c = [inv[i][0] * p[0] + inv[i][1] * p[1] + inv[i][2] * p[2] for i in range(3)]
        if min(c) < -1e-9:
            return None
        s = c[0] + c[1] + c[2]
        return (c[0] / s, c[1] / s, c[2] / s)

    def build_mesh(self):
        verts, tris = [], []
        n = self.subdivide
        for f, (_sphere, (a, b, c)) in enumerate(self.faces):
            index = {}
            for i in range(n + 1):
                for j in range(n + 1 - i):
                    k = n - i - j
                    bary = (i / float(n), j / float(n), k / float(n))
                    x = bary[0] * a[0] + bary[1] * b[0] + bary[2] * c[0]
                    y = bary[0] * a[1] + bary[1] * b[1] + bary[2] * c[1]
                    lon, lat = lonlat(self.to_sphere(f, bary))
                    index[(i, j)] = len(verts)
                    verts.append((x, y, lon, lat))
            for i in range(n):
                for j in range(n - i):
                    tris.append((index[(i, j)], index[(i + 1, j)], index[(i, j + 1)]))
                    if i + j < n - 1:
                        tris.append((index[(i + 1, j)], index[(i + 1, j + 1)], index[(i, j + 1)]))
        return verts, tris

    def forward(self, lon, lat):
        p = unit(lon, lat)
        for f in range(len(self.faces)):
            b = self.to_face(f, p)
            if b is not None:
                a, bb, c = self.faces[f][1]
                return (b[0] * a[0] + b[1] * bb[0] + b[2] * c[0], b[0] * a[1] + b[1] * bb[1] + b[2] * c[1])
        return None


class Octahedral(Polyhedral):
    """Octant faces with an 'angular' face mapping: distances along face edges stay in
    proportion to arc length, which keeps the poles and corners far less stretched than
    a gnomonic face would."""

    def to_face(self, face, p):
        inv = self.inverses[face]
        c = [inv[i][0] * p[0] + inv[i][1] * p[1] + inv[i][2] * p[2] for i in range(3)]
        if min(c) < -1e-9:
            return None
        # The face vertices are orthonormal, so c are direction cosines; use angles.
        ang = [math.asin(max(0.0, min(1.0, v))) for v in c]
        s = sum(ang)
        return (ang[0] / s, ang[1] / s, ang[2] / s)

    def to_sphere(self, face, b):
        (A, B, C), _net = self.faces[face]
        top = max(b)
        if top >= 1 - 1e-12:
            return (A, B, C)[list(b).index(top)]
        # Find s with sum(sin^2(s * b_i)) = 1, then the direction cosines are sin(s * b_i).
        # Every angle s * b_i stays within 90 degrees on [lo, hi], so the sum only grows.
        lo, hi = HALF_PI, HALF_PI / top
        for _ in range(50):
            mid = (lo + hi) / 2
            total = sum(math.sin(mid * v) ** 2 for v in b)
            if total < 1:
                lo = mid
            else:
                hi = mid
        s = (lo + hi) / 2
        c = [math.sin(s * v) for v in b]
        p = [c[0] * A[i] + c[1] * B[i] + c[2] * C[i] for i in range(3)]
        n = math.sqrt(sum(v * v for v in p))
        return (p[0] / n, p[1] / n, p[2] / n)


def waterman_butterfly():
    """An octahedral butterfly in Waterman's arrangement: the four northern octants fan out
    round the North Pole, each southern octant folds out below its northern twin. Octant
    edges on meridians 20 W, 70 E, 160 E and 110 W, as on Waterman's map. (Waterman's own
    map uses a truncated-octahedron face layout; this keeps its shape and cuts.)"""
    north, south = (0.0, 0.0, 1.0), (0.0, 0.0, -1.0)
    meridians = [160.0, -110.0, -20.0, 70.0, 160.0]
    angles = [150.0, 210.0, 270.0, 330.0, 390.0]
    q = [(math.cos(a * D2R), math.sin(a * D2R)) for a in angles]
    pole = (0.0, 0.0)
    faces = []
    for k in range(4):
        e0, e1 = unit(meridians[k], 0.0), unit(meridians[k + 1], 0.0)
        faces.append(((north, e0, e1), (pole, q[k], q[k + 1])))
        tip = (q[k][0] + q[k + 1][0] - pole[0], q[k][1] + q[k + 1][1] - pole[1])
        faces.append(((south, e0, e1), (tip, q[k], q[k + 1])))
    proj = Octahedral('waterman', 'Butterfly (octahedral, Waterman cuts)', faces)
    proj.subdivide = 20
    return proj


def _cross(a, b):
    return (a[1] * b[2] - a[2] * b[1], a[2] * b[0] - a[0] * b[2], a[0] * b[1] - a[1] * b[0])


def _dot(a, b):
    return a[0] * b[0] + a[1] * b[1] + a[2] * b[2]


def _norm(a):
    n = math.sqrt(_dot(a, a))
    return (a[0] / n, a[1] / n, a[2] / n)


class WatermanW5(Projection):
    """Waterman's butterfly on his W5 polyhedron, a truncated octahedron, built as d3-geo's
    reference implementation (geoPolyhedralWaterman) builds it.

    Each octant becomes a hexagon by cutting its corners where the octant's edges are split
    1:3 (18.43 degrees from each octahedron vertex); each corner cut off is a triangle hung
    on its own hexagon. Every face is a gnomonic projection about its centre (great circles
    stay straight), and the faces are unfolded in d3's tree, each joined to its parent along
    their shared edge. The globe is turned 20 degrees so the cuts fall on 20 W, 70 E, 160 E and
    110 W, as on Waterman's map."""

    interrupted = True
    rotatable = False
    ROTATE = 20.0                         # d3 example: .rotate([20, 0])
    ANGLE = -30.0                         # d3: .angle(-30)
    PARENTS = [-1, 0, 0, 1, 0, 1, 4, 5]   # hexagons; corner triangles follow their hexagon
    subdivide = 10

    def __init__(self, pid='waterman_w5', name='Waterman butterfly (W5)'):
        Projection.__init__(self, pid, name)
        octa = [unit(*v) for v in ((0, 90), (-90, 0), (0, 0), (90, 0), (180, 0), (0, -90))]
        octa_faces = [(0, 2, 1), (0, 3, 2), (5, 1, 2), (5, 2, 3), (0, 1, 4), (0, 4, 3), (5, 4, 1), (5, 3, 4)]
        k1, k2 = 3 / math.sqrt(10), 1 / math.sqrt(10)   # 18.43 degrees along a 90-degree edge
        faces, parents, centres = [], list(self.PARENTS), []
        hexagons = []
        for tri in octa_faces:
            pts = [octa[i] for i in tri]
            hexagon = []
            a = pts[-1]
            for b in pts:
                hexagon.append(tuple(a[i] * k1 + b[i] * k2 for i in range(3)))
                hexagon.append(tuple(b[i] * k1 + a[i] * k2 for i in range(3)))
                a = b
            hexagons.append(hexagon)
            faces.append(hexagon)
            centres.append(_norm(tuple(sum(p[i] for p in hexagon) for i in range(3))))
        for j, tri in enumerate(octa_faces):
            hexagon = hexagons[j]
            for i in range(3):
                faces.append([octa[tri[i]], hexagon[(2 * i + 2) % 6], hexagon[(2 * i + 1) % 6]])
                parents.append(j)
                centres.append(octa[tri[i]])
        self.faces = faces
        # Each face's tangent-plane basis: centre c, east e, north n (right-handed from outside).
        self.bases = []
        for c in centres:
            e = _cross((0.0, 0.0, 1.0), c)
            e = _norm(e) if _dot(e, e) > 1e-12 else (0.0, 1.0, 0.0)
            self.bases.append((c, e, _cross(c, e)))
        # Edge planes for "is this point on the face" (each face is a convex spherical polygon).
        self.edges = []
        for f, poly in enumerate(faces):
            c = self.bases[f][0]
            planes = []
            for k in range(len(poly)):
                nrm = _cross(poly[k], poly[(k + 1) % len(poly)])
                planes.append(nrm if _dot(nrm, c) > 0 else tuple(-v for v in nrm))
            self.edges.append(planes)
        # Unfold: a complex similarity z -> a * z + b per face, joining shared edges.
        self.transforms = [None] * len(faces)
        self.transforms[0] = (complex(1, 0), complex(0, 0))
        for f in range(1, len(faces)):
            self._place(f, parents)
        turn = complex(math.cos(self.ANGLE * D2R), math.sin(self.ANGLE * D2R))
        self.transforms = [(a * turn, b * turn) for a, b in self.transforms]

    def _place(self, f, parents):
        p = parents[f]
        if self.transforms[p] is None:
            self._place(p, parents)
        shared = [v for v in self.faces[f] if any(_dot(v, w) > 1 - 1e-9 for w in self.faces[p])]
        s0, s1 = shared[0], shared[1]
        pa, pb = self.transforms[p]
        P0, P1 = pa * self.local(p, s0) + pb, pa * self.local(p, s1) + pb
        C0, C1 = self.local(f, s0), self.local(f, s1)
        a = (P1 - P0) / (C1 - C0)
        self.transforms[f] = (a, P0 - a * C0)

    def local(self, f, p):
        """Unit vector -> gnomonic plane coordinates of face f, as a complex number."""
        c, e, n = self.bases[f]
        d = _dot(p, c)
        return complex(_dot(p, e) / d, _dot(p, n) / d)

    def sphere(self, f, z):
        """Gnomonic plane point of face f -> (lon, lat) on the real globe."""
        c, e, n = self.bases[f]
        q = _norm(tuple(c[i] + z.real * e[i] + z.imag * n[i] for i in range(3)))
        lon, lat = lonlat(q)
        return ((lon - self.ROTATE + 540.0) % 360.0) - 180.0, lat

    def face_of(self, p):
        for f, planes in enumerate(self.edges):
            if all(_dot(nrm, p) >= -1e-12 for nrm in planes):
                return f
        return None

    def forward(self, lon, lat):
        p = unit(lon + self.ROTATE, lat)
        f = self.face_of(p)
        if f is None:
            return None
        a, b = self.transforms[f]
        z = a * self.local(f, p) + b
        return z.real, z.imag

    def build_mesh(self):
        verts, tris = [], []
        n = self.subdivide
        for f, poly in enumerate(self.faces):
            a_t, b_t = self.transforms[f]
            corners = [self.local(f, v) for v in poly]
            # Hexagons are fanned from their centre (local 0); triangles are used as they are.
            fans = ([(0j, corners[k], corners[(k + 1) % 6]) for k in range(6)] if len(poly) == 6
                    else [tuple(corners)])
            for z0, z1, z2 in fans:
                index = {}
                for i in range(n + 1):
                    for j in range(n + 1 - i):
                        z = z0 + (z1 - z0) * (i / float(n)) + (z2 - z0) * (j / float(n))
                        w = a_t * z + b_t
                        lon, lat = self.sphere(f, z)
                        index[(i, j)] = len(verts)
                        verts.append((w.real, w.imag, lon, lat))
                for i in range(n):
                    for j in range(n - i):
                        tris.append((index[(i, j)], index[(i + 1, j)], index[(i, j + 1)]))
                        if i + j < n - 1:
                            tris.append((index[(i + 1, j)], index[(i + 1, j + 1)], index[(i, j + 1)]))
        return verts, tris


# Buckminster Fuller's icosahedron orientation (R. W. Gray's coordinates): every vertex
# falls in the sea, so the net can be cut without slicing continents.
FULLER_VERTICES = [
    (10.53620, 64.70000), (-5.24539, 2.30088), (58.15771, 10.44738), (122.30000, 39.10000),
    (-143.47849, 50.10320), (-67.13233, 23.71793), (36.52151, -50.10320), (112.86767, -23.71793),
    (174.75461, -2.30088), (-121.84229, -10.44738), (-57.70000, -39.10000), (-169.46380, -64.70000)]
# The unfolding: (face, parent face) in placing order, faces numbered as icosa_faces()
# returns them. Chosen by tools/derive_dymaxion.py: the spanning tree of face adjacencies
# that keeps the most land joined, among those whose net does not overlap itself.
DYMAXION_TREE = [(0, None), (1, 0), (2, 0), (5, 0), (3, 2), (8, 2), (4, 3), (10, 3), (11, 8), (9, 8),
                 (12, 4), (17, 11), (14, 12), (15, 17), (6, 14), (19, 14), (16, 15), (7, 6), (18, 19),
                 (13, 18)]
DYMAXION_TURN = 120  # degrees, so the net lies landscape


def icosa_faces():
    """The 20 faces as vertex index triples, counter-clockwise seen from outside."""
    pts = [unit(*v) for v in FULLER_VERTICES]

    def dist(i, j):
        return math.acos(max(-1.0, min(1.0, sum(pts[i][k] * pts[j][k] for k in range(3)))))
    edge = min(dist(i, j) for i in range(12) for j in range(i + 1, 12))
    near = lambda i, j: abs(dist(i, j) - edge) < 1e-3  # noqa: E731
    faces = []
    for i in range(12):
        for j in range(i + 1, 12):
            for k in range(j + 1, 12):
                if near(i, j) and near(j, k) and near(i, k):
                    a, b, c = pts[i], pts[j], pts[k]
                    n = (
                        (b[1] - a[1]) * (c[2] - a[2]) - (b[2] - a[2]) * (c[1] - a[1]),
                        (b[2] - a[2]) * (c[0] - a[0]) - (b[0] - a[0]) * (c[2] - a[2]),
                        (b[0] - a[0]) * (c[1] - a[1]) - (b[1] - a[1]) * (c[0] - a[0]))
                    if n[0] * a[0] + n[1] * a[1] + n[2] * a[2] < 0:
                        j2, k2 = k, j
                    else:
                        j2, k2 = j, k
                    faces.append((i, j2, k2))
    return pts, faces


def unfold(faces, tree):
    """Lay the faces of a triangulated polyhedron flat. tree: [(face, parent)] with the
    root's parent None. Returns {face: (p0, p1, p2)} planar points matching face vertex order."""
    s3 = math.sqrt(3) / 2
    placed = {}
    for face, parent in tree:
        if parent is None:
            placed[face] = ((0.0, 0.0), (1.0, 0.0), (0.5, s3))
            continue
        pf, ff = faces[parent], faces[face]
        shared = [v for v in ff if v in pf]
        p_pos = dict(zip(pf, placed[parent]))
        a, b = shared
        pa, pb = p_pos[a], p_pos[b]
        other_parent = [p_pos[v] for v in pf if v not in shared][0]
        # The new vertex mirrors the parent's third vertex across the shared edge.
        mx, my = (pa[0] + pb[0]) / 2, (pa[1] + pb[1]) / 2
        new = (2 * mx - other_parent[0], 2 * my - other_parent[1])
        pos = {a: pa, b: pb}
        third = [v for v in ff if v not in shared][0]
        pos[third] = new
        placed[face] = tuple(pos[v] for v in ff)
    return placed


def dymaxion():
    pts, faces = icosa_faces()
    tree = DYMAXION_TREE or default_icosa_tree(faces)
    nets = unfold(faces, tree)
    turn = (DYMAXION_TURN if DYMAXION_TREE else 0) * D2R
    ct, st = math.cos(turn), math.sin(turn)
    out = []
    for f, tri in enumerate(faces):
        net = tuple((x * ct - y * st, x * st + y * ct) for x, y in nets[f])
        out.append(((pts[tri[0]], pts[tri[1]], pts[tri[2]]), net))
    proj = Polyhedral('dymaxion', 'Dymaxion (Fuller)', out)
    proj.subdivide = 12
    return proj


def default_icosa_tree(faces):
    """Breadth-first unfolding from face 0 (used until a better tree is derived)."""
    adj = {f: [] for f in range(len(faces))}
    for f in range(len(faces)):
        for g in range(f + 1, len(faces)):
            if len(set(faces[f]) & set(faces[g])) == 2:
                adj[f].append(g)
                adj[g].append(f)
    tree, seen, queue = [(0, None)], {0}, [0]
    while queue:
        f = queue.pop(0)
        for g in adj[f]:
            if g not in seen:
                seen.add(g)
                tree.append((g, f))
                queue.append(g)
    return tree


# ---------------------------------------------------------------- the globe

class Orthographic(Projection):
    kind = 'globe'
    rotatable = True

    def __init__(self):
        Projection.__init__(self, 'orthographic', 'Orthographic globe')
        self._bounds = (-1.0, -1.0, 1.0, 1.0)

    def build_mesh(self):
        return [(-1.0, -1.0, 0.0, 0.0), (1.0, 1.0, 0.0, 0.0)], []

    @staticmethod
    def ortho_inverse(x, y, lon0, lat0):
        """Point on the unit disk -> (lon, lat), or None off the globe."""
        rho2 = x * x + y * y
        if rho2 > 1.0:
            return None
        rho = math.sqrt(rho2)
        if rho < 1e-12:
            return lon0, lat0
        c = math.asin(rho)
        sc, cc = math.sin(c), math.cos(c)
        p0 = lat0 * D2R
        lat = math.asin(max(-1.0, min(1.0, cc * math.sin(p0) + y * sc * math.cos(p0) / rho)))
        lon = lon0 * D2R + math.atan2(x * sc, rho * cc * math.cos(p0) - y * sc * math.sin(p0))
        return ((lon * R2D + 540.0) % 360.0) - 180.0, lat * R2D

    def forward_view(self, lon, lat, lon0, lat0):
        lo, la, p0 = (lon - lon0) * D2R, lat * D2R, lat0 * D2R
        cosc = math.sin(p0) * math.sin(la) + math.cos(p0) * math.cos(la) * math.cos(lo)
        if cosc < 0:
            return None
        return (math.cos(la) * math.sin(lo),
                math.cos(p0) * math.sin(la) - math.sin(p0) * math.cos(la) * math.cos(lo))

    def forward(self, lon, lat):
        return self.forward_view(lon, lat, 0.0, 0.0)


# ---------------------------------------------------------------- registry

GOODE_LOBES = [(-180.0, -40.0, 0.0, 90.0, -100.0), (-40.0, 180.0, 0.0, 90.0, 30.0),
               (-180.0, -100.0, -90.0, 0.0, -160.0), (-100.0, -20.0, -90.0, 0.0, -60.0),
               (-20.0, 80.0, -90.0, 0.0, 20.0), (80.0, 180.0, -90.0, 0.0, 140.0)]
# Philbrick's Sinu-Mollweide: an unbroken north, the south cut into four ocean lobes.
SINU_MOLLWEIDE_LOBES = [(-180.0, 180.0, 0.0, 90.0, 0.0)] + GOODE_LOBES[2:]
MERCATOR_LIMIT = 85.0511287798  # Web Mercator's square world


def _build():
    return [
        Graticule('mercator', 'Mercator', mercator, kind='cylindrical', lat_limit=MERCATOR_LIMIT),
        Graticule('robinson', 'Robinson', robinson),
        dymaxion(),
        Graticule('gall_peters', 'Gall–Peters', gall_peters, kind='cylindrical'),
        Graticule('equal_earth', 'Equal Earth', equal_earth),
        Graticule('sinu_mollweide', 'Sinu-Mollweide (interrupted)', sinu_mollweide,
                  lobes=SINU_MOLLWEIDE_LOBES),
        Graticule('goode', 'Goode homolosine (interrupted)', homolosine, lobes=GOODE_LOBES),
        Graticule('lambert_cea', 'Cylindrical equal-area', lambert_cea, kind='cylindrical'),
        Peirce(),
        Graticule('winkel_tripel', 'Winkel tripel', winkel_tripel),
        waterman_butterfly(),
        Orthographic(),
        WatermanW5(),   # added later: last, so saved projection choices keep their numbers
    ]


# Order matches the spec's list and the settings.
ALL = _build()
BY_ID = dict((p.id, p) for p in ALL)
IDS = [p.id for p in ALL]


def get(pid):
    return BY_ID[pid]
