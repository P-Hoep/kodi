"""Settings actions: find a location by name or ZIP, and test every data source."""

import time

import xbmcaddon
import xbmcgui

from . import config, geo, net, radar
from .sources import coops, gibs, nws, openmeteo

ADDON_ID = config.ADDON_ID
NAME = config.ADDON_NAME


def find_location():
    addon = xbmcaddon.Addon(ADDON_ID)
    query = xbmcgui.Dialog().input('City, town or ZIP / postal code')
    if not query:
        addon.openSettings()
        return
    try:
        results = openmeteo.geocode(query)
    except net.HttpError as error:
        xbmcgui.Dialog().ok(NAME, 'Search failed: %s' % error)
        addon.openSettings()
        return
    if not results:
        xbmcgui.Dialog().ok(NAME, 'No places found for "%s".' % query)
        addon.openSettings()
        return
    choice = xbmcgui.Dialog().select('Choose your location', [r[0] for r in results])
    if choice >= 0:
        name, lat, lon = results[choice]
        addon.setSettingNumber('lat', round(lat, 4))
        addon.setSettingNumber('lon', round(lon, 4))
        addon.setSettingString('location_name', name.split(',')[0])
        if geo.inside(lat, lon, geo.CONUS) and not addon.getSetting('nws_email'):
            email = xbmcgui.Dialog().input('Optional: your email for the US weather service (weather.gov asks '
                                           'apps to identify themselves)')
            if email:
                addon.setSettingString('nws_email', email.strip())
    addon.openSettings()


def test_sources():
    """Fetch one small thing from every source and show a status table."""
    addon = xbmcaddon.Addon(ADDON_ID)
    s = config.read({'boolean': addon.getSettingBool, 'integer': addon.getSettingInt,
                     'number': addon.getSettingNumber, 'string': addon.getSetting})
    net.set_contact(s.get('nws_email'))
    lat, lon = s['lat'], s['lon']
    view = geo.Viewport(lat, lon, s['zoom'], 1920, 1080)
    chains = radar.Chains(s)
    tests = [
        ('Open-Meteo forecast', lambda: openmeteo.forecast(lat, lon) and 'ok'),
        ('Open-Meteo air quality', lambda: 'AQI %s' % openmeteo.air_quality(lat, lon)['current'].get('us_aqi')),
        ('IEM NEXRAD radar', lambda: _frame(chains.iem, view, 'past') if chains.iem.covers(lat, lon)
         else 'outside coverage (RainViewer is used)'),
        ('HRRR future radar', lambda: _frame(chains.hrrr, view, 'future') if chains.hrrr.covers(lat, lon)
         else 'outside coverage'),
        ('RainViewer', lambda: _frame(chains.rainviewer, view, 'past')),
        ('NASA GIBS satellite', lambda: _gibs(view)),
        ('NWS alerts', lambda: '%d active' % len(nws.alerts_for_point(lat, lon)) if geo.inside(lat, lon, geo.CONUS)
         else 'US only'),
        ('NOAA tides', lambda: _tides(lat, lon)),
    ]
    if chains.rainbow:
        tests.append(('Rainbow.ai', lambda: 'snapshot %s' % chains.rainbow.snapshot()))
    if chains.libre:
        tests.append(('LibreWXR', lambda: _frame(chains.libre, view, 'past')))
    progress = xbmcgui.DialogProgress()
    progress.create(NAME, 'Testing sources...')
    lines = []
    for i, (name, fn) in enumerate(tests):
        if progress.iscanceled():
            break
        progress.update(int(100 * i / len(tests)), name)
        started = time.time()
        try:
            result = fn()
            lines.append('[COLOR FF69F0AE]OK[/COLOR]    %s: %s (%.1f s)' % (name, result, time.time() - started))
        except Exception as error:
            lines.append('[COLOR FFFF6E6E]DOWN[/COLOR]  %s: %s' % (name, error))
    progress.close()
    xbmcgui.Dialog().textviewer('%s: source test' % NAME, '\n'.join(lines))


def _frame(source, view, kind):
    frames = source.frames(view, kind, 60, (320, 180))
    if not frames:
        return 'no frames listed'
    body = source.fetch(frames[-1]['parts'][0][0])
    return '%d frames, newest %s, %d KB' % (len(frames), time.strftime('%H:%M', time.localtime(frames[-1]['t'])),
                                            len(body) // 1024)


def _gibs(view):
    src = gibs.GIBS()
    if not src.covers(view.lat, view.lon):
        return 'outside GOES coverage'
    url, t, day, _ = src.image(view, (320, 180))
    body = net.fetch_image(url, timeout=20)
    return '%s %s, %d KB' % ('GeoColor' if day else 'infrared', time.strftime('%H:%M', time.localtime(t)),
                             len(body) // 1024)


def _tides(lat, lon):
    best = coops.nearest(coops.stations(), lat, lon)
    if not best:
        return 'no tide station within %d km' % coops.COASTAL_KM
    return '%s (%d km)' % (best[2], best[0])
