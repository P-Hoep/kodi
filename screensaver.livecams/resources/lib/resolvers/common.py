"""Data passed between the resolvers and the player. No Kodi imports."""


class ResolveError(Exception):
    """kind: 'http' (the camera's fault), 'network' (maybe ours), or 'skip' (can't show it
    here, e.g. below the minimum resolution: skipped without counting as a failure)."""

    def __init__(self, message, kind='http', height=0):
        Exception.__init__(self, message)
        self.kind = kind
        self.height = height


class Options(object):
    def __init__(self, min_height=0, data_saver=False, isa=False, insecure=True, kodi_major=21,
                 youtube_installed=False, timeout=4.0):
        self.min_height = min_height
        self.data_saver = data_saver
        self.isa = isa                      # use inputstream.adaptive (setting on and installed)
        self.insecure = insecure            # allow hosts whose certificate chain doesn't verify
        self.kodi_major = kodi_major
        self.youtube_installed = youtube_installed
        self.timeout = timeout


class PlayableItem(object):
    def __init__(self, url, mime='application/vnd.apple.mpegurl', properties=None, height=0, insecure=False):
        self.url = url
        self.mime = mime
        self.properties = properties or {}
        self.height = height                # tallest variant the manifest offers, 0 if unknown
        self.insecure = insecure

    def __repr__(self):
        return '<PlayableItem %s>' % self.url
