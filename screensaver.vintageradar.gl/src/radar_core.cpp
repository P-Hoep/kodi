#include "radar_core.hpp"

#include <algorithm>
#include <cctype>
#include <cmath>
#include <cstdio>
#include <cstdlib>
#include <cstring>
#include <sstream>

namespace radar {
namespace {
constexpr double PI = 3.14159265358979323846;
constexpr double DEG = PI / 180.0;
constexpr double RAD = 180.0 / PI;

double clampd(double v, double lo, double hi) { return v < lo ? lo : (v > hi ? hi : v); }
int clampi(int v, int lo, int hi) { return v < lo ? lo : (v > hi ? hi : v); }

std::string squawk_text(const Json* j) {
  if (!j) return "";
  if (j->type == Json::Str) return j->str;
  if (j->type == Json::Num) {
    char b[16];
    std::snprintf(b, sizeof b, "%04.0f", j->num);
    return b;
  }
  return "";
}

[[maybe_unused]] std::string one_decimal(double v, int precision = 1) {
  char b[48];
  std::snprintf(b, sizeof b, "%.*f", precision, v);
  return b;
}
}  // namespace

// ---- geometry ------------------------------------------------------------------------------

double distance_m(LatLon a, LatLon b) {
  const double p1 = a.lat * DEG, p2 = b.lat * DEG;
  const double dp = (b.lat - a.lat) * DEG, dl = (b.lon - a.lon) * DEG;
  const double h = std::sin(dp / 2) * std::sin(dp / 2) +
                   std::cos(p1) * std::cos(p2) * std::sin(dl / 2) * std::sin(dl / 2);
  return 2.0 * EARTH_RADIUS_M * std::asin(std::sqrt(clampd(h, 0.0, 1.0)));
}

double bearing_deg(LatLon a, LatLon b) {
  const double p1 = a.lat * DEG, p2 = b.lat * DEG;
  const double dl = (b.lon - a.lon) * DEG;
  const double y = std::sin(dl) * std::cos(p2);
  const double x = std::cos(p1) * std::sin(p2) - std::sin(p1) * std::cos(p2) * std::cos(dl);
  return normalize_deg(std::atan2(y, x) * RAD);
}

LatLon destination(LatLon from, double bearing, double distance) {
  if (distance <= 0.0) return from;
  const double d = distance / EARTH_RADIUS_M;
  const double brg = bearing * DEG;
  const double p1 = from.lat * DEG, l1 = from.lon * DEG;
  const double p2 = std::asin(std::sin(p1) * std::cos(d) + std::cos(p1) * std::sin(d) * std::cos(brg));
  const double l2 = l1 + std::atan2(std::sin(brg) * std::sin(d) * std::cos(p1),
                                    std::cos(d) - std::sin(p1) * std::sin(p2));
  LatLon out;
  out.lat = p2 * RAD;
  out.lon = std::fmod(l2 * RAD + 540.0, 360.0) - 180.0;
  return out;
}

double normalize_deg(double d) {
  d = std::fmod(d, 360.0);
  return d < 0.0 ? d + 360.0 : d;
}

double angle_delta(double from, double to) {
  return std::fmod(to - from + 540.0, 360.0) - 180.0;
}

bool crossed_deg(double previous, double current, double target) {
  previous = normalize_deg(previous);
  current = normalize_deg(current);
  target = normalize_deg(target);
  if (previous == current) return false;
  if (previous < current) return target > previous && target <= current;
  return target > previous || target <= current;  // the sweep wrapped past north
}

void east_north_m(LatLon home, LatLon p, double* east, double* north) {
  const double mid = (home.lat + p.lat) * 0.5 * DEG;
  *north = (p.lat - home.lat) * DEG * EARTH_RADIUS_M;
  *east = (p.lon - home.lon) * DEG * EARTH_RADIUS_M * std::cos(mid);
}

// ---- settings ------------------------------------------------------------------------------

void Settings::sanitise() {
  if (!(lat >= -90.0 && lat <= 90.0)) lat = 0.0;
  if (!(lon >= -180.0 && lon <= 180.0)) lon = 0.0;
  while (lon < -180.0) lon += 360.0;
  while (lon > 180.0) lon -= 360.0;
  range_km = clampi(range_km, 5, 400);
  units = clampi(units, 0, 1);
  refresh_seconds = clampi(refresh_seconds, 10, 120);
  min_altitude = clampi(min_altitude, 0, 3);
  sweep_seconds = clampi(sweep_seconds, 2, 12);
  label_detail = clampi(label_detail, 0, 2);
  max_contacts = clampi(max_contacts, 5, 200);
  detail_seconds = clampi(detail_seconds, 4, 60);
  list_seconds = clampi(list_seconds, 3, 60);
  theme = clampi(theme, 0, 3);
  dim = clampi(dim, 0, 80);
  quality = clampi(quality, 0, 2);
  location_name = trim_string(location_name);
  if (location_name.empty()) location_name = "Home";
}

// ---- feed parsing --------------------------------------------------------------------------

bool parse_adsblol(const std::string& text, Feed* feed, std::string* error) {
  try {
    const Json root = Json::parse(text);
    if (!root.is_obj()) {
      *error = "adsb.lol: response is not an object";
      return false;
    }
    feed->source = "adsb.lol";
    feed->aircraft.clear();
    feed->source_time = root.num_or("now", 0.0);
    if (feed->source_time > 1e11) feed->source_time /= 1000.0;  // milliseconds
    const Json* ac = root.get("ac");
    if (!ac || !ac->is_arr()) {
      *error = "adsb.lol: no aircraft list";
      return false;
    }
    feed->total = static_cast<int>(ac->arr.size());
    feed->aircraft.reserve(ac->arr.size());
    for (const Json& j : ac->arr) {
      if (!j.is_obj()) continue;
      Aircraft a;
      a.hex = lower_string(j.str_or("hex"));
      double lat = 0.0, lon = 0.0;
      if (a.hex.empty() || !j.has_num("lat", &lat) || !j.has_num("lon", &lon)) continue;
      if (!(lat >= -90.0 && lat <= 90.0 && lon >= -180.0 && lon <= 180.0)) continue;
      a.lat = lat;
      a.lon = lon;
      a.has_pos = true;
      a.flight = trim_string(j.str_or("flight"));
      a.reg = trim_string(j.str_or("r"));
      a.type_code = trim_string(j.str_or("t"));
      a.category = trim_string(j.str_or("category"));
      a.emergency = trim_string(j.str_or("emergency"));
      a.type = trim_string(j.str_or("type"));
      a.squawk = squawk_text(j.get("squawk"));

      const Json* alt = j.get("alt_baro");
      if (alt && alt->type == Json::Str && alt->str == "ground") {
        a.on_ground = true;
      } else if (alt && alt->number(&a.alt_ft)) {
        a.has_alt = true;
      }
      if (j.has_num("alt_geom", &a.alt_geom_ft)) {
        a.has_alt_geom = true;
        if (!a.has_alt && !a.on_ground) {
          a.alt_ft = a.alt_geom_ft;
          a.has_alt = true;
        }
      }
      a.has_gs = j.has_num("gs", &a.gs_kt);
      a.has_track = j.has_num("track", &a.track);
      if (!a.has_track && j.has_num("true_heading", &a.track)) a.has_track = true;
      a.has_baro_rate = j.has_num("baro_rate", &a.baro_rate_fpm);
      a.has_geom_rate = j.has_num("geom_rate", &a.geom_rate_fpm);
      a.has_nav_alt = j.has_num("nav_altitude_mcp", &a.nav_alt_ft);
      a.has_nav_heading = j.has_num("nav_heading", &a.nav_heading);
      a.has_nav_qnh = j.has_num("nav_qnh", &a.nav_qnh);
      a.has_ias = j.has_num("ias", &a.ias_kt);
      a.has_tas = j.has_num("tas", &a.tas_kt);
      a.has_mach = j.has_num("mach", &a.mach);
      a.has_mag_heading = j.has_num("mag_heading", &a.mag_heading);
      a.has_true_heading = j.has_num("true_heading", &a.true_heading);
      a.has_seen = j.has_num("seen", &a.seen);
      a.has_seen_pos = j.has_num("seen_pos", &a.seen_pos);
      a.has_rssi = j.has_num("rssi", &a.rssi);
      a.messages = static_cast<int>(j.num_or("messages", 0));
      a.version = static_cast<int>(j.num_or("version", 0));

      double flags = 0.0;
      if (j.has_num("dbFlags", &flags)) {
        const int f = static_cast<int>(flags);
        a.military = (f & 1) != 0;
        a.interesting = (f & 2) != 0;
        a.pia = (f & 4) != 0;
        a.ladd = (f & 8) != 0;
      }
      a.alert = j.bool_or("alert", false);
      a.spi = j.bool_or("spi", false);
      a.has_nac_p = j.has_num("nac_p", &a.nac_p);
      a.has_nac_v = j.has_num("nac_v", &a.nac_v);
      a.has_sil = j.has_num("sil", &a.sil);
      a.has_nic = j.has_num("nic", &a.nic);
      a.has_rc = j.has_num("rc", &a.rc_m);
      const Json* mlat = j.get("mlat");
      const Json* tisb = j.get("tisb");
      a.mlat = mlat && mlat->is_arr() && !mlat->arr.empty();
      a.tisb = tisb && tisb->is_arr() && !tisb->arr.empty();
      feed->aircraft.push_back(std::move(a));
    }
    error->clear();
    return true;
  } catch (const std::exception& e) {
    *error = std::string("adsb.lol: ") + e.what();
    return false;
  }
}

bool parse_opensky(const std::string& text, Feed* feed, std::string* error) {
  try {
    const Json root = Json::parse(text);
    if (!root.is_obj()) {
      *error = "OpenSky: response is not an object";
      return false;
    }
    feed->source = "OpenSky";
    feed->aircraft.clear();
    feed->source_time = root.num_or("time", 0.0);
    const Json* states = root.get("states");
    if (!states) {
      // OpenSky answers {"time": ...} with no states when the bbox is empty.
      feed->total = 0;
      error->clear();
      return true;
    }
    if (!states->is_arr()) {
      *error = "OpenSky: states is not an array";
      return false;
    }
    feed->total = static_cast<int>(states->arr.size());
    for (const Json& s : states->arr) {
      if (!s.is_arr() || s.arr.size() < 17) continue;
      const auto& v = s.arr;
      Aircraft a;
      a.hex = lower_string(v[0].type == Json::Str ? v[0].str : "");
      if (a.hex.empty()) continue;
      double lon = 0.0, lat = 0.0;
      if (!v[5].number(&lon) || !v[6].number(&lat)) continue;
      if (!(lat >= -90.0 && lat <= 90.0 && lon >= -180.0 && lon <= 180.0)) continue;
      a.lon = lon;
      a.lat = lat;
      a.has_pos = true;
      a.flight = trim_string(v[1].type == Json::Str ? v[1].str : "");
      a.on_ground = v[8].type == Json::Bool ? v[8].boolean : (v[8].type == Json::Num && v[8].num != 0);
      double value = 0.0;
      if (v[7].number(&value)) {
        a.alt_ft = value / FT_TO_M;
        a.has_alt = true;
      }
      if (v[13].number(&value)) {
        a.alt_geom_ft = value / FT_TO_M;
        a.has_alt_geom = true;
        if (!a.has_alt) {
          a.alt_ft = a.alt_geom_ft;
          a.has_alt = true;
        }
      }
      if (v[9].number(&value)) {
        a.gs_kt = value / KT_TO_MS;
        a.has_gs = true;
      }
      if (v[10].number(&value)) {
        a.track = normalize_deg(value);
        a.has_track = true;
      }
      if (v[11].number(&value)) {
        a.baro_rate_fpm = value / (FT_TO_M / 60.0);
        a.has_baro_rate = true;
      }
      a.squawk = v[14].type == Json::Str ? v[14].str : squawk_text(&v[14]);
      a.spi = v[15].type == Json::Bool ? v[15].boolean : (v[15].type == Json::Num && v[15].num != 0);
      const int category =
          v.size() > 17 && v[17].type == Json::Num ? static_cast<int>(v[17].num) : 0;
      static const char* kCategories[20] = {
          "",     "A1", "A2", "A3", "A4", "A5", "A6", "A7", "B1", "B2", "B3",
          "B4",   "B5", "B6", "B7", "C1", "C2", "C3", "C4", "C5"};
      if (category > 0 && category < 20) a.category = kCategories[category];
      a.type = "opensky";
      const double time_position = v[3].type == Json::Num ? v[3].num : 0.0;
      if (time_position > 0.0 && feed->source_time > 0.0) {
        a.seen_pos = std::max(0.0, feed->source_time - time_position);
        a.has_seen_pos = true;
      }
      feed->aircraft.push_back(std::move(a));
    }
    error->clear();
    return true;
  } catch (const std::exception& e) {
    *error = std::string("OpenSky: ") + e.what();
    return false;
  }
}

// ---- model ---------------------------------------------------------------------------------

Model::Model() { s_.sanitise(); }

Model::Model(const Settings& settings) : s_(settings) { s_.sanitise(); }

void Model::set_settings(const Settings& settings) {
  s_ = settings;
  s_.sanitise();
  update(last_update_ < 0.0 ? 0.0 : last_update_);
}

std::string Model::lower(std::string text) { return lower_string(text); }

bool Model::passes_filter(const Aircraft& ac) const {
  if (!ac.has_pos) return false;
  if (ac.on_ground && !s_.show_ground) return false;
  if (!ac.on_ground) {
    const int floor_ft = min_altitude_ft();
    if (floor_ft > 0 && ac.has_alt && ac.alt_ft < floor_ft) return false;
  }
  return true;
}

int Model::min_altitude_ft() const {
  static const int kFeet[4] = {0, 1000, 5000, 10000};
  return kFeet[clampi(s_.min_altitude, 0, 3)];
}

void Model::apply_feed(const Feed& feed, double now) {
  std::vector<bool> seen(contacts_.size(), false);
  for (const Aircraft& a : feed.aircraft) {
    if (!passes_filter(a)) continue;
    const std::string hex = lower(a.hex);
    if (hex.empty()) continue;
    int found = -1;
    for (size_t i = 0; i < contacts_.size(); ++i) {
      if (lower(contacts_[i].ac.hex) == hex) {
        found = static_cast<int>(i);
        break;
      }
    }
    const double age = a.has_seen_pos ? clampd(a.seen_pos, 0.0, 300.0) : 0.0;
    if (found < 0) {
      Contact c;
      c.ac = a;
      c.first_seen = now;
      c.last_seen = now;
      c.fix_time = now - age;
      c.base_lat = a.lat;
      c.base_lon = a.lon;
      c.lat = a.lat;
      c.lon = a.lon;
      c.fresh = true;
      contacts_.push_back(std::move(c));
      seen.push_back(true);
    } else {
      Contact& c = contacts_[found];
      c.ac = a;
      c.fresh = true;
      c.last_seen = now;
      c.fix_time = now - age;
      c.base_lat = a.lat;
      c.base_lon = a.lon;
      // A new fix may be much newer than the last one; keep the last known position as the
      // basis for this frame's prediction rather than jumping the blip mid-frame.
      c.lat = a.lat;
      c.lon = a.lon;
      seen[static_cast<size_t>(found)] = true;
    }
  }
  for (size_t i = 0; i < contacts_.size(); ++i) {
    if (!seen[i]) contacts_[i].fresh = false;
  }
  has_feed_ = true;
  last_feed_at_ = now;
  feed_received_at_ = now;
  feed_error_.clear();
  feed_source_ = feed.source;
  feed_error_at_ = -1.0;
}

void Model::apply_error(const std::string& error, double now) {
  feed_error_ = error;
  feed_error_at_ = now;
}

double Model::feed_age(double now) const {
  return feed_received_at_ < 0.0 ? -1.0 : std::max(0.0, now - feed_received_at_);
}

bool Model::stale(double now) const {
  return !has_feed_ || feed_age(now) > s_.refresh_seconds * 3.0;
}

void Model::remove_contacts(double now) {
  contacts_.erase(std::remove_if(contacts_.begin(), contacts_.end(),
                                 [&](const Contact& c) {
                                   return !passes_filter(c.ac) || now - c.last_seen > 90.0;
                                 }),
                  contacts_.end());
}

void Model::update(double now) {
  double dt = last_update_ < 0.0 ? 0.0 : std::max(0.0, now - last_update_);
  dt = std::min(dt, 5.0);  // a paused/backgrounded app does not teleport the sweep
  if (dt > 0.0) {
    sweep_deg_ = normalize_deg(sweep_deg_ + 360.0 * dt / std::max(1.0, sweep_period()));
  }
  const double range_m = s_.range_km * 1000.0;
  const LatLon home{s_.lat, s_.lon};

  for (Contact& c : contacts_) {
    double age = now - c.fix_time;
    age = clampd(age, 0.0, MAX_EXTRAPOLATION_S);
    LatLon p{c.base_lat, c.base_lon};
    if (!c.ac.on_ground && c.ac.has_gs && c.ac.has_track && c.ac.gs_kt > 0.5) {
      p = destination(p, c.ac.track, c.ac.gs_kt * KT_TO_MS * age);
    }
    c.lat = p.lat;
    c.lon = p.lon;
    c.distance_m = distance_m(home, p);
    c.bearing_deg = c.distance_m > 1.0 ? bearing_deg(home, p) : 0.0;
    double east = 0.0, north = 0.0;
    east_north_m(home, p, &east, &north);
    c.x = east / range_m;
    c.y = north / range_m;
    c.in_range = c.distance_m <= range_m;

    if (c.in_range && crossed_deg(sweep_deg_ - 360.0 * dt / std::max(1.0, sweep_period()),
                                 sweep_deg_, c.bearing_deg)) {
      for (int i = MAX_ECHOES - 1; i > 0; --i) c.echoes[static_cast<size_t>(i)] = c.echoes[static_cast<size_t>(i - 1)];
      c.echoes[0] = Echo{true, c.x, c.y, sweep_deg_};
      c.echo_count = std::min(MAX_ECHOES, c.echo_count + 1);
    }
    compute_blip(c, now);
  }

  remove_contacts(now);
  rebuild_order();
  update_spotlight(now, dt);
  last_update_ = now;
}

void Model::compute_blip(Contact& c, double now) const {
  const double since = normalize_deg(sweep_deg_ - c.bearing_deg);
  double alpha = 0.14 + 0.86 * std::exp(-since / (360.0 * 0.22));
  if (since < 90.0) alpha += 0.85 * std::exp(-since / 10.0);
  if (!c.fresh) {
    const double fade = clampd(1.0 - (now - c.last_seen) / 75.0, 0.0, 1.0);
    alpha *= 0.30 + 0.70 * fade;
  }
  if (c.ac.military) alpha *= 1.15;
  if (c.selected) alpha = std::max(alpha, 0.95);
  c.blip = clampd(alpha, 0.0, 1.7);
}

void Model::rebuild_order() {
  order_.clear();
  in_range_count_ = 0;
  for (size_t i = 0; i < contacts_.size(); ++i) {
    if (contacts_[i].in_range) {
      ++in_range_count_;
      order_.push_back(static_cast<int>(i));
    }
  }
  std::sort(order_.begin(), order_.end(), [&](int a, int b) {
    if (contacts_[static_cast<size_t>(a)].distance_m != contacts_[static_cast<size_t>(b)].distance_m)
      return contacts_[static_cast<size_t>(a)].distance_m < contacts_[static_cast<size_t>(b)].distance_m;
    return aircraft_name(contacts_[static_cast<size_t>(a)].ac) <
           aircraft_name(contacts_[static_cast<size_t>(b)].ac);
  });
  if (static_cast<int>(order_.size()) > s_.max_contacts) {
    // Keep the nearest contacts plus every emergency, which must never be crowded out.
    std::vector<int> kept;
    for (int i = 0; i < static_cast<int>(order_.size()); ++i) {
      const Contact& c = contacts_[static_cast<size_t>(order_[static_cast<size_t>(i)])];
      const bool emergency = !emergency_label(c.ac).empty();
      if (i < s_.max_contacts || emergency) kept.push_back(order_[static_cast<size_t>(i)]);
    }
    order_.swap(kept);
  }
}

Contact* Model::find(const std::string& hex) {
  const std::string key = lower(hex);
  for (Contact& c : contacts_)
    if (lower(c.ac.hex) == key) return &c;
  return nullptr;
}

const Contact* Model::spotlight() const {
  for (const Contact& c : contacts_)
    if (lower(c.ac.hex) == spotlight_hex_) return &c;
  return nullptr;
}

int Model::page_count() const {
  const int n = static_cast<int>(order_.size());
  return std::max(1, (n + page_rows_ - 1) / page_rows_);
}

void Model::set_page_rows(int rows) { page_rows_ = std::max(1, rows); }

void Model::set_page(int page) {
  page_locked_ = true;
  page_ = clampi(page, 0, page_count() - 1);
}

void Model::update_spotlight(double now, double dt) {
  if (order_.empty()) {
    spotlight_hex_.clear();
    pinned_ = false;
    page_ = 0;
    page_locked_ = false;
    spotlight_timer_ = 0.0;
    for (Contact& c : contacts_) c.selected = false;
    return;
  }
  int pos = -1;
  for (size_t i = 0; i < order_.size(); ++i) {
    if (lower(contacts_[static_cast<size_t>(order_[i])].ac.hex) == spotlight_hex_) {
      pos = static_cast<int>(i);
      break;
    }
  }
  if (pos < 0) {
    // The spotlight plane left the screen: fall back to the nearest, and let auto-rotation
    // resume even if the user had pinned it.
    pinned_ = false;
    page_locked_ = false;
    pos = 0;
    spotlight_hex_ = lower(contacts_[static_cast<size_t>(order_[0])].ac.hex);
    spotlight_timer_ = 0.0;
    spotlight_changed_at_ = now;
  } else if (!pinned_ && dt > 0.0) {
    spotlight_timer_ += dt;
    if (spotlight_timer_ >= std::max(1.0, static_cast<double>(s_.detail_seconds))) {
      spotlight_timer_ = 0.0;
      pos = (pos + 1) % static_cast<int>(order_.size());
      spotlight_hex_ = lower(contacts_[static_cast<size_t>(order_[static_cast<size_t>(pos)])].ac.hex);
      spotlight_changed_at_ = now;
      page_locked_ = false;
    }
  }
  if (!page_locked_) page_ = pos / page_rows_;
  page_ = clampi(page_, 0, page_count() - 1);
  for (Contact& c : contacts_) c.selected = (lower(c.ac.hex) == spotlight_hex_);
}

void Model::pin(const std::string& hex) {
  const std::string key = lower(hex);
  for (size_t i = 0; i < order_.size(); ++i) {
    if (lower(contacts_[static_cast<size_t>(order_[i])].ac.hex) == key) {
      pinned_ = true;
      spotlight_hex_ = key;
      spotlight_timer_ = 0.0;
      spotlight_changed_at_ = last_update_ < 0.0 ? 0.0 : last_update_;
      page_locked_ = false;
      page_ = static_cast<int>(i) / page_rows_;
      for (Contact& c : contacts_) c.selected = (lower(c.ac.hex) == spotlight_hex_);
      return;
    }
  }
}

void Model::unpin() {
  pinned_ = false;
  spotlight_timer_ = 0.0;
}

void Model::step_spotlight(int delta) {
  if (order_.empty()) return;
  int pos = -1;
  for (size_t i = 0; i < order_.size(); ++i) {
    if (lower(contacts_[static_cast<size_t>(order_[i])].ac.hex) == spotlight_hex_) {
      pos = static_cast<int>(i);
      break;
    }
  }
  if (pos < 0) pos = 0;
  int next = (pos + delta) % static_cast<int>(order_.size());
  if (next < 0) next += static_cast<int>(order_.size());
  pin(contacts_[static_cast<size_t>(order_[static_cast<size_t>(next)])].ac.hex);
}

double Model::seconds_to_sweep() const {
  const double period = std::max(1.0, sweep_period());
  return (360.0 - sweep_deg_) / 360.0 * period;
}

double Model::spotlight_progress() const {
  if (pinned_) return 0.0;
  return clampd(spotlight_timer_ / std::max(1.0, static_cast<double>(s_.detail_seconds)), 0.0, 1.0);
}

int Model::spotlight_position() const {
  for (size_t i = 0; i < order_.size(); ++i)
    if (lower(contacts_[static_cast<size_t>(order_[i])].ac.hex) == spotlight_hex_)
      return static_cast<int>(i);
  return -1;
}

void Model::reset_clock(double now) {
  last_update_ = now;
  sweep_deg_ = 0.0;
}

// ---- formatting ----------------------------------------------------------------------------

std::string trim_string(std::string text) {
  size_t a = 0, b = text.size();
  while (a < b && std::isspace(static_cast<unsigned char>(text[a]))) ++a;
  while (b > a && std::isspace(static_cast<unsigned char>(text[b - 1]))) --b;
  return text.substr(a, b - a);
}

std::string upper_string(std::string text) {
  for (char& c : text) c = static_cast<char>(std::toupper(static_cast<unsigned char>(c)));
  return text;
}

std::string lower_string(std::string text) {
  for (char& c : text) c = static_cast<char>(std::tolower(static_cast<unsigned char>(c)));
  return text;
}

std::string fmt_commas(long long value) {
  const bool negative = value < 0;
  const std::string digits = std::to_string(negative ? -value : value);
  std::string out;
  const int n = static_cast<int>(digits.size());
  for (int i = 0; i < n; ++i) {
    if (i > 0 && (n - i) % 3 == 0) out += ',';
    out += digits[static_cast<size_t>(i)];
  }
  return negative ? "-" + out : out;
}

std::string fmt_altitude(const Aircraft& ac, int units, bool compact) {
  if (ac.on_ground) return "GND";
  if (!ac.has_alt) return "N/A";
  if (units == 1) {
    if (ac.alt_ft >= 18000.0) {
      char b[32];
      std::snprintf(b, sizeof b, "FL%03d", static_cast<int>(std::lround(ac.alt_ft / 100.0)));
      return b;
    }
    return fmt_commas(static_cast<long long>(std::lround(ac.alt_ft))) + (compact ? "FT" : " FT");
  }
  const long long metres = static_cast<long long>(std::lround(ac.alt_ft * FT_TO_M));
  return fmt_commas(metres) + (compact ? "M" : " M");
}

std::string fmt_speed(const Aircraft& ac, int units, bool compact) {
  if (!ac.has_gs) return "N/A";
  if (units == 1)
    return fmt_commas(static_cast<long long>(std::lround(ac.gs_kt))) + (compact ? "KT" : " KT");
  return fmt_commas(static_cast<long long>(std::lround(ac.gs_kt * 1.852))) +
         (compact ? "KM/H" : " KM/H");
}

std::string fmt_distance(double metres, int units, bool compact) {
  if (metres < 0.0) return "N/A";
  char b[48];
  if (units == 1) {
    const double nm = metres / METRES_PER_NM;
    if (nm < 100.0)
      std::snprintf(b, sizeof b, "%.1f%s", nm, compact ? "NM" : " NM");
    else
      std::snprintf(b, sizeof b, "%.0f%s", nm, compact ? "NM" : " NM");
  } else if (metres < 1000.0) {
    std::snprintf(b, sizeof b, "%.0f%s", metres, compact ? "M" : " M");
  } else if (metres < 10000.0) {
    std::snprintf(b, sizeof b, "%.1f%s", metres / 1000.0, compact ? "KM" : " KM");
  } else {
    std::snprintf(b, sizeof b, "%.0f%s", metres / 1000.0, compact ? "KM" : " KM");
  }
  return b;
}

std::string fmt_vertical_rate(const Aircraft& ac, int units, bool compact) {
  if (!ac.has_baro_rate && !ac.has_geom_rate) return "LEVEL";
  const double fpm = ac.has_baro_rate ? ac.baro_rate_fpm : ac.geom_rate_fpm;
  if (std::fabs(fpm) < 50.0) return "LEVEL";
  char b[48];
  if (units == 1)
    std::snprintf(b, sizeof b, "%+lld%s", static_cast<long long>(std::lround(fpm / 5.0) * 5.0),
                  compact ? "FPM" : " FPM");
  else
    std::snprintf(b, sizeof b, "%+.1f%s", fpm * 0.00508, compact ? "M/S" : " M/S");
  return b;
}

std::string fmt_deg(double value) {
  char b[32];
  std::snprintf(b, sizeof b, "%03d°", static_cast<int>(std::lround(normalize_deg(value))) % 360);
  return b;
}

std::string fmt_bearing(double value) { return fmt_deg(value); }

std::string fmt_coord(double value, bool latitude) {
  char b[48];
  const char hemi = latitude ? (value < 0 ? 'S' : 'N') : (value < 0 ? 'W' : 'E');
  std::snprintf(b, sizeof b, "%.4f%c", std::fabs(value), hemi);
  return b;
}

std::string fmt_seen(double seconds) {
  if (seconds < 0.0) return "N/A";
  char b[32];
  if (seconds < 10.0)
    std::snprintf(b, sizeof b, "%.1f s", seconds);
  else if (seconds < 120.0)
    std::snprintf(b, sizeof b, "%.0f s", seconds);
  else
    std::snprintf(b, sizeof b, "%.0f min", seconds / 60.0);
  return b;
}

std::string aircraft_name(const Aircraft& ac) {
  std::string name = upper_string(trim_string(ac.flight));
  if (name.empty()) name = upper_string(trim_string(ac.reg));
  if (name.empty()) name = upper_string(trim_string(ac.hex));
  return name;
}

std::string category_name(const std::string& code) {
  static const struct {
    const char* code;
    const char* name;
  } kNames[] = {
      {"A1", "LIGHT"},       {"A2", "SMALL"},        {"A3", "LARGE"},
      {"A4", "HIGH VORTEX"}, {"A5", "HEAVY"},        {"A6", "HIGH PERF"},
      {"A7", "ROTORCRAFT"},  {"B1", "GLIDER"},       {"B2", "LIGHTER-THAN-AIR"},
      {"B3", "PARACHUTIST"}, {"B4", "ULTRALIGHT"},   {"B5", "RESERVED"},
      {"B6", "UAV"},         {"B7", "SPACE"},        {"C1", "SURFACE EMERG"},
      {"C2", "SURFACE SERVICE"}, {"C3", "POINT OBSTACLE"}, {"C4", "CLUSTER OBSTACLE"},
      {"C5", "LINE OBSTACLE"}, {"A0", "NO INFO"},    {"B0", "NO INFO"},
      {"C0", "NO INFO"}};
  const std::string up = upper_string(trim_string(code));
  for (const auto& n : kNames)
    if (up == n.code) return n.name;
  return up;
}

std::string source_name(const Aircraft& ac) {
  if (ac.mlat) return "MLAT";
  if (ac.tisb) return "TIS-B";
  const std::string t = lower_string(ac.type);
  if (t.find("adsb") == 0) return "ADS-B";
  if (t == "mode_s") return "MODE S";
  if (t == "adsr") return "ADS-R";
  if (t == "opensky") return "OPENSKY";
  return t.empty() ? "UNKNOWN" : upper_string(t);
}

std::string emergency_label(const Aircraft& ac) {
  const std::string e = upper_string(trim_string(ac.emergency));
  if (!e.empty() && e != "NONE") return e;
  if (ac.squawk == "7500") return "HIJACK";
  if (ac.squawk == "7600") return "RADIO FAIL";
  if (ac.squawk == "7700") return "EMERGENCY";
  return "";
}

std::string flag_text(const Aircraft& ac) {
  std::vector<std::string> flags;
  if (ac.military) flags.push_back("MILITARY");
  const std::string e = emergency_label(ac);
  if (!e.empty()) flags.push_back(e);
  if (ac.interesting) flags.push_back("INTERESTING");
  if (ac.pia) flags.push_back("PIA");
  if (ac.ladd) flags.push_back("LADD");
  if (ac.alert) flags.push_back("ALERT");
  if (ac.spi) flags.push_back("SPI");
  std::string out;
  for (const std::string& f : flags) {
    if (!out.empty()) out += " · ";
    out += f;
  }
  return out;
}

std::string range_text(int range_km, int units) {
  if (units == 1) {
    char b[64];
    std::snprintf(b, sizeof b, "%d KM / %d NM", range_km,
                  static_cast<int>(std::lround(range_km / 1.852)));
    return b;
  }
  return std::to_string(range_km) + " KM";
}

std::string range_short(int range_km, int units) {
  if (units == 1) {
    char b[48];
    std::snprintf(b, sizeof b, "%dNM", static_cast<int>(std::lround(range_km / 1.852)));
    return b;
  }
  return std::to_string(range_km) + "KM";
}

}  // namespace radar
