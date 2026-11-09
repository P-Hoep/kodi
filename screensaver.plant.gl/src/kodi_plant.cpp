// Kodi binary add-on: Growing Plant (OpenGL) screensaver around plantgl::App.
#include <kodi/addon-instance/Screensaver.h>

#include <chrono>
#include <memory>
#include <string>

#include "gl_include.hpp"
#include "plant_app.hpp"

namespace {

template <typename T>
T clamp(T v, T lo, T hi) { return v < lo ? lo : (v > hi ? hi : v); }

// Setting ids and defaults match tools/make_settings_plant_gl.py.
plantgl::Settings read_settings() {
  plantgl::Settings s;
  s.preset = clamp(kodi::addon::GetSettingInt("preset", s.preset), 0, 5);
  s.seed = clamp(kodi::addon::GetSettingInt("seed", s.seed), 0, 999);
  s.quality = clamp(kodi::addon::GetSettingInt("quality", s.quality), 0, 2);
  s.leaf_density =
      clamp(kodi::addon::GetSettingInt("leaf_density", s.leaf_density), 0, 2);
  s.growth_speed =
      clamp(kodi::addon::GetSettingInt("growth_speed", s.growth_speed), 0, 3);
  s.hold_seconds =
      clamp(kodi::addon::GetSettingInt("hold_seconds", s.hold_seconds), 0, 60);
  s.motion = clamp(kodi::addon::GetSettingInt("motion", s.motion), 0, 5);
  s.camera_speed =
      clamp(kodi::addon::GetSettingInt("camera_speed", s.camera_speed), 10, 200);
  s.framing = clamp(kodi::addon::GetSettingInt("framing", s.framing), 0, 2);
  s.background = clamp(kodi::addon::GetSettingInt("background", s.background), 0, 6);
  s.particles = kodi::addon::GetSettingBoolean("particles", s.particles);
  s.ground = kodi::addon::GetSettingBoolean("ground", s.ground);
  s.dim = clamp(kodi::addon::GetSettingInt("dim", s.dim), 0, 80);
  s.sanitise();
  return s;
}

const char* gl_version() {
  const auto* v = reinterpret_cast<const char*>(glGetString(GL_VERSION));
  return v ? v : "unknown";
}

}  // namespace

class ATTR_DLL_LOCAL CGrowingPlantGL : public kodi::addon::CInstanceScreensaver {
 public:
  explicit CGrowingPlantGL(const kodi::addon::IInstanceInfo& instance)
      : CInstanceScreensaver(instance) {}

  bool Start() override {
    std::string error;
    app_ = std::make_unique<plantgl::App>();
    const auto seed = static_cast<unsigned>(
        std::chrono::steady_clock::now().time_since_epoch().count());
    if (!app_->init(read_settings(), seed, &error)) {
      kodi::Log(ADDON_LOG_ERROR, "Growing Plant (OpenGL): cannot start: %s", error.c_str());
      app_.reset();
      return false;
    }
    started_ = std::chrono::steady_clock::now();
    kodi::Log(ADDON_LOG_INFO,
              "Growing Plant (OpenGL): started, seed %u, preset %d, background %d, GL %s",
              app_->seed(), app_->preset_index(), app_->background_index(), gl_version());
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
      kodi::Log(ADDON_LOG_DEBUG,
                "Growing Plant (OpenGL): %.1f fps, preset %d, sky %d, motion %d, "
                "%d vertices in %d batches, growth %d%%",
                frames_ / (now - fps_since_), app_->preset_index(), app_->background_index(),
                app_->motion_index(), app_->vertex_count(), app_->batch_count(),
                static_cast<int>(app_->growth01() * 100.0));
      frames_ = 0;
      fps_since_ = now;
    }
  }

 private:
  std::unique_ptr<plantgl::App> app_;
  std::chrono::steady_clock::time_point started_;
  int frames_ = 0;
  double fps_since_ = 0.0;
};

class ATTR_DLL_LOCAL CGrowingPlantGLAddon : public kodi::addon::CAddonBase {
 public:
  CGrowingPlantGLAddon() = default;
  ADDON_STATUS CreateInstance(const kodi::addon::IInstanceInfo& instance,
                              KODI_ADDON_INSTANCE_HDL& hdl) override {
    if (instance.IsType(ADDON_INSTANCE_SCREENSAVER)) {
      hdl = new CGrowingPlantGL(instance);
      return ADDON_STATUS_OK;
    }
    return ADDON_STATUS_UNKNOWN;
  }
};

ADDONCREATOR(CGrowingPlantGLAddon)
