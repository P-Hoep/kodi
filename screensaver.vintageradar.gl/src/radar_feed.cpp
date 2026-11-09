#include "radar_feed.hpp"

#include <algorithm>
#include <chrono>
#include <cmath>
#include <cstdio>
#include <utility>

namespace radar {
namespace {
constexpr double PI = 3.14159265358979323846;

std::string error_join(const std::string& first, const std::string& second) {
  if (first.empty()) return second;
  if (second.empty()) return first;
  return first + " | " + second;
}
}  // namespace

int fetch_radius_nm(int range_km) {
  // Pull a little past the displayed range so a plane does not pop into existence at the rim.
  const double nm = std::ceil((range_km / 1.852) * 1.25);
  return static_cast<int>(std::max(10.0, std::min(250.0, nm)));
}

std::string adsblol_url(const Settings& settings) {
  char b[256];
  std::snprintf(b, sizeof b, "https://api.adsb.lol/v2/lat/%.3f/lon/%.3f/dist/%d", settings.lat,
                settings.lon, fetch_radius_nm(settings.range_km));
  return b;
}

std::string opensky_url(const Settings& settings) {
  const double pad_km = settings.range_km * 1.35 + 5.0;
  const double dlat = pad_km / 111.32;
  const double coslat = std::max(0.15, std::cos(settings.lat * PI / 180.0));
  const double dlon = dlat / coslat;
  char b[384];
  std::snprintf(b, sizeof b,
                "https://opensky-network.org/api/states/all?lamin=%.4f&lomin=%.4f&lamax=%.4f"
                "&lomax=%.4f",
                std::max(-90.0, settings.lat - dlat), std::max(-180.0, settings.lon - dlon),
                std::min(90.0, settings.lat + dlat), std::min(180.0, settings.lon + dlon));
  return b;
}

FeedPump::FeedPump(const Settings& settings, Fetch fetch)
    : settings_(settings), fetch_(std::move(fetch)) {}

FeedPump::~FeedPump() { stop(); }

void FeedPump::start() {
  if (running_.exchange(true)) return;
  stop_ = false;
  thread_ = std::thread([this] { run(); });
}

void FeedPump::stop() {
  stop_ = true;
  if (thread_.joinable()) thread_.join();
  running_ = false;
}

std::string FeedPump::url() const {
  std::lock_guard<std::mutex> lock(mutex_);
  return url_;
}

bool FeedPump::take(Feed* feed, std::string* error, bool* is_error) {
  std::lock_guard<std::mutex> lock(mutex_);
  if (!has_result_) return false;
  has_result_ = false;
  if (result_is_error_) {
    *error = pending_error_;
    *is_error = true;
    return true;
  }
  *feed = std::move(pending_feed_);
  pending_feed_ = Feed();
  *is_error = false;
  error->clear();
  return true;
}

bool FeedPump::sleep_ms(int ms) const {
  for (int waited = 0; waited < ms; waited += 100) {
    if (stop_) return false;
    std::this_thread::sleep_for(std::chrono::milliseconds(100));
  }
  return !stop_;
}

void FeedPump::run() {
  while (!stop_) {
    fetching_ = true;
    const std::string primary = adsblol_url(settings_);
    {
      std::lock_guard<std::mutex> lock(mutex_);
      url_ = primary;
    }
    std::string body, error;
    bool ok = fetch_(primary, &body, &error);
    Feed feed;
    std::string parse_error;
    bool good = false;
    if (ok) {
      good = parse_adsblol(body, &feed, &parse_error);
      if (!good) error = parse_error;
    }
    if (!good) {
      const std::string fallback = opensky_url(settings_);
      std::string body2, error2;
      if (fetch_(fallback, &body2, &error2)) {
        Feed fallback_feed;
        std::string fallback_error;
        if (parse_opensky(body2, &fallback_feed, &fallback_error)) {
          feed = std::move(fallback_feed);
          good = true;
        } else {
          error = error_join(error, fallback_error);
        }
      } else {
        error = error_join(error, error2);
      }
    }
    {
      std::lock_guard<std::mutex> lock(mutex_);
      if (good) {
        pending_feed_ = std::move(feed);
        result_is_error_ = false;
      } else {
        pending_error_ = error.empty() ? "No data from adsb.lol or OpenSky" : error;
        result_is_error_ = true;
      }
      has_result_ = true;
    }
    fetching_ = false;
    if (stop_) break;
    const int wait = (good ? std::max(10, settings_.refresh_seconds)
                           : std::min(30, std::max(10, settings_.refresh_seconds / 2))) *
                     1000;
    if (!sleep_ms(wait)) break;
  }
  running_ = false;
}

}  // namespace radar
