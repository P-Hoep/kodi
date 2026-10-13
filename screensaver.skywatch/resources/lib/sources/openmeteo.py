"""Open-Meteo (keyless, non-commercial): forecast, archive, air quality, marine, geocoding.

Everything is requested in metric units with unix times (timeformat=unixtime); units.py
converts for display. Responses are trimmed to plain dicts of lists before caching.
"""

import time

from .. import net

FORECAST = 'https://api.open-meteo.com/v1/forecast'
ARCHIVE = 'https://archive-api.open-meteo.com/v1/archive'
AIR = 'https://air-quality-api.open-meteo.com/v1/air-quality'
MARINE = 'https://marine-api.open-meteo.com/v1/marine'
GEOCODE = 'https://geocoding-api.open-meteo.com/v1/search'
ATTRIBUTION = 'Weather data by Open-Meteo.com'

CURRENT = ('temperature_2m,apparent_temperature,relative_humidity_2m,dew_point_2m,weather_code,is_day,'
           'wind_speed_10m,wind_direction_10m,wind_gusts_10m,pressure_msl,cloud_cover,visibility,uv_index,'
           'precipitation')
HOURLY = ('temperature_2m,apparent_temperature,precipitation_probability,precipitation,weather_code,'
          'wind_speed_10m,wind_gusts_10m,wind_direction_10m,pressure_msl,cloud_cover,is_day,'
          'wind_direction_850hPa,dew_point_2m,relative_humidity_2m')
DAILY = ('weather_code,temperature_2m_max,temperature_2m_min,precipitation_probability_max,precipitation_sum,'
         'snowfall_sum,wind_speed_10m_max,wind_gusts_10m_max,wind_direction_10m_dominant,sunrise,sunset,'
         'uv_index_max,daylight_duration')


def _section(data, name):
    sec = data.get(name) or {}
    return dict((k, v) for k, v in sec.items())


def forecast(lat, lon):
    url = ('%s?latitude=%.4f&longitude=%.4f&current=%s&minutely_15=precipitation,snowfall,weather_code'
           '&hourly=%s&daily=%s&timezone=auto&timeformat=unixtime&forecast_days=16&past_days=7'
           '&forecast_minutely_15=96&past_minutely_15=4'
           % (FORECAST, lat, lon, CURRENT, HOURLY, DAILY))
    data = net.fetch_json(url, timeout=15)
    return {
        'offset': data.get('utc_offset_seconds', 0),
        'tz': data.get('timezone', ''),
        'elevation': data.get('elevation'),
        'current': _section(data, 'current'),
        'minutely': _section(data, 'minutely_15'),
        'hourly': _section(data, 'hourly'),
        'daily': _section(data, 'daily'),
        'fetched': time.time(),
    }


def archive(lat, lon, start, end):
    """Daily max/min temperature (°C) from start to end ('YYYY-MM-DD')."""
    url = ('%s?latitude=%.4f&longitude=%.4f&start_date=%s&end_date=%s'
           '&daily=temperature_2m_max,temperature_2m_min&timezone=auto' % (ARCHIVE, lat, lon, start, end))
    data = net.fetch_json(url, timeout=60)
    daily = data.get('daily') or {}
    return {'time': daily.get('time') or [], 'max': daily.get('temperature_2m_max') or [],
            'min': daily.get('temperature_2m_min') or []}


POLLEN = ('alder_pollen', 'birch_pollen', 'grass_pollen', 'mugwort_pollen', 'olive_pollen', 'ragweed_pollen')


def air_quality(lat, lon):
    url = ('%s?latitude=%.4f&longitude=%.4f&current=us_aqi,us_aqi_pm2_5,us_aqi_pm10,us_aqi_ozone,'
           'us_aqi_nitrogen_dioxide,us_aqi_sulphur_dioxide,us_aqi_carbon_monoxide,pm2_5,pm10,ozone,%s'
           '&hourly=us_aqi&forecast_days=2&timezone=auto&timeformat=unixtime'
           % (AIR, lat, lon, ','.join(POLLEN)))
    data = net.fetch_json(url, timeout=15)
    return {'current': _section(data, 'current'), 'hourly': _section(data, 'hourly'),
            'offset': data.get('utc_offset_seconds', 0)}


def marine(lat, lon):
    url = ('%s?latitude=%.4f&longitude=%.4f&current=wave_height,wave_period,wave_direction,'
           'sea_surface_temperature,swell_wave_height,swell_wave_period'
           '&hourly=wave_height&forecast_days=2&timezone=auto&timeformat=unixtime' % (MARINE, lat, lon))
    data = net.fetch_json(url, timeout=15)
    return {'current': _section(data, 'current'), 'hourly': _section(data, 'hourly')}


def geocode(query, count=10):
    """[(display name, lat, lon)] for a city name or postal code."""
    from urllib.parse import quote
    data = net.fetch_json('%s?name=%s&count=%d&language=en&format=json' % (GEOCODE, quote(query), count))
    out = []
    for r in data.get('results') or []:
        parts = [r.get('name')]
        for key in ('admin1', 'country_code'):
            if r.get(key) and r.get(key) not in parts:
                parts.append(r.get(key))
        out.append((', '.join(p for p in parts if p), r['latitude'], r['longitude']))
    return out
