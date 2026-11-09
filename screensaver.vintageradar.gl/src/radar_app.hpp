// The OpenGL renderer: a 1920x1080 virtual scope layout letterboxed into whatever surface Kodi
// (or the GLFW harness) gives us. All radar drawing is procedural; the only textures are the
// Doto font atlases.
#pragma once
#include <memory>
#include <string>

#include "radar_core.hpp"
#include "radar_feed.hpp"

namespace radar {

class App {
 public:
  App();
  ~App();
  App(const App&) = delete;
  App& operator=(const App&) = delete;

  // `fetch` may be empty, in which case no worker thread runs and the caller feeds the model.
  bool init(const Settings& settings, const std::string& media_dir, FeedPump::Fetch fetch,
            std::string* error);
  void set_settings(const Settings& settings);
  void apply_feed(const Feed& feed, double now);
  void apply_error(const std::string& error, double now);

  // Draw one frame. `now` is any monotonic seconds clock.
  void render(double now, int width, int height);
  void release();

  // Virtual-layout helpers used by the harness for a clickable selection.
  std::string pick(double screen_x, double screen_y, int width, int height) const;
  void select(const std::string& hex);
  void step_spotlight(int delta);
  void set_page(int page);

  const Model& model() const;

 private:
  struct Impl;
  std::unique_ptr<Impl> impl_;
};

}  // namespace radar
