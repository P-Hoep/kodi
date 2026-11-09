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


def pan_offset(display_width, screen_width, elapsed, show_for, enabled=True):
    """The image's left edge in screen pixels at `elapsed` seconds into the cycle."""
    extent = pan_extent(display_width, screen_width)
    if not enabled or extent <= 0 or show_for <= 0:
        return 0
    return -int(round(extent * ease(elapsed / float(show_for))))


def centre_offset(display_width, screen_width):
    """The left edge for an image narrower than the screen: centred, or 0 when wider."""
    if display_width >= screen_width:
        return 0
    return int((screen_width - display_width) / 2)
