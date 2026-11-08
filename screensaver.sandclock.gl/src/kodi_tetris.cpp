// Kodi binary add-on: the Tetris AI (OpenGL) screensaver around tetrisgl::App.
#include <kodi/addon-instance/Screensaver.h>

#include <chrono>
#include <cstdio>
#include <ctime>
#include <memory>
#include <string>

#include "gl_include.hpp"
#include "tetris_app.hpp"

namespace {

template <typename T>
T clamp(T v, T lo, T hi) { return v < lo ? lo : (v > hi ? hi : v); }

// Setting ids and defaults match screensaver.tetris/resources/lib/config.py and
// tools/make_settings_tetris_gl.py.
tetris::Settings read_settings() {
  using namespace ::tetris;
  Settings s;
  s.skill = clamp(kodi::addon::GetSettingInt("skill", s.skill), 0, 4);
  s.speed = clamp(kodi::addon::GetSettingInt("speed", s.speed), 25, 400);
  s.start_level = clamp(kodi::addon::GetSettingInt("start_level", s.start_level), 1, 10);
  s.progressive = kodi::addon::GetSettingBoolean("progressive", s.progressive);
  s.ghost = kodi::addon::GetSettingBoolean("ghost", s.ghost);
  s.show_next = kodi::addon::GetSettingBoolean("show_next", s.show_next);
  s.scheme = clamp(kodi::addon::GetSettingInt("scheme", s.scheme), 0, scheme_count());
  s.block_size = clamp(kodi::addon::GetSettingInt("block_size", s.block_size), BLOCK_W_MIN,
                       BLOCK_W_MAX);
  s.show_grid = kodi::addon::GetSettingBoolean("show_grid", s.show_grid);
  s.show_hud = kodi::addon::GetSettingBoolean("show_hud", s.show_hud);
  s.hud_opacity = clamp(kodi::addon::GetSettingInt("hud_opacity", s.hud_opacity), 0, 90);
  parse_colour(kodi::addon::GetSettingString("background", ""), &s.background);
  const char* const letters = "IOTSZJL";
  for (int i = 0; i < 7; ++i) {
    char id[16];
    std::snprintf(id, sizeof id, "custom_%c", letters[i]);
    parse_colour(kodi::addon::GetSettingString(id, ""), &s.custom[i]);
  }
  s.show_clock = kodi::addon::GetSettingBoolean("show_clock", s.show_clock);
  s.clock_style = clamp(kodi::addon::GetSettingInt("clock_style", s.clock_style), 0, 1);
  s.clock_seconds = kodi::addon::GetSettingBoolean("clock_seconds", s.clock_seconds);
  s.clock_24h = kodi::addon::GetSettingBoolean("clock_24h", s.clock_24h);
  s.clock_position = clamp(kodi::addon::GetSettingInt("clock_position", s.clock_position), 0, 1);
  parse_colour(kodi::addon::GetSettingString("clock_colour", ""), &s.clock_colour);
  s.sanitise();
  return s;
}

double seconds_since_midnight() {
  std::time_t t = std::time(nullptr);
  std::tm lt;
#ifdef _WIN32
  localtime_s(&lt, &t);
#else
  localtime_r(&t, &lt);
#endif
  return lt.tm_hour * 3600.0 + lt.tm_min * 60.0 + lt.tm_sec;
}

}  // namespace

class ATTR_DLL_LOCAL CTetrisGL : public kodi::addon::CInstanceScreensaver {
 public:
  explicit CTetrisGL(const kodi::addon::IInstanceInfo& instance)
      : CInstanceScreensaver(instance) {}

  bool Start() override {
    std::string error;
    app_ = std::make_unique<sandclock::tetrisgl::App>();
    if (!app_->init(read_settings(),
                    static_cast<unsigned>(
                        std::chrono::steady_clock::now().time_since_epoch().count()),
                    &error)) {
      kodi::Log(ADDON_LOG_ERROR, "Tetris AI (OpenGL): cannot start: %s", error.c_str());
      app_.reset();
      return false;
    }
    started_ = std::chrono::steady_clock::now();
    kodi::Log(ADDON_LOG_INFO, "Tetris AI (OpenGL): started, %d x %d board, %d px blocks, GL %s",
              app_->columns(), app_->rows(), app_->settings().block_size,
              reinterpret_cast<const char*>(glGetString(GL_VERSION)));
    return true;
  }

  void Stop() override {
    if (app_) app_->release();  // the GL context is still current here
    app_.reset();
  }

  void Render() override {
    if (!app_) return;
    const double now =
        std::chrono::duration<double>(std::chrono::steady_clock::now() - started_).count();
    app_->render(now, seconds_since_midnight(), Width(), Height());

    ++frames_;
    if (now - fps_since_ >= 10.0) {
      kodi::Log(ADDON_LOG_DEBUG, "Tetris AI (OpenGL): %.1f fps", frames_ / (now - fps_since_));
      frames_ = 0;
      fps_since_ = now;
    }
  }

 private:
  std::unique_ptr<sandclock::tetrisgl::App> app_;
  std::chrono::steady_clock::time_point started_;
  int frames_ = 0;
  double fps_since_ = 0;
};

class ATTR_DLL_LOCAL CTetrisGLAddon : public kodi::addon::CAddonBase {
 public:
  CTetrisGLAddon() = default;
  ADDON_STATUS CreateInstance(const kodi::addon::IInstanceInfo& instance,
                              KODI_ADDON_INSTANCE_HDL& hdl) override {
    if (instance.IsType(ADDON_INSTANCE_SCREENSAVER)) {
      hdl = new CTetrisGL(instance);
      return ADDON_STATUS_OK;
    }
    return ADDON_STATUS_UNKNOWN;
  }
};

ADDONCREATOR(CTetrisGLAddon)
