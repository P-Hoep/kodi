// The clock loop from screensaver.py without Kodi: decides when digits crumble, plans the
// flights and keeps the lists of grains the GPU draws. Time comes in as arguments, so it is
// deterministic and testable. The GPU evaluates each grain's flight from its start data and the
// current time; nothing is uploaded per frame, only when a crumble or a prune changes the lists.
#pragma once
#include <memory>
#include <random>
#include <string>
#include <vector>

#include "sand.hpp"

namespace sandclock {

// One grain as the vertex shader reads it: 4 x vec4.
//   a0 = x0, y0, fall_px, scatter_px      start cell (top-left) and the way down
//   a1 = delay, fall_s, slide_s, born     seconds; the grain starts at born + delay
//   a2 = dx, dy, base_y, 0                slide down the pile; base_y = H-(row+1)*g
//   a3 = r, g, b, seed                    colour 0..1
struct Instance {
    float a0[4], a1[4], a2[4], a3[4];
};

struct SinkState {  // Pile::sunk() as uniforms
    float base_t, base_sunk, speed, change_t, change_speed;
};

class Engine {
public:
    Engine(const Settings& s, const Font& font, unsigned seed);

    // real: seconds on a steady clock; clock: seconds since local midnight.
    void update(double real, double clock);

    int grain() const { return g_; }
    const Settings& settings() const { return s_; }
    const std::vector<Instance>& pile() const { return pile_; }
    const std::vector<Instance>& glyphs() const { return glyph_inst_; }
    bool take_pile_dirty() { bool d = pile_dirty_; pile_dirty_ = false; return d; }
    bool take_glyph_dirty() { bool d = glyph_dirty_; glyph_dirty_ = false; return d; }
    SinkState sink() const;
    double pile_height_px() const { return height_; }
    double sink_speed_now() const { return sim_ ? sim_->speed : 0; }
    uint32_t background() const { return bg_; }

private:
    void show(double seconds, double ox, double oy);
    void crumble(double boundary, double t0);
    void rebuild(double t);
    void rebuild_glyphs();
    std::string text_at(double seconds) const;
    std::vector<uint32_t> colours_for(double seconds, const std::string& text,
                                      const std::vector<bool>& changed);
    static Instance make(double x, double y, double fall_px, double scatter, double delay_s,
                         double fall_s, double slide_s, double born, double dx, double dy,
                         double base_y, uint32_t colour, int seed);

    Settings s_;
    Font font_;
    int g_;
    Grid grid_;
    std::mt19937 rng_;
    uint32_t bg_;

    std::unique_ptr<Pile> sim_;
    std::vector<Instance> pile_, glyph_inst_;
    struct Meta { double t_land, base_y; };
    std::vector<Meta> meta_;
    std::vector<double> land_times_;
    std::vector<std::pair<double, int>> inflow_;
    struct Hide { double at; std::vector<int> slots; };
    std::vector<Hide> hides_;

    std::string text_;
    std::vector<Box> boxes_;
    std::vector<uint32_t> colours_;
    std::vector<bool> hidden_;
    uint32_t last_colour_ = 0;
    bool has_last_ = false;

    bool started_ = false;
    double start_ = 0, boundary_ = 0, crumbled_ = -1, next_rebuild_ = 0, target_ = 0, height_ = 0;
    double interval_ = 1;
    bool pile_dirty_ = true, glyph_dirty_ = true;
};

}  // namespace sandclock
