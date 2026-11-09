// The radar's data model: no GL, no Kodi, no networking. Feed parsing, great-circle work,
// dead reckoning, the sweep clock, contact ageing and the spotlight/list state live here, so
// the renderer and the Python app can share the same rules and the tests can drive time.
#pragma once
#include <array>
#include <cstdint>
#include <string>
#include <vector>

#include "json.hpp"

namespace radar {

constexpr double EARTH_RADIUS_M = 6371008.8;
constexpr double METRES_PER_NM = 1852.0;
constexpr double KT_TO_MS = 0.5144444444444445;
constexpr double FT_TO_M = 0.3048;
constexpr double MAX_EXTRAPOLATION_S = 90.0;
constexpr int MAX_ECHOES = 3;

struct LatLon {
  double lat = 0.0;
  double lon = 0.0;
};

double distance_m(LatLon a, LatLon b);
double bearing_deg(LatLon a, LatLon b);
LatLon destination(LatLon from, double bearing, double distance_m);
double normalize_deg(double d);
double angle_delta(double from, double to);
bool crossed_deg(double previous, double current, double target);
void east_north_m(LatLon home, LatLon p, double* east, double* north);

// Values match tools/vintageradar_settings.py.
struct Settings {
  std::string location_name = "Home";
  double lat = 44.9031331;
  double lon = -93.3096136;
  int range_km = 60;
  int units = 1;  // 0 metric, 1 aviation
  int refresh_seconds = 20;
  bool show_ground = false;
  int min_altitude = 0;  // index: 0 all, 1 >=1000 ft, 2 >=5000 ft, 3 >=10000 ft
  int sweep_seconds = 6;
  bool show_labels = true;
  int label_detail = 1;  // 0 callsign, 1 callsign + altitude/speed, 2 callsign + type
  bool show_history = true;
  int max_contacts = 40;
  bool show_panel = true;
  int detail_seconds = 10;
  int list_seconds = 8;
  int theme = 0;  // 0 P1 green, 1 P3 amber, 2 P11 ice, 3 white
  bool crt = true;
  int dim = 0;
  int quality = 1;  // 0 low, 1 normal, 2 high

  void sanitise();
};

struct Aircraft {
  std::string hex;
  std::string flight;
  std::string reg;
  std::string type_code;   // t: e.g. B738
  std::string category;    // e.g. A3
  std::string emergency;   // e.g. none / general / lifeguard
  std::string squawk;
  std::string type;        // message source, e.g. adsb_icao

  bool has_pos = false;
  double lat = 0.0, lon = 0.0;
  bool on_ground = false;
  bool has_alt = false;
  double alt_ft = 0.0;      // baro, else geometric
  bool has_alt_geom = false;
  double alt_geom_ft = 0.0;
  bool has_gs = false;
  double gs_kt = 0.0;
  bool has_track = false;
  double track = 0.0;
  bool has_baro_rate = false;
  double baro_rate_fpm = 0.0;
  bool has_geom_rate = false;
  double geom_rate_fpm = 0.0;

  bool has_nav_alt = false;
  double nav_alt_ft = 0.0;
  bool has_nav_heading = false;
  double nav_heading = 0.0;
  bool has_nav_qnh = false;
  double nav_qnh = 0.0;
  bool has_ias = false;
  double ias_kt = 0.0;
  bool has_tas = false;
  double tas_kt = 0.0;
  bool has_mach = false;
  double mach = 0.0;
  bool has_mag_heading = false;
  double mag_heading = 0.0;
  bool has_true_heading = false;
  double true_heading = 0.0;

  bool has_seen = false;
  double seen = 0.0;
  bool has_seen_pos = false;
  double seen_pos = 0.0;
  bool has_rssi = false;
  double rssi = 0.0;
  int messages = 0;
  int version = 0;
  bool military = false;
  bool interesting = false;
  bool pia = false;
  bool ladd = false;
  bool alert = false;
  bool spi = false;
  bool has_nac_p = false;
  double nac_p = 0.0;
  bool has_nac_v = false;
  double nac_v = 0.0;
  bool has_sil = false;
  double sil = 0.0;
  bool has_nic = false;
  double nic = 0.0;
  bool has_rc = false;
  double rc_m = 0.0;
  bool mlat = false;
  bool tisb = false;
};

struct Feed {
  std::vector<Aircraft> aircraft;
  double source_time = 0.0;  // seconds since the epoch, as reported by the source
  int total = 0;
  std::string source = "adsb.lol";
};

bool parse_adsblol(const std::string& text, Feed* feed, std::string* error);
bool parse_opensky(const std::string& text, Feed* feed, std::string* error);

struct Echo {
  bool active = false;
  double x = 0.0, y = 0.0;  // normalized to the range circle, x east, y north
  double at_deg = 0.0;      // sweep angle when captured
};

struct Contact {
  Aircraft ac;
  bool fresh = false;
  double first_seen = 0.0;
  double last_seen = 0.0;
  double fix_time = 0.0;    // model clock of the reported fix
  double base_lat = 0.0, base_lon = 0.0;

  double lat = 0.0, lon = 0.0;
  double distance_m = 0.0;
  double bearing_deg = 0.0;
  double x = 0.0, y = 0.0;  // normalized, x east, y north
  bool in_range = false;
  double blip = 0.0;
  bool selected = false;
  std::array<Echo, MAX_ECHOES> echoes{};
  int echo_count = 0;
};

class Model {
 public:
  Model();
  explicit Model(const Settings& settings);

  void set_settings(const Settings& settings);
  const Settings& settings() const { return s_; }

  // `now` is any monotonic seconds clock. The app passes steady_clock elapsed time; tests pass
  // made-up values.
  void apply_feed(const Feed& feed, double now);
  void apply_error(const std::string& error, double now);
  void update(double now);

  const std::vector<Contact>& contacts() const { return contacts_; }
  const std::vector<int>& order() const { return order_; }  // in-range, nearest first
  Contact* find(const std::string& hex);
  const Contact* spotlight() const;
  std::string spotlight_hex() const { return spotlight_hex_; }
  bool pinned() const { return pinned_; }
  void pin(const std::string& hex);
  void unpin();
  void step_spotlight(int delta);
  void set_page(int page);
  int page() const { return page_; }
  int page_count() const;
  int page_rows() const { return page_rows_; }
  void set_page_rows(int rows);

  double sweep_deg() const { return sweep_deg_; }
  double sweep_period() const { return s_.sweep_seconds; }
  double spotlight_changed_at() const { return spotlight_changed_at_; }
  double spotlight_progress() const;
  int spotlight_position() const;  // index in order(), or -1
  double feed_age(double now) const;
  double seconds_to_sweep() const;
  const std::string& feed_error() const { return feed_error_; }
  const std::string& feed_source() const { return feed_source_; }
  bool has_feed() const { return has_feed_; }
  int in_range_count() const { return in_range_count_; }
  int known_count() const { return static_cast<int>(contacts_.size()); }
  bool stale(double now) const;

  void reset_clock(double now);

 private:
  bool passes_filter(const Aircraft& ac) const;
  int min_altitude_ft() const;
  void rebuild_order();
  void update_spotlight(double now, double dt);
  void compute_blip(Contact& c, double now) const;
  void remove_contacts(double now);
  static std::string lower(std::string text);

  Settings s_;
  std::vector<Contact> contacts_;
  std::vector<int> order_;
  std::string spotlight_hex_;
  bool pinned_ = false;
  int page_ = 0;
  int page_rows_ = 9;
  bool page_locked_ = false;
  double spotlight_timer_ = 0.0;
  double spotlight_changed_at_ = 0.0;
  double sweep_deg_ = 0.0;
  double last_update_ = -1.0;
  double last_feed_at_ = -1.0;
  double feed_received_at_ = -1.0;
  double feed_error_at_ = -1.0;
  bool has_feed_ = false;
  std::string feed_error_;
  std::string feed_source_;
  int in_range_count_ = 0;
};

// ---- display formatting (shared by the GL panel and the Python app)
std::string trim_string(std::string text);
std::string upper_string(std::string text);
std::string lower_string(std::string text);
std::string fmt_commas(long long value);
std::string fmt_altitude(const Aircraft& ac, int units, bool compact = false);
std::string fmt_speed(const Aircraft& ac, int units, bool compact = false);
std::string fmt_distance(double metres, int units, bool compact = false);
std::string fmt_vertical_rate(const Aircraft& ac, int units, bool compact = false);
std::string fmt_deg(double value);
std::string fmt_bearing(double value);
std::string fmt_coord(double value, bool latitude);
std::string fmt_seen(double seconds);
std::string aircraft_name(const Aircraft& ac);
std::string category_name(const std::string& code);
std::string source_name(const Aircraft& ac);
std::string emergency_label(const Aircraft& ac);
std::string flag_text(const Aircraft& ac);
std::string range_text(int range_km, int units);
std::string range_short(int range_km, int units);

}  // namespace radar
