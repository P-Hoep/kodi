// Kodi binary add-on: a screensaver instance around Engine + Renderer. Built against the
// kodi-addon-dev-kit (Kodi 21 "Omega", screensaver API 2.2.0). Kodi creates the GL context and
// calls Render() once per frame on its render thread.
#include <kodi/addon-instance/Screensaver.h>

#include <chrono>
#include <cstdlib>
#include <ctime>
#include <memory>
#include <string>

#include "engine.hpp"
#include "gl_include.hpp"
#include "renderer.hpp"

namespace {

using sandclock::Settings;

uint32_t parse_colour(const std::string& text, uint32_t fallback) {
    std::string v = text;
    if (!v.empty() && v[0] == '#') v.erase(0, 1);
    if (v.size() != 6 && v.size() != 8) return fallback;
    char* end = nullptr;
    unsigned long n = std::strtoul(v.c_str(), &end, 16);
    return (end && *end == 0) ? (uint32_t)(n & 0xFFFFFF) : fallback;  // AARRGGBB or RRGGBB
}

int parse_minutes(const std::string& text, int fallback) {
    int h = 0, m = 0;
    if (std::sscanf(text.c_str(), "%d:%d", &h, &m) != 2 || h < 0 || h > 23 || m < 0 || m > 59) return fallback;
    return h * 60 + m;
}

template <typename T>
T clamp(T v, T lo, T hi) { return v < lo ? lo : (v > hi ? hi : v); }

// Same setting ids and defaults as the Python add-on (resources/settings.xml is generated from
// the same table).
Settings read_settings() {
    Settings s;
    s.seconds = kodi::addon::GetSettingBoolean("seconds", s.seconds);
    s.hours = clamp(kodi::addon::GetSettingInt("hours", s.hours), 0, 1);
    s.crumble = clamp(kodi::addon::GetSettingInt("crumble", s.crumble), 0, 1);
    s.speed = clamp(kodi::addon::GetSettingInt("speed", s.speed), 0, 2);
    s.font = clamp(kodi::addon::GetSettingInt("font", s.font), 0, 8);
    s.weight = clamp(kodi::addon::GetSettingInt("weight", s.weight), 0, 2);
    s.size = clamp(kodi::addon::GetSettingInt("size", s.size), 40, 95);
    s.position = clamp(kodi::addon::GetSettingInt("position", s.position), 0, 1);
    s.grain = clamp(kodi::addon::GetSettingInt("grain", s.grain), 0, 2);
    s.grain_look = clamp(kodi::addon::GetSettingInt("grain_look", s.grain_look), 0, 2);
    s.gravity = clamp(kodi::addon::GetSettingInt("gravity", s.gravity), 0, 2);
    s.pile = clamp(kodi::addon::GetSettingInt("pile", s.pile), 10, 50);
    s.colour_mode = clamp(kodi::addon::GetSettingInt("colour_mode", s.colour_mode), 0, 3);
    s.palette = clamp(kodi::addon::GetSettingInt("palette", s.palette), 0, (int)sandclock::PALETTES.size() - 1);
    s.colour = parse_colour(kodi::addon::GetSettingString("colour", ""), s.colour);
    s.background = parse_colour(kodi::addon::GetSettingString("background", ""), s.background);
    s.night_palette = clamp(kodi::addon::GetSettingInt("night_palette", s.night_palette), 0, (int)sandclock::PALETTES.size());
    s.night_dim = clamp(kodi::addon::GetSettingInt("night_dim", s.night_dim), 0, 80);
    s.day_start = parse_minutes(kodi::addon::GetSettingString("day_start", ""), s.day_start);
    s.night_start = parse_minutes(kodi::addon::GetSettingString("night_start", ""), s.night_start);
    s.dim = clamp(kodi::addon::GetSettingInt("dim", s.dim), 0, 80);
    s.drift = kodi::addon::GetSettingBoolean("drift", s.drift);
    return s;
}

double seconds_since_midnight() {
    using namespace std::chrono;
    auto now = system_clock::now();
    std::time_t t = system_clock::to_time_t(now);
    std::tm lt;
#ifdef _WIN32
    localtime_s(&lt, &t);
#else
    localtime_r(&t, &lt);
#endif
    long ms = (long)(duration_cast<milliseconds>(now.time_since_epoch()).count() % 1000);
    return lt.tm_hour * 3600.0 + lt.tm_min * 60.0 + lt.tm_sec + ms / 1000.0;
}

}  // namespace

class ATTR_DLL_LOCAL CSandClock : public kodi::addon::CInstanceScreensaver {
public:
    explicit CSandClock(const kodi::addon::IInstanceInfo& instance) : CInstanceScreensaver(instance) {}

    bool Start() override {
        try {
            Settings s = read_settings();
            sandclock::Font font = sandclock::Font::load(kodi::addon::GetAddonPath("resources/fonts.json"),
                                                         sandclock::FONT_FOLDERS[s.font], s.weight);
            std::string error;
            renderer_ = std::make_unique<sandclock::Renderer>();
            if (!renderer_->init(&error)) {
                kodi::Log(ADDON_LOG_ERROR, "Sand Clock: shader error: %s", error.c_str());
                renderer_.reset();
                return false;
            }
            engine_ = std::make_unique<sandclock::Engine>(
                s, font, (unsigned)std::chrono::steady_clock::now().time_since_epoch().count());
            started_ = std::chrono::steady_clock::now();
            kodi::Log(ADDON_LOG_INFO, "Sand Clock: started, grain %d px, GL %s", engine_->grain(),
                      (const char*)glGetString(GL_VERSION));
            return true;
        } catch (const std::exception& e) {
            kodi::Log(ADDON_LOG_ERROR, "Sand Clock: cannot start: %s", e.what());
            return false;
        }
    }

    void Stop() override {
        if (renderer_) renderer_->release();  // the GL context is still current here
        renderer_.reset();
        engine_.reset();
    }

    void Render() override {
        if (!engine_ || !renderer_) return;
        double now = std::chrono::duration<double>(std::chrono::steady_clock::now() - started_).count();
        engine_->update(now, seconds_since_midnight());
        renderer_->draw(*engine_, now, Width(), Height());
    }

private:
    std::unique_ptr<sandclock::Engine> engine_;
    std::unique_ptr<sandclock::Renderer> renderer_;
    std::chrono::steady_clock::time_point started_;
};

class ATTR_DLL_LOCAL CSandClockAddon : public kodi::addon::CAddonBase {
public:
    CSandClockAddon() = default;
    ADDON_STATUS CreateInstance(const kodi::addon::IInstanceInfo& instance,
                                KODI_ADDON_INSTANCE_HDL& hdl) override {
        if (instance.IsType(ADDON_INSTANCE_SCREENSAVER)) {
            hdl = new CSandClock(instance);
            return ADDON_STATUS_OK;
        }
        return ADDON_STATUS_UNKNOWN;
    }
};

ADDONCREATOR(CSandClockAddon)
