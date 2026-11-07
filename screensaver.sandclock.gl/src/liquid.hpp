// Liquid Clock: the clock's digits shimmer like liquid, melt into stretched drops that fall
// into a pool, and the pool is a wave simulation that ripples where drops land and sloshes from
// side to side now and then. Same clock loop and layout as Engine (sand), different physics:
//  - a drop's fall is evaluated on the GPU from its start data and the time, as the sand grains
//    are (Instance, see engine.hpp); drops are cheap and need no per-frame upload;
//  - the pool is a 1-D shallow-water heightfield (COLS columns) stepped on the CPU, and uploaded
//    each frame as one triangle strip (a few KB), so it runs on a 32-bit set-top box.
// Time comes in as arguments, like Engine, so it is testable.
#pragma once
#include <memory>
#include <queue>
#include <random>
#include <string>
#include <vector>

#include "engine.hpp"
#include "sand.hpp"

namespace sandclock {

struct PoolVertex {
    float x, y;      // screen px (1920x1080 space)
    float depth;     // px below the surface: 0 on the surface vertex
    float shade;     // slope shading, -0.25 .. 0.25
};

class LiquidEngine {
public:
    static constexpr int COLS = 192;   // pool columns, each W / COLS px wide

    LiquidEngine(const Settings& s, const Font& font, unsigned seed);

    // real: seconds on a steady clock; clock: seconds since local midnight.
    void update(double real, double clock);

    int grain() const { return g_; }
    const Settings& settings() const { return s_; }
    uint32_t background() const { return bg_; }
    float wobble() const { return 0.3f * g_; }

    const std::vector<Instance>& drops() const { return drops_; }
    const std::vector<Instance>& glyphs() const { return glyph_inst_; }
    bool take_drops_dirty() { bool d = drops_dirty_; drops_dirty_ = false; return d; }
    bool take_glyph_dirty() { bool d = glyph_dirty_; glyph_dirty_ = false; return d; }
    const std::vector<PoolVertex>& pool() const { return pool_; }
    const float* pool_colour() const { return pool_rgb_; }

    // Same names as Engine, for the harness's status line.
    const std::vector<Instance>& pile() const { return drops_; }
    bool take_pile_dirty() { return take_drops_dirty(); }
    double pile_height_px() const { return level_; }
    double sink_speed_now() const { return drain_; }

private:
    struct Splash {
        double t;
        int col;
        float strength;
        float rgb[3];
        bool operator<(const Splash& o) const { return t > o.t; }   // min-heap on t
    };

    void show(double seconds, double ox, double oy);
    void crumble(double boundary, double t0);
    void housekeeping(double t);
    void rebuild_glyphs();
    void advance(double real);
    void step_waves(double dt);
    void slosh(double t);
    void build_pool();
    std::string text_at(double seconds) const;
    std::vector<uint32_t> colours_for(double seconds, const std::string& text,
                                      const std::vector<bool>& changed);

    Settings s_;
    Font font_;
    int g_;
    Grid grid_;
    std::mt19937 rng_;
    uint32_t bg_;

    std::vector<Instance> drops_, glyph_inst_;
    std::vector<double> drop_end_;                 // when each drop has landed
    std::vector<PoolVertex> pool_;
    std::priority_queue<Splash> splashes_;
    std::vector<std::pair<double, int>> inflow_;   // (time, cells) over the last INFLOW seconds
    struct Hide { double at; std::vector<int> slots; };
    std::vector<Hide> hides_;

    std::vector<float> h_, v_, vtmp_;              // surface height and velocity per column
    double level_ = 0;                             // mean liquid height, px
    double drain_ = 0;                             // px/s the level sinks
    float pool_rgb_[3] = {0.3f, 0.6f, 0.9f};
    bool pool_colour_set_ = false;

    std::string text_;
    std::vector<Box> boxes_;
    std::vector<uint32_t> colours_;
    std::vector<bool> hidden_;
    uint32_t last_colour_ = 0;
    bool has_last_ = false;

    bool started_ = false;
    double start_ = 0, boundary_ = 0, crumbled_ = -1, next_housekeeping_ = 0, target_ = 0;
    double interval_ = 1, last_sim_ = -1, sim_acc_ = 0, next_slosh_ = 0;
    bool drops_dirty_ = true, glyph_dirty_ = true;
};

}  // namespace sandclock
