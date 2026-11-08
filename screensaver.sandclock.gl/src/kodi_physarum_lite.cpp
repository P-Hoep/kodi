// Kodi binary add-on: the Physarum Lite screensaver around lite::App.
// See kodi_physarum.cpp for the same wrapper with the clock on by default and the timers; this one
// has no timers and an optional clock (off unless the user turns it on).
#include <kodi/addon-instance/Screensaver.h>

#include <chrono>
#include <cstdlib>
#include <ctime>
#include <memory>
#include <string>

#include "gl_include.hpp"
#include "physarum_lite_app.hpp"

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

int get_int(const char* id, int fallback, int lo, int hi) { return clamp(kodi::addon::GetSettingInt(id, fallback), lo, hi); }

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

// Setting ids and defaults match tools/make_settings_physarum_lite.py.
sandclock::physarum::lite::Settings read_settings() {
    using namespace sandclock::physarum::lite;
    Settings s;
    s.preset = get_int("preset", s.preset, 0, PRESET_COUNT);
    s.species = get_int("species", s.species, 0, 2);
    s.species_differ = kodi::addon::GetSettingBoolean("species_differ", s.species_differ);
    s.scale = get_int("scale", s.scale, 40, 300);
    s.sa = (float)get_int("sa", (int)s.sa, 5, 120);
    s.ra = (float)get_int("ra", (int)s.ra, 5, 120);
    s.so = (float)get_int("so", (int)s.so, 1, 60);
    s.ss = (float)get_int("ss", (int)s.ss, 2, 50);
    s.decay = (float)get_int("decay", (int)s.decay, 70, 99);
    s.diffuse = (float)get_int("diffuse", (int)s.diffuse, 0, 100);
    s.deposit = (float)get_int("deposit", (int)s.deposit, 5, 100);
    s.jitter = (float)get_int("jitter", (int)s.jitter, 0, 45);
    s.repel = (float)get_int("repel", (int)s.repel, 0, 100);
    s.agents = get_int("agents", s.agents, 0, AGENT_COUNT - 1);
    s.trail = get_int("trail", s.trail, 0, LITE_TRAIL_COUNT - 1);
    s.pace = get_int("pace", s.pace, 1, 4);
    s.start = get_int("start", s.start, 0, LITE_START_COUNT - 1);
    s.food = get_int("food", s.food, 0, FOOD_COUNT - 1);
    s.food_nodes = get_int("food_nodes", s.food_nodes, 3, 40);
    s.clock = get_int("clock", s.clock, 0, CLOCK_COUNT - 1);
    s.food_strength = get_int("food_strength", s.food_strength, 10, 100);
    s.clock_font = get_int("clock_font", s.clock_font, 0, 8);
    s.clock_weight = get_int("clock_weight", s.clock_weight, 0, 2);
    s.seconds = kodi::addon::GetSettingBoolean("seconds", s.seconds);
    s.hours = get_int("hours", s.hours, 0, 1);
    s.clock_size = get_int("clock_size", s.clock_size, 20, 90);
    s.clock_colour_mode = get_int("clock_colour_mode", s.clock_colour_mode, 0, 2);
    s.clock_colour = parse_colour(kodi::addon::GetSettingString("clock_colour", ""), s.clock_colour);
    s.clock_opacity = get_int("clock_opacity", s.clock_opacity, 10, 100);
    s.colour_mode = get_int("colour_mode", s.colour_mode, 0, MODE_COUNT - 1);
    s.palette = get_int("palette", s.palette, 0, PALETTE_COUNT - 1);
    s.colour = parse_colour(kodi::addon::GetSettingString("colour", ""), s.colour);
    s.background = parse_colour(kodi::addon::GetSettingString("background", ""), s.background);
    s.brightness = get_int("brightness", s.brightness, 30, 300);
    s.cycle = get_int("cycle", s.cycle, 0, 100);
    s.glow = get_int("glow", s.glow, 0, 100);
    s.screen_fx = get_int("screen_fx", s.screen_fx, 0, 2);
    s.dim = get_int("dim", s.dim, 0, 80);
    s.view = get_int("view", s.view, 0, VIEW_COUNT - 1);
    s.camera = get_int("camera", s.camera, 0, CAMERA_COUNT - 1);
    s.camera_speed = get_int("camera_speed", s.camera_speed, 5, 100);
    s.zoom = get_int("zoom", s.zoom, 1, 12);
    return s;
}

}  // namespace

class ATTR_DLL_LOCAL CPhysarumLite : public kodi::addon::CInstanceScreensaver {
public:
    explicit CPhysarumLite(const kodi::addon::IInstanceInfo& instance) : CInstanceScreensaver(instance) {}

    bool Start() override {
        std::string error;
        app_ = std::make_unique<sandclock::physarum::lite::App>();
        if (!app_->init(read_settings(), (unsigned)std::chrono::steady_clock::now().time_since_epoch().count(),
                        kodi::addon::GetAddonPath("resources/fonts.json"), &error)) {
            kodi::Log(ADDON_LOG_ERROR, "Physarum Lite: cannot start: %s", error.c_str());
            app_.reset();
            return false;
        }
        if (!error.empty()) kodi::Log(ADDON_LOG_WARNING, "Physarum Lite: %s", error.c_str());
        started_ = std::chrono::steady_clock::now();
        kodi::Log(ADDON_LOG_INFO, "Physarum Lite: started, %d agents, %d x %d trail (%s), pace %d, GL %s",
                  app_->agents_w() * app_->agents_h(), app_->trail_w(), app_->trail_h(),
                  app_->half_float() ? "half float" : "8 bit", app_->pace(),
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

        // A frame rate line in the log: the only way to tell a device that holds 60 from one that
        // alternates between 60 and 30 (which is what a missed frame looks like). Ten-second
        // samples for the first minute, then one a minute so a screensaver left on overnight does
        // not fill the log.
        ++frames_;
        double span = now - last_log_;
        if (span >= (samples_ < 6 ? 10.0 : 60.0)) {
            kodi::Log(ADDON_LOG_INFO, "Physarum Lite: %.1f fps, %.1f steps/s (pace %d)", (frames_ - frames_at_log_) / span,
                      (app_->steps() - steps_at_log_) / span, app_->pace());
            last_log_ = now;
            frames_at_log_ = frames_;
            steps_at_log_ = app_->steps();
            ++samples_;
        }
    }

private:
    std::unique_ptr<sandclock::physarum::lite::App> app_;
    std::chrono::steady_clock::time_point started_;
    double last_log_ = 0;                    // seconds on the same clock as Render's `now`
    long frames_ = 0, frames_at_log_ = 0, steps_at_log_ = 0;
    int samples_ = 0;
};

class ATTR_DLL_LOCAL CPhysarumLiteAddon : public kodi::addon::CAddonBase {
public:
    CPhysarumLiteAddon() = default;
    ADDON_STATUS CreateInstance(const kodi::addon::IInstanceInfo& instance,
                                KODI_ADDON_INSTANCE_HDL& hdl) override {
        if (instance.IsType(ADDON_INSTANCE_SCREENSAVER)) {
            hdl = new CPhysarumLite(instance);
            return ADDON_STATUS_OK;
        }
        return ADDON_STATUS_UNKNOWN;
    }
};

ADDONCREATOR(CPhysarumLiteAddon)
