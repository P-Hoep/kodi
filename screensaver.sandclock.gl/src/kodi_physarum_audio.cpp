// Kodi binary add-on: the Physarum music visualisation around audio::App.
//
// Kodi hands a visualisation the decoded audio (44.1 kHz stereo float, interleaved) on one thread
// and calls Render() on the GUI thread with the GL context current. Start() is called once per
// track (Kodi stops and restarts the instance when the song changes), so that is where the app is
// built and where the audio format is registered with the analyser.
#include <kodi/addon-instance/Visualization.h>

#include <chrono>
#include <cstdlib>
#include <memory>
#include <mutex>
#include <string>

#include "gl_include.hpp"
#include "physarum_audio.hpp"

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

// Setting ids and defaults match tools/make_settings_physarum_audio.py.
sandclock::physarum::audio::Settings read_settings() {
    using namespace sandclock::physarum::audio;
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
    s.trail = get_int("trail", s.trail, 0, AUDIO_TRAIL_COUNT - 1);
    s.pace = get_int("pace", s.pace, 1, 4);
    s.start = get_int("start", s.start, 0, AUDIO_START_COUNT - 1);
    s.food = get_int("food", s.food, 0, FOOD_COUNT - 1);
    s.food_nodes = get_int("food_nodes", s.food_nodes, 3, 40);
    s.reactivity = get_int("reactivity", s.reactivity, 0, 150);
    s.sensitivity = get_int("sensitivity", s.sensitivity, 50, 200);
    s.react_speed = kodi::addon::GetSettingBoolean("react_speed", s.react_speed);
    s.react_trails = kodi::addon::GetSettingBoolean("react_trails", s.react_trails);
    s.react_beat = kodi::addon::GetSettingBoolean("react_beat", s.react_beat);
    s.react_colour = kodi::addon::GetSettingBoolean("react_colour", s.react_colour);
    s.beat_zoom = get_int("beat_zoom", s.beat_zoom, 0, 25);
    s.beat_wave = get_int("beat_wave", s.beat_wave, 0, 100);
    s.spectrum = get_int("spectrum", s.spectrum, 0, 2);
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

class ATTR_DLL_LOCAL CPhysarumVisualization : public kodi::addon::CInstanceVisualization {
public:
    explicit CPhysarumVisualization(const kodi::addon::IInstanceInfo& instance)
        : CInstanceVisualization(instance) {}

    bool Start(int channels, int samplesPerSec, int bitsPerSample, const std::string& songName) override {
        Stop();

        std::string error;
        auto app = std::make_shared<sandclock::physarum::audio::App>();
        const unsigned seed =
            (unsigned)std::chrono::steady_clock::now().time_since_epoch().count();
        if (!app->init(read_settings(), seed, &error)) {
            kodi::Log(ADDON_LOG_ERROR, "Physarum Visualisation: cannot start: %s", error.c_str());
            return false;
        }
        if (!error.empty()) kodi::Log(ADDON_LOG_WARNING, "Physarum Visualisation: %s", error.c_str());
        app->start_audio(samplesPerSec, channels);
        {
            std::lock_guard<std::mutex> lock(mu_);
            app_ = app;
        }
        started_ = std::chrono::steady_clock::now();
        last_log_ = 0;
        frames_ = frames_at_log_ = steps_at_log_ = 0;
        samples_ = 0;
        kodi::Log(ADDON_LOG_INFO,
                  "Physarum Visualisation: started \"%s\", %d agents, %d x %d trail (%s), pace %d, "
                  "audio %d Hz / %d ch / %d bit, GL %s",
                  songName.c_str(), app->agents_w() * app->agents_h(), app->trail_w(), app->trail_h(),
                  app->half_float() ? "half float" : "8 bit", app->pace(), samplesPerSec, channels,
                  bitsPerSample, (const char*)glGetString(GL_VERSION));
        return true;
    }

    void Stop() override {
        std::shared_ptr<sandclock::physarum::audio::App> keep;
        {
            std::lock_guard<std::mutex> lock(mu_);
            keep.swap(app_);
        }
        if (keep) keep->release();  // the GL context is still current here
    }

    // Called on Kodi's audio path. The analyser copies into its ring under its own lock; the app
    // is kept alive by the shared_ptr even if Stop() runs at the same moment.
    void AudioData(const float* audioData, size_t audioDataLength) override {
        std::shared_ptr<sandclock::physarum::audio::App> app;
        {
            std::lock_guard<std::mutex> lock(mu_);
            app = app_;
        }
        if (app) app->push_audio(audioData, audioDataLength);
    }

    bool IsDirty() override { return true; }

    void Render() override {
        std::shared_ptr<sandclock::physarum::audio::App> app;
        {
            std::lock_guard<std::mutex> lock(mu_);
            app = app_;
        }
        if (!app) return;
        double now = std::chrono::duration<double>(std::chrono::steady_clock::now() - started_).count();
        app->render(now, Width(), Height());

        // A frame rate line in the log, with the audio's level and bass so a quiet or a loud mix
        // can be told apart from a broken analyser: ten-second samples for the first minute, then
        // one a minute.
        ++frames_;
        double span = now - last_log_;
        if (span >= (samples_ < 6 ? 10.0 : 60.0)) {
            const auto& a = app->audio();
            kodi::Log(ADDON_LOG_INFO, "Physarum Visualisation: %.1f fps, %.1f steps/s (pace %d), level %.2f bass %.2f beat %.0f%%",
                      (frames_ - frames_at_log_) / span, (app->steps() - steps_at_log_) / span, app->pace(),
                      a.level, a.bass, a.beat * 100.0f);
            last_log_ = now;
            frames_at_log_ = frames_;
            steps_at_log_ = app->steps();
            ++samples_;
        }
    }

private:
    std::mutex mu_;
    std::shared_ptr<sandclock::physarum::audio::App> app_;
    std::chrono::steady_clock::time_point started_;
    double last_log_ = 0;
    long frames_ = 0, frames_at_log_ = 0, steps_at_log_ = 0;
    int samples_ = 0;
};

class ATTR_DLL_LOCAL CPhysarumVisualizationAddon : public kodi::addon::CAddonBase {
public:
    CPhysarumVisualizationAddon() = default;
    ADDON_STATUS CreateInstance(const kodi::addon::IInstanceInfo& instance,
                                KODI_ADDON_INSTANCE_HDL& hdl) override {
        if (instance.IsType(ADDON_INSTANCE_VISUALIZATION)) {
            hdl = new CPhysarumVisualization(instance);
            return ADDON_STATUS_OK;
        }
        return ADDON_STATUS_UNKNOWN;
    }
};

ADDONCREATOR(CPhysarumVisualizationAddon)
