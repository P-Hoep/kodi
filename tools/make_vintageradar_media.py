#!/usr/bin/env python3
"""Generate the vintage radar add-ons' media: the Doto font atlases (GL: core + glow in R/G,
app: white alpha), the radar disc and sweep art for the Python app, blips, panels, the CRT
overlay, and the icon/fanart.

The GL atlas metrics JSON is read by screensaver.vintageradar.gl/src/radar_app.cpp. The app
atlas is written with PNG filter 0 only, so the add-on's pure-Python decoder stays small.

Run:  python3 tools/make_vintageradar_media.py
"""
from __future__ import annotations

import json
import math
import os
import struct
import zlib

import numpy as np
from PIL import Image, ImageDraw, ImageFilter, ImageFont

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
FONT_PATH = os.path.join(ROOT, "tools", ".wordclock-fonts", "Doto[ROND,wght].ttf")
SAVER_MEDIA = os.path.join(ROOT, "screensaver.vintageradar.gl", "resources", "media")
APP_MEDIA = os.path.join(ROOT, "script.vintageradar", "resources", "media")

ROUNDNESS = 100
WEIGHT = 900

# cp, advance at the current atlas size
CHARSET = [32] + list(range(33, 127)) + [0xB0, 0xB7]
GL_SIZES = [("small", 44), ("mid", 64), ("big", 104)]
APP_SIZES = [("tiny", 15), ("small", 22), ("mid", 32), ("big", 52)]


def font(size: int) -> ImageFont.FreeTypeFont:
    f = ImageFont.truetype(FONT_PATH, size)
    try:
        f.set_variation_by_axes([ROUNDNESS, WEIGHT])
    except Exception:
        f.set_variation_by_name(b"Black")
    return f


def glyph_metrics(f: ImageFont.FreeTypeFont) -> list[dict]:
    out = []
    for cp in CHARSET:
        ch = chr(cp)
        advance = float(f.getlength(ch))
        bbox = f.getbbox(ch, anchor="ls")
        out.append({"cp": cp, "ch": ch, "advance": advance, "bbox": bbox})
    return out


def build_atlas(name: str, size: int, glow_channels: bool) -> dict:
    f = font(size)
    ascent, descent = f.getmetrics()
    glyphs = glyph_metrics(f)
    blur = max(3, round(size / 15))
    pad = max(8, blur * 3)

    min_y0 = min(g["bbox"][1] for g in glyphs)
    max_y1 = max(g["bbox"][3] for g in glyphs)
    min_x0 = min(g["bbox"][0] for g in glyphs)
    max_adv = max(g["advance"] for g in glyphs)
    max_x1 = max(g["bbox"][2] for g in glyphs)

    cell_ox = max(pad, -min_x0 + pad // 2)
    baseline = max(pad, -min_y0 + pad // 2)
    cell_w = int(math.ceil(cell_ox + max(max_adv, max_x1) + pad))
    cell_h = int(math.ceil(baseline + max_y1 + pad))
    columns = 16
    rows = (len(glyphs) + columns - 1) // columns
    atlas_w = cell_w * columns
    atlas_h = cell_h * rows

    atlas = Image.new("RGBA", (atlas_w, atlas_h), (0, 0, 0, 0))
    for i, g in enumerate(glyphs):
        cell = Image.new("L", (cell_w, cell_h), 0)
        if g["cp"] != 32:
            ImageDraw.Draw(cell).text((cell_ox, baseline), g["ch"], font=f, fill=255, anchor="ls")
        glow = cell.filter(ImageFilter.GaussianBlur(blur))
        if glow_channels:
            r = cell
            b = Image.new("L", (cell_w, cell_h), 0)
            rga = Image.merge("RGBA", (r, glow, b, Image.new("L", (cell_w, cell_h), 255)))
        else:
            # White with a baked soft halo; the app tints it and the alpha carries the glow.
            soft = Image.fromarray(
                np.clip(np.asarray(cell, np.float32) + np.asarray(glow, np.float32) * 0.55, 0, 255)
                .astype(np.uint8)
            )
            white = Image.new("L", (cell_w, cell_h), 255)
            rga = Image.merge("RGBA", (white, white, white, soft))
        col, row = i % columns, i // columns
        atlas.paste(rga, (col * cell_w, row * cell_h))
    return {
        "name": name,
        "image": atlas,
        "json": {
            "font": "Doto",
            "size": size,
            "ascent": ascent,
            "descent": descent,
            "line_height": round(size * 1.35),
            "blur": blur,
            "cell_w": cell_w,
            "cell_h": cell_h,
            "cell_ox": cell_ox,
            "cell_oy": -baseline,
            "columns": columns,
            "rows": rows,
            "atlas_w": atlas_w,
            "atlas_h": atlas_h,
            "glyphs": [{"cp": g["cp"], "advance": round(g["advance"], 3)} for g in glyphs],
        },
    }


def write_png_filter0(path: str, image: Image.Image) -> None:
    """RGBA PNG with filter 0 on every row, so the add-on's decoder needs no heuristics."""
    image = image.convert("RGBA")
    w, h = image.size
    data = image.tobytes()
    raw = bytearray()
    stride = w * 4
    for y in range(h):
        raw.append(0)
        raw += data[y * stride : (y + 1) * stride]

    def chunk(tag: bytes, body: bytes) -> bytes:
        return (
            struct.pack(">I", len(body))
            + tag
            + body
            + struct.pack(">I", zlib.crc32(tag + body) & 0xFFFFFFFF)
        )

    with open(path, "wb") as f:
        f.write(b"\x89PNG\r\n\x1a\n")
        f.write(chunk(b"IHDR", struct.pack(">IIBBBBB", w, h, 8, 6, 0, 0, 0)))
        f.write(chunk(b"IDAT", zlib.compress(bytes(raw), 9)))
        f.write(chunk(b"IEND", b""))


def white_alpha(mask: np.ndarray) -> Image.Image:
    mask = np.clip(mask, 0, 255).astype(np.uint8)
    white = Image.new("L", (mask.shape[1], mask.shape[0]), 255)
    return Image.merge("RGBA", (white, white, white, Image.fromarray(mask)))


def draw_radar_disc(width: int = 1400) -> Image.Image:
    """The app's radar face: white on transparent, tinted with the theme by Kodi."""
    ss = 2
    s = width * ss
    c = s / 2
    outer = s * 0.492
    bezel_in = s * 0.454
    disc = s * 0.450

    # Radial haze inside the disc.
    yy, xx = np.mgrid[0:s, 0:s].astype(np.float32)
    dx, dy = xx - c, yy - c
    r = np.sqrt(dx * dx + dy * dy) / (s / 2)
    disc_n = disc / (s / 2)
    inside = np.clip(1.0 - r / disc_n, 0.0, 1.0)
    haze = (inside**1.6) * 18.0 + (inside > 0) * 7.0
    # A gentle sweep-shaped static sheen in the upper left, like a photographed CRT.
    angle = np.degrees(np.arctan2(dx, -dy)) % 360.0
    sheen = np.clip(1.0 - np.abs(((angle - 315.0 + 180.0) % 360.0) - 180.0) / 55.0, 0, 1)
    mask = haze + sheen * inside * 7.0

    im = white_alpha(mask)
    d = ImageDraw.Draw(im)
    white = (255, 255, 255, 255)
    dim = (255, 255, 255, 255)

    def ring(radius: float, alpha: int, stroke: float) -> None:
        layer = Image.new("L", (s, s), 0)
        ImageDraw.Draw(layer).ellipse(
            (c - radius, c - radius, c + radius, c + radius), outline=alpha, width=max(1, round(stroke))
        )
        im.alpha_composite(Image.merge("RGBA", (Image.new("L", (s, s), 255),) * 3 + (layer,)))

    # Range rings.
    for frac, a in ((0.25, 120), (0.5, 150), (0.75, 120), (1.0, 210)):
        ring(disc * frac, a, ss * 2)
    # Faint half-rings for a denser vintage graticule.
    for frac in (0.125, 0.375, 0.625, 0.875):
        ring(disc * frac, 42, ss * 1)

    # Spokes and azimuth ticks.
    lines = Image.new("RGBA", (s, s), (0, 0, 0, 0))
    ld = ImageDraw.Draw(lines)
    for deg in range(0, 360, 10):
        major = deg % 90 == 0
        mid = deg % 30 == 0
        alpha = 105 if major else (62 if mid else 26)
        lw = ss * (3 if major else 2)
        a = math.radians(deg)
        x0 = c + math.sin(a) * disc * 0.06
        y0 = c - math.cos(a) * disc * 0.06
        x1 = c + math.sin(a) * disc * 0.985
        y1 = c - math.cos(a) * disc * 0.985
        ld.line((x0, y0, x1, y1), fill=(255, 255, 255, alpha), width=lw)
    im.alpha_composite(lines)

    # Rim ticks: every 2 degrees, longer every 10, crossing the bezel band.
    ticks = Image.new("RGBA", (s, s), (0, 0, 0, 0))
    td = ImageDraw.Draw(ticks)
    for deg in range(0, 360, 2):
        a = math.radians(deg)
        long = deg % 10 == 0
        alpha = 220 if deg % 30 == 0 else (170 if long else 90)
        r0 = bezel_in * (1.005 if long else 1.015)
        r1 = outer * (0.965 if long else 0.985)
        td.line(
            (c + math.sin(a) * r0, c - math.cos(a) * r0, c + math.sin(a) * r1, c - math.cos(a) * r1),
            fill=(255, 255, 255, alpha),
            width=ss * (3 if deg % 30 == 0 else (2 if long else 1)),
        )
    im.alpha_composite(ticks)

    # Bezel bands.
    ring(outer, 230, ss * 3)
    ring(outer * 0.985, 120, ss * 2)
    ring(bezel_in, 200, ss * 2)
    ring(bezel_in * 1.012, 70, ss * 1)

    # Compass labels every 30 degrees, sitting in the bezel band.
    f = font(round(s * 0.028))
    labels = Image.new("RGBA", (s, s), (0, 0, 0, 0))
    ldraw = ImageDraw.Draw(labels)
    lr = (outer + bezel_in) / 2
    for deg in range(0, 360, 30):
        a = math.radians(deg)
        x = c + math.sin(a) * lr
        y = c - math.cos(a) * lr
        ldraw.text((x, y), "%03d" % deg, font=f, fill=(255, 255, 255, 235), anchor="mm")
    im.alpha_composite(labels)

    # Centre cross.
    cd = ImageDraw.Draw(im)
    cross = s * 0.012
    cd.line((c - cross, c, c + cross, c), fill=white, width=ss * 2)
    cd.line((c, c - cross, c, c + cross), fill=white, width=ss * 2)
    cd.ellipse((c - ss * 3, c - ss * 3, c + ss * 3, c + ss * 3), fill=white)

    # Fine phosphor speckle.
    rng = np.random.default_rng(7)
    speck = Image.new("L", (s, s), 0)
    sp = speck.load()
    for _ in range(int(s * s * 0.00022)):
        x = int(rng.integers(0, s))
        y = int(rng.integers(0, s))
        dx2, dy2 = x - c, y - c
        if dx2 * dx2 + dy2 * dy2 < disc * disc:
            sp[x, y] = int(rng.integers(5, 22))
    im.alpha_composite(Image.merge("RGBA", (Image.new("L", (s, s), 255),) * 3 + (speck,)))

    return im.resize((width, width), Image.LANCZOS)


def draw_sweep(width: int = 1400) -> Image.Image:
    s = width
    c = s / 2
    disc = s * 0.450
    yy, xx = np.mgrid[0:s, 0:s].astype(np.float32)
    dx, dy = xx - c, yy - c
    rr = np.sqrt(dx * dx + dy * dy) / (s / 2)
    rn = disc / (s / 2)
    theta = np.degrees(np.arctan2(dx, -dy)) % 360.0
    behind = (360.0 - theta) % 360.0
    trail = np.clip((100.0 - behind) / 100.0, 0.0, 1.0) ** 2.3
    lead = np.exp(-behind / 1.7) + np.exp(-(360.0 - behind) / 1.2) * 0.35
    radial = np.clip((rn - rr) / 0.06, 0, 1) * (1.0 - 0.30 * np.clip(rr / rn, 0, 1))
    inside = (rr <= rn).astype(np.float32)
    alpha = (trail * 0.40 + lead * 0.95) * radial * inside * 255.0
    return white_alpha(alpha)


def draw_glow(size: int, core: float, halo: float) -> Image.Image:
    yy, xx = np.mgrid[0:size, 0:size].astype(np.float32)
    c = (size - 1) / 2.0
    r = np.sqrt((xx - c) ** 2 + (yy - c) ** 2) / (size / 2.0)
    a = (np.exp(-(r / core) ** 2 * 3.2) + np.exp(-(r / halo) ** 2 * 3.2) * 0.30) * 255.0
    return white_alpha(a)


def draw_ring(size: int) -> Image.Image:
    yy, xx = np.mgrid[0:size, 0:size].astype(np.float32)
    c = (size - 1) / 2.0
    r = np.sqrt((xx - c) ** 2 + (yy - c) ** 2) / (size / 2.0)
    a = np.exp(-((r - 0.78) / 0.055) ** 2) * 235.0
    return white_alpha(a)


def draw_panel(w: int, h: int) -> Image.Image:
    ss = 2
    im = Image.new("RGBA", (w * ss, h * ss), (0, 0, 0, 0))
    d = ImageDraw.Draw(im)
    W, H = w * ss, h * ss
    edge = 235
    # Outer frame with clipped corners.
    k = 10 * ss
    pts = [(k, 0), (W - k, 0), (W, k), (W, H - k), (W - k, H), (k, H), (0, H - k), (0, k)]
    d.line(pts + [pts[0]], fill=(255, 255, 255, edge), width=ss * 2, joint="curve")
    d.line([(1, H / 2), (1, H / 2)], fill=(255, 255, 255, 0))
    # Header rule and corner brackets.
    d.line((8 * ss, 38 * ss, W - 8 * ss, 38 * ss), fill=(255, 255, 255, 120), width=ss)
    b = 26 * ss
    for x, y, sx, sy in ((0, 0, 1, 1), (W, 0, -1, 1), (0, H, 1, -1), (W, H, -1, -1)):
        d.line((x + sx * 2 * ss, y + sy * 14 * ss, x + sx * 2 * ss, y + sy * 2 * ss),
               fill=(255, 255, 255, 255), width=ss * 3)
        d.line((x + sx * 2 * ss, y + sy * 2 * ss, x + sx * 14 * ss, y + sy * 2 * ss),
               fill=(255, 255, 255, 255), width=ss * 3)
    im = im.resize((w, h), Image.LANCZOS)
    glow = im.filter(ImageFilter.GaussianBlur(1.6))
    out = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    out.alpha_composite(glow)
    out.alpha_composite(im)
    return out


def draw_scanlines(w: int, h: int) -> Image.Image:
    yy, xx = np.mgrid[0:h, 0:w].astype(np.float32)
    line = (yy.astype(np.int32) % 3 == 0).astype(np.float32) * 26.0
    nx = (xx - w / 2) / (w / 2)
    ny = (yy - h / 2) / (h / 2)
    vignette = np.clip((np.sqrt(nx * nx + ny * ny) - 0.55) / 0.75, 0, 1) ** 1.7 * 130.0
    a = np.clip(line + vignette, 0, 255)
    black = Image.new("L", (w, h), 0)
    return Image.merge("RGBA", (black, black, black, Image.fromarray(a.astype(np.uint8))))


def draw_icon(size: int = 512) -> Image.Image:
    bg = Image.new("RGB", (size, size), (2, 8, 4))
    # Green glow behind the disc.
    disc = draw_radar_disc(size - 40)
    tint = Image.new("RGBA", disc.size, (70, 255, 120, 255))
    tint.putalpha(disc.getchannel("A"))
    sweep = draw_sweep(size - 40)
    st = Image.new("RGBA", sweep.size, (150, 255, 180, 255))
    st.putalpha(sweep.getchannel("A"))
    bg = bg.convert("RGBA")
    bg.alpha_composite(disc, (20, 20))
    bg.alpha_composite(st, (20, 20))
    d = ImageDraw.Draw(bg)
    for x, y, r in ((0.62, 0.35, 7), (0.41, 0.58, 5), (0.58, 0.66, 4)):
        cx, cy = 20 + x * (size - 40), 20 + y * (size - 40)
        d.ellipse((cx - r, cy - r, cx + r, cy + r), fill=(215, 255, 225, 255))
    return bg.convert("RGB")


def draw_fanart(w: int = 1920, h: int = 1080) -> Image.Image:
    base = Image.new("RGB", (w, h), (2, 7, 4))
    # Soft green vignette/glow.
    small = Image.new("L", (w // 8, h // 8), 0)
    d = ImageDraw.Draw(small)
    d.ellipse((w // 40, h // 40, w // 8 - w // 40, h // 8 - h // 40), fill=45)
    halo = small.resize((w, h), Image.BICUBIC).filter(ImageFilter.GaussianBlur(80))
    green = Image.new("RGB", (w, h), (10, 55, 22))
    base = Image.composite(green, base, halo)
    # Radar on the right.
    disc = draw_radar_disc(880)
    tint = Image.new("RGBA", disc.size, (95, 255, 145, 255))
    tint.putalpha(disc.getchannel("A"))
    sweep = draw_sweep(880)
    st = Image.new("RGBA", sweep.size, (170, 255, 195, 255))
    st.putalpha(sweep.getchannel("A"))
    layer = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    layer.alpha_composite(tint, (940, 100))
    layer.alpha_composite(st, (940, 100))
    base = Image.alpha_composite(base.convert("RGBA"), layer)
    d = ImageDraw.Draw(base)
    f_big = font(118)
    f_mid = font(40)
    f_small = font(28)
    d.text((92, 300), "VINTAGE", font=f_big, fill=(140, 255, 170))
    d.text((92, 418), "RADAR", font=f_big, fill=(140, 255, 170))
    d.text((96, 560), "AIRCRAFT OVERHEAD, ON A 1970s SCOPE", font=f_mid, fill=(80, 190, 110))
    d.text((96, 630), "ADS-B  ·  SWEEP  ·  CONTACT LIST", font=f_small, fill=(45, 120, 70))
    return base.convert("RGB")


def main() -> None:
    os.makedirs(os.path.join(SAVER_MEDIA, "fonts"), exist_ok=True)
    os.makedirs(os.path.join(APP_MEDIA, "fonts"), exist_ok=True)

    for name, size in GL_SIZES:
        a = build_atlas(name, size, True)
        img = a["image"]
        png = os.path.join(SAVER_MEDIA, "fonts", "font_%s.png" % name)
        img.save(png, optimize=True)
        with open(os.path.join(SAVER_MEDIA, "fonts", "font_%s.json" % name), "w") as f:
            json.dump(a["json"], f, indent=1)
        print("gl", name, size, img.size)

    for name, size in APP_SIZES:
        a = build_atlas(name, size, False)
        img = a["image"]
        png = os.path.join(APP_MEDIA, "fonts", "app_%s.png" % name)
        write_png_filter0(png, img)
        with open(os.path.join(APP_MEDIA, "fonts", "app_%s.json" % name), "w") as f:
            json.dump(a["json"], f, indent=1)
        print("app", name, size, img.size)

    draw_radar_disc().save(os.path.join(APP_MEDIA, "radar.png"), optimize=True)
    draw_sweep().save(os.path.join(APP_MEDIA, "sweep.png"), optimize=True)
    draw_glow(96, 0.16, 0.46).save(os.path.join(APP_MEDIA, "blip.png"), optimize=True)
    draw_glow(48, 0.24, 0.62).save(os.path.join(APP_MEDIA, "echo.png"), optimize=True)
    draw_ring(96).save(os.path.join(APP_MEDIA, "ring.png"), optimize=True)
    draw_panel(908, 540).save(os.path.join(APP_MEDIA, "panel_list.png"), optimize=True)
    draw_panel(908, 316).save(os.path.join(APP_MEDIA, "panel_detail.png"), optimize=True)
    draw_panel(1400, 780).save(os.path.join(APP_MEDIA, "panel_overlay.png"), optimize=True)
    Image.new("RGBA", (4, 4), (0, 0, 0, 0)).save(
        os.path.join(APP_MEDIA, "transparent.png"), optimize=True)
    draw_scanlines(1920, 1080).save(os.path.join(APP_MEDIA, "scanlines.png"), optimize=True)
    solid = Image.new("RGB", (8, 8), (255, 255, 255))
    solid.save(os.path.join(APP_MEDIA, "solid.png"))

    draw_icon(512).save(os.path.join(APP_MEDIA, "icon.png"), optimize=True)
    draw_icon(512).save(os.path.join(SAVER_MEDIA, "icon.png"), optimize=True)
    draw_fanart().save(os.path.join(SAVER_MEDIA, "fanart.jpg"), quality=90)
    draw_fanart().save(os.path.join(APP_MEDIA, "fanart.jpg"), quality=90)
    print("done")


if __name__ == "__main__":
    main()
