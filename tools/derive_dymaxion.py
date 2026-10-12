"""Choose how to unfold Fuller's icosahedron into the Dymaxion net (needs Pillow, numpy).

  python3 tools/derive_dymaxion.py tools/.world-cache/OSM_Land_Water_Map_2048.png

Each of the 30 icosahedron edges is scored by how much land its arc crosses. A net keeps
19 of them joined (a spanning tree of the faces) and cuts the other 11, so the best net
keeps the land-heavy edges and cuts across open sea, which is what Fuller did by hand.
Random spanning trees biased towards land are tried; trees whose unfolded triangles
overlap are rejected, and among the rest the one with the least land cut and the most
TV-friendly shape wins. Prints DYMAXION_TREE and DYMAXION_TURN for projections.py.
"""

import math
import os
import random
import sys

import numpy as np
from PIL import Image

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'screensaver.godsworld.map'))
from resources.lib import projections as P  # noqa: E402


def land_mask(path):
    img = np.array(Image.open(path).convert('L'))
    return img < 101  # land grey 75, water 128


def arc_land(mask, a, b, samples=120):
    h, w = mask.shape
    total = 0
    for i in range(samples + 1):
        t = i / float(samples)
        p = [a[k] * (1 - t) + b[k] * t for k in range(3)]
        n = math.sqrt(sum(v * v for v in p))
        lon, lat = P.lonlat([v / n for v in p])
        x = int((lon + 180) / 360.0 * w) % w
        y = min(h - 1, int((90 - lat) / 180.0 * h))
        total += mask[y, x]
    return total / float(samples + 1)


def triangles_overlap(t1, t2):
    def shrink(t):
        cx = sum(p[0] for p in t) / 3.0
        cy = sum(p[1] for p in t) / 3.0
        return [(cx + (p[0] - cx) * 0.97, cy + (p[1] - cy) * 0.97) for p in t]
    t1, t2 = shrink(t1), shrink(t2)
    for tri in (t1, t2):
        for i in range(3):
            p, q = tri[i], tri[(i + 1) % 3]
            nx, ny = q[1] - p[1], p[0] - q[0]
            a = [nx * v[0] + ny * v[1] for v in t1]
            b = [nx * v[0] + ny * v[1] for v in t2]
            if max(a) < min(b) or max(b) < min(a):
                return False
    return True


def tree_order(n_faces, edges):
    adj = {f: [] for f in range(n_faces)}
    for f, g in edges:
        adj[f].append(g)
        adj[g].append(f)
    order, seen, queue = [(0, None)], {0}, [0]
    while queue:
        f = queue.pop(0)
        for g in adj[f]:
            if g not in seen:
                seen.add(g)
                order.append((g, f))
                queue.append(g)
    return order


def best_turn(points):
    """Rotation (degrees) giving the smallest bounding box with width >= height."""
    best = None
    for deg in range(0, 180):
        a = math.radians(deg)
        xs = [p[0] * math.cos(a) - p[1] * math.sin(a) for p in points]
        ys = [p[0] * math.sin(a) + p[1] * math.cos(a) for p in points]
        w, h = max(xs) - min(xs), max(ys) - min(ys)
        if w < h:
            continue
        score = w * h + abs(w / h - 16 / 9.0) * 0.5
        if best is None or score < best[0]:
            best = (score, deg, w / h)
    return best


def main():
    mask = land_mask(sys.argv[1])
    pts, faces = P.icosa_faces()
    adjacency = []
    for f in range(len(faces)):
        for g in range(f + 1, len(faces)):
            shared = set(faces[f]) & set(faces[g])
            if len(shared) == 2:
                a, b = [pts[v] for v in shared]
                adjacency.append((f, g, arc_land(mask, a, b)))
    rng = random.Random(1)
    best = None
    for attempt in range(20000):
        # Randomised Kruskal: land-heavy edges tend to be joined first.
        order = sorted(adjacency, key=lambda e: -(e[2] + rng.random() * 0.25))
        parent = list(range(len(faces)))

        def find(x):
            while parent[x] != x:
                parent[x] = parent[parent[x]]
                x = parent[x]
            return x
        kept, cut_land = [], 0.0
        for f, g, land in order:
            rf, rg = find(f), find(g)
            if rf != rg:
                parent[rf] = rg
                kept.append((f, g))
            else:
                cut_land += land
        tree = tree_order(len(faces), kept)
        net = P.unfold(faces, tree)
        tris = [net[f] for f in range(len(faces))]
        if any(triangles_overlap(tris[i], tris[j]) for i in range(len(tris)) for j in range(i + 1, len(tris))):
            continue
        turn = best_turn([p for t in tris for p in t])
        if turn is None:
            continue
        score = cut_land * 10 + turn[0] * 0.02
        if best is None or score < best[0]:
            best = (score, cut_land, tree, turn)
            print('attempt %d: land cut %.3f, aspect %.2f' % (attempt, cut_land, turn[2]))
    _score, cut_land, tree, turn = best
    print('\nDYMAXION_TREE = %r' % (tree,))
    print('DYMAXION_TURN = %d' % turn[1])


if __name__ == '__main__':
    main()
