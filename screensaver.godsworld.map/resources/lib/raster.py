"""Pixels in pure Python: PNG reading and writing, and whole-image operations. No Kodi imports.

Kodi on Android has no imaging library, so every per-pixel step here is arranged to run
inside C: bytes slicing with strides, bytes.translate, zlib, and map() over array('I').
RGBA images are kept either as bytearrays (4 bytes per pixel) or as array('I') with one
32-bit word per pixel (R in the low byte on little-endian machines), which lets a lookup
table move whole pixels at once: array('I', map(src.__getitem__, lut)).
"""

import struct
import sys
import zlib
from array import array
from itertools import accumulate, repeat
from operator import add

SIGNATURE = b'\x89PNG\r\n\x1a\n'
CHANNELS = {0: 1, 2: 3, 3: 1, 4: 2, 6: 4}  # colour type -> samples per pixel
LITTLE = sys.byteorder == 'little'


class Raster(object):
    """w x h pixels, `channels` bytes each (1 = grey/index, 4 = RGBA), row by row."""

    def __init__(self, w, h, channels, data):
        self.w, self.h, self.channels = w, h, channels
        self.data = data

    def words(self):
        """RGBA as array('I') plus one transparent word at the end (the 'no data' index)."""
        assert self.channels == 4
        out = array('I')
        out.frombytes(bytes(self.data))
        if not LITTLE:
            out.byteswap()
        out.append(0)
        return out


# ---------------------------------------------------------------- PNG reading

def _chunks(data):
    if not data.startswith(SIGNATURE):
        raise ValueError('not a PNG')
    i = len(SIGNATURE)
    while i + 8 <= len(data):
        length, kind = struct.unpack('>I4s', data[i:i + 8])
        yield kind, data[i + 8:i + 8 + length]
        if kind == b'IEND':
            return
        i += 12 + length


def _unfilter(raw, h, stride, bpp):
    """Undo PNG row filters. Filter 0 rows are plain slices; Sub and Up use C-level map and
    accumulate; Average and Paeth fall back to a Python loop (slow, but rare in our sources)."""
    step = stride + 1
    if all(raw[y * step] == 0 for y in range(h)):
        return b''.join(raw[y * step + 1:(y + 1) * step] for y in range(h))
    out = bytearray(stride * h)
    prev = bytes(stride)
    for y in range(h):
        ftype = raw[y * step]
        line = bytearray(raw[y * step + 1:(y + 1) * step])
        if ftype == 1:
            for c in range(bpp):
                line[c::bpp] = bytes(map(int.__and__, accumulate(line[c::bpp], add), repeat(255)))
        elif ftype == 2:
            line = bytearray(map(int.__and__, map(add, line, prev), repeat(255)))
        elif ftype == 3:
            for x in range(stride):
                left = line[x - bpp] if x >= bpp else 0
                line[x] = (line[x] + ((left + prev[x]) >> 1)) & 0xFF
        elif ftype == 4:
            for x in range(stride):
                a = line[x - bpp] if x >= bpp else 0
                b = prev[x]
                c = prev[x - bpp] if x >= bpp else 0
                p = a + b - c
                pa, pb, pc = abs(p - a), abs(p - b), abs(p - c)
                pred = a if pa <= pb and pa <= pc else (b if pb <= pc else c)
                line[x] = (line[x] + pred) & 0xFF
        out[y * stride:(y + 1) * stride] = line
        prev = line
    return bytes(out)


def _unpack_bits(data, w, h, depth):
    """Palette/grey images with 1, 2 or 4 bits per pixel -> one byte per pixel."""
    per = 8 // depth
    mask = (1 << depth) - 1
    stride = (w * depth + 7) // 8
    table = [bytes((b >> (8 - depth * (k + 1))) & mask for k in range(per)) for b in range(256)]
    out = bytearray()
    for y in range(h):
        row = b''.join(table[b] for b in data[y * stride:(y + 1) * stride])
        out += row[:w]
    return bytes(out)


def decode(data, want=4):
    """PNG bytes -> Raster with `want` channels: 4 (RGBA) or 1 (first channel / palette index)."""
    width = height = depth = ctype = None
    palette = trns = None
    idat = []
    for kind, body in _chunks(data):
        if kind == b'IHDR':
            width, height, depth, ctype, _c, _f, interlace = struct.unpack('>IIBBBBB', body)
            if interlace or ctype not in CHANNELS or (depth != 8 and not (ctype in (0, 3) and depth < 8)):
                raise ValueError('unsupported PNG (depth %s, type %s, interlace %s)' % (depth, ctype, interlace))
        elif kind == b'PLTE':
            palette = body
        elif kind == b'tRNS':
            trns = body
        elif kind == b'IDAT':
            idat.append(body)
    raw = zlib.decompress(b''.join(idat))
    n = width * height
    if depth < 8:
        stride = (width * depth + 7) // 8
        pix = _unpack_bits(_unfilter(raw, height, stride, 1), width, height, depth)
        if ctype == 0:  # scale grey levels up to 0-255
            scale = 255 // ((1 << depth) - 1)
            pix = pix.translate(bytes(min(255, i * scale) for i in range(256)))
    else:
        bpp = CHANNELS[ctype]
        pix = _unfilter(raw, height, width * bpp, bpp)
    if want == 1:
        if ctype in (0, 3):
            return Raster(width, height, 1, bytearray(pix))
        return Raster(width, height, 1, bytearray(pix[0::CHANNELS[ctype]]))
    out = bytearray(b'\xff') * (4 * n)
    if ctype == 6:
        out[:] = pix
    elif ctype == 2:
        for c in range(3):
            out[c::4] = pix[c::3]
    elif ctype == 0:
        for c in range(3):
            out[c::4] = pix
    elif ctype == 4:
        for c in range(3):
            out[c::4] = pix[0::2]
        out[3::4] = pix[1::2]
    else:  # palette
        pal = palette + bytes(768 - len(palette))
        for c in range(3):
            out[c::4] = pix.translate(bytes(pal[c::3]))
        if trns:
            alpha = bytes(trns) + b'\xff' * (256 - len(trns))
            out[3::4] = pix.translate(alpha)
    return Raster(width, height, 4, out)


def read(path, want=4):
    with open(path, 'rb') as handle:
        return decode(handle.read(), want)


# ---------------------------------------------------------------- PNG writing

def _chunk(kind, body):
    return struct.pack('>I4s', len(body), kind) + body + struct.pack('>I', zlib.crc32(kind + body) & 0xFFFFFFFF)


def _rows(raw, h, stride):
    zero = b'\x00'
    return b''.join(zero + raw[y * stride:(y + 1) * stride] for y in range(h))


def encode_rgba(w, h, raw, level=1):
    """RGBA bytes -> PNG bytes (unfiltered rows; level 1 is fast and good enough here)."""
    return (SIGNATURE + _chunk(b'IHDR', struct.pack('>IIBBBBB', w, h, 8, 6, 0, 0, 0))
            + _chunk(b'IDAT', zlib.compress(_rows(raw, h, w * 4), level)) + _chunk(b'IEND', b''))


def encode_words(w, h, words, level=1):
    """array('I') RGBA words (exactly w * h of them) -> PNG bytes."""
    if not LITTLE:
        words = array('I', words)
        words.byteswap()
    return encode_rgba(w, h, words.tobytes(), level)


def encode_indexed(w, h, raw, palette, transparent=(), level=6):
    """One byte per pixel plus a palette of (r, g, b) -> PNG bytes. Indexes listed in
    `transparent` are fully transparent."""
    plte = b''.join(bytes(c) for c in palette)
    out = SIGNATURE + _chunk(b'IHDR', struct.pack('>IIBBBBB', w, h, 8, 3, 0, 0, 0)) + _chunk(b'PLTE', plte)
    if transparent:
        trns = bytearray(b'\xff' * (max(transparent) + 1))
        for i in transparent:
            trns[i] = 0
        out += _chunk(b'tRNS', bytes(trns))
    return out + _chunk(b'IDAT', zlib.compress(_rows(raw, h, w), level)) + _chunk(b'IEND', b'')


def write(path, data):
    tmp = path + '.tmp'
    with open(tmp, 'wb') as handle:
        handle.write(data)
    import os
    os.replace(tmp, path)


# ---------------------------------------------------------------- whole-image operations

def roll_words(words, w, h, shift):
    """Rotate every row of an array('I') image left by `shift` pixels (keeps the sentinel)."""
    shift %= w
    if not shift:
        return words
    out = array('I')
    for y in range(h):
        start = y * w
        out.extend(words[start + shift:start + w])
        out.extend(words[start:start + shift])
    out.append(words[w * h] if len(words) > w * h else 0)
    return out


def upsample2(data, w, h, channels):
    """Double a raster in both directions by repeating pixels."""
    row_out = bytearray(w * 2 * channels)
    out = bytearray()
    stride = w * channels
    for y in range(h):
        row = data[y * stride:(y + 1) * stride]
        for c in range(channels):
            row_out[c::2 * channels] = row[c::channels]
            row_out[channels + c::2 * channels] = row[c::channels]
        out += row_out
        out += row_out
    return out


def pair_map(a, b, table):
    """Per-byte f(a, b) for two equal-length byte strings, via a 65536-entry table indexed
    by a | b << 8. Runs in C apart from map() itself."""
    pair = bytearray(len(a) * 2)
    if LITTLE:
        pair[0::2], pair[1::2] = a, b
    else:
        pair[1::2], pair[0::2] = a, b
    idx = array('H')
    idx.frombytes(bytes(pair))
    return bytes(map(table.__getitem__, idx))


def pair_table(fn):
    """65536-byte table for pair_map: entry a | b << 8 = fn(a, b) clamped to 0-255."""
    out = bytearray(65536)
    for b in range(256):
        base = b << 8
        for a in range(256):
            v = fn(a, b)
            out[base | a] = 0 if v < 0 else (255 if v > 255 else int(v))
    return bytes(out)


def scale_table(k, offset=0.0):
    return bytes(max(0, min(255, int(i * k + offset + 0.5))) for i in range(256))
