"""YouTube (v1.1, off by default): hand the video to the YouTube add-on. No Kodi imports.

This depends on plugin.video.youtube and its own API-key setup, and broadcasters change
live video ids, so a camera that stops working is handled like any other failure.
"""

import re

from .common import PlayableItem, ResolveError

PLUGIN = 'plugin://plugin.video.youtube/play/?video_id=%s'
_PATTERNS = [r'[?&]v=([A-Za-z0-9_-]{11})', r'youtu\.be/([A-Za-z0-9_-]{11})', r'/live/([A-Za-z0-9_-]{11})',
             r'/embed/([A-Za-z0-9_-]{11})', r'/shorts/([A-Za-z0-9_-]{11})']


def video_id(url):
    for pattern in _PATTERNS:
        match = re.search(pattern, url or '')
        if match:
            return match.group(1)
    return None


def resolve(cam, options):
    if not options.youtube_installed:
        raise ResolveError('the YouTube add-on is not installed', 'skip')
    vid = video_id(cam.url)
    if not vid:
        raise ResolveError('%s: no video id in %s' % (cam.title, cam.url), 'http')
    return PlayableItem(PLUGIN % vid, mime='')
