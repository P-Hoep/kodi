// Background feed pump. It owns the HTTP work and parsing so the render thread (and Kodi's UI)
// never waits for the network. A fetch function is injected: Kodi's VFS in the add-on, libcurl in
// the test window. The pump object is shared-owned and may outlive the renderer when the app
// stops with a request still in flight.
#pragma once
#include <atomic>
#include <functional>
#include <mutex>
#include <string>
#include <thread>

#include "radar_core.hpp"

namespace radar {

std::string adsblol_url(const Settings& settings);
std::string opensky_url(const Settings& settings);
int fetch_radius_nm(int range_km);

class FeedPump {
 public:
  using Fetch = std::function<bool(const std::string& url, std::string* body,
                                   std::string* error)>;

  FeedPump(const Settings& settings, Fetch fetch);
  ~FeedPump();

  FeedPump(const FeedPump&) = delete;
  FeedPump& operator=(const FeedPump&) = delete;

  void start();
  void stop();
  bool running() const { return running_.load(); }
  bool fetching() const { return fetching_.load(); }
  std::string url() const;

  // Render thread: true when a new result has arrived since the previous call. `is_error`
  // distinguishes a feed from a failure message.
  bool take(Feed* feed, std::string* error, bool* is_error);

 private:
  void run();
  bool sleep_ms(int ms) const;

  Settings settings_;
  Fetch fetch_;
  std::thread thread_;
  std::atomic<bool> stop_{false};
  std::atomic<bool> running_{false};
  std::atomic<bool> fetching_{false};

  mutable std::mutex mutex_;
  std::string url_;
  bool has_result_ = false;
  bool result_is_error_ = false;
  Feed pending_feed_;
  std::string pending_error_;
};

}  // namespace radar
