// Kodi binary add-on: Vintage Radar screensaver around radar::App.
#include <kodi/Filesystem.h>
#include <kodi/addon-instance/Screensaver.h>

#include <chrono>
#include <memory>
#include <string>

#include "gl_include.hpp"
#include "radar_app.hpp"

namespace {

template <typename T>
T clamp(T v, T lo, T hi) {
  return v < lo ? lo : (v > hi ? hi : v);
}

double setting_double(const char* name, double fallback) {
  // Number settings must be read as numbers; the string getter warns and returns empty.
  return kodi::addon::GetSettingFloat(name, static_cast<float>(fallback));
}

// Setting ids and defaults match tools/make_settings_vintageradar.py.
radar::Settings read_settings() {
  radar::Settings s;
  s.location_name = kodi::addon::GetSettingString("location_name", s.location_name);
  s.lat = setting_double("latitude", s.lat);
  s.lon = setting_double("longitude", s.lon);
  s.range_km = clamp(kodi::addon::GetSettingInt("range_km", s.range_km), 5, 400);
  s.units = clamp(kodi::addon::GetSettingInt("units", s.units), 0, 1);
  s.refresh_seconds = clamp(kodi::addon::GetSettingInt("refresh_seconds", s.refresh_seconds), 10, 120);
  s.show_ground = kodi::addon::GetSettingBoolean("show_ground", s.show_ground);
  s.min_altitude = clamp(kodi::addon::GetSettingInt("min_altitude", s.min_altitude), 0, 3);
  s.sweep_seconds = clamp(kodi::addon::GetSettingInt("sweep_seconds", s.sweep_seconds), 2, 12);
  s.show_labels = kodi::addon::GetSettingBoolean("show_labels", s.show_labels);
  s.label_detail = clamp(kodi::addon::GetSettingInt("label_detail", s.label_detail), 0, 2);
  s.show_history = kodi::addon::GetSettingBoolean("show_history", s.show_history);
  s.max_contacts = clamp(kodi::addon::GetSettingInt("max_contacts", s.max_contacts), 5, 200);
  s.show_panel = kodi::addon::GetSettingBoolean("show_panel", s.show_panel);
  s.detail_seconds = clamp(kodi::addon::GetSettingInt("detail_seconds", s.detail_seconds), 4, 60);
  s.list_seconds = clamp(kodi::addon::GetSettingInt("list_seconds", s.list_seconds), 3, 60);
  s.theme = clamp(kodi::addon::GetSettingInt("theme", s.theme), 0, 3);
  s.crt = kodi::addon::GetSettingBoolean("crt", s.crt);
  s.dim = clamp(kodi::addon::GetSettingInt("dim", s.dim), 0, 80);
  s.quality = clamp(kodi::addon::GetSettingInt("quality", s.quality), 0, 2);
  s.sanitise();
  return s;
}

bool fetch_url(const std::string& url, std::string* body, std::string* error) {
  kodi::vfs::CFile file;
  if (!file.CURLCreate(url)) {
    *error = "cannot create HTTP request";
    return false;
  }
  file.CURLAddOption(ADDON_CURL_OPTION_PROTOCOL, "connection-timeout", "8");
  file.CURLAddOption(ADDON_CURL_OPTION_PROTOCOL, "user-agent",
                     "VintageRadar/1.0 (Kodi screensaver)");
  if (!file.CURLOpen(0)) {
    *error = "HTTP request failed";
    return false;
  }
  body->clear();
  char buffer[16384];
  for (;;) {
    const ssize_t n = file.Read(buffer, sizeof buffer);
    if (n < 0) {
      *error = "HTTP read failed";
      return false;
    }
    if (n == 0) break;
    body->append(buffer, static_cast<size_t>(n));
    if (body->size() > 4u * 1024u * 1024u) {
      *error = "HTTP response too large";
      return false;
    }
  }
  if (body->empty()) {
    *error = "empty HTTP response";
    return false;
  }
  return true;
}

const char* gl_version() {
  const auto* v = reinterpret_cast<const char*>(glGetString(GL_VERSION));
  return v ? v : "unknown";
}

}  // namespace

class ATTR_DLL_LOCAL CVintageRadarGL : public kodi::addon::CInstanceScreensaver {
 public:
  explicit CVintageRadarGL(const kodi::addon::IInstanceInfo& instance)
      : CInstanceScreensaver(instance) {}

  bool Start() override {
    const radar::Settings settings = read_settings();
    std::string error;
    app_ = std::make_unique<radar::App>();
    if (!app_->init(settings, kodi::addon::GetAddonPath("resources/media"), fetch_url, &error)) {
      kodi::Log(ADDON_LOG_ERROR, "Vintage Radar: cannot start: %s", error.c_str());
      app_.reset();
      return false;
    }
    started_ = std::chrono::steady_clock::now();
    kodi::Log(ADDON_LOG_INFO,
              "Vintage Radar: started at %.4f, %.4f, range %d km, theme %d, GL %s",
              settings.lat, settings.lon, settings.range_km, settings.theme, gl_version());
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
    if (now - fps_since_ >= 15.0) {
      kodi::Log(ADDON_LOG_DEBUG,
                "Vintage Radar: %.1f fps, %d in range, %d tracked, source %s, age %.0fs",
                frames_ / (now - fps_since_), app_->model().in_range_count(),
                app_->model().known_count(), app_->model().feed_source().c_str(),
                app_->model().feed_age(now));
      frames_ = 0;
      fps_since_ = now;
    }
  }

 private:
  std::unique_ptr<radar::App> app_;
  std::chrono::steady_clock::time_point started_;
  int frames_ = 0;
  double fps_since_ = 0.0;
};

class ATTR_DLL_LOCAL CVintageRadarGLAddon : public kodi::addon::CAddonBase {
 public:
  CVintageRadarGLAddon() = default;
  ADDON_STATUS CreateInstance(const kodi::addon::IInstanceInfo& instance,
                              KODI_ADDON_INSTANCE_HDL& hdl) override {
    if (instance.IsType(ADDON_INSTANCE_SCREENSAVER)) {
      hdl = new CVintageRadarGL(instance);
      return ADDON_STATUS_OK;
    }
    return ADDON_STATUS_UNKNOWN;
  }
};

ADDONCREATOR(CVintageRadarGLAddon)
