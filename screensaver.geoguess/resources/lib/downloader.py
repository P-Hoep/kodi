"""Image download, temporary files and prefetching. No Kodi imports.

Images go to Kodi's temp folder so the image control can read a local file. Signed URLs from the
datasets server expire; a refused download asks the client for that row again (by row_idx) once
before it is called a failure.
"""

import os
import queue
import struct
import threading

from . import config, hf_client, net

# Two files per row (the panorama and, with the map answer on, its map). Keeping the two newest
# rows and the one being replaced fits in six; eight leaves a little slack.
KEEP_FILES = 8
PREFIX = 'geoguess-'


class Downloaded(object):
    __slots__ = ('item', 'path', 'width', 'height', 'map_path')

    def __init__(self, item, path, width, height, map_path=None):
        self.item = item
        self.path = path
        self.width = width
        self.height = height
        self.map_path = map_path

    def __repr__(self):
        return 'Downloaded(%d, %r, %dx%d, map %r)' % (self.item.row_idx, self.path, self.width,
                                                     self.height, self.map_path)


# -- image dimensions from the file header ----------------------------------

def jpeg_size(data):
    """(width, height) from a JPEG's start-of-frame marker, or (0, 0)."""
    i = 2
    n = len(data)
    while i + 4 <= n:
        if data[i] != 0xFF:
            i += 1
            continue
        marker = data[i + 1]
        if marker in (0xD8, 0xD9, 0x01) or 0xD0 <= marker <= 0xD7:
            i += 2
            continue
        length = struct.unpack('>H', data[i + 2:i + 4])[0]
        if length < 2:
            return 0, 0
        if 0xC0 <= marker <= 0xCF and marker not in (0xC4, 0xC8, 0xCC):
            if i + 9 > n:
                return 0, 0
            height, width = struct.unpack('>HH', data[i + 5:i + 9])
            return int(width), int(height)
        i += 2 + length
    return 0, 0


def image_size(data):
    """(width, height) for a PNG or JPEG header, or (0, 0) when it cannot be read."""
    if data.startswith(b'\x89PNG\r\n\x1a\n') and len(data) >= 24:
        return struct.unpack('>II', data[16:24])
    if data.startswith(b'\xff\xd8'):
        return jpeg_size(data)
    return 0, 0


# -- temp files ---------------------------------------------------------------

class TempStore(object):
    """Files under one folder, at most KEEP_FILES of them, removed again on exit."""

    def __init__(self, directory, keep=KEEP_FILES):
        self.directory = directory
        self.keep = keep

    def _name(self, row_idx, suffix='.jpg'):
        return os.path.join(self.directory, '%s%d%s' % (PREFIX, int(row_idx), suffix))

    def _save(self, row_idx, suffix, data):
        os.makedirs(self.directory, exist_ok=True)
        path = self._name(row_idx, suffix)
        temporary = path + '.part'
        with open(temporary, 'wb') as handle:
            handle.write(data)
        os.replace(temporary, path)
        self.trim()
        return path

    def save(self, row_idx, data):
        """Write the panorama bytes and return the path; the folder is created when missing."""
        return self._save(row_idx, '.jpg', data)

    def save_map(self, row_idx, data):
        """Write the answer map bytes; it has its own name so the panorama is left alone."""
        return self._save(row_idx, '-map.jpg', data)

    def _files(self):
        try:
            names = os.listdir(self.directory)
        except OSError:
            return []
        paths = [os.path.join(self.directory, name) for name in names if name.startswith(PREFIX)]
        return [path for path in paths if os.path.isfile(path)]

    def trim(self):
        """Delete the oldest files beyond the cap."""
        extra = self._files()
        if len(extra) <= self.keep:
            return
        extra.sort(key=lambda path: os.path.getmtime(path))
        for path in extra[:len(extra) - self.keep]:
            try:
                os.remove(path)
            except OSError:
                pass

    def clear(self):
        for path in self._files():
            try:
                os.remove(path)
            except OSError:
                pass


# -- downloading --------------------------------------------------------------

class Downloader(object):
    def __init__(self, client, store, timeout=None, maps=False):
        self.client = client
        self.store = store
        self.timeout = timeout
        self.maps = maps

    def _fetch(self, item):
        kwargs = {} if self.timeout is None else {'timeout': self.timeout}
        return net.fetch_image(item.src, **kwargs)

    def _fetch_map(self, item):
        """The zoomed answer map for a row, or None when it cannot be had.

        The map is an extra request, so its failure must not cost the panorama: the screensaver
        shows the place name instead when this returns None.
        """
        if not self.maps or item.latitude is None or item.longitude is None:
            return None
        try:
            data = net.fetch_image(config.map_url(config.map_bbox(item.latitude, item.longitude)))
        except net.HttpError:
            return None
        return self.store.save_map(item.row_idx, data)

    def download(self, item):
        """Image bytes saved to the temp store. A refused URL is re-requested once by row_idx."""
        try:
            data = self._fetch(item)
        except net.HttpError as error:
            if error.retryable:
                raise
            fresh = self.client.row(item.row_idx)
            if fresh is None:
                raise
            item = fresh
            data = self._fetch(item)
        path = self.store.save(item.row_idx, data)
        map_path = self._fetch_map(item)
        width, height = item.width, item.height
        if width <= 0 or height <= 0:
            width, height = image_size(data)
        return Downloaded(item, path, width, height, map_path)


# -- prefetching --------------------------------------------------------------

class Prefetcher(object):
    """Downloads submitted items one at a time on a daemon thread, ahead of the display."""

    def __init__(self, downloader):
        self._downloader = downloader
        self._items = queue.Queue()
        self._results = queue.Queue()
        self._stop = threading.Event()
        self._thread = threading.Thread(target=self._run, name='geoguess-prefetch')
        self._thread.daemon = True
        self._thread.start()

    def submit(self, item):
        self._items.put(item)

    def result(self, timeout=0.2):
        """(item, Downloaded or Exception) once ready, else None."""
        try:
            return self._results.get(timeout=timeout)
        except queue.Empty:
            return None

    def _run(self):
        while not self._stop.is_set():
            try:
                item = self._items.get(timeout=0.2)
            except queue.Empty:
                continue
            if item is None:
                break
            try:
                result = self._downloader.download(item)
            except hf_client.Aborted:
                break
            except Exception as error:     # handed to the display loop, which skips the row
                result = error
            self._results.put((item, result))

    def close(self):
        self._stop.set()
        try:
            self._items.put_nowait(None)
        except Exception:
            pass
        if self._thread.is_alive():
            self._thread.join(2)
