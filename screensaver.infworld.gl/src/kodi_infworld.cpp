// Kodi binary add-on: Endless World (OpenGL) screensaver around infworldgl::App.
#include <kodi/addon-instance/Screensaver.h>

#include <chrono>
#include <memory>
#include <string>

#include "gl_include.hpp"
#include "infworld_app.hpp"

namespace {

template <typename T>
T clamp(T v, T lo, T hi) { return v < lo ? lo : (v > hi ? hi : v); }

// Setting ids and defaults match tools/make_settings_infworld.py.
sandclock::infworld::Settings read_settings() {
  using namespace sandclock::infworld;
  Settings s;
  s.seed = clamp(kodi::addon::GetSettingInt("seed", s.seed), 0, 999);
  s.range = clamp(kodi::addon::GetSettingInt("range", s.range), 3, 9);
  s.detail = clamp(kodi::addon::GetSettingInt("detail", s.detail), 0, 2);
  s.trees = clamp(kodi::addon::GetSettingInt("trees", s.trees), 0, 3);
  s.mode = clamp(kodi::addon::GetSettingInt("mode", s.mode), 0, 2);
  s.speed = clamp(kodi::addon::GetSettingInt("speed", s.speed), 10, 200);
  s.height = clamp(kodi::addon::GetSettingInt("height", s.height), 20, 400);
  s.wander = kodi::addon::GetSettingBoolean("wander", s.wander);
  s.water = kodi::addon::GetSettingBoolean("water", s.water);
  s.dim = clamp(kodi::addon::GetSettingInt("dim", s.dim), 0, 80);
  s.draw_res = clamp(kodi::addon::GetSettingInt("draw_res", s.draw_res), 0, 4);
  s.adaptive = kodi::addon::GetSettingBoolean("adaptive", s.adaptive);
  s.sanitise();
  return s;
}

}  // namespace

class ATTR_DLL_LOCAL CInfWorldGL : public kodi::addon::CInstanceScreensaver {
 public:
  explicit CInfWorldGL(const kodi::addon::IInstanceInfo& instance)
      : CInstanceScreensaver(instance) {}

  bool Start() override {
    std::string error;
    app_ = std::make_unique<sandclock::infworldgl::App>();
    if (!app_->init(read_settings(),
                    static_cast<unsigned>(
                        std::chrono::steady_clock::now().time_since_epoch().count()),
                    kodi::addon::GetAddonPath("resources/textures"), &error)) {
      kodi::Log(ADDON_LOG_ERROR, "Endless World (OpenGL): cannot start: %s", error.c_str());
      app_.reset();
      return false;
    }
    started_ = std::chrono::steady_clock::now();
    kodi::Log(ADDON_LOG_INFO,
              "Endless World (OpenGL): started, seed %u, range %d, detail %d, GL %s",
              app_->seed(), app_->settings().range, app_->settings().detail,
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
    app_->render(now, Width(), Height());

    ++frames_;
    if (now - fps_since_ >= 10.0) {
      kodi::Log(ADDON_LOG_DEBUG, "Endless World (OpenGL): %.1f fps, %d terrain chunks, %d tree draw %s",
                frames_ / (now - fps_since_), app_->chunks_drawn(), app_->trees_drawn(),
                app_->quality() < 0.999 ? "(reduced)" : "");
      frames_ = 0;
      fps_since_ = now;
    }
  }

 private:
  std::unique_ptr<sandclock::infworldgl::App> app_;
  std::chrono::steady_clock::time_point started_;
  int frames_ = 0;
  double fps_since_ = 0;
};

class ATTR_DLL_LOCAL CInfWorldGLAddon : public kodi::addon::CAddonBase {
 public:
  CInfWorldGLAddon() = default;
  ADDON_STATUS CreateInstance(const kodi::addon::IInstanceInfo& instance,
                              KODI_ADDON_INSTANCE_HDL& hdl) override {
    if (instance.IsType(ADDON_INSTANCE_SCREENSAVER)) {
      hdl = new CInfWorldGL(instance);
      return ADDON_STATUS_OK;
    }
    return ADDON_STATUS_UNKNOWN;
  }
};

ADDONCREATOR(CInfWorldGLAddon)
