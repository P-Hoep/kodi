// Cellular Automata 3D with GL: a voxel cellular automaton ray-marched on the GPU.
//   volume: two RGBA8 textures ping-ponged by one fragment shader per generation. The N x N x N
//           grid is laid out as N slices of N x N in 2D (OpenGL ES 2.0 has no 3D textures), each
//           slice surrounded by a border that holds the wrapped (or dead) edge, so the update
//           shader reads its 26 neighbours at fixed offsets with no wrap arithmetic per neighbour.
//   draw:   a ray is cast per pixel through a cube; the first live voxel it meets is shaded with
//           an entry-face normal, edge darkening and fog. Drawn at no more than the "Draw the 3D
//           scene at" resolution and scaled up once.
// The update and draw shaders are generated at init with the wrap, sparks, grid, colour mode,
// background and glow compiled in as constants. There is no clock in this add-on.
// GLSL 1.20 / GLSL ES 1.00 (and 1.50 core with a VAO). Uniforms are packed so the shaders fit the
// 16 fragment uniform vectors GLES 2 promises.
#pragma once
#include <string>
#include <vector>

#include "voxel.hpp"

namespace sandclock {
namespace voxel {

class App {
public:
    ~App();

    // GL context must be current. seed: for the soups, the walks and the sparks. If the settings
    // ask for Rotate, init() builds the Custom settings and the preset changes start on the timer.
    bool init(const Settings& settings, unsigned seed, std::string* error);
    void release();

    // Run the generations that are due and draw (letterboxed 16:9 into fb_w x fb_h). now: seconds
    // on a steady clock.
    void render(double now, int fb_w, int fb_h);

    int n() const { return n_; }
    int cells() const { return n_ * n_ * n_; }
    long generation() const { return generation_; }
    int steps_per_frame_limit() const { return max_steps_; }

    // Tests and the harness's --selftest.
    void upload_state(const std::vector<uint8_t>& states);   // n^3 state values
    void step(int n);
    void read_state(std::vector<uint8_t>* states);
    struct Measure { bool any_alive; unsigned checksum; };
    Measure measure();
    void reseed(double now);

    // The GLSL init() would compile for these settings, without a GL context. The harness's
    // --dump-shaders writes them out for validation with glslangValidator.
    static void shader_sources(const Settings& settings, std::string* update, std::string* draw,
                               std::string* present);

    // Automatic draw caps (tests lower them to exercise the scale-up path).
    static int draw_cap_w, draw_cap_h;

private:
    struct Target { unsigned tex = 0, fbo = 0; int w = 0, h = 0; };
    struct UpdateU { int src = -1, rule = -1, seed = -1, sparks = -1; };
    struct DrawU { int state = -1, pal = -1, colour = -1, bg = -1,
                   eye = -1, right = -1, up = -1, fwd = -1; };
    struct ReduceU { int src = -1, srcsize = -1, first = -1; };
    struct PresentU { int tex = -1; };

    bool make_target(Target* t, int w, int h, bool linear);
    bool build(const Settings& settings, unsigned seed, std::string* error);
    void rotate_if_due(double now);
    void draw_quad();
    void step_saved(int n);
    void restart(double now);
    void set_palette();
    void upload_rule();
    void update_camera(double dt);
    int loc(unsigned prog, const char* name) const;
    static std::string update_source(const Settings& s, const Atlas& a);
    static std::string draw_source(const Settings& s, const Atlas& a);
    static std::string present_source(const Settings& s);

    Settings s_;                     // the settings in effect (a preset applied)
    Settings user_;                  // as given: the preset choice and the performance settings
    bool rotating_ = false;
    std::vector<int> rotation_;      // preset indices, shuffled
    size_t rotation_pos_ = 0;
    double next_rotate_ = 0;         // 0 until the first frame sets the timer
    Rule3D rule_;
    Atlas atlas_;
    int n_ = 0;

    unsigned prog_update_ = 0, prog_draw_ = 0, prog_reduce_ = 0, prog_present_ = 0;
    unsigned vbo_ = 0, vao_ = 0, pal_tex_ = 0, rule_tex_ = 0;
    UpdateU uu_;
    DrawU du_;
    ReduceU ru_;
    PresentU pu_;

    Target state_[2];
    int cur_ = 0;
    std::vector<Target> chain_;
    Target draw_;
    bool draw_scaled_ = false;
    std::mt19937 rng_;
    int draw_pref_ = 0;

    // The orbiting camera: azimuth, elevation and distance from the middle of the volume.
    double cam_t_ = 0, yaw_ = 0.7, pitch_ = 0.42, dist_ = 1.8;

    double last_now_ = -1, acc_ = 0, last_restart_ = 0, next_check_ = 0, next_governor_ = 0, ema_dt_ = 0.016;
    long generation_ = 0, gens_at_check_ = 0;
    int max_steps_ = 4, steps_limit_ = 64, dead_checks_ = 0, stagnant_checks_ = 0;
    std::vector<unsigned> history_;
    bool ready_ = false;
};

}  // namespace voxel
}  // namespace sandclock
