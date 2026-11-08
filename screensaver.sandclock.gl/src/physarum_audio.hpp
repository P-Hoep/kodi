// Physarum Lite as a music visualisation: the same agent model and drawing as the Physarum Lite
// screensaver, with its behaviour and its picture driven by the music Kodi is playing.
//
// There is no clock and no timer. The audio analyser (audio_react.hpp) turns Kodi's samples into
// an overall level, five bands, a beat impulse and a 32-band spectrum. The simulation uses them
// to move faster, deposit more and wander further on loud passages and beats; the draw shader
// uses them to raise the brightness, pulse the camera, send a ring across the screen on every
// beat, shift the palette and (optionally) show the spectrum as bars or a ring.
//
// Settings defaults are deliberately light, like Physarum Lite: 16 thousand agents on a 480 x 270
// trail, no glow, no screen effect, one simulation step per displayed frame. The scene is drawn
// at no more than twice the trail resolution and scaled up.
#pragma once

#include <cstdint>
#include <random>
#include <string>
#include <vector>

#include "audio_react.hpp"
#include "physarum.hpp"
#include "physarum_tables.hpp"

namespace sandclock {
namespace physarum {
namespace audio {

using Params = sandclock::physarum::Params;
using sandclock::physarum::AGENT_COUNT;
using sandclock::physarum::AGENT_SIZES;
using sandclock::physarum::CAMERA_COUNT;
using sandclock::physarum::FOOD_COUNT;
using sandclock::physarum::MODE_COUNT;
using sandclock::physarum::PALETTE_COUNT;
using sandclock::physarum::PRESET_COUNT;
using sandclock::physarum::VIEW_COUNT;

// The shared start list without "From the clock digits" (there is no clock here).
constexpr int AUDIO_START_COUNT = 6;

// The Physarum Lite trail list (480 x 270 first) plus the small map for very weak GPUs. Mirrored
// by tools/make_settings_physarum_audio.py.
constexpr Size AUDIO_TRAIL_SIZES[] = {{480, 270}, {640, 360}, {960, 540}, {1280, 720}, {1920, 1080},
                                      {2560, 1440}, {3840, 2160}, {320, 180}};
constexpr int AUDIO_TRAIL_COUNT = 8;

enum SpectrumStyle { SPECTRUM_OFF, SPECTRUM_BARS, SPECTRUM_RING };

struct Settings {
    // Behaviour, exactly as in Physarum Lite.
    int preset = 0;                  // index into PRESETS; PRESET_COUNT = Custom
    int species = 0;                 // 0..2: one, two or three species
    bool species_differ = true;
    int scale = 100;                 // pattern scale, %
    float sa = 22.5f, ra = 45, so = 9, ss = 10, decay = 90, diffuse = 100, deposit = 30, jitter = 0, repel = 50;

    // Size and speed. Light defaults: 16 thousand agents on 480 x 270, one step per frame.
    int agents = 0;
    int trail = 0;
    int pace = 1;                    // frames per step, 1..4

    // Start and food.
    int start = 0;
    int food = 0;
    int food_nodes = 12;

    // Music. Sensitivity is the analyser's automatic gain (100 = as designed); reactivity is how
    // much of the movement the audio is allowed to change. The boolean switches let a user pick
    // which kinds of reaction they want without turning the whole thing off.
    int reactivity = 70;             // %
    int sensitivity = 100;           // %
    bool react_speed = true;         // loud passages move the agents faster
    bool react_trails = true;        // bass makes stronger, longer-lasting trails
    bool react_beat = true;          // beats add a camera pulse, a ring and a jitter kick
    bool react_colour = true;        // the palette drifts with the music
    int beat_zoom = 8;               // % of zoom on a beat
    int beat_wave = 60;              // % strength of the ring / trail warp
    int spectrum = SPECTRUM_BARS;    // off, bars along the bottom, ring around the edge

    // Colours.
    int colour_mode = 0;
    int palette = 0;
    uint32_t colour = 0xFFD36B;
    uint32_t background = 0x000000;
    int brightness = 100;            // %
    int cycle = 20;
    int glow = 0;                    // off by default: it costs speed
    int screen_fx = 0;
    int dim = 0;

    // Camera and 3D.
    int view = 0;
    int camera = 0;
    int camera_speed = 30;
    int zoom = 3;
};

// The behaviour before the audio is applied: the fixed preset or the Custom sliders.
Params params_for(const Settings& s, float px_scale);

// The audio-modulated behaviour. Exposed for tests and the harness.
Params reactive_params(const Params& base, const Settings& s, const AudioState& a);

class App {
public:
    ~App();
    static bool force_rgba8;         // tests: use the 8-bit trail map even where half floats work
    static int draw_cap_w, draw_cap_h;

    // GL context must be current.
    bool init(const Settings& settings, unsigned seed, std::string* error);
    void release();

    // Kodi's audio comes from another thread; push() only copies into the analyser's ring.
    void start_audio(int sample_rate, int channels);
    void push_audio(const float* interleaved, size_t float_count);

    // now: seconds on a steady clock. One step runs on every pace-th frame.
    void render(double now, int fb_w, int fb_h);

    int agents_w() const { return aw_; }
    int agents_h() const { return ah_; }
    int trail_w() const { return tw_; }
    int trail_h() const { return th_; }
    bool half_float() const { return half_; }
    long steps() const { return steps_; }
    int pace() const { return pace_; }
    int preset() const { return preset_; }
    const AudioState& audio() const { return analyzer_.state(); }

    // Tests and the harness.
    void step(int n, const Params& p);
    void set_agents(const std::vector<float>& x, const std::vector<float>& y, const std::vector<float>& heading);
    void read_agents(std::vector<float>* x, std::vector<float>* y, std::vector<float>* heading);
    void set_trail(const std::vector<uint8_t>& rgba);
    void read_trail(std::vector<uint8_t>* rgba);
    float deposit_amount(const Params& p) const;
    int deposit_stride() const;
    static constexpr long DEPOSIT_BUDGET = 1L << 20;

private:
    struct Target { unsigned tex = 0, fbo = 0; int w = 0, h = 0; };
    bool make_target(Target* t, int w, int h, bool linear, bool half);
    void draw_quad();
    void step_saved(int n, const Params& p);
    void restart();
    void set_palette();
    void build_food();
    void update_camera(double dt);
    void update_spectrum();
    int u(unsigned prog, const char* name) const;

    Settings s_;
    Params params_;
    AudioAnalyzer analyzer_;
    int preset_ = 0;
    std::mt19937 rng_;
    unsigned prog_sense_ = 0, prog_move_ = 0, prog_deposit_ = 0, prog_diffuse_ = 0, prog_init_ = 0;
    unsigned prog_draw_ = 0, prog_upscale_ = 0;
    unsigned vbo_ = 0, points_vbo_ = 0, vao_ = 0, pal_tex_ = 0, food_tex_ = 0, spec_tex_ = 0;
    Target pos_[2], head_[2], trail_[2], draw_;
    int cp_ = 0, ch_ = 0, ct_ = 0;
    int aw_ = 0, ah_ = 0, tw_ = 0, th_ = 0, block_rows_ = 0;
    int species_ = 1;
    bool half_ = false;
    float px_scale_ = 1;

    // Food source positions (x, y pairs in screen uv).
    std::vector<float> nodes_;

    double cam_x_ = 0.5, cam_y_ = 0.5, cam_t_ = 0, zoom_ = 1, rot_ = 0;
    double last_now_ = -1;
    double hue_boost_ = 0;           // extra palette phase accumulated from the music
    long steps_ = 0;
    int pace_ = 1, frames_since_step_ = 0;
    bool ready_ = false;
};

}  // namespace audio
}  // namespace physarum
}  // namespace sandclock
