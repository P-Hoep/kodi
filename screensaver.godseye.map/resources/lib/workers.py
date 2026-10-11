"""A tiny daemon-thread pool. Kodi kills a screensaver that takes over 5 s to exit, and
concurrent.futures joins its threads at exit, so slow downloads would hold the exit up."""

import threading

try:
    import queue
except ImportError:  # pragma: no cover
    import Queue as queue

_STOP = object()


class Workers(object):
    def __init__(self, count, name='worker', on_error=None):
        self._queue = queue.Queue()
        self._on_error = on_error or (lambda error: None)
        self._threads = []
        for i in range(count):
            t = threading.Thread(target=self._run, name='%s-%d' % (name, i))
            t.daemon = True
            t.start()
            self._threads.append(t)

    def submit(self, fn, *args):
        self._queue.put((fn, args))

    def _run(self):
        while True:
            job = self._queue.get()
            if job is _STOP:
                return
            fn, args = job
            try:
                fn(*args)
            except Exception as error:  # keep the worker alive
                self._on_error(error)

    def shutdown(self):
        # Drop queued work, then ask each thread to finish its current job and stop.
        try:
            while True:
                self._queue.get_nowait()
        except queue.Empty:
            pass
        for _ in self._threads:
            self._queue.put(_STOP)
