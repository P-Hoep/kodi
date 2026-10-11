"""A minimal pure-Python PNG reader and writer (8-bit images), for small images only.

Kodi on Android has no imaging library; the cloud overlay is a few hundred pixels wide,
so decoding it in Python is cheap enough."""

import struct
import zlib

SIGNATURE = b'\x89PNG\r\n\x1a\n'
CHANNELS = {0: 1, 2: 3, 3: 1, 4: 2, 6: 4}  # colour type -> samples per pixel


def _paeth(a, b, c):
    p = a + b - c
    pa, pb, pc = abs(p - a), abs(p - b), abs(p - c)
    if pa <= pb and pa <= pc:
        return a
    return b if pb <= pc else c


def decode(data):
    """-> (width, height, pixels) with pixels a list of (r, g, b, a) tuples, row by row."""
    if not data.startswith(SIGNATURE):
        raise ValueError('not a PNG')
    i = len(SIGNATURE)
    idat = []
    palette = trns = None
    width = height = depth = ctype = None
    while i + 8 <= len(data):
        length, kind = struct.unpack('>I4s', data[i:i + 8])
        body = data[i + 8:i + 8 + length]
        if kind == b'IHDR':
            width, height, depth, ctype, _comp, _filt, interlace = struct.unpack('>IIBBBBB', body)
            if depth != 8 or interlace or ctype not in CHANNELS:
                raise ValueError('unsupported PNG (depth %s, type %s, interlace %s)' % (depth, ctype, interlace))
        elif kind == b'PLTE':
            palette = [tuple(body[p:p + 3]) for p in range(0, len(body) - 2, 3)]
        elif kind == b'tRNS':
            trns = body
        elif kind == b'IDAT':
            idat.append(body)
        elif kind == b'IEND':
            break
        i += 12 + length
    raw = zlib.decompress(b''.join(idat))
    bpp = CHANNELS[ctype]
    stride = width * bpp
    prev = bytearray(stride)
    pixels = []
    pos = 0
    for _y in range(height):
        ftype = raw[pos]
        line = bytearray(raw[pos + 1:pos + 1 + stride])
        pos += 1 + stride
        if ftype == 1:
            for x in range(bpp, stride):
                line[x] = (line[x] + line[x - bpp]) & 0xFF
        elif ftype == 2:
            for x in range(stride):
                line[x] = (line[x] + prev[x]) & 0xFF
        elif ftype == 3:
            for x in range(stride):
                left = line[x - bpp] if x >= bpp else 0
                line[x] = (line[x] + ((left + prev[x]) >> 1)) & 0xFF
        elif ftype == 4:
            for x in range(stride):
                left = line[x - bpp] if x >= bpp else 0
                upleft = prev[x - bpp] if x >= bpp else 0
                line[x] = (line[x] + _paeth(left, prev[x], upleft)) & 0xFF
        prev = line
        for x in range(0, stride, bpp):
            if ctype == 0:
                v = line[x]
                pixels.append((v, v, v, 0 if trns and len(trns) >= 2 and v == trns[1] else 255))
            elif ctype == 4:
                v = line[x]
                pixels.append((v, v, v, line[x + 1]))
            elif ctype == 2:
                pixels.append((line[x], line[x + 1], line[x + 2], 255))
            elif ctype == 6:
                pixels.append((line[x], line[x + 1], line[x + 2], line[x + 3]))
            else:  # palette
                idx = line[x]
                r, g, b = palette[idx]
                pixels.append((r, g, b, trns[idx] if trns and idx < len(trns) else 255))
    return width, height, pixels


def encode_rgba(width, height, pixels):
    """RGBA pixels (list of 4-tuples, row by row) -> PNG bytes."""
    raw = bytearray()
    for y in range(height):
        raw.append(0)
        for r, g, b, a in pixels[y * width:(y + 1) * width]:
            raw.extend((r, g, b, a))

    def chunk(kind, body):
        return struct.pack('>I4s', len(body), kind) + body + struct.pack('>I', zlib.crc32(kind + body) & 0xFFFFFFFF)
    return (SIGNATURE + chunk(b'IHDR', struct.pack('>IIBBBBB', width, height, 8, 6, 0, 0, 0))
            + chunk(b'IDAT', zlib.compress(bytes(raw), 6)) + chunk(b'IEND', b''))
