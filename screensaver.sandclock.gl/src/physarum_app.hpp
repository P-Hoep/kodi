// The Physarum screensaver with GL. Everything lives on the GPU:
//   agents: two pairs of ping-pong RGBA8 textures, one texel per agent:
//           position (x in RG, y in BA, 16 bits each) and heading (RG, 16 bits);
//   trail:  one ping-pong pair the size of the trail map, R G B = the three species' trails,
//           A = food (the clock digits and food sources), which every species is drawn to.
// One step is four passes: sense and turn (heading), move (position), deposit (every agent drawn
// as a point into the trail with additive blending; the vertex shader reads the agent's position
// from its texture), and diffuse + decay + feed (trail). The draw pass colours the trail through a
// camera or a 3D-looking view, and the clock is drawn on top or fed into the trail as food.
// GLSL 1.20 / GLSL ES 1.00 (1.50 core with a VAO). Needs vertex texture fetch and highp floats in
// fragment shaders, which GLES 2 devices Kodi runs on have.
#pragma once
#include <random>
#include <string>
#include <vector>

#include "physarum.hpp"
#include "sand.hpp"

namespace sandclock {
namespace physarum {

class App {
public:
    ~App();
    static bool force_rgba8;          // tests: use the 8-bit trail map even where half floats work

    // GL context must be current. fonts_json: for the clock; empty = no clock.
    bool init(const Settings& settings, unsigned seed, const std::string& fonts_json, std::string* error);
    void release();

    // now: seconds on a steady clock; clock: seconds since local midnight.
    void render(double now, double clock, int fb_w, int fb_h);

    int agents_w() const { return aw_; }
    int agents_h() const { return ah_; }
    int trail_w() const { return tw_; }
    int trail_h() const { return th_; }
    bool half_float() const { return half_; }
    long steps() const { return steps_; }
    int steps_per_frame_limit() const { return max_steps_; }
    const Behaviour& behaviour() const { return behaviour_; }

    // Tests and the harness's --selftest. Positions are 0..1 of the trail, headings 0..1 of a turn.
    void step(int n, const Params& p);
    void set_agents(const std::vector<float>& x, const std::vector<float>& y, const std::vector<float>& heading);
    void read_agents(std::vector<float>* x, std::vector<float>* y, std::vector<float>* heading);
    void set_trail(const std::vector<uint8_t>& rgba);       // trail_w * trail_h * 4
    void read_trail(std::vector<uint8_t>* rgba);
    float deposit_amount(const Params& p) const;   // per agent per step
    int deposit_stride() const;                     // 1 = every agent deposits every step
    static constexpr long DEPOSIT_BUDGET = 1L << 20;

private:
    struct Target { unsigned tex = 0, fbo = 0; int w = 0, h = 0; };
    bool make_target(Target* t, int w, int h, bool linear, bool half);
    void draw_quad();
    void restart(double now);
    void set_palette();
    void update_clock(double clock);
    void build_food();
    void update_camera(double dt);
    int u(unsigned prog, const char* name) const;

    Settings s_;
    Behaviour behaviour_{Settings(), 1, 1};
    std::mt19937 rng_;
    unsigned prog_sense_ = 0, prog_move_ = 0, prog_deposit_ = 0, prog_diffuse_ = 0, prog_init_ = 0;
    unsigned prog_draw_ = 0, prog_clock_ = 0;
    unsigned vbo_ = 0, points_vbo_ = 0, vao_ = 0, pal_tex_ = 0, clock_tex_ = 0, food_tex_ = 0;
    Target pos_[2], head_[2], trail_[2];
    int cp_ = 0, ch_ = 0, ct_ = 0;
    int aw_ = 0, ah_ = 0, tw_ = 0, th_ = 0, block_rows_ = 0;
    int species_ = 1;
    bool half_ = false;
    float px_scale_ = 1;

    // The clock and the food.
    sandclock::Font font_;
    bool has_font_ = false;
    std::string clock_text_;
    std::vector<uint8_t> clock_px_;           // the clock bitmap (RGBA), clock_w_ x clock_h_
    int clock_w_ = 0, clock_h_ = 0;
    float clock_rect_[4] = {0, 0, 0, 0};      // x, y, w, h in screen uv (0..1), y up
    std::vector<float> nodes_;                // food sources: x, y pairs in screen uv
    bool restart_pending_ = true;

    double cam_x_ = 0.5, cam_y_ = 0.5, cam_t_ = 0, zoom_ = 1, rot_ = 0;
    double last_now_ = -1, acc_ = 0, last_restart_ = 0, next_governor_ = 0, ema_dt_ = 0.016;
    long steps_ = 0;
    int max_steps_ = 2, steps_limit_ = 32;
    bool ready_ = false;
};

}  // namespace physarum
}  // namespace sandclock
