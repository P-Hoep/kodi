// Kodi binary add-on: the Cellular Automata screensaver around automata::App.
// See kodi_addon.cpp (Sand Clock) for the same wrapper pattern.
#include <kodi/addon-instance/Screensaver.h>

#include <chrono>
#include <cstdlib>
#include <ctime>
#include <memory>
#include <string>

#include "automata_app.hpp"
#include "gl_include.hpp"

namespace {

template <typename T>
T clamp(T v, T lo, T hi) { return v < lo ? lo : (v > hi ? hi : v); }

uint32_t parse_colour(const std::string& text, uint32_t fallback) {
    std::string v = text;
    if (!v.empty() && v[0] == '#') v.erase(0, 1);
    if (v.size() != 6 && v.size() != 8) return fallback;
    char* end = nullptr;
    unsigned long n = std::strtoul(v.c_str(), &end, 16);
    return (end && *end == 0) ? (uint32_t)(n & 0xFFFFFF) : fallback;  // AARRGGBB or RRGGBB
}

// Setting ids and defaults match tools/make_settings_automata.py.
sandclock::automata::Settings read_settings() {
    using namespace sandclock::automata;
    Settings s;
    s.rule = clamp(kodi::addon::GetSettingInt("rule", s.rule), 0, RULE_COUNT);
    s.custom_rule = kodi::addon::GetSettingString("custom_rule", s.custom_rule);
    s.wrap = kodi::addon::GetSettingBoolean("wrap", s.wrap);
    s.grid = clamp(kodi::addon::GetSettingInt("grid", s.grid), 0, GRID_COUNT - 1);
    s.speed = clamp(kodi::addon::GetSettingInt("speed", s.speed), 0, SPEED_COUNT - 1);
    s.sparks = clamp(kodi::addon::GetSettingInt("sparks", s.sparks), 0, 1000);
    s.start = clamp(kodi::addon::GetSettingInt("start", s.start), 0, START_COUNT - 1);
    s.density = clamp(kodi::addon::GetSettingInt("density", s.density), 1, 90);
    s.auto_restart = kodi::addon::GetSettingBoolean("auto_restart", s.auto_restart);
    s.restart_every = clamp(kodi::addon::GetSettingInt("restart_every", s.restart_every), 0, RESTART_COUNT - 1);
    s.palette = clamp(kodi::addon::GetSettingInt("palette", s.palette), 0, PALETTE_COUNT - 1);
    s.colour = parse_colour(kodi::addon::GetSettingString("colour", ""), s.colour);
    s.background = parse_colour(kodi::addon::GetSettingString("background", ""), s.background);
    s.cycle = clamp(kodi::addon::GetSettingInt("cycle", s.cycle), 0, 100);
    s.age_span = clamp(kodi::addon::GetSettingInt("age_span", s.age_span), 1, 255);
    s.trail = clamp(kodi::addon::GetSettingInt("trail", s.trail), 0, 95);
    s.shape = clamp(kodi::addon::GetSettingInt("shape", s.shape), 0, 2);
    s.dim = clamp(kodi::addon::GetSettingInt("dim", s.dim), 0, 80);
    s.colour_mode = clamp(kodi::addon::GetSettingInt("colour_mode", s.colour_mode), 0, MODE_COUNT - 1);
    s.background_style = clamp(kodi::addon::GetSettingInt("background_style", s.background_style), 0, 2);
    s.glow = clamp(kodi::addon::GetSettingInt("glow", s.glow), 0, 100);
    s.screen_fx = clamp(kodi::addon::GetSettingInt("screen_fx", s.screen_fx), 0, 2);
    s.clock = clamp(kodi::addon::GetSettingInt("clock", s.clock), 0, CLOCK_COUNT - 1);
    s.clock_font = clamp(kodi::addon::GetSettingInt("clock_font", s.clock_font), 0, 8);
    s.clock_weight = clamp(kodi::addon::GetSettingInt("clock_weight", s.clock_weight), 0, 2);
    s.seconds = kodi::addon::GetSettingBoolean("seconds", s.seconds);
    s.hours = clamp(kodi::addon::GetSettingInt("hours", s.hours), 0, 1);
    s.clock_size = clamp(kodi::addon::GetSettingInt("clock_size", s.clock_size), 20, 90);
    s.clock_colour_mode = clamp(kodi::addon::GetSettingInt("clock_colour_mode", s.clock_colour_mode), 0, 2);
    s.clock_colour = parse_colour(kodi::addon::GetSettingString("clock_colour", ""), s.clock_colour);
    s.clock_opacity = clamp(kodi::addon::GetSettingInt("clock_opacity", s.clock_opacity), 10, 100);
    s.view = clamp(kodi::addon::GetSettingInt("view", s.view), 0, VIEW_COUNT - 1);
    s.camera = clamp(kodi::addon::GetSettingInt("camera", s.camera), 0, CAMERA_COUNT - 1);
    s.camera_speed = clamp(kodi::addon::GetSettingInt("camera_speed", s.camera_speed), 5, 100);
    s.zoom = clamp(kodi::addon::GetSettingInt("zoom", s.zoom), 1, 16);
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

class ATTR_DLL_LOCAL CAutomata : public kodi::addon::CInstanceScreensaver {
public:
    explicit CAutomata(const kodi::addon::IInstanceInfo& instance) : CInstanceScreensaver(instance) {}

    bool Start() override {
        std::string error;
        app_ = std::make_unique<sandclock::automata::App>();
        if (!app_->init(read_settings(), (unsigned)std::chrono::steady_clock::now().time_since_epoch().count(),
                        kodi::addon::GetAddonPath("resources/fonts.json"), &error)) {
            kodi::Log(ADDON_LOG_ERROR, "Cellular Automata: cannot start: %s", error.c_str());
            app_.reset();
            return false;
        }
        if (!error.empty()) kodi::Log(ADDON_LOG_WARNING, "Cellular Automata: %s", error.c_str());
        started_ = std::chrono::steady_clock::now();
        kodi::Log(ADDON_LOG_INFO, "Cellular Automata: started, %d x %d cells, GL %s", app_->cols(), app_->rows(),
                  (const char*)glGetString(GL_VERSION));
        return true;
    }

    void Stop() override {
        if (app_) app_->release();  // the GL context is still current here
        app_.reset();
    }

    void Render() override {
        if (!app_) return;
        double now = std::chrono::duration<double>(std::chrono::steady_clock::now() - started_).count();
        app_->render(now, seconds_since_midnight(), Width(), Height());
    }

private:
    std::unique_ptr<sandclock::automata::App> app_;
    std::chrono::steady_clock::time_point started_;
};

class ATTR_DLL_LOCAL CAutomataAddon : public kodi::addon::CAddonBase {
public:
    CAutomataAddon() = default;
    ADDON_STATUS CreateInstance(const kodi::addon::IInstanceInfo& instance,
                                KODI_ADDON_INSTANCE_HDL& hdl) override {
        if (instance.IsType(ADDON_INSTANCE_SCREENSAVER)) {
            hdl = new CAutomata(instance);
            return ADDON_STATUS_OK;
        }
        return ADDON_STATUS_UNKNOWN;
    }
};

ADDONCREATOR(CAutomataAddon)
