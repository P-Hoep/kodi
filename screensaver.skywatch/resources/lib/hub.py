"""The data hub: fetches every non-radar dataset on its own schedule into the JSON cache, so
scenes only ever read cached values. Shared by the background service and the screensaver.
No Kodi imports.

Each job has a cache key, a time-to-live, a source id (for back-off and status) and a
condition (is the scene that needs it on, is the location in the US...). Failures keep
serving the cached value and mark the source Stale; without a cached value it is Down and
the scenes that need it are skipped.
"""

import math
import threading
import time

from . import climate, geo, net
from .sources import coops, nws, openmeteo, usgs

MIN = 60
HOUR = 3600
DAY = 86400


def loc_key(lat, lon):
    return '%.3f,%.3f' % (lat, lon)


class Job(object):
    def __init__(self, name, source, ttl, fetch, enabled=lambda: True, retry=300):
        self.name = name
        self.source = source
        self.ttl = ttl
        self.fetch = fetch
        self.enabled = enabled
        self.retry = retry


class Hub(object):
    def __init__(self, settings, store, budget, log=None):
        self.s = settings
        self.store = store
        self.budget = budget
        self.log = log or (lambda msg: None)
        self.lat, self.lon = settings['lat'], settings['lon']
        self.loc = loc_key(self.lat, self.lon)
        self.us = geo.inside(self.lat, self.lon, geo.CONUS) or self._us_extra()
        self.lock = threading.Lock()
        self.inflight = set()
        self.next_try = {}
        self.version = 0
        self.jobs = self._jobs()
        net.set_contact(settings.get('nws_email'))

    def _us_extra(self):
        # Alaska, Hawaii, Puerto Rico: NWS covers them even though the radar mosaic doesn't.
        lat, lon = self.lat, self.lon
        return (51 <= lat <= 72 and -170 <= lon <= -129) or (18 <= lat <= 23 and -161 <= lon <= -154) or \
               (17.5 <= lat <= 18.6 and -67.5 <= lon <= -65)

    def scene_on(self, sid):
        return self.s.get('scene_' + sid, 0) != 0

    # ------------------------------------------------------------ jobs

    def _jobs(self):
        s, lat, lon = self.s, self.lat, self.lon
        fish = self.fish_spot()
        jobs = [
            Job('forecast', 'openmeteo', 15 * MIN, lambda: openmeteo.forecast(lat, lon), retry=2 * MIN),
            Job('air', 'openmeteo-air', HOUR, lambda: openmeteo.air_quality(lat, lon),
                lambda: self.scene_on('air')),
            Job('nws_point', 'nws', 30 * DAY, lambda: nws.point(lat, lon), lambda: self.us),
            Job('alerts', 'nws', 5 * MIN, lambda: nws.alerts_for_point(lat, lon),
                lambda: self.us and s.get('alert_level', 1) != 3, retry=2 * MIN),
            Job('nws_forecast', 'nws', HOUR, self._nws_forecast,
                lambda: self.us and self.scene_on('daily') and bool(self.get('nws_point'))),
            Job('afd', 'nws', HOUR, self._afd,
                lambda: self.us and self.scene_on('discussion') and bool(self.get('nws_point'))),
            Job('archive', 'openmeteo-archive', 3650 * DAY, self._archive,
                lambda: self.scene_on('climate') or self.scene_on('year'), retry=HOUR),
            Job('recent', 'openmeteo-archive', DAY, self._recent,
                lambda: self.scene_on('climate') or self.scene_on('year'), retry=HOUR),
            Job('tide_stations', 'coops', 30 * DAY, coops.stations,
                lambda: self.scene_on('marine') or self.scene_on('fishing'), retry=HOUR),
            Job('tides', 'coops', 6 * HOUR, self._tides,
                lambda: (self.scene_on('marine') or self.scene_on('fishing')) and self.tide_station() is not None),
            Job('marine', 'openmeteo-marine', HOUR, self._marine,
                lambda: self.scene_on('marine') and self.tide_station() is not None),
            Job('gauge', 'usgs', 30 * MIN, lambda: usgs.gauge(s['fish_gauge']),
                lambda: self.scene_on('fishing') and s.get('fish_spot') == 2 and bool(s.get('fish_gauge'))),
        ]
        if fish != (lat, lon):
            jobs.append(Job('fish_forecast', 'openmeteo', HOUR, lambda: openmeteo.forecast(*self.fish_spot()),
                            lambda: self.scene_on('fishing')))
        return jobs

    def key(self, name):
        if name in ('tide_stations',):
            return name
        if name in ('gauge',):
            return 'gauge:%s' % self.s.get('fish_gauge')
        return '%s:%s' % (name, self.loc)

    def _nws_forecast(self):
        point = self.get('nws_point')
        if not point or not point.get('forecast'):
            raise net.HttpError('no NWS point yet')
        return nws.forecast_periods(point['forecast'])

    def _afd(self):
        point = self.get('nws_point')
        if not point or not point.get('cwa'):
            raise net.HttpError('no NWS point yet')
        return nws.discussion(point['cwa'])

    def _archive(self):
        end = time.strftime('%Y-%m-%d', time.gmtime(time.time() - 7 * DAY))
        return openmeteo.archive(self.lat, self.lon, '1940-01-01', end)

    def _recent(self):
        start = time.strftime('%Y-%m-%d', time.gmtime(time.time() - 400 * DAY))
        end = time.strftime('%Y-%m-%d', time.gmtime(time.time() - 2 * DAY))
        return openmeteo.archive(self.lat, self.lon, start, end)

    def _tides(self):
        station = self.tide_station()
        fc = self.get('forecast') or {}
        offset = fc.get('offset', 0)
        start = math.floor((time.time() + offset) / DAY) * DAY - offset - 2 * HOUR
        data = coops.tides(station[1], start, 30)
        data['station'] = station[1]
        data['name'] = station[2]
        data['distance_km'] = station[0]
        data['water'] = coops.water_temperature(station[1])
        return data

    def _marine(self):
        station = self.tide_station()
        return openmeteo.marine(station[3], station[4])

    def fish_spot(self):
        s = self.s
        if s.get('fish_spot') == 1 and (s.get('fish_lat') or s.get('fish_lon')):
            return s['fish_lat'], s['fish_lon']
        return self.lat, self.lon

    def tide_station(self):
        """(distance km, id, name, lat, lon) of the CO-OPS station to use, or None."""
        s = self.s
        if s.get('fish_spot') == 3 and s.get('fish_station'):
            return (0.0, s['fish_station'].strip(), s['fish_station'].strip(), self.lat, self.lon)
        stations = self.store.value('tide_stations')
        if not stations:
            return None
        return coops.nearest(stations, self.lat, self.lon)

    # ------------------------------------------------------------ running

    def due(self, now=None):
        now = time.time() if now is None else now
        out = []
        for job in self.jobs:
            if job.name in self.inflight or now < self.next_try.get(job.name, 0):
                continue
            try:
                if not job.enabled():
                    continue
            except Exception:
                continue
            if self.store.fresh(self.key(job.name)):
                continue
            if not self.budget.ready(job.source, now):
                continue
            out.append(job)
        return out

    def run(self, job):
        key = self.key(job.name)
        started = time.time()
        try:
            value = job.fetch()
            self.store.put(key, value, job.ttl)
            self.budget.count(job.source)
            self.budget.ok(job.source)
            with self.lock:
                self.version += 1
            self.log('%s: fetched in %.1f s' % (job.name, time.time() - started))
        except Exception as error:
            status = getattr(error, 'status', None)
            if status == 429 or (status or 0) >= 500:
                self.budget.failed(job.source, status, str(error))
            if self.store.value(key) is not None:
                self.budget.stale(job.source, str(error))
            else:
                self.budget.status[job.source] = ('Down', str(error), time.time())
            self.next_try[job.name] = time.time() + job.retry
            self.log('%s failed: %s' % (job.name, error))
        finally:
            self.inflight.discard(job.name)

    def run_due(self, submit=None):
        """Start every due job (in submit's workers, or inline)."""
        started = 0
        for job in self.due():
            self.inflight.add(job.name)
            if submit:
                submit(self.run, job)
            else:
                self.run(job)
            started += 1
        return started

    # ------------------------------------------------------------ reading

    def get(self, name):
        return self.store.value(self.key(name))

    def age(self, name):
        _v, fetched, _fresh = self.store.get(self.key(name))
        return None if fetched is None else time.time() - fetched

    def climate(self):
        """Normals, records and the merged daily history, computed once per archive version."""
        archive = self.get('archive')
        if not archive:
            return None
        stamp = (len(archive.get('time') or []), (self.get('recent') or {}).get('time', [''])[-1:],
                 (self.get('forecast') or {}).get('fetched'))
        cached = getattr(self, '_climate', None)
        if cached and cached[0] == stamp:
            return cached[1]
        normal_rows = self.store.getkv('normals:' + self.loc)
        record_rows = self.store.getkv('records:' + self.loc)
        if not normal_rows or self.store.getkv('normals_n:' + self.loc) != len(archive['time']):
            normal_rows = climate.normals(archive)
            record_rows = climate.records(archive)
            self.store.setkv('normals:' + self.loc, normal_rows)
            self.store.setkv('records:' + self.loc, record_rows)
            self.store.setkv('normals_n:' + self.loc, len(archive['time']))
        fc_daily = climate.forecast_daily(self.get('forecast'))
        daily = climate.merge_daily(archive, self.get('recent') or {}, fc_daily)
        value = {'normals': normal_rows, 'records': record_rows, 'daily': daily,
                 'history': climate.by_day(daily)}
        self._climate = (stamp, value)
        return value

    def forecast_age(self):
        return self.age('forecast')

    def alerts(self):
        """Active alerts at the home point filtered by the alert-level setting."""
        if not self.us:
            return []
        level = self.s.get('alert_level', 1)
        if level == 3:
            return []
        minimum = {0: 3, 1: 2, 2: 1}[level]
        now = time.time()
        return [a for a in self.get('alerts') or [] if a['level'] >= minimum and (not a['ends'] or a['ends'] > now)]


def scene_needs(sid):
    """Which datasets a scene can't do without (used by the player to skip scenes)."""
    return {
        'current': ['forecast'], 'nexthours': ['forecast'], 'hourly': ['forecast'], 'daily': ['forecast'],
        'climate': ['archive', 'forecast'], 'year': ['archive'], 'fishing': ['forecast'],
        'air': ['air'], 'marine': ['tides'], 'discussion': ['afd'],
    }.get(sid, [])

