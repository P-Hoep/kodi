// The Cellular Automata screensaver with GL: the grid lives in two RGBA8 textures that a
// fragment shader ping-pongs between, one pass per generation, so millions of cells cost a few
// texture reads each. Channels per cell:
//   R state (0 dead, 1 alive, 2.. dying), G age in generations / 255, B trail glow, A alive (0/1).
// The draw pass maps each screen pixel to a point on the grid through a camera (pan, zoom, turn)
// or a 3D-looking view (raised blocks, a landscape, a tunnel, a globe) and colours it. A clock in
// the middle is drawn on top and/or written into the grid (digits that burst into life, are cut
// out of the cells, or are made of living cells).
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

private:
    struct Target { unsigned tex = 0, fbo = 0; int w = 0, h = 0; };
    bool make_target(Target* t, int w, int h, bool linear);
    void draw_quad();
    void restart(double now);
    void set_palette();
    void update_clock(double clock);
    void update_camera(double dt);
    int u(unsigned prog, const char* name) const;

    Settings s_;
    Rule rule_;
    unsigned prog_update_ = 0, prog_init_ = 0, prog_draw_ = 0, prog_reduce_ = 0, prog_clock_ = 0;
    unsigned vbo_ = 0, vao_ = 0, pal_tex_ = 0, clock_tex_ = 0;
    Target state_[2];
    int cur_ = 0;
    std::vector<Target> chain_;
    std::mt19937 rng_;
    int cols_ = 0, rows_ = 0;

    // The clock.
    sandclock::Font font_;
    bool has_font_ = false;
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

}  // namespace automata
}  // namespace sandclock
