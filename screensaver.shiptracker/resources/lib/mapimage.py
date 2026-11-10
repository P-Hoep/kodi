"""The Blue Marble base map, downloaded once per bounding box and kept in the profile folder.

The image is requested from NASA GIBS at the exact size of the map control, so it is already at
TV resolution when Kodi displays it. The cache key is the request URL, so changing any edge of
the box or the control size produces a new file and the old one can be pruned. A cached file is
used even when the request fails, which keeps the screen usable offline.
"""

import os
import tempfile

from . import config, net


def map_path(folder, bounds, width=config.MAP_WIDTH, height=config.MAP_HEIGHT):
    return os.path.join(folder, config.map_cache_name(bounds, width, height))


def has_map(path):
    try:
        return os.path.getsize(path) > 2000
    except OSError:
        return False


def ensure_map(folder, bounds, width=config.MAP_WIDTH, height=config.MAP_HEIGHT,
               fetch=None, max_bytes=8 * 1024 * 1024):
    """Download the map when it is not cached. Returns the local path, or None."""
    path = map_path(folder, bounds, width, height)
    if has_map(path):
        return path
    if not os.path.isdir(folder):
        try:
            os.makedirs(folder, exist_ok=True)
        except OSError:
            return None
    fetch = fetch or (lambda url: net.fetch(url, timeout=45,
                                            headers={'Accept': 'image/jpeg'},
                                            max_bytes=max_bytes))
    url = config.map_url(bounds, width, height)
    try:
        body = fetch(url)
        if len(body) < 2000:
            raise net.HttpError('map image too small', 'http')
        handle, temp = tempfile.mkstemp(prefix='.map-', suffix='.tmp', dir=folder)
        try:
            with os.fdopen(handle, 'wb') as out:
                out.write(body)
            os.replace(temp, path)
        except Exception:
            try:
                os.remove(temp)
            except OSError:
                pass
            raise
    except Exception:
        return path if has_map(path) else None
    return path


def clear(folder):
    removed = 0
    try:
        names = os.listdir(folder)
    except OSError:
        return 0
    for name in names:
        if name.startswith('map_') and name.endswith('.jpg'):
            try:
                os.remove(os.path.join(folder, name))
                removed += 1
            except OSError:
                pass
    return removed
