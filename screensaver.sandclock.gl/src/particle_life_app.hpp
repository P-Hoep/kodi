// Particle Life on the GPU: the CPU model in particle_life.*, drawn with additive point sprites
// into an accumulation target that fades itself, so particles leave soft trails. The scene is
// rendered at a capped resolution and scaled up once, and positions are interpolated between
// fixed simulation steps, so motion is smooth even when the simulation runs at 30 steps a second.
// GLSL 1.20 / GLSL ES 1.00 style; gl_util.hpp supplies the dialect prefixes and state restore.
#pragma once

#include <random>
#include <string>
#include <vector>

#include "particle_life.hpp"

namespace sandclock {
namespace particlelife {

class App {
public:
    ~App();

    // The GL context must be current. seed: the starting positions and any random rules.
    // Returns false with *error set if a shader or a target cannot be made.
    bool init(const Settings& settings, unsigned seed, std::string* error);
    void release();

    // Advances the simulation as needed and draws to the current framebuffer, filling fb_w x
    // fb_h. now: seconds on a steady clock (monotonic, may start anywhere).
    void render(double now, int fb_w, int fb_h);

    int particles() const { return world_.count(); }
    int species() const { return world_.rules().species; }
    int draw_width() const { return scene_.w; }
    int draw_height() const { return scene_.h; }
    const Settings& settings() const { return s_; }
    const World& world() const { return world_; }
    std::string rules_text() const { return world_.rules().to_string(); }
    std::string note() const { return note_; }

    // Tests and the harness's --selftest: draw one frame with a fixed interpolated state and
    // report how many pixels ended up brighter than the background.
    int rendered_pixels(int fb_w, int fb_h);

    // Absolute ceilings for the scene target (tests can lower them).
    static int draw_cap_w, draw_cap_h;

private:
    struct Target { unsigned tex = 0, fbo = 0; int w = 0, h = 0; };
    struct PointsU {
        int world = -1, point = -1, alpha = -1, soft = -1, mode = -1, time = -1;
        int cam = -1, zoom = -1;
    };
    struct FadeU { int bg = -1; };
    struct PresentU { int tex = -1, dim = -1; };
    struct Attr { int pos = -1, speed = -1, colour = -1; };

    bool make_target(Target* t, int w, int h);
    void destroy_target(Target* t);
    void draw_quad();
    void update_world_size(int fb_w, int fb_h);
    void build_colours();
    void upload_particles(float t);
    void camera_at(double now, float* cx, float* cy, float* zoom) const;
    void apply_random_look();
    void restart(double now);
    void evolve(double now);
    int loc(unsigned prog, const char* name) const;
    static uint32_t dark_tint(std::mt19937& rng);

    Settings s_;
    World world_;
    std::mt19937 rng_;
    unsigned seed_ = 0;
    std::string note_;

    unsigned prog_points_ = 0, prog_fade_ = 0, prog_present_ = 0;
    unsigned vbo_particles_ = 0, vbo_colours_ = 0, vbo_quad_ = 0, vao_ = 0;
    PointsU pu_;
    FadeU fu_;
    PresentU xu_;
    Attr attr_;
    Target scene_;
    float point_max_ = 64.0f;
    int fb_w_ = 0, fb_h_ = 0;
    int draw_pref_ = 0;

    std::vector<float> frame_;         // interpolated x, y, speed
    std::vector<float> colour_;        // rgb, phase per particle
    bool colours_dirty_ = true;

    double last_now_ = -1, acc_ = 0, next_restart_ = -1, next_evolve_ = -1;
    float last_dt_ = 1.0f / 60.0f;
    long steps_ = 0;
    bool world_sized_ = false;
    bool ready_ = false;
};

}  // namespace particlelife
}  // namespace sandclock
