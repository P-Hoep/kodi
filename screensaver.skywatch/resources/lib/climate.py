"""Climate normals, records and anomalies from Open-Meteo's ERA5 archive. No Kodi imports.

The archive is fetched once per location (1940 to a week ago) and cached forever; a small
"recent" fetch fills in the last year. Normals use 1991-2020 with a +/-7 day window, giving
about 450 samples per calendar day, stored as 366 rows of mean/p10/p90 of the daily high and
low. Records are the highest high and lowest low on each calendar day since 1940.
"""

import time

NORMAL_YEARS = (1991, 2020)
WINDOW = 7
DAYS = []   # 'MM-DD' for each day of a leap year, index = day of year - 1
for _m, _n in enumerate((31, 29, 31, 30, 31, 30, 31, 31, 30, 31, 30, 31)):
    DAYS += ['%02d-%02d' % (_m + 1, _d + 1) for _d in range(_n)]
INDEX = dict((d, i) for i, d in enumerate(DAYS))
MONTHS = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec']


def _pct(values, p):
    if not values:
        return None
    v = sorted(values)
    k = (len(v) - 1) * p
    lo = int(k)
    hi = min(len(v) - 1, lo + 1)
    return v[lo] + (v[hi] - v[lo]) * (k - lo)


def by_day(archive):
    """{'MM-DD': [(year, max, min)]} from an archive dict of parallel lists."""
    out = {}
    for date, hi, lo in zip(archive.get('time') or [], archive.get('max') or [], archive.get('min') or []):
        if hi is None or lo is None:
            continue
        out.setdefault(date[5:], []).append((int(date[:4]), hi, lo))
    return out


def normals(archive, years=NORMAL_YEARS, window=WINDOW):
    """366 rows of {'hi', 'lo', 'hi10', 'hi90', 'lo10', 'lo90'} (°C), or None rows when missing."""
    days = by_day(archive)
    rows = []
    for i in range(len(DAYS)):
        his, los = [], []
        for k in range(i - window, i + window + 1):
            for year, hi, lo in days.get(DAYS[k % len(DAYS)], ()):
                if years[0] <= year <= years[1]:
                    his.append(hi)
                    los.append(lo)
        if not his:
            rows.append(None)
            continue
        rows.append({'hi': sum(his) / len(his), 'lo': sum(los) / len(los),
                     'hi10': _pct(his, 0.1), 'hi90': _pct(his, 0.9),
                     'lo10': _pct(los, 0.1), 'lo90': _pct(los, 0.9)})
    return rows


def records(archive):
    """366 rows of {'hi': (value, year), 'lo': (value, year)} or None."""
    days = by_day(archive)
    rows = []
    for d in DAYS:
        entries = days.get(d)
        if not entries:
            rows.append(None)
            continue
        hi = max(entries, key=lambda e: (e[1], e[0]))
        lo = min(entries, key=lambda e: (e[2], -e[0]))
        rows.append({'hi': (hi[1], hi[0]), 'lo': (lo[2], lo[0])})
    return rows


def day_label(mmdd):
    m, d = mmdd.split('-')
    return '%s %d' % (MONTHS[int(m) - 1], int(d))


def fact(mmdd, year, high, low, history, normal, units):
    """One sentence about today: 'Warmest Oct 12 since 2015', a record, or near normal."""
    if high is None or normal is None:
        return ''
    label = day_label(mmdd)
    past = [e for e in history.get(mmdd, ()) if e[0] < year]
    first_year = min([e[0] for e in past] or [year])
    anomaly = high - normal['hi']
    if anomaly >= 2.5:
        warmer = [e[0] for e in past if e[1] >= high]
        if not warmer:
            return 'Warmest %s since records began in %d' % (label, first_year)
        return 'Warmest %s since %d' % (label, max(warmer))
    if anomaly <= -2.5:
        colder = [e[0] for e in past if e[1] <= high]
        if not colder:
            return 'Coldest %s high since records began in %d' % (label, first_year)
        return 'Coldest %s high since %d' % (label, max(colder))
    word = 'above' if anomaly > 0 else 'below'
    if abs(units.dt(anomaly)) < 0.5:
        return 'Right at the normal high for %s' % label
    return "Today's high is %d° %s normal" % (abs(int(round(units.dt(anomaly)))), word)


def merge_daily(*sources):
    """Merge dicts of {'time': ['YYYY-MM-DD'], 'max': [], 'min': []}; later sources win."""
    rows = {}
    for src in sources:
        for date, hi, lo in zip(src.get('time') or [], src.get('max') or [], src.get('min') or []):
            if hi is not None and lo is not None:
                rows[date] = (hi, lo)
    dates = sorted(rows)
    return {'time': dates, 'max': [rows[d][0] for d in dates], 'min': [rows[d][1] for d in dates]}


def forecast_daily(fc):
    """The forecast's daily max/min as an archive-shaped dict (dates in the location's time)."""
    daily = (fc or {}).get('daily') or {}
    offset = (fc or {}).get('offset', 0)
    dates = [time.strftime('%Y-%m-%d', time.gmtime(t + offset)) for t in daily.get('time') or []]
    return {'time': dates, 'max': daily.get('temperature_2m_max') or [], 'min': daily.get('temperature_2m_min') or []}


def anomalies(daily, normal_rows, dates):
    """Daily mean anomaly (°C) for each 'YYYY-MM-DD' in dates (None where unknown)."""
    lookup = dict(zip(daily['time'], zip(daily['max'], daily['min'])))
    out = []
    for date in dates:
        v = lookup.get(date)
        n = normal_rows[INDEX[date[5:]]] if date[5:] in INDEX else None
        if v is None or n is None:
            out.append(None)
        else:
            out.append((v[0] + v[1]) / 2.0 - (n['hi'] + n['lo']) / 2.0)
    return out
