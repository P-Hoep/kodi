// Core tests: geometry, feed parsing, contact ageing, the sweep clock, filters and formatting.
// No GL, no Kodi, no network. Pass the fixtures directory as argv[1] (ctest does that).
#include <cmath>
#include <cstdio>
#include <fstream>
#include <sstream>
#include <string>

#include "radar_core.hpp"
#include "radar_feed.hpp"

using namespace radar;

static int failures = 0;

#define CHECK(cond)                                                       \
  do {                                                                    \
    if (!(cond)) {                                                        \
      std::printf("FAIL %s:%d  %s\n", __FILE__, __LINE__, #cond);         \
      ++failures;                                                         \
    }                                                                     \
  } while (0)

static std::string slurp(const std::string& path) {
  std::ifstream in(path, std::ios::binary);
  std::stringstream ss;
  ss << in.rdbuf();
  return ss.str();
}

static bool near(double a, double b, double eps) { return std::fabs(a - b) <= eps; }

static void test_geometry() {
  const LatLon a{0.0, 0.0}, b{0.0, 1.0};
  CHECK(near(distance_m(a, b), 111195.08, 30.0));
  CHECK(near(bearing_deg(a, b), 90.0, 0.01));
  const LatLon c = destination(a, 90.0, 111195.08);
  CHECK(near(c.lat, 0.0, 0.001));
  CHECK(near(c.lon, 1.0, 0.01));
  CHECK(near(normalize_deg(-10.0), 350.0, 1e-9));
  CHECK(crossed_deg(350.0, 10.0, 0.0));
  CHECK(!crossed_deg(350.0, 355.0, 10.0));
  CHECK(near(angle_delta(10.0, 350.0), -20.0, 1e-9));

  double e = 0, n = 0;
  east_north_m({44.9, -93.3}, {44.9, -93.29}, &e, &n);
  CHECK(e > 700.0 && e < 900.0);
  CHECK(std::fabs(n) < 5.0);
}

static void test_adsblol(const std::string& dir) {
  Feed feed;
  std::string error;
  const std::string body = slurp(dir + "/adsblol.json");
  CHECK(!body.empty());
  CHECK(parse_adsblol(body, &feed, &error));
  CHECK(feed.source == "adsb.lol");
  CHECK(feed.total == 9);
  CHECK(feed.aircraft.size() == 8);  // the aircraft with no position is skipped
  CHECK(near(feed.source_time, 1794198643.003, 0.01));

  const Aircraft* dal = nullptr;
  const Aircraft* mil = nullptr;
  const Aircraft* em = nullptr;
  const Aircraft* gnd = nullptr;
  const Aircraft* mlat = nullptr;
  for (const Aircraft& a : feed.aircraft) {
    if (a.flight == "DAL2954") dal = &a;
    if (a.hex == "ae1234") mil = &a;
    if (a.hex == "ab5678") em = &a;
    if (a.hex == "a99999") gnd = &a;
    if (a.hex == "abc123") mlat = &a;
  }
  CHECK(dal != nullptr);
  if (dal) {
    CHECK(near(dal->alt_ft, 24150.0, 0.1));
    CHECK(near(dal->gs_kt, 399.5, 0.1));
    CHECK(near(dal->track, 274.8, 0.1));
    CHECK(dal->type_code == "B739");
    CHECK(dal->category == "A3");
    CHECK(dal->squawk == "2622");
    CHECK(dal->has_seen_pos);
  }
  CHECK(mil != nullptr);
  if (mil) CHECK(mil->military);
  CHECK(em != nullptr);
  if (em) {
    CHECK(em->squawk == "7700");
    CHECK(!emergency_label(*em).empty());
  }
  CHECK(gnd != nullptr);
  if (gnd) CHECK(gnd->on_ground);
  CHECK(mlat != nullptr);
  if (mlat) {
    CHECK(mlat->mlat);
    CHECK(mlat->has_alt);
    CHECK(near(mlat->alt_ft, 8000.0, 1.0));  // only alt_geom is reported
  }

  Feed bad;
  std::string bad_error;
  CHECK(!parse_adsblol("{\"now\": 1}", &bad, &bad_error));
  CHECK(!parse_adsblol("not json", &bad, &bad_error));
}

static void test_opensky(const std::string& dir) {
  Feed feed;
  std::string error;
  const std::string body = slurp(dir + "/opensky.json");
  CHECK(parse_opensky(body, &feed, &error));
  CHECK(feed.source == "OpenSky");
  CHECK(feed.aircraft.size() == 4);
  const Aircraft& first = feed.aircraft[0];
  CHECK(first.flight == "DAL2954");
  CHECK(near(first.alt_ft, 24147.0, 2.0));  // 7360.2 m
  CHECK(near(first.gs_kt, 399.5, 0.5));
  const Aircraft& uav = feed.aircraft[3];
  CHECK(uav.flight.empty());
  CHECK(uav.category == "B6");
}

static void test_model(const std::string& dir) {
  Feed feed;
  std::string error;
  CHECK(parse_adsblol(slurp(dir + "/adsblol.json"), &feed, &error));

  Settings s;
  s.sweep_seconds = 2;
  s.detail_seconds = 10;
  Model m(s);

  m.apply_feed(feed, 1000.0);
  m.update(1000.0);
  CHECK(m.has_feed());
  CHECK(m.known_count() == 7);  // ground contact filtered by default
  CHECK(m.in_range_count() == 7);
  CHECK(m.contacts().size() == 7u);
  const Contact* nearest = m.spotlight();
  CHECK(nearest != nullptr);
  if (nearest) CHECK(aircraft_name(nearest->ac) == "DAL2954");
  CHECK(m.page_count() == 1);
  CHECK(!m.feed_error().empty() == false);
  CHECK(m.feed_age(1012.0) > 11.0);
  CHECK(!m.stale(1012.0));

  // Order is nearest first.
  const auto& order = m.order();
  CHECK(order.size() == 7u);
  for (size_t i = 1; i < order.size(); ++i) {
    CHECK(m.contacts()[static_cast<size_t>(order[i - 1])].distance_m <=
          m.contacts()[static_cast<size_t>(order[i])].distance_m + 0.001);
  }

  // The sweep moves, and when it passes a contact the echo history fills.
  m.update(1000.5);
  CHECK(near(m.sweep_deg(), 90.0, 0.01));
  bool any_echo = false;
  for (const Contact& c : m.contacts()) any_echo = any_echo || c.echo_count > 0;
  CHECK(any_echo);

  // Spotlight auto-rotation. Timers advance by the (capped) update step, so walk the clock.
  const std::string first = m.spotlight_hex();
  m.update(1005.5);
  m.update(1010.6);
  CHECK(m.spotlight_hex() != first);
  m.step_spotlight(1);
  CHECK(m.pinned());
  const std::string pinned = m.spotlight_hex();
  m.update(1030.0);
  CHECK(m.spotlight_hex() == pinned);
  m.unpin();
  CHECK(!m.pinned());

  // Ground filter.
  Settings g = s;
  g.show_ground = true;
  Model mg(g);
  mg.apply_feed(feed, 500.0);
  mg.update(500.0);
  CHECK(mg.known_count() == 8);

  // Altitude filter.
  Settings hi = s;
  hi.min_altitude = 3;  // 10,000 ft
  Model mh(hi);
  mh.apply_feed(feed, 500.0);
  mh.update(500.0);
  CHECK(mh.known_count() == 3);  // DAL (24150), UAL (13950), N88EM (12000)

  // Pages.
  Settings pag = s;
  pag.max_contacts = 5;
  Model mp(pag);
  mp.set_page_rows(4);
  mp.apply_feed(feed, 500.0);
  mp.update(500.0);
  CHECK(mp.page_count() == 2);
  mp.set_page(1);
  CHECK(mp.page() == 1);

  // A stale feed is reported as such.
  CHECK(m.stale(1400.0));

  // Errors clear on the next good feed.
  m.apply_error("boom", 1500.0);
  CHECK(!m.feed_error().empty());
  m.apply_feed(feed, 1600.0);
  m.update(1600.0);
  CHECK(m.feed_error().empty());
}

static void test_formatting() {
  Settings s;
  CHECK(lower_string("ADS-B") == "ads-b");
  CHECK(upper_string("ads-b") == "ADS-B");
  CHECK(trim_string("  hi  ") == "hi");
  CHECK(fmt_commas(1234567) == "1,234,567");
  CHECK(fmt_commas(-1200) == "-1,200");

  Aircraft a;
  a.has_alt = true;
  a.alt_ft = 35000;
  CHECK(fmt_altitude(a, 1) == "FL350");
  CHECK(fmt_altitude(a, 0) == "10,668 M");
  a.alt_ft = 3200;
  CHECK(fmt_altitude(a, 1) == "3,200 FT");
  CHECK(fmt_altitude(a, 1, true) == "3,200FT");
  a.on_ground = true;
  CHECK(fmt_altitude(a, 1) == "GND");
  a.on_ground = false;

  a.has_gs = true;
  a.gs_kt = 420;
  CHECK(fmt_speed(a, 1) == "420 KT");
  CHECK(fmt_speed(a, 0, true) == "778KM/H");

  CHECK(fmt_distance(45.0 * METRES_PER_NM, 1) == "45.0 NM");
  CHECK(fmt_distance(1500.0, 0) == "1.5 KM");

  a.has_baro_rate = true;
  a.baro_rate_fpm = 640;
  CHECK(fmt_vertical_rate(a, 1) == "+640 FPM");
  a.baro_rate_fpm = 10;
  CHECK(fmt_vertical_rate(a, 1) == "LEVEL");

  CHECK(fmt_bearing(310.4) == "310°");
  CHECK(fmt_coord(44.9031, true) == "44.9031N");
  CHECK(fmt_coord(-93.3096, false) == "93.3096W");
  CHECK(fmt_seen(2.14) == "2.1 s");
  CHECK(fmt_seen(65.0) == "65 s");
  CHECK(fmt_seen(180.0) == "3 min");

  Aircraft named;
  named.flight = " dal2954 ";
  CHECK(aircraft_name(named) == "DAL2954");
  named.flight.clear();
  named.reg = "n12345";
  CHECK(aircraft_name(named) == "N12345");
  named.reg.clear();
  named.hex = "a1b2c3";
  CHECK(aircraft_name(named) == "A1B2C3");

  CHECK(category_name("A3") == "LARGE");
  CHECK(category_name("B6") == "UAV");
  CHECK(category_name("b6") == "UAV");
  CHECK(source_name(named) == "UNKNOWN");
  named.mlat = true;
  CHECK(source_name(named) == "MLAT");

  Aircraft em;
  em.squawk = "7700";
  CHECK(emergency_label(em) == "EMERGENCY");
  em.emergency = "general";
  CHECK(emergency_label(em) == "GENERAL");
  em.military = true;
  CHECK(flag_text(em).find("MILITARY") != std::string::npos);

  CHECK(range_text(60, 1) == "60 KM / 32 NM");
  CHECK(range_short(60, 1) == "32NM");
  CHECK(range_short(60, 0) == "60KM");
}

static void test_settings_and_feed() {
  Settings s;
  s.range_km = 999;
  s.sweep_seconds = 1;
  s.theme = 9;
  s.lat = 500;
  s.location_name = "   ";
  s.sanitise();
  CHECK(s.range_km == 400);
  CHECK(s.sweep_seconds == 2);
  CHECK(s.theme == 3);
  CHECK(s.lat == 0.0);
  CHECK(s.location_name == "Home");

  Settings d;
  CHECK(fetch_radius_nm(60) == 41);
  CHECK(fetch_radius_nm(5) == 10);
  const std::string url = adsblol_url(d);
  CHECK(url.find("api.adsb.lol/v2/lat/44.903/lon/-93.310/dist/41") != std::string::npos);
  const std::string sky = opensky_url(d);
  CHECK(sky.find("opensky-network.org/api/states/all?lamin=") != std::string::npos);
  CHECK(sky.find("lamax=") != std::string::npos);
}

int main(int argc, char** argv) {
  const std::string dir = argc > 1 ? argv[1] : "tests/fixtures";
  test_geometry();
  test_adsblol(dir);
  test_opensky(dir);
  test_model(dir);
  test_formatting();
  test_settings_and_feed();
  if (failures == 0) std::printf("radar_core: all tests passed\n");
  return failures == 0 ? 0 : 1;
}
