# -*- coding: utf-8 -*-
"""iNaturalist data layer (no Kodi imports, so it can be tested anywhere)."""
import json
import math
import re
from datetime import date, datetime, timedelta, timezone
from urllib.parse import urlencode
from urllib.request import Request, urlopen

OBS_URL = "https://api.inaturalist.org/v1/observations"
PLACES_URL = "https://api.inaturalist.org/v1/places/autocomplete"
NOMINATIM_URL = "https://nominatim.openstreetmap.org/search"
USER_AGENT = "KodiBirdSightingsScreensaver/1.0 (personal, non-commercial home use)"
OPEN_LICENSES = "cc0,cc-by,cc-by-nc,cc-by-sa,cc-by-nd,cc-by-nc-sa,cc-by-nc-nd"
BIRDS_TAXON_ID = 3  # Aves

_SIZE_RE = re.compile(r"/(?:square|small|medium|large|original)\.")


def _clean(text):
    """Kodi labels interpret [B], $INFO etc., so neutralise user-provided text."""
    if not text:
        return ""
    return str(text).replace("[", "(").replace("]", ")").replace("$", "").strip()


def photo_url(url, size):
    """iNaturalist photo URLs end in square.jpg; swap in medium/large/original."""
    if not url:
        return ""
    return _SIZE_RE.sub("/%s." % size, url, count=1)


def haversine_km(lat1, lng1, lat2, lng2):
    r = 6371.0088
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp = p2 - p1
    dl = math.radians(lng2 - lng1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * r * math.asin(math.sqrt(a))


def _parse_time(obs):
    t = obs.get("time_observed_at")
    if t:
        try:
            return datetime.fromisoformat(t.replace("Z", "+00:00")), True
        except ValueError:
            pass
    d = obs.get("observed_on") or (obs.get("observed_on_details") or {}).get("date")
    if d:
        try:
            return datetime.strptime(d[:10], "%Y-%m-%d"), False
        except ValueError:
            pass
    return None, False


def _parse_latlng(obs):
    loc = obs.get("location")
    if isinstance(loc, str) and "," in loc:
        try:
            a, b = loc.split(",", 1)
            return float(a), float(b)
        except ValueError:
            pass
    coords = (obs.get("geojson") or {}).get("coordinates")
    if coords and len(coords) == 2:
        return float(coords[1]), float(coords[0])
    return None, None


class Sighting(object):
    def __init__(self):
        self.id = 0
        self.common = ""
        self.sci = ""
        self.taxon_id = 0
        self.url_medium = ""
        self.url_large = ""
        self.attribution = ""
        self.user = ""
        self.place = ""
        self.distance_km = None
        self.observed = None
        self.has_time = False
        self.quality = ""

    @property
    def sort_key(self):
        if self.observed is None:
            return 0.0
        try:
            return self.observed.timestamp()
        except (OverflowError, OSError, ValueError):
            return 0.0

    def ago(self, short=False, now=None):
        if self.observed is None:
            return ""
        if self.has_time and self.observed.tzinfo is not None:
            now = now or datetime.now(timezone.utc)
            secs = max(0, (now - self.observed.astimezone(timezone.utc)).total_seconds())
            mins = int(secs // 60)
            if mins < 2:
                return "now" if short else "just now"
            if mins < 60:
                return "%dm" % mins if short else "%d min ago" % mins
            hrs = mins // 60
            if hrs < 24:
                return "%dh" % hrs if short else "%d hr ago" % hrs
            days = hrs // 24
        else:
            days = (date.today() - self.observed.date()).days
            if days <= 0:
                return "today"
        if short:
            return "%dd" % days
        return "yesterday" if days == 1 else "%d days ago" % days

    def distance_text(self, miles=False):
        if self.distance_km is None:
            return ""
        if miles:
            d = self.distance_km * 0.621371
            unit = "mi"
        else:
            d, unit = self.distance_km, "km"
        return ("%.1f %s away" % (d, unit)) if d < 10 else ("%d %s away" % (round(d), unit))


def parse_observation(obs, origin=None):
    photos = obs.get("photos") or []
    if not photos:
        return None
    p0 = photos[0]
    base = p0.get("url") or ""
    if not base:
        return None
    taxon = obs.get("taxon") or {}
    common = (taxon.get("preferred_common_name") or taxon.get("english_common_name")
              or obs.get("species_guess") or taxon.get("name") or "Unidentified bird")
    if common.islower():
        common = common.title()
    s = Sighting()
    s.id = obs.get("id") or 0
    s.common = _clean(common)
    sci = taxon.get("name") or ""
    s.sci = "" if sci.lower() == common.lower() else _clean(sci)
    s.taxon_id = taxon.get("id") or sci or s.common
    s.url_medium = photo_url(base, "medium")
    s.url_large = photo_url(base, "large")
    user = obs.get("user") or {}
    s.user = _clean(user.get("name") or user.get("login"))
    lic = p0.get("license_code")
    s.attribution = _clean(p0.get("attribution") or
                           ("(c) %s, all rights reserved" % (s.user or "unknown")))
    if not lic and "rights reserved" not in s.attribution:
        s.attribution += ", all rights reserved"
    place = _clean(obs.get("place_guess"))
    parts = [x.strip() for x in place.split(",") if x.strip()]
    s.place = ", ".join(parts[:2]) if len(parts) > 2 else place
    s.observed, s.has_time = _parse_time(obs)
    s.quality = obs.get("quality_grade") or ""
    lat, lng = _parse_latlng(obs)
    if origin and lat is not None:
        s.distance_km = haversine_km(origin[0], origin[1], lat, lng)
    return s


def build_params(lat, lng, radius_km, days, max_obs, research_only=False,
                 exclude_captive=True, open_license_only=False, locale="en", today=None):
    today = today or date.today()
    params = {
        "taxon_id": BIRDS_TAXON_ID,
        "photos": "true",
        "d1": (today - timedelta(days=days)).isoformat(),
        "d2": today.isoformat(),
        "lat": "%.5f" % lat,
        "lng": "%.5f" % lng,
        "radius": radius_km,
        "per_page": max(1, min(200, max_obs)),
        "order": "desc",
        "order_by": "observed_on",
        "locale": locale,
    }
    if research_only:
        params["quality_grade"] = "research"
    if exclude_captive:
        params["captive"] = "false"
    if open_license_only:
        params["photo_license"] = OPEN_LICENSES
    return params


def _get_json(url, timeout):
    req = Request(url, headers={"User-Agent": USER_AGENT, "Accept": "application/json"})
    with urlopen(req, timeout=timeout) as r:
        return json.loads(r.read().decode("utf-8"))


def sightings_from_response(data, origin=None):
    out, seen = [], set()
    for obs in data.get("results") or []:
        s = parse_observation(obs, origin)
        if s and s.id not in seen:
            seen.add(s.id)
            out.append(s)
    species = {}
    for s in out:
        species[s.taxon_id] = species.get(s.taxon_id, 0) + 1
    return {"sightings": out, "species_counts": species,
            "total": data.get("total_results", len(out))}


def fetch_sightings(lat, lng, radius_km, days, max_obs, research_only=False,
                    exclude_captive=True, open_license_only=False, timeout=45):
    params = build_params(lat, lng, radius_km, days, max_obs, research_only,
                          exclude_captive, open_license_only)
    data = _get_json(OBS_URL + "?" + urlencode(params), timeout)
    return sightings_from_response(data, (lat, lng))


def geocode(query, timeout=20):
    """Place name -> [{display, short, lat, lng}]. Nominatim first, iNaturalist places as fallback."""
    out = []
    try:
        url = NOMINATIM_URL + "?" + urlencode(
            {"q": query, "format": "jsonv2", "limit": 8, "addressdetails": 1})
        for d in _get_json(url, timeout):
            addr = d.get("address") or {}
            city = (addr.get("city") or addr.get("town") or addr.get("village")
                    or addr.get("hamlet") or addr.get("municipality")
                    or addr.get("county") or d.get("name"))
            state = addr.get("state") or addr.get("country")
            short = ", ".join(x for x in (city, state) if x) or (d.get("display_name") or "")[:40]
            out.append({"display": d.get("display_name") or short, "short": short,
                        "lat": float(d["lat"]), "lng": float(d["lon"])})
    except Exception:
        out = []
    if out:
        return out
    url = PLACES_URL + "?" + urlencode({"q": query, "per_page": 8})
    for d in _get_json(url, timeout).get("results") or []:
        loc = d.get("location") or ""
        if "," not in loc:
            continue
        a, b = loc.split(",", 1)
        name = d.get("display_name") or d.get("name") or query
        out.append({"display": name, "short": name.split(",")[0] + (", " + name.split(",")[-1].strip() if "," in name else ""),
                    "lat": float(a), "lng": float(b)})
    return out
