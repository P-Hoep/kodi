// Liquid Clock: the clock's digits shimmer like liquid, melt into streams that fall into a pool,
// and the pool is a one-dimensional shallow-water simulation. Every colour of liquid is a fluid
// of its own: it has a volume in every column and never blends with the others, so the pool
// settles into coloured layers (heavy liquids below lighter ones) and the falling streams keep
// their colour. Splashes throw spray droplets and foam.
//  - a drop's fall is evaluated on the GPU from its start data and the time, as the sand grains
//    are (Instance, see engine.hpp); drops are cheap and need no per-frame upload;
//  - the pool is swept columns with a velocity at each face (h, u). Mass moves between columns,
//    momentum comes from the surface slope, gravity and drag: waves, sloshing and impacts;
//  - the water body is uploaded each frame as one triangle strip per fluid (a few KB).
// Time comes in as arguments, like Engine, so it is testable.
#pragma once
#include <cstdint>
#include <queue>
#include <random>
#include <string>
#include <vector>

#include "engine.hpp"
#include "sand.hpp"

namespace sandclock {

// A splash droplet or a foam fleck: the vertex shader throws it from its start and lets gravity
// take over, so it never needs an upload per frame either.
//   a0 = x0, y0, vx, vy (screen px, px/s)
//   a1 = born, life, size (px), gravity (px/s^2)
//   a2 = r, g, b, alpha
//   a3 = seed, stretch, -, -
struct SprayInstance {
    float a0[4], a1[4], a2[4], a3[4];
};

// One vertex of a water band: the water body is drawn as one triangle strip per fluid, between
// the fluid's top and bottom interfaces. Both vertices of a column carry the free surface so the
// fragment shader knows how deep it is and where the waterline is.
struct WaterVertex {
    float x, y;        // screen px
    float surf_y;      // the pool surface at this column
    float top_y;       // this fluid's top interface at this column
    float slope;       // d(surface)/dx, for the specular highlight
    float pad;
};

// A fluid's slice of the pool: where its vertices live in the upload buffer and its colour.
struct WaterBand {
    size_t first = 0;   // index of the first vertex
    size_t count = 0;   // number of vertices (a triangle strip)
    float rgb[3] = {0, 0, 0};
};

class LiquidEngine {
public:
    static constexpr int COLS = 256;         // pool columns, each W / COLS px wide
    static constexpr int MAX_FLUIDS = 8;     // coloured liquids that can be in the pool at once

    LiquidEngine(const Settings& s, const Font& font, unsigned seed);

    // real: seconds on a steady clock; clock: seconds since local midnight.
    void update(double real, double clock);

    int grain() const { return g_; }
    const Settings& settings() const { return s_; }
    uint32_t background() const { return bg_; }
    float wobble() const { return 0.18f * g_; }

    const std::vector<Instance>& drops() const { return drops_; }
    const std::vector<Instance>& glyphs() const { return glyph_inst_; }
    bool take_drops_dirty() { bool d = drops_dirty_; drops_dirty_ = false; return d; }
    bool take_glyph_dirty() { bool d = glyph_dirty_; glyph_dirty_ = false; return d; }

    const std::vector<SprayInstance>& spray() const { return spray_; }
    const std::vector<SprayInstance>& foam() const { return foam_; }
    bool take_spray_dirty() { bool d = spray_dirty_; spray_dirty_ = false; return d; }

    // The water body: bands in the shared vertex buffer, and the surface (topmost band) for the
    // renderer's status line.
    const std::vector<WaterVertex>& water() const { return water_; }
    const std::vector<WaterBand>& bands() const { return bands_; }

    // Same names as Engine, for the harness's status line.
    const std::vector<Instance>& pile() const { return drops_; }
    bool take_pile_dirty() { return take_drops_dirty(); }
    double pile_height_px() const { return level_; }
    double sink_speed_now() const { return drain_; }

    // For tests and the harness: the coloured liquids in the pool.
    int fluid_count() const;
    uint32_t fluid_colour(int slot) const { return fluids_[slot].colour; }
    float fluid_volume(int slot) const;
    size_t spray_count() const { return spray_.size(); }
    size_t foam_count() const { return foam_.size(); }

private:
    struct Fluid {
        bool active = false;
        uint32_t key = 0;
        uint32_t colour = 0;
        float rgb[3] = {0, 0, 0};
        float density = 0;
    };
    struct Splash {
        double t;
        int col;
        float strength;
        float speed;
        uint32_t colour;
        bool operator<(const Splash& o) const { return t > o.t; }   // min-heap on t
    };

    void show(double seconds, double ox, double oy);
    void crumble(double boundary, double t0);
    void housekeeping(double t);
    void rebuild_glyphs();
    void advance(double real);
    void step_waves(double dt);
    void transport(double dt);
    void slosh(double t);
    void drain(double dt);
    void build_water();
    void add_spray(const Splash& sp, double now, bool foam);
    int fluid_for(uint32_t colour);
    float column_depth(int col) const;
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
    std::priority_queue<Splash> splashes_;
    std::vector<std::pair<double, int>> inflow_;   // (time, cells) over the last INFLOW seconds
    struct Hide { double at; std::vector<int> slots; };
    std::vector<Hide> hides_;

    // The pool. thick_[k][i] is how many px of fluid k stand in column i; the free surface is
    // their sum. u_ is the water's velocity at each face between columns.
    Fluid fluids_[MAX_FLUIDS];
    float thick_[MAX_FLUIDS][COLS];
    float u_[COLS + 1];
    float h_[COLS];
    std::vector<int> order_;                       // active fluids, heaviest first
    std::vector<WaterVertex> water_;
    std::vector<WaterBand> bands_;
    float tb_[MAX_FLUIDS][COLS + 1];               // scratch: column boundary thicknesses
    float tb2_[MAX_FLUIDS][COLS + 1];              // scratch: the same, one smoothing pass ago
    float surfy_[COLS + 1];                        // scratch: surface y at each boundary

    std::vector<SprayInstance> spray_, foam_;
    bool spray_dirty_ = true;

    double level_ = 0;                             // mean liquid depth, px
    double drain_ = 0;                             // px/s the level sinks

    std::string text_;
    std::vector<Box> boxes_;
    std::vector<uint32_t> colours_;
    std::vector<bool> hidden_;
    uint32_t last_colour_ = 0;
    bool has_last_ = false;

    bool started_ = false;
    double start_ = 0, boundary_ = 0, crumbled_ = -1, next_housekeeping_ = 0, target_ = 0;
    double interval_ = 1, last_sim_ = -1, sim_acc_ = 0, next_slosh_ = 0;
    int last_crumble_cells_ = 1;
    bool drops_dirty_ = true, glyph_dirty_ = true;
};

}  // namespace sandclock
