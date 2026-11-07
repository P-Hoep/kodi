"""The background refresher: fetches due feeds on its own thread and posts each result to the
window's event queue as ('feed', feed_id, new_ids). The GUI thread never touches the network.
"""

import threading

import xbmc

from .. import kodi
from ..feeds import refresh

PASS_SECONDS = 30


class FeedWorker(threading.Thread):
    def __init__(self, store, feeds, opts, post):
        threading.Thread.__init__(self, name='rsslivetiles-feeds')
        self.daemon = True
        self.store = store
        self.feeds = list(feeds)
        self.opts = opts
        self.post = post
        self.stopping = threading.Event()
        self.wake = threading.Event()
        self.force = set()
        self.monitor = xbmc.Monitor()

    def stop(self):
        self.stopping.set()
        self.wake.set()

    def stopped(self):
        return self.stopping.is_set() or self.monitor.abortRequested()

    def refresh_now(self, feed_ids=None):
        """Fetch now: the given feeds, or all of them."""
        self.force.update(feed_ids or [f.id for f in self.feeds])
        self.wake.set()

    def set_feeds(self, feeds):
        self.feeds = list(feeds)
        self.wake.set()

    def run(self):
        while not self.stopped():
            forced, self.force = self.force, set()
            work = [f for f in self.feeds if f.enabled]
            due = [f for f in work if f.id in forced or refresh.is_due(f, self.store.load(f.id), self.opts,
                                                                           kodi.epoch())]
            if due:
                self.post(('status', 'updating'))
                errors = 0
                for f in due:
                    if self.stopped():
                        return
                    try:
                        results = list(refresh.refresh_due(self.store, [f], self.opts, log=kodi.debug,
                                                           stop=self.stopped, force=True))
                    except Exception as err:          # never let one feed kill the worker
                        kodi.log('refresh of %s crashed: %s' % (f.url, err), xbmc.LOGERROR)
                        continue
                    for feed, data, new_ids in results:
                        if data.error:
                            errors += 1
                        self.post(('feed', feed.id, new_ids))
                self.post(('status', 'offline' if errors == len(due) and errors > 1 else ''))
            self.wake.wait(PASS_SECONDS)
            self.wake.clear()
