"""HLS: probe the manifest, then hand Kodi the URL. No Kodi imports.

The probe fetches the manifest with a 4 s timeout and wants #EXTM3U plus at least one
variant (#EXT-X-STREAM-INF) or segment (#EXTINF). A failed probe costs no screen time.
Some camera hosts send an incomplete certificate chain; with the insecure option on, the
probe retries without verification and Kodi is told the same (|verifypeer=false).
"""

import re
from urllib.parse import urljoin

from .. import net
from .common import PlayableItem, ResolveError

MAX_MANIFEST = 1024 * 1024
DATA_SAVER_HEIGHT = 720
_ATTR = re.compile(r'([A-Z0-9-]+)=("[^"]*"|[^,]*)')


class Manifest(object):
    def __init__(self, url, variants, segments):
        self.url = url
        self.variants = variants      # [(bandwidth, width, height, absolute uri)]
        self.segments = segments

    @property
    def height(self):
        heights = [min(w, h) for _b, w, h, _u in self.variants if w and h]
        return max(heights) if heights else 0


def parse(text, url):
    """Manifest text -> Manifest. Raises ResolveError when it isn't a usable playlist."""
    text = text.lstrip('﻿').lstrip()
    if not text.startswith('#EXTM3U'):
        raise ResolveError('not an HLS playlist', 'http')
    variants, segments = [], 0
    pending = None
    for line in text.splitlines():
        line = line.strip()
        if line.startswith('#EXT-X-STREAM-INF:'):
            attrs = dict((k, v.strip('"')) for k, v in _ATTR.findall(line.split(':', 1)[1]))
            w = h = 0
            match = re.match(r'^(\d+)x(\d+)$', attrs.get('RESOLUTION', ''))
            if match:
                w, h = int(match.group(1)), int(match.group(2))
            try:
                bandwidth = int(attrs.get('BANDWIDTH', '0'))
            except ValueError:
                bandwidth = 0
            pending = (bandwidth, w, h)
        elif line.startswith('#EXTINF'):
            segments += 1
        elif line and not line.startswith('#') and pending is not None:
            variants.append(pending + (urljoin(url, line),))
            pending = None
    if not variants and not segments:
        raise ResolveError('playlist has no variants or segments', 'http')
    return Manifest(url, variants, segments)


def choose_variant(variants, cap=DATA_SAVER_HEIGHT):
    """Data saver: the lowest variant at or above cap, else the highest below it."""
    sized = [v for v in variants if v[1] and v[2]]
    if not sized:
        return None
    above = [v for v in sized if min(v[1], v[2]) >= cap]
    if above:
        return min(above, key=lambda v: (min(v[1], v[2]), v[0]))
    return max(sized, key=lambda v: (min(v[1], v[2]), v[0]))


def probe(url, timeout=4.0, insecure=True, fetch=net.fetch):
    """(Manifest, insecure used). Raises ResolveError."""
    try:
        response = fetch(url, timeout=timeout, max_bytes=MAX_MANIFEST)
        used_insecure = False
    except net.HttpError as error:
        if error.kind != 'cert' or not insecure:
            raise ResolveError(str(error), 'http' if error.kind == 'cert' else error.kind)
        try:
            response = fetch(url, timeout=timeout, max_bytes=MAX_MANIFEST, verify=False)
            used_insecure = True
        except net.HttpError as error2:
            raise ResolveError(str(error2), error2.kind if error2.kind != 'cert' else 'http')
    if response.status != 200:
        raise ResolveError('%s: HTTP %s' % (net.short(url), response.status), 'http')
    return parse(response.body.decode('utf-8', 'replace'), response.url or url), used_insecure


def resolve(cam, options, fetch=net.fetch):
    manifest, insecure = probe(cam.url, options.timeout, options.insecure, fetch)
    height = manifest.height
    if options.min_height and not cam.height and height and height < options.min_height:
        raise ResolveError('%s: %dp is below the minimum' % (cam.title, height), 'skip', height)
    url = cam.url
    properties = {}
    use_isa = options.isa and not insecure
    if options.data_saver and manifest.variants and not use_isa:
        variant = choose_variant(manifest.variants)
        if variant is not None:
            url = variant[3]
            height = min(variant[1], variant[2])
    if use_isa:
        properties['inputstream'] = 'inputstream.adaptive'
        if options.kodi_major < 21:
            properties['inputstream.adaptive.manifest_type'] = 'hls'
        if options.data_saver:
            properties['inputstream.adaptive.chooser_resolution_max'] = '720p'
    if insecure:
        url += '|verifypeer=false'
    return PlayableItem(url, properties=properties, height=height, insecure=insecure)
