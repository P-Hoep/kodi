// Kodi binary add-on: the Cellular Automata Lite screensaver around automata::lite::App.
// Same wrapper as kodi_automata.cpp, without the clock settings and with the draw-resolution
// setting.
#include <kodi/addon-instance/Screensaver.h>

#include <chrono>
#include <cstdlib>
#include <memory>
#include <string>

#include "automata_lite_app.hpp"
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

// Setting ids and defaults match tools/make_settings_automata_lite.py.
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
    s.draw = clamp(kodi::addon::GetSettingInt("draw", s.draw), 0, 5);
    s.view = clamp(kodi::addon::GetSettingInt("view", s.view), 0, VIEW_COUNT - 1);
    s.camera = clamp(kodi::addon::GetSettingInt("camera", s.camera), 0, CAMERA_COUNT - 1);
    s.camera_speed = clamp(kodi::addon::GetSettingInt("camera_speed", s.camera_speed), 5, 100);
    s.zoom = clamp(kodi::addon::GetSettingInt("zoom", s.zoom), 1, 16);
    return s;
}

}  // namespace

class ATTR_DLL_LOCAL CAutomataLite : public kodi::addon::CInstanceScreensaver {
public:
    explicit CAutomataLite(const kodi::addon::IInstanceInfo& instance) : CInstanceScreensaver(instance) {}

    bool Start() override {
        std::string error;
        app_ = std::make_unique<sandclock::automata::lite::App>();
        if (!app_->init(read_settings(), (unsigned)std::chrono::steady_clock::now().time_since_epoch().count(),
                        &error)) {
            kodi::Log(ADDON_LOG_ERROR, "Cellular Automata Lite: cannot start: %s", error.c_str());
            app_.reset();
            return false;
        }
        if (!error.empty()) kodi::Log(ADDON_LOG_WARNING, "Cellular Automata Lite: %s", error.c_str());
        started_ = std::chrono::steady_clock::now();
        kodi::Log(ADDON_LOG_INFO, "Cellular Automata Lite: started, %d x %d cells, GL %s", app_->cols(), app_->rows(),
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
        app_->render(now, Width(), Height());
    }

private:
    std::unique_ptr<sandclock::automata::lite::App> app_;
    std::chrono::steady_clock::time_point started_;
};

class ATTR_DLL_LOCAL CAutomataLiteAddon : public kodi::addon::CAddonBase {
public:
    CAutomataLiteAddon() = default;
    ADDON_STATUS CreateInstance(const kodi::addon::IInstanceInfo& instance,
                                KODI_ADDON_INSTANCE_HDL& hdl) override {
        if (instance.IsType(ADDON_INSTANCE_SCREENSAVER)) {
            hdl = new CAutomataLite(instance);
            return ADDON_STATUS_OK;
        }
        return ADDON_STATUS_UNKNOWN;
    }
};

ADDONCREATOR(CAutomataLiteAddon)
