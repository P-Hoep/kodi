"""One resolver per url_type behind resolve(camera) -> PlayableItem or None. v1 plays HLS;
YouTube is behind a setting; html_page cameras never reach this point (see catalog.py).
No Kodi imports: the session passes in what it knows about Kodi (Options)."""

from . import hls, youtube
from .common import Options, PlayableItem, ResolveError  # noqa: F401

RESOLVERS = {'hls': hls.resolve, 'youtube': youtube.resolve}


def resolve(cam, options):
    """PlayableItem for a camera; raises ResolveError when it can't be played."""
    resolver = RESOLVERS.get(cam.kind)
    if resolver is None:
        raise ResolveError('no resolver for %s' % cam.kind, 'http')
    return resolver(cam, options)
