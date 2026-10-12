"""Build Couchstronomy's bundled data in screensaver.couchstronomy/resources/data.

  python3 tools/make_couch_data.py          # needs Pillow and numpy; downloads once into tools/.couch-cache

Sources (see the add-on's LICENSE.txt for the notices):
  stars           HYG database v4.1 (Hipparcos, Yale, Gliese), CC BY-SA 4.0, astronexus
  constellations  d3-celestial (lines, boundaries, name positions), BSD-3, Olaf Frohn
  deep sky        d3-celestial messier.json, dsos.bright.json, dsonames.json, BSD-3
  planets         VSOP87B (Bretagnon & Francou) as packaged by astronomia, MIT
  Moon texture    NASA Scientific Visualization Studio, CGI Moon Kit (LRO LROC colour map)

Outputs:
  stars.bin / stars.json   J2000 unit vectors, proper-motion vectors, V magnitude, B-V,
                           float32 columns, sorted brightest first; names and designations
  sky.json                 constellations, boundaries, deep-sky objects
  vsop87.json              truncated VSOP87B series
  moon.bin                 256x256 orthographic near side, grey + alpha
"""

import csv
import json
import math
import os
import re
import struct
import sys
import zlib
import urllib.request
from array import array

import numpy as np
from PIL import Image

HERE = os.path.dirname(os.path.abspath(__file__))
ADDON = os.path.normpath(os.path.join(HERE, '..', 'screensaver.couchstronomy'))
OUT = os.path.join(ADDON, 'resources', 'data')
CACHE = os.path.join(HERE, '.couch-cache')
sys.path.insert(0, ADDON)

from resources.lib import astro  # noqa: E402

D3 = 'https://raw.githubusercontent.com/ofrohn/d3-celestial/master/data/'
ASTRONOMIA = 'https://raw.githubusercontent.com/commenthol/astronomia/master/data/'
SOURCES = {
    'hygdata_v41.csv': 'https://raw.githubusercontent.com/astronexus/HYG-Database/main/hyg/CURRENT/hygdata_v41.csv',
    'moon_color_1k.jpg': 'https://svs.gsfc.nasa.gov/vis/a000000/a004700/a004720/lroc_color_poles_1k.jpg',
}
for _name in ('constellations.lines.json', 'constellations.json', 'constellations.borders.json',
              'messier.json', 'dsos.bright.json', 'dsonames.json'):
    SOURCES[_name] = D3 + _name
for _planet in ('mercury', 'venus', 'earth', 'mars', 'jupiter', 'saturn', 'uranus', 'neptune'):
    SOURCES['vsop87B%s.js' % _planet] = ASTRONOMIA + 'vsop87B%s.js' % _planet

STAR_LIMIT = 8.0          # faintest magnitude bundled
NAME_LIMIT = 6.5          # Bayer/Flamsteed designations kept down to this magnitude
MAS = math.pi / 180.0 / 3600.0 / 1000.0

GREEK = {'Alp': 'α', 'Bet': 'β', 'Gam': 'γ', 'Del': 'δ', 'Eps': 'ε', 'Zet': 'ζ', 'Eta': 'η', 'The': 'θ',
         'Iot': 'ι', 'Kap': 'κ', 'Lam': 'λ', 'Mu': 'μ', 'Nu': 'ν', 'Xi': 'ξ', 'Omi': 'ο', 'Pi': 'π',
         'Rho': 'ρ', 'Sig': 'σ', 'Tau': 'τ', 'Ups': 'υ', 'Phi': 'φ', 'Chi': 'χ', 'Psi': 'ψ', 'Ome': 'ω'}


def fetch(name):
    path = os.path.join(CACHE, name)
    if not os.path.exists(path):
        os.makedirs(CACHE, exist_ok=True)
        print('downloading', SOURCES[name])
        req = urllib.request.Request(SOURCES[name], headers={'User-Agent': 'couchstronomy-build'})
        data = urllib.request.urlopen(req, timeout=120).read()
        with open(path + '.tmp', 'wb') as handle:
            handle.write(data)
        os.replace(path + '.tmp', path)
    return path


def load_json(name):
    with open(fetch(name), encoding='utf-8') as handle:
        return json.load(handle)


# ---------------------------------------------------------------- stars

def bayer_label(bayer, flam, con):
    """'α Lyr', 'ε¹ Lyr' (HYG writes 'Eps-1'), '61 Cyg' or ''."""
    if bayer:
        base, _, num = bayer.partition('-')
        letter = GREEK.get(base, base)
        sup = ''.join('⁰¹²³⁴⁵⁶⁷⁸⁹'[int(c)] for c in num if c.isdigit())
        return '%s%s %s' % (letter, sup, con)
    if flam:
        return '%s %s' % (flam, con)
    return ''


def build_stars():
    rows = []
    with open(fetch('hygdata_v41.csv'), encoding='utf-8') as handle:
        for r in csv.DictReader(handle):
            if r['proper'] == 'Sol' or not r['mag']:
                continue
            mag = float(r['mag'])
            if mag > STAR_LIMIT:
                continue
            rows.append((mag, r))
    rows.sort(key=lambda item: item[0])
    cols = [array('f') for _ in range(8)]   # x y z vx vy vz mag bv
    names = []
    for i, (mag, r) in enumerate(rows):
        ra = float(r['ra']) * 15.0 * astro.DEG
        dec = float(r['dec']) * astro.DEG
        pmra = float(r['pmra'] or 0.0)
        pmdec = float(r['pmdec'] or 0.0)
        if abs(pmra) >= 9999 or abs(pmdec) >= 9999:   # HYG's placeholder for "unknown"
            pmra = pmdec = 0.0
        ca, sa, cd, sd = math.cos(ra), math.sin(ra), math.cos(dec), math.sin(dec)
        u = (cd * ca, cd * sa, sd)
        # HYG's pmra is mu_alpha * cos(dec), in mas/yr.
        ea = (-sa, ca, 0.0)
        ed = (-sd * ca, -sd * sa, cd)
        v = tuple(pmra * MAS * ea[k] + pmdec * MAS * ed[k] for k in range(3))
        bv = float(r['ci']) if r['ci'] else 0.6
        for k, value in enumerate(u + v + (mag, bv)):
            cols[k].append(value)
        proper = r['proper']
        desig = bayer_label(r['bayer'], r['flam'], r['con'])
        if proper or (desig and mag <= NAME_LIMIT):
            dist = float(r['dist'] or 0)
            names.append([i, proper, desig, r['con'], round(dist * 3.26156, 1) if 0 < dist < 100000 else None,
                          int(r['hip']) if r['hip'] else None, r['spect'], r['var'] or ''])
    blob = b''.join(c.tobytes() for c in cols)
    with open(os.path.join(OUT, 'stars.bin'), 'wb') as handle:
        handle.write(blob)
    meta = {'count': len(rows), 'columns': ['x', 'y', 'z', 'vx', 'vy', 'vz', 'mag', 'bv'], 'type': 'float32-le',
            'epoch': 2000.0, 'limit': STAR_LIMIT, 'names': names,
            'source': 'HYG database v4.1 (CC BY-SA 4.0), github.com/astronexus/HYG-Database'}
    with open(os.path.join(OUT, 'stars.json'), 'w', encoding='utf-8') as handle:
        json.dump(meta, handle, ensure_ascii=False, separators=(',', ':'))
    print('stars: %d (mag <= %.1f), %d named, %.0f KB' % (len(rows), STAR_LIMIT, len(names), len(blob) / 1024.0))


# ---------------------------------------------------------------- constellations and deep sky

def r4(x):
    return round(x, 4)


def build_sky():
    lines = load_json('constellations.lines.json')
    info = {f['id']: f for f in load_json('constellations.json')['features']}
    cons = []
    for f in lines['features']:
        cid = f['id']
        meta = info.get(cid, {})
        props = meta.get('properties', {})
        label = meta.get('geometry', {}).get('coordinates', [0, 0])
        polylines = [[[r4(p[0] % 360.0), r4(p[1])] for p in line] for line in f['geometry']['coordinates']]
        cons.append({'id': cid, 'name': props.get('name', cid), 'gen': props.get('gen', ''),
                     'rank': int(props.get('rank', 3)), 'label': [r4(label[0] % 360.0), r4(label[1])],
                     'lines': polylines})
    borders = []
    for f in load_json('constellations.borders.json')['features']:
        for line in f['geometry']['coordinates']:
            borders.append([[r4(p[0] % 360.0), r4(p[1])] for p in line])

    names = load_json('dsonames.json')
    dsos = []
    seen = set()
    for f in load_json('messier.json')['features']:
        p = f['properties']
        lon, lat = f['geometry']['coordinates']
        dsos.append(dso_entry(p['name'], p.get('desig', ''), p.get('alt', ''), p['type'], p['mag'], p['dim'],
                              lon, lat))
        seen.add(p.get('desig', ''))
        seen.add(p['name'])
    for f in load_json('dsos.bright.json')['features']:
        p = f['properties']
        # The bright list spells Messier objects 'M 16'; those are already in.
        if p['desig'] in seen or p['desig'].replace(' ', '') in seen or p['type'] == 'pos':
            continue
        lon, lat = f['geometry']['coordinates']
        alt = names.get(f['id'], {}).get('name', '') if isinstance(names.get(f['id']), dict) else ''
        dsos.append(dso_entry(p['desig'], '', alt, p['type'], p['mag'], p['dim'], lon, lat))
    out = {'constellations': cons, 'borders': borders, 'dsos': dsos,
           'source': 'd3-celestial (BSD-3-Clause), Olaf Frohn; Messier and NGC/IC catalogues'}
    with open(os.path.join(OUT, 'sky.json'), 'w', encoding='utf-8') as handle:
        json.dump(out, handle, ensure_ascii=False, separators=(',', ':'))
    print('constellations: %d, boundary lines: %d, deep-sky objects: %d' % (len(cons), len(borders), len(dsos)))


def dso_entry(name, desig, alt, kind, mag, dim, lon, lat):
    major = minor = 0.0
    nums = [float(x) for x in re.findall(r'[\d.]+', str(dim))]
    if nums:
        major = nums[0]
        minor = nums[1] if len(nums) > 1 else nums[0]
    try:
        mag = float(mag)
    except (TypeError, ValueError):
        mag = 99.0
    if mag >= 99:
        mag = None
    return {'name': name, 'desig': desig, 'alt': alt, 'type': kind, 'mag': mag,
            'size': [major, minor], 'ra': r4(lon % 360.0), 'dec': r4(lat)}


# ---------------------------------------------------------------- VSOP87

def parse_vsop(name):
    text = open(fetch(name), encoding='utf-8').read()
    out = {}
    for coord in 'LBR':
        block = re.search(r'\b%s: \{(.*?)\n  \}' % coord, text, re.S).group(1)
        powers = []
        for m in re.finditer(r'"(\d)": \[(.*?)\n    \]', block, re.S):
            terms = [[float(a), float(b), float(c)] for a, b, c in
                     re.findall(r'\[([-\deE.+]+), ([-\deE.+]+), ([-\deE.+]+)\]', m.group(2))]
            powers.append((int(m.group(1)), terms))
        powers.sort()
        out[coord] = [terms for _p, terms in powers]
    return out


def truncate(series, eps, tau_max=0.15):
    """Keep terms whose size over +-150 years (tau_max millennia) exceeds eps."""
    out = []
    for a, terms in enumerate(series):
        k = tau_max ** a
        out.append([t for t in terms if abs(t[0]) * k >= eps])
    while out and not out[-1]:
        out.pop()
    return out


def build_vsop(eps=2e-8):
    full, short = {}, {}
    for planet in ('mercury', 'venus', 'earth', 'mars', 'jupiter', 'saturn', 'uranus', 'neptune'):
        s = parse_vsop('vsop87B%s.js' % planet)
        full[planet] = s
        rmean = s['R'][0][0][0]
        short[planet] = {'L': truncate(s['L'], eps), 'B': truncate(s['B'], eps), 'R': truncate(s['R'], eps * rmean)}
    for planet in full:
        n_full = sum(len(t) for c in 'LBR' for t in full[planet][c])
        n_short = sum(len(t) for c in 'LBR' for t in short[planet][c])
        print('  %-8s %5d of %5d terms' % (planet, n_short, n_full))
    with open(os.path.join(OUT, 'vsop87.json'), 'w') as handle:
        json.dump(short, handle, separators=(',', ':'))
    print('vsop87: %.0f KB' % (os.path.getsize(os.path.join(OUT, 'vsop87.json')) / 1024.0))
    return full


def check_vsop(full):
    """Largest geocentric difference, truncated vs full series, 1950-2100 (arcseconds)."""
    from resources.lib import vsop87
    vsop87._series = None
    worst = {}
    for year in range(1950, 2101, 3):
        jd = astro.J2000 + (year - 2000) * 365.25 + 17.3 * year % 365
        vsop87._series = full
        e_full = vsop87.helio('earth', jd)
        p_full = {p: vsop87.helio(p, jd) for p in full if p != 'earth'}
        vsop87._series = None
        e = vsop87.helio('earth', jd)
        for planet, pf in p_full.items():
            g1 = astro.sub(pf, e_full)
            g2 = astro.sub(vsop87.helio(planet, jd), e)
            worst[planet] = max(worst.get(planet, 0), astro.angle(g1, g2) / astro.ARCSEC)
        sun = astro.angle(astro.scale(e_full, -1), astro.scale(e, -1)) / astro.ARCSEC
        worst['sun'] = max(worst.get('sun', 0), sun)
    print('  truncation error (arcsec): ' + ', '.join('%s %.2f' % kv for kv in sorted(worst.items())))


# ---------------------------------------------------------------- Moon

def build_moon(size=256):
    src = np.asarray(Image.open(fetch('moon_color_1k.jpg')).convert('L'), dtype=np.float32)
    h, w = src.shape
    yy, xx = np.mgrid[0:size, 0:size]
    x = (xx + 0.5) / size * 2 - 1
    y = 1 - (yy + 0.5) / size * 2
    r2 = x * x + y * y
    inside = r2 <= 1.0
    z = np.sqrt(np.clip(1 - r2, 0, 1))
    lat = np.arcsin(np.clip(y, -1, 1))
    lon = np.arctan2(x, z)        # near side centred on longitude 0
    u = ((lon / (2 * math.pi) + 0.5) * w).astype(int) % w
    v = np.clip(((0.5 - lat / math.pi) * h).astype(int), 0, h - 1)
    img = np.where(inside, src[v, u], 0)
    # The colour map is albedo only. Stretch it a little so the maria read at TV sizes.
    img = np.clip((img - 40) * 1.35 + 40, 0, 255)
    alpha = np.clip((1.0 - np.sqrt(r2)) * size / 2 + 0.5, 0, 1) * 255
    out = np.dstack([img, alpha]).astype(np.uint8)
    write_raw('moon.bin', size, size, 2, out)
    Image.fromarray(out, 'LA').save(os.path.join(CACHE, 'moon-preview.png'))
    print('moon: %dx%d' % (size, size))


def write_raw(name, w, h, channels, pixels):
    """'CSKY' + width, height, channels (uint16 each) + zlib of the raw 8-bit pixels: no
    PNG filters to undo, so loading is one zlib call even on a Fire TV."""
    body = zlib.compress(np.ascontiguousarray(pixels, dtype=np.uint8).tobytes(), 9)
    with open(os.path.join(OUT, name), 'wb') as handle:
        handle.write(b'CSKY' + struct.pack('<HHH', w, h, channels) + body)


def main():
    os.makedirs(OUT, exist_ok=True)
    build_stars()
    build_sky()
    full = build_vsop()
    check_vsop(full)
    build_moon()


if __name__ == '__main__':
    main()
