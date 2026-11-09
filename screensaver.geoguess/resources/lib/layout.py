"""Where the image sits and how far it has panned. No Kodi imports.

The panorama always fills the full screen height. Its width follows its aspect ratio, so a wide
image is wider than the screen and pans from its left edge to its right edge over the time the
location is shown; a narrower one is centred and does not move.
"""

import math


def display_size(image_width, image_height, screen_width, screen_height):
    """(width, height) on screen: full screen height, width by aspect ratio.

    A panorama might be taller than the screen, and Kodi's image control keeps the aspect ratio
    when given one of the two sides, so both sides are computed from the height.
    """
    if image_width <= 0 or image_height <= 0:
        return screen_width, screen_height
    scale = float(screen_height) / float(image_height)
    return max(1, int(round(image_width * scale))), screen_height


def pan_extent(display_width, screen_width):
    """How far the left edge travels: zero when the image is no wider than the screen."""
    return max(0, int(display_width) - int(screen_width))


def ease(u):
    """Sine ease in and out, so the pan starts and stops softly. u is clamped to 0..1."""
    u = max(0.0, min(1.0, float(u)))
    return 0.5 - 0.5 * math.cos(math.pi * u)


def pan_offset(display_width, screen_width, elapsed, show_for, enabled=True, passes=1):
    """The image's left edge in screen pixels at `elapsed` seconds into the pan.

    One pass sweeps the panorama from its left edge to its right edge in `show_for` seconds,
    easing in and out. With several passes the direction reverses at each end, so the same
    panorama is shown back and forth; the last pass may end at either edge. `elapsed` past the
    end keeps the last position.
    """
    extent = pan_extent(display_width, screen_width)
    passes = max(1, int(passes))
    if not enabled or extent <= 0 or show_for <= 0:
        return 0
    index = min(int(elapsed / float(show_for)), passes - 1)
    u = (elapsed - index * float(show_for)) / float(show_for)
    if index % 2:
        u = 1.0 - u
    return -int(round(extent * ease(u)))


def centre_offset(display_width, screen_width):
    """The left edge for an image narrower than the screen: centred, or 0 when wider."""
    if display_width >= screen_width:
        return 0
    return int((screen_width - display_width) / 2)


def world_point(latitude, longitude, width, height):
    """Pixel position of (latitude, longitude) on an equirectangular world map.

    The map spans 180 degrees west to east across `width` and 90 north to south across
    `height`. Out-of-range values are clamped to the edge rather than wrapped, so a bad row
    puts the pin at the border instead of somewhere unrelated.
    """
    lat = max(-90.0, min(90.0, float(latitude)))
    lon = max(-180.0, min(180.0, float(longitude)))
    x = (lon + 180.0) / 360.0 * width
    y = (90.0 - lat) / 180.0 * height
    return x, y
