"""A small PNG reader and writer, so the app can compose its text without Pillow.

Kodi does not expose the skin's fonts to add-ons, so the app draws every string from the
Doto atlases under resources/media/fonts into plain RGBA PNGs and hands those to image
controls. That needs a decoder for the atlases (written by tools/make_vintageradar_media.py
with filter 0 only) and an encoder for the composed images. The decoder also copes with the
other filter types and the usual 8-bit colour types, so regenerating the media with a newer
Pillow cannot break the app.

No external modules: this has to run on Kodi's bundled CPython on Android, macOS and Linux.
"""

import struct
import zlib

_PNG_SIGNATURE = b'\x89PNG\r\n\x1a\n'


class PngError(Exception):
    pass


def decode(data):
    """Decode an 8-bit, non-interlaced PNG to (width, height, rgba bytearray)."""
    if not data.startswith(_PNG_SIGNATURE):
        raise PngError('not a PNG')
    pos = len(_PNG_SIGNATURE)
    header = None
    palette = None
    trns = None
    idat = []
    while pos + 8 <= len(data):
        length = struct.unpack('>I', data[pos:pos + 4])[0]
        kind = data[pos + 4:pos + 8]
        body = data[pos + 8:pos + 8 + length]
        pos += 12 + length
        if kind == b'IHDR':
            header = struct.unpack('>IIBBBBB', body[:13])
        elif kind == b'IDAT':
            idat.append(body)
        elif kind == b'PLTE':
            palette = body
        elif kind == b'tRNS':
            trns = body
        elif kind == b'IEND':
            break
    if header is None or not idat:
        raise PngError('missing IHDR or IDAT')
    width, height, depth, color_type, compression, filter_method, interlace = header
    if depth != 8:
        raise PngError('unsupported bit depth %d' % depth)
    if compression != 0 or filter_method != 0 or interlace != 0:
        raise PngError('unsupported PNG variant')
    channels = {0: 1, 2: 3, 3: 1, 4: 2, 6: 4}.get(color_type)
    if channels is None:
        raise PngError('unsupported colour type %d' % color_type)
    raw = zlib.decompress(b''.join(idat))
    stride = width * channels
    if len(raw) < height * (stride + 1):
        raise PngError('short image data')
    pixels = bytearray(height * stride)
    previous = bytearray(stride)
    offset = 0
    for y in range(height):
        kind = raw[offset]
        offset += 1
        line = bytearray(raw[offset:offset + stride])
        offset += stride
        if kind == 1:  # Sub
            for i in range(channels, stride):
                line[i] = (line[i] + line[i - channels]) & 0xFF
        elif kind == 2:  # Up
            for i in range(stride):
                line[i] = (line[i] + previous[i]) & 0xFF
        elif kind == 3:  # Average
            for i in range(stride):
                left = line[i - channels] if i >= channels else 0
                line[i] = (line[i] + ((left + previous[i]) >> 1)) & 0xFF
        elif kind == 4:  # Paeth
            for i in range(stride):
                left = line[i - channels] if i >= channels else 0
                up = previous[i]
                up_left = previous[i - channels] if i >= channels else 0
                p = left + up - up_left
                pa = abs(p - left)
                pb = abs(p - up)
                pc = abs(p - up_left)
                if pa <= pb and pa <= pc:
                    predictor = left
                elif pb <= pc:
                    predictor = up
                else:
                    predictor = up_left
                line[i] = (line[i] + predictor) & 0xFF
        elif kind != 0:
            raise PngError('bad filter %d' % kind)
        pixels[y * stride:(y + 1) * stride] = line
        previous = line
    return width, height, _to_rgba(pixels, width, height, color_type, palette, trns)


def _to_rgba(pixels, width, height, color_type, palette, trns):
    if color_type == 6:
        return pixels
    count = width * height
    out = bytearray(count * 4)
    if color_type == 2:
        for i in range(count):
            out[i * 4:i * 4 + 3] = pixels[i * 3:i * 3 + 3]
            out[i * 4 + 3] = 255
    elif color_type == 0:
        for i in range(count):
            v = pixels[i]
            out[i * 4] = out[i * 4 + 1] = out[i * 4 + 2] = v
            out[i * 4 + 3] = 255
    elif color_type == 4:
        for i in range(count):
            v = pixels[i * 2]
            out[i * 4] = out[i * 4 + 1] = out[i * 4 + 2] = v
            out[i * 4 + 3] = pixels[i * 2 + 1]
    else:  # palette
        if not palette:
            raise PngError('palette image without PLTE')
        entries = len(palette) // 3
        alpha = trns or b''
        for i in range(count):
            index = pixels[i]
            if index >= entries:
                index = 0
            out[i * 4] = palette[index * 3]
            out[i * 4 + 1] = palette[index * 3 + 1]
            out[i * 4 + 2] = palette[index * 3 + 2]
            out[i * 4 + 3] = alpha[index] if index < len(alpha) else 255
    return out


def encode_rgba(width, height, pixels):
    """Encode RGBA bytes as a PNG with filter 0 on every row."""
    if len(pixels) != width * height * 4:
        raise PngError('pixel buffer does not match the size')
    raw = bytearray()
    stride = width * 4
    for y in range(height):
        raw.append(0)
        raw += pixels[y * stride:(y + 1) * stride]
    def chunk(kind, body):
        return (struct.pack('>I', len(body)) + kind + body +
                struct.pack('>I', zlib.crc32(kind + body) & 0xFFFFFFFF))
    header = struct.pack('>IIBBBBB', width, height, 8, 6, 0, 0, 0)
    return (_PNG_SIGNATURE + chunk(b'IHDR', header) +
            chunk(b'IDAT', zlib.compress(bytes(raw), 6)) + chunk(b'IEND', b''))
