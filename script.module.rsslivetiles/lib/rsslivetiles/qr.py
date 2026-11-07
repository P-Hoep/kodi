"""QR codes for article links in the detail view. The matrix comes from pyqrcode (Kodi's
script.module.pyqrcode); the PNG is written here with zlib, so no pypng is needed.
"""

import os
import struct
import zlib


def matrix(text, error='M'):
    """text -> list of rows of 0/1, or None when pyqrcode is not available."""
    try:
        import pyqrcode
    except ImportError:
        return None
    try:
        return pyqrcode.create(text, error=error, mode='binary').code
    except Exception:
        return None


def png_bytes(rows, scale=8, quiet=4, dark=0, light=255):
    """A greyscale PNG of a 0/1 matrix, each module scale x scale px, with a quiet zone."""
    size = len(rows)
    side = (size + 2 * quiet) * scale
    blank = bytes([light]) * side
    lines = []
    for _ in range(quiet * scale):
        lines.append(b'\x00' + blank)
    for row in rows:
        line = bytearray([light]) * (quiet * scale)
        for cell in row:
            line += bytes([dark if cell else light]) * scale
        line += bytearray([light]) * (quiet * scale)
        for _ in range(scale):
            lines.append(b'\x00' + bytes(line))
    for _ in range(quiet * scale):
        lines.append(b'\x00' + blank)

    def chunk(kind, data):
        body = kind + data
        return struct.pack('>I', len(data)) + body + struct.pack('>I', zlib.crc32(body) & 0xffffffff)

    header = struct.pack('>IIBBBBB', side, side, 8, 0, 0, 0, 0)
    return (b'\x89PNG\r\n\x1a\n' + chunk(b'IHDR', header) + chunk(b'IDAT', zlib.compress(b''.join(lines), 9))
            + chunk(b'IEND', b''))


def write(text, path):
    """Write a QR code PNG for text to path (once). Returns path, or '' on failure."""
    if os.path.exists(path):
        return path
    rows = matrix(text)
    if not rows:
        return ''
    folder = os.path.dirname(path)
    if folder and not os.path.isdir(folder):
        os.makedirs(folder, exist_ok=True)
    tmp = path + '.tmp'
    with open(tmp, 'wb') as handle:
        handle.write(png_bytes(rows))
    os.replace(tmp, path)
    return path
