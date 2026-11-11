// Kodi binary add-on: the Particle Life screensaver around particlelife::App.
// Setting ids and defaults match tools/make_settings_particle_life.py.
#include <kodi/addon-instance/Screensaver.h>

#include <chrono>
#include <cstdlib>
#include <ctime>
#include <functional>
#include <memory>
#include <string>

#include "gl_include.hpp"
#include "particle_life_app.hpp"

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

sandclock::particlelife::Settings read_settings() {
    using namespace sandclock::particlelife;
    Settings s;
    s.matrix_mode = kodi::addon::GetSettingInt("matrix_mode", s.matrix_mode);
    s.preset = kodi::addon::GetSettingInt("preset", s.preset);
    s.custom_matrix = kodi::addon::GetSettingString("custom_matrix", s.custom_matrix);
    s.species = kodi::addon::GetSettingInt("species", s.species);
    s.particles = kodi::addon::GetSettingInt("particles", s.particles);
    s.radius = kodi::addon::GetSettingInt("radius", s.radius);
    s.force = kodi::addon::GetSettingInt("force", s.force);
    s.friction = kodi::addon::GetSettingInt("friction", s.friction);
    s.speed = kodi::addon::GetSettingInt("speed", s.speed);
    s.wrap = kodi::addon::GetSettingBoolean("wrap", s.wrap);
    s.start = kodi::addon::GetSettingInt("start", s.start);
    s.palette = kodi::addon::GetSettingInt("palette", s.palette);
    s.colour_mode = kodi::addon::GetSettingInt("colour_mode", s.colour_mode);
    s.size = kodi::addon::GetSettingInt("size", s.size);
    s.glow = kodi::addon::GetSettingInt("glow", s.glow);
    s.trail = kodi::addon::GetSettingInt("trail", s.trail);
    s.background = parse_colour(kodi::addon::GetSettingString("background", ""), s.background);
    s.dim = kodi::addon::GetSettingInt("dim", s.dim);
    s.draw = kodi::addon::GetSettingInt("draw", s.draw);
    s.camera = kodi::addon::GetSettingInt("camera", s.camera);
    s.camera_zoom = kodi::addon::GetSettingInt("camera_zoom", s.camera_zoom);
    s.camera_speed = kodi::addon::GetSettingInt("camera_speed", s.camera_speed);
    s.vary = kodi::addon::GetSettingInt("vary", s.vary);
    s.restart = kodi::addon::GetSettingInt("restart", s.restart);
    s.evolve = kodi::addon::GetSettingInt("evolve", s.evolve);
    s.seed_text = kodi::addon::GetSettingString("seed_text", s.seed_text);
    return sanitise(s);
}

// A clock seed, mixed with the optional seed text so the same text always starts the same world.
unsigned make_seed(const std::string& text) {
    unsigned seed = (unsigned)std::chrono::steady_clock::now().time_since_epoch().count();
    if (!text.empty()) seed ^= (unsigned)std::hash<std::string>{}(text) + 0x9e3779b9u;
    return seed;
}

}  // namespace

class ATTR_DLL_LOCAL CParticleLife : public kodi::addon::CInstanceScreensaver {
public:
    explicit CParticleLife(const kodi::addon::IInstanceInfo& instance) : CInstanceScreensaver(instance) {}

    bool Start() override {
        std::string error;
        sandclock::particlelife::Settings settings = read_settings();
        app_ = std::make_unique<sandclock::particlelife::App>();
        if (!app_->init(settings, make_seed(settings.seed_text), &error)) {
            kodi::Log(ADDON_LOG_ERROR, "Particle Life: cannot start: %s", error.c_str());
            app_.reset();
            return false;
        }
        if (!error.empty()) kodi::Log(ADDON_LOG_WARNING, "Particle Life: %s", error.c_str());
        started_ = std::chrono::steady_clock::now();
        kodi::Log(ADDON_LOG_INFO, "Particle Life: started, %d particles, %d species, GL %s", app_->particles(),
                  app_->species(), (const char*)glGetString(GL_VERSION));
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
    std::unique_ptr<sandclock::particlelife::App> app_;
    std::chrono::steady_clock::time_point started_;
};

class ATTR_DLL_LOCAL CParticleLifeAddon : public kodi::addon::CAddonBase {
public:
    CParticleLifeAddon() = default;
    ADDON_STATUS CreateInstance(const kodi::addon::IInstanceInfo& instance,
                                KODI_ADDON_INSTANCE_HDL& hdl) override {
        if (instance.IsType(ADDON_INSTANCE_SCREENSAVER)) {
            hdl = new CParticleLife(instance);
            return ADDON_STATUS_OK;
        }
        return ADDON_STATUS_UNKNOWN;
    }
};

ADDONCREATOR(CParticleLifeAddon)
