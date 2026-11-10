"""Where the image sits and how far it has panned. No Kodi imports.

The panorama always fills the full screen height. Its width follows its aspect ratio, so a wide
image is wider than the screen and pans from its left edge to its right edge over the time the
location is shown; a narrower one is centred and does not move.
"""

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


def pan_offset(display_width, screen_width, elapsed, show_for, enabled=True, passes=1):
    """The image's left edge in screen pixels at `elapsed` seconds into the pan.

    One pass sweeps the panorama from its left edge to its right edge in `show_for` seconds at
    a constant speed. With several passes the direction reverses at each end, so the same
    panorama is shown back and forth; the last pass may end at either edge. `elapsed` past the
    end keeps the last position.
    """
    extent = pan_extent(display_width, screen_width)
    passes = max(1, int(passes))
    if not enabled or extent <= 0 or show_for <= 0:
        return 0
    index = min(int(elapsed / float(show_for)), passes - 1)
    u = (elapsed - index * float(show_for)) / float(show_for)
    u = max(0.0, min(1.0, u))
    if index % 2:
        u = 1.0 - u
    return -int(round(extent * u))


def centre_offset(display_width, screen_width):
    """The left edge for an image narrower than the screen: centred, or 0 when wider."""
    if display_width >= screen_width:
        return 0
    return int((screen_width - display_width) / 2)


def map_point(latitude, longitude, bbox, width, height):
    """Pixel position of (latitude, longitude) inside a map drawn for `bbox`.

    bbox is (left, bottom, right, top) in degrees, the same bounds the image was requested for.
    The result is clamped to the image, so a point just outside a window that had to be slid
    inward still gets a pin on the border rather than off the map.
    """
    left, bottom, right, top = [float(value) for value in bbox]
    if right <= left or top <= bottom:
        return 0.0, 0.0
    u = (float(longitude) - left) / (right - left)
    v = (top - float(latitude)) / (top - bottom)
    return max(0.0, min(1.0, u)) * width, max(0.0, min(1.0, v)) * height
