// Cellular Automata Lite with GL: the same GPU automaton as automata_app, with the shaders written
// for speed on weak 32-bit ARM GPUs.
//   grid: two RGBA8 textures ping-ponged by one fragment shader per generation.
//         R state (0 dead, 1 alive, 2.. dying), G age / 255, B trail glow, A alive.
//   draw: the screen is mapped to grid points (flat, or one of the 3D-looking views) and coloured.
// The update and draw shaders are generated at init with the chosen rule, wrap, colour mode, view,
// background, shape, glow and screen effect compiled in as constants, so none of the options that
// are not in use cost anything. The clock, when it is on, is compiled in the same way: with it off
// (the update shader never reads a mask; there is no mask texture and no overlay pass) the cost is
// exactly that of a build without a clock at all. The draw pass renders into a target no larger
// than twice the grid (and never above 1920 x 1080) and scales that up, which is where most of the
// saving on a TV box comes from; the clock overlay is drawn after the scale-up, so its digits stay
// sharp whatever the scene is drawn at.
// GLSL 1.20 / GLSL ES 1.00 (and 1.50 core with a VAO). Uniforms are packed into vec4s so the
// shaders fit the 16 fragment uniform vectors GLES 2 promises.
#pragma once
#include <random>
#include <string>
#include <vector>

#include "automata.hpp"
#include "sand.hpp"

namespace sandclock {
namespace automata {
namespace lite {

class App {
public:
    ~App();

    // GL context must be current. seed: for the soups and sparks. fonts_json: path to the fonts
    // (for the clock); empty or unreadable = no clock.
    bool init(const Settings& settings, unsigned seed, const std::string& fonts_json, std::string* error);
    void release();

    // Run the generations that are due, draw to the current framebuffer (letterboxed 16:9 into
    // fb_w x fb_h), look after restarts. now: seconds on a steady clock; clock: seconds since
    // local midnight.
    void render(double now, double clock, int fb_w, int fb_h);

    int cols() const { return cols_; }
    int rows() const { return rows_; }
    long generation() const { return generation_; }
    int steps_per_frame_limit() const { return max_steps_; }
    bool has_clock() const { return has_font_; }

    // Tests and the harness's --selftest.
    void upload_state(const std::vector<uint8_t>& states);   // cols*rows state values
    void step(int n);
    void read_state(std::vector<uint8_t>* states);
    struct Measure { bool any_alive; unsigned checksum; };
    Measure measure();
    void reseed(double now);

    // The GLSL init() would compile for these settings, without a GL context. `draw` is the source
    // of the draw pass; `update` and `present` are the two other fragment shaders; `clock` is the
    // overlay pass (empty when the clock is off, or when its mode draws the time into the cells
    // instead). Assumes the clock font would load. The harness's --dump-shaders writes these out
    // for validation with glslangValidator.
    static void shader_sources(const Settings& settings, std::string* update, std::string* draw,
                               std::string* present, std::string* clock);

    // Absolute ceilings for the draw pass (tests lower them to exercise the scale-up path).
    static int draw_cap_w, draw_cap_h;

private:
    struct Target { unsigned tex = 0, fbo = 0; int w = 0, h = 0; };
    struct UpdateU { int src = -1, grid = -1, inv = -1, rules = -1, states = -1, seed = -1,
                    mask = -1, maskrect = -1, maskmode = -1; };
    struct InitU { int grid = -1, mode = -1, density = -1, seed = -1; };
    struct DrawU { int state = -1, pal = -1, p0 = -1, p1 = -1, p2 = -1, p3 = -1, colour = -1, bg = -1; };
    struct ReduceU { int src = -1, srcsize = -1, first = -1; };
    struct PresentU { int tex = -1; };
    struct ClockU { int mask = -1, rect = -1, ccol = -1; };

    bool make_target(Target* t, int w, int h, bool linear);
    void draw_quad();
    void step_saved(int n);
    void restart(double now);
    void set_palette();
    void update_clock(double clock);
    void update_camera(double dt);
    int loc(unsigned prog, const char* name) const;
    static std::string update_source(const Settings& s, const Rule& rule, int clock_mask);
    static std::string draw_source(const Settings& s, const Rule& rule);
    static std::string present_source(const Settings& s);
    static const char* clock_source();

    Settings s_;
    Rule rule_;
    unsigned prog_update_ = 0, prog_init_ = 0, prog_draw_ = 0, prog_reduce_ = 0, prog_present_ = 0;
    unsigned prog_clock_ = 0;
    unsigned vbo_ = 0, vao_ = 0, pal_tex_ = 0, clock_tex_ = 0;
    UpdateU uu_;
    InitU iu_;
    DrawU du_;
    ReduceU ru_;
    PresentU pu_;
    ClockU cu_;
    Target state_[2];
    int cur_ = 0;
    std::vector<Target> chain_;
    Target draw_;
    bool draw_scaled_ = false;
    std::mt19937 rng_;
    int cols_ = 0, rows_ = 0;
    int draw_pref_ = 0;                  // Settings::draw: 0 auto, 1..4 a cap, 5 full screen

    // The clock. clock_mask_: 0 the update shader has no mask at all, 1 the digits come alive once
    // when the time changes, 2 they are cut out of the cells, 3 they are alive every generation.
    sandclock::Font font_;
    bool has_font_ = false;
    int clock_mask_ = 0;
    std::string clock_text_;
    float clock_rect_[4] = {0, 0, 0, 0};    // x, y, w, h in grid uv (0..1), y up
    bool seed_pending_ = false;

    // The camera: where it is on the grid (uv, wraps), how far in, which way it faces.
    double cam_x_ = 0.5, cam_y_ = 0.5, cam_t_ = 0, zoom_ = 1, rot_ = 0;

    double last_now_ = -1, acc_ = 0, last_restart_ = 0, next_check_ = 0, next_governor_ = 0, ema_dt_ = 0.016;
    long generation_ = 0, gens_at_check_ = 0;
    int max_steps_ = 4, steps_limit_ = 64, dead_checks_ = 0, stagnant_checks_ = 0;
    std::vector<unsigned> history_;
    bool ready_ = false;
};

}  // namespace lite
}  // namespace automata
}  // namespace sandclock
