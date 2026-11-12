"""Bake crab.glb into the Space Crab screensaver's model files.

Run:
  python3 tools/make_crab_model.py [path/to/crab.glb]

Writes, into screensaver.spacecrab/resources/model/ and screensaver.spacecrab.armv7/...:
  crab.bin        mesh + baked skinning palette (format below)
  crab_color.jpg  base colour, 2048 x 2048
  crab_normal.jpg tangent-space normal map, 2048 x 2048

The screensaver never parses glTF. The skeleton is evaluated here: the clip is sampled at
FRAMES evenly spaced times, and every joint's skinning matrix (joint world matrix x inverse bind
matrix) is stored per frame, already including a transform that centres the crab and scales it
to a bounding radius of 1 (y up, facing +z). Joints whose skinning matrix is the same in every
frame as another joint's (unanimated children follow their parent exactly) are merged, which
brings the palette under the 256 vertex-uniform vectors of older GLES 2 GPUs (Mali-450).

crab.bin, little-endian:
  char[4] 'CRB1'
  u32 vertexCount, u32 indexCount, u32 paletteSize, u32 frameCount
  f32 duration (seconds of one loop)
  f32 radius   (bounding radius over all frames, ~1)
  f32 centreY  (unused, 0)
  vertices: vertexCount x 32 bytes
     f32 x,y,z  bind-pose position (model space before skinning)
     i8  nx,ny,nz,0   normal (normalised by 127)
     i8  tx,ty,tz,tw  tangent, w = handedness
     u16 u,v          uv (normalised by 65535)
     u8  j0..j3       palette indices
     u8  w0..w3       weights (normalised by 255, sum 255)
  indices: indexCount x u16
  palette: frameCount x paletteSize x 12 f32 (rows of a 3x4 matrix)
"""

import io
import json
import os
import struct
import sys

import numpy as np
from PIL import Image

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.normpath(os.path.join(HERE, '..'))
SRC = sys.argv[1] if len(sys.argv) > 1 else os.path.join(REPO, 'crab.glb')
OUTS = [os.path.join(REPO, a, 'resources', 'model')
        for a in ('screensaver.spacecrab', 'screensaver.spacecrab.armv7')]
FRAMES = 48
TEX = 2048


def load(path):
    d = open(path, 'rb').read()
    assert d[:4] == b'glTF'
    jlen = struct.unpack('<I', d[12:16])[0]
    j = json.loads(d[20:20 + jlen])
    blen = struct.unpack('<I', d[20 + jlen:24 + jlen])[0]
    b = d[28 + jlen:28 + jlen + blen]
    return j, b


def accessor(j, b, i):
    a = j['accessors'][i]
    bv = j['bufferViews'][a['bufferView']]
    nc = {'SCALAR': 1, 'VEC2': 2, 'VEC3': 3, 'VEC4': 4, 'MAT4': 16}[a['type']]
    dt = {5126: np.float32, 5123: np.uint16, 5125: np.uint32, 5121: np.uint8}[a['componentType']]
    off = bv.get('byteOffset', 0) + a.get('byteOffset', 0)
    isz = np.dtype(dt).itemsize * nc
    st = bv.get('byteStride', 0)
    if st and st != isz:
        raw = np.frombuffer(b, np.uint8, count=st * a['count'], offset=off)
        raw = raw.reshape(a['count'], st)[:, :isz].copy()
        return raw.view(dt).reshape(a['count'], nc)
    return np.frombuffer(b, dt, count=a['count'] * nc, offset=off).reshape(a['count'], nc).copy()


def quat_mat(q):
    x, y, z, w = q
    return np.array([
        [1 - 2 * (y * y + z * z), 2 * (x * y - z * w), 2 * (x * z + y * w)],
        [2 * (x * y + z * w), 1 - 2 * (x * x + z * z), 2 * (y * z - x * w)],
        [2 * (x * z - y * w), 2 * (y * z + x * w), 1 - 2 * (x * x + y * y)]])


def slerp(a, b, t):
    d = float(np.dot(a, b))
    if d < 0:
        b, d = -b, -d
    if d > 0.9995:
        r = a + (b - a) * t
    else:
        th = np.arccos(d)
        r = (np.sin((1 - t) * th) * a + np.sin(t * th) * b) / np.sin(th)
    return r / np.linalg.norm(r)


def trs(t, r, s):
    m = np.eye(4)
    m[:3, :3] = quat_mat(r) * np.asarray(s)[None, :]
    m[:3, 3] = t
    return m


def main():
    j, b = load(SRC)
    nodes = j['nodes']
    prim = j['meshes'][0]['primitives'][0]
    A = prim['attributes']
    pos = accessor(j, b, A['POSITION']).astype(np.float32)
    nrm = accessor(j, b, A['NORMAL']).astype(np.float32)
    tan = accessor(j, b, A['TANGENT']).astype(np.float32)
    uv = accessor(j, b, A['TEXCOORD_0']).astype(np.float32)
    jnt = accessor(j, b, A['JOINTS_0']).astype(np.int64)
    wgt = accessor(j, b, A['WEIGHTS_0']).astype(np.float32)
    idx = accessor(j, b, prim['indices']).ravel()
    assert pos.shape[0] < 65536

    skin = j['skins'][0]
    joints = skin['joints']
    ibm = accessor(j, b, skin['inverseBindMatrices']).reshape(-1, 4, 4).transpose(0, 2, 1)

    parent = {}
    for i, n in enumerate(nodes):
        for c in n.get('children', []):
            parent[c] = i

    def rest(i):
        n = nodes[i]
        if 'matrix' in n:
            return None
        return (np.array(n.get('translation', [0, 0, 0]), float),
                np.array(n.get('rotation', [0, 0, 0, 1]), float),
                np.array(n.get('scale', [1, 1, 1]), float))

    anim = j['animations'][0]
    chans = {}
    for c in anim['channels']:
        s = anim['samplers'][c['sampler']]
        times = accessor(j, b, s['input']).ravel()
        vals = accessor(j, b, s['output']).astype(float)
        chans[(c['target']['node'], c['target']['path'])] = (times, vals)
    duration = max(t[-1] for t, _ in chans.values())

    def sample(key, t, default):
        if key not in chans:
            return default
        times, vals = chans[key]
        if t <= times[0]:
            return vals[0]
        if t >= times[-1]:
            return vals[-1]
        k = int(np.searchsorted(times, t) - 1)
        f = (t - times[k]) / (times[k + 1] - times[k])
        if key[1] == 'rotation':
            return slerp(vals[k], vals[k + 1], f)
        return vals[k] * (1 - f) + vals[k + 1] * f

    def local(i, t):
        n = nodes[i]
        if 'matrix' in n:
            return np.array(n['matrix'], float).reshape(4, 4).T
        T, R, S = rest(i)
        return trs(sample((i, 'translation'), t, T), sample((i, 'rotation'), t, R),
                   sample((i, 'scale'), t, S))

    def world(i, t, cache):
        if i in cache:
            return cache[i]
        m = local(i, t)
        if i in parent:
            m = world(parent[i], t, cache) @ m
        cache[i] = m
        return m

    # The clip's last key equals its first, so frames sample [0, duration) and wrap.
    times = [duration * k / FRAMES for k in range(FRAMES)]
    pal = np.zeros((FRAMES, len(joints), 4, 4))
    for f, t in enumerate(times):
        cache = {}
        for k, ji in enumerate(joints):
            pal[f, k] = world(ji, t, cache) @ ibm[k]

    # Skin every frame to find the bounds (and to check the merge below changes nothing).
    def skin_frame(P, f):
        M = P[f][jnt]                      # (V, 4, 4, 4)
        Mb = np.einsum('vk,vkab->vab', wgt, M)
        return np.einsum('vab,vb->va', Mb[:, :3, :3], pos) + Mb[:, :3, 3]

    allp = np.concatenate([skin_frame(pal, f) for f in range(0, FRAMES, 4)])
    lo, hi = allp.min(0), allp.max(0)
    centre = (lo + hi) / 2
    radius = float(np.linalg.norm(allp - centre, axis=1).max())
    print('bounds', lo, hi, 'radius', radius)

    # Centre and scale to radius 1. The model's head already looks along +z.
    N = np.eye(4)
    N[:3, :3] /= radius
    N[:3, 3] = -centre / radius
    pal = np.einsum('ab,fjbc->fjac', N, pal)

    # Merge joints whose matrices agree in every frame.
    used = sorted(set(np.unique(jnt[wgt > 0]).tolist()))
    uniq, remap = [], {}
    for k in used:
        for u_i, u in enumerate(uniq):
            if np.abs(pal[:, k] - pal[:, u]).max() < 1e-5:
                remap[k] = u_i
                break
        else:
            remap[k] = len(uniq)
            uniq.append(k)
    print('joints', len(joints), 'used', len(used), 'palette', len(uniq))
    assert len(uniq) <= 80, 'palette too large for GLES 2 uniforms'
    newpal = pal[:, uniq][:, :, :3, :]          # (F, P, 3, 4)

    # Vertex weights: fold merged joints, keep the top four, quantise to sum 255.
    V = pos.shape[0]
    J8 = np.zeros((V, 4), np.uint8)
    W8 = np.zeros((V, 4), np.uint8)
    for v in range(V):
        acc = {}
        for k in range(4):
            if wgt[v, k] > 0:
                p = remap[int(jnt[v, k])]
                acc[p] = acc.get(p, 0.0) + float(wgt[v, k])
        items = sorted(acc.items(), key=lambda x: -x[1])[:4]
        tot = sum(w for _, w in items)
        q = [int(round(255 * w / tot)) for _, w in items]
        q[0] += 255 - sum(q)
        for k, (p, _) in enumerate(items):
            J8[v, k] = p
            W8[v, k] = q[k]

    # Check: the merged, quantised skin matches the original within a hair.
    def skin_new(f):
        M = np.concatenate([newpal[f], np.tile([[[0, 0, 0, 1]]], (len(uniq), 1, 1))], 1)[J8]
        Mb = np.einsum('vk,vkab->vab', W8 / 255.0, M)
        return np.einsum('vab,vb->va', Mb[:, :3, :3], pos) + Mb[:, :3, 3]
    for f in (0, FRAMES // 3):
        ref = (skin_frame(pal, f))
        err = np.abs(skin_new(f) - ref).max()
        print('frame', f, 'max skin error', err)
        assert err < 0.01

    def i8(a):
        return np.clip(np.round(a * 127), -127, 127).astype(np.int8)

    n4 = np.concatenate([nrm / np.linalg.norm(nrm, axis=1, keepdims=True), np.zeros((V, 1))], 1)
    t3 = tan[:, :3] / np.maximum(np.linalg.norm(tan[:, :3], axis=1, keepdims=True), 1e-8)
    t4 = np.concatenate([t3, np.sign(tan[:, 3:4]) + (tan[:, 3:4] == 0)], 1)
    uv16 = np.clip(np.round(uv * 65535), 0, 65535).astype(np.uint16)

    vt = np.dtype([('p', '<f4', 3), ('n', 'i1', 4), ('t', 'i1', 4), ('uv', '<u2', 2),
                   ('j', 'u1', 4), ('w', 'u1', 4)])
    verts = np.zeros(V, vt)
    verts['p'] = pos
    verts['n'] = i8(n4)
    verts['t'] = i8(t4)
    verts['uv'] = uv16
    verts['j'] = J8
    verts['w'] = W8
    assert vt.itemsize == 32

    blob = io.BytesIO()
    blob.write(b'CRB1')
    blob.write(struct.pack('<4I3f', V, len(idx), len(uniq), FRAMES, duration, 1.0, 0.0))
    blob.write(verts.tobytes())
    blob.write(idx.astype('<u2').tobytes())
    blob.write(newpal.astype('<f4').tobytes())

    # Textures.
    def image(tex_index):
        im = j['images'][j['textures'][tex_index]['source']]
        bv = j['bufferViews'][im['bufferView']]
        o = bv.get('byteOffset', 0)
        return Image.open(io.BytesIO(b[o:o + bv['byteLength']])).convert('RGB')

    mat = j['materials'][0]
    color = image(mat['pbrMetallicRoughness']['baseColorTexture']['index'])
    normal = image(mat['normalTexture']['index'])
    color = color.resize((TEX, TEX), Image.LANCZOS)
    normal = normal.resize((TEX, TEX), Image.LANCZOS)

    for out in OUTS:
        os.makedirs(out, exist_ok=True)
        with open(os.path.join(out, 'crab.bin'), 'wb') as fh:
            fh.write(blob.getvalue())
        color.save(os.path.join(out, 'crab_color.jpg'), quality=90, optimize=True)
        normal.save(os.path.join(out, 'crab_normal.jpg'), quality=94, optimize=True)
        print('wrote', out)


if __name__ == '__main__':
    main()
