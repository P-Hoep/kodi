#include "liquid.hpp"

#include <algorithm>
#include <cmath>

namespace sandclock {

namespace {
constexpr double HOUSEKEEPING = 1.5;        // s between clean-ups and drain-speed updates
constexpr double LEAD_MARGIN = 0.12;        // s between planning a melt and starting it
constexpr double INFLOW_SECONDS = 20.0;
constexpr double FILL = 0.6;                // how much of a cell's area is liquid
constexpr double SUB_DT = 1.0 / 240.0;      // wave step
constexpr float SPLASH_KICK = 260.0f;       // px/s a drop gives the surface
constexpr float COLOUR_MIX = 0.0009f;       // how fast the pool takes the colour of what lands
constexpr float SLOSH_SCALE[3] = {0.6f, 1.0f, 1.7f};
constexpr double CELL = (double)W / LiquidEngine::COLS;
constexpr double SURFACE_MARGIN = 70.0;     // drops run this far under the pool, which is drawn over them

Instance make_instance(double x, double y, double fall_px, double delay_s, double fall_s, double born,
                       uint32_t c, int seed) {
    Instance i;
    i.a0[0] = (float)x; i.a0[1] = (float)y; i.a0[2] = (float)fall_px; i.a0[3] = 0;
    i.a1[0] = (float)delay_s; i.a1[1] = (float)fall_s; i.a1[2] = 0; i.a1[3] = (float)born;
    i.a2[0] = i.a2[1] = i.a2[2] = i.a2[3] = 0;
    i.a3[0] = ((c >> 16) & 255) / 255.f; i.a3[1] = ((c >> 8) & 255) / 255.f;
    i.a3[2] = (c & 255) / 255.f; i.a3[3] = (float)(seed % 997);
    return i;
}
}  // namespace

LiquidEngine::LiquidEngine(const Settings& s, const Font& font, unsigned seed)
    : s_(s), font_(font), g_(grain_px(s, font)), grid_(g_), rng_(seed), bg_(s.background) {
    h_.assign(COLS, 0.f);
    v_.assign(COLS, 0.f);
    vtmp_.assign(COLS, 0.f);
    pool_.resize(2 * (COLS + 1));
}

std::string LiquidEngine::text_at(double seconds) const {
    long t = (long)seconds % 86400;
    if (t < 0) t += 86400;
    return time_text(s_, (int)(t / 3600), (int)(t / 60 % 60), (int)(t % 60));
}

std::vector<uint32_t> LiquidEngine::colours_for(double seconds, const std::string& text,
                                                const std::vector<bool>& changed) {
    int minute = (int)((long)seconds % 86400 / 60);
    std::vector<uint32_t> out;
    auto fresh = [&] {
        last_colour_ = pick(palette(s_, minute), last_colour_, has_last_, rng_);
        has_last_ = true;
        return last_colour_;
    };
    switch (s_.colour_mode) {
        case COLOUR_ONE: out.assign(text.size(), s_.colour); break;
        case COLOUR_RAINBOW: out.assign(text.size(), rainbow(seconds)); break;
        case COLOUR_EVERY_CHANGE: out.assign(text.size(), fresh()); break;
        default:
            for (size_t i = 0; i < text.size(); ++i)
                out.push_back((changed[i] || i >= colours_.size()) ? fresh() : colours_[i]);
    }
    double f = dim_factor(s_, minute);
    for (auto& c : out) c = scale_colour(c, f);
    return out;
}

void LiquidEngine::rebuild_glyphs() {
    glyph_inst_.clear();
    for (size_t i = 0; i < text_.size(); ++i) {
        if (hidden_[i]) continue;
        for (const GrainCell& c : grains(font_, text_[i], boxes_[i], grid_))
            glyph_inst_.push_back(make_instance(grid_.x(c.col), c.y, 0, 1e6, 0, 0, colours_[i], c.col * 131 + (int)c.y));
    }
    glyph_dirty_ = true;
}

void LiquidEngine::show(double seconds, double ox, double oy) {
    std::string text = text_at(seconds);
    auto boxes = layout(s_, font_, text, ox, oy);
    bool same = text.size() == text_.size();
    std::vector<bool> changed(text.size());
    for (size_t i = 0; i < text.size(); ++i) changed[i] = !same || text[i] != text_[i];
    colours_ = colours_for(seconds, text, changed);
    text_ = text;
    boxes_ = boxes;
    hidden_.assign(text.size(), false);
    hides_.clear();
    rebuild_glyphs();
    if (!pool_colour_set_ && !colours_.empty()) {
        for (int k = 0; k < 3; ++k) pool_rgb_[k] = ((colours_[0] >> (16 - 8 * k)) & 255) / 255.f;
        pool_colour_set_ = true;
    }
}

void LiquidEngine::crumble(double boundary, double t0) {
    std::string next = text_at(boundary);
    bool whole = s_.crumble == 1 || next.size() != text_.size();
    std::vector<int> slots;
    for (size_t i = 0; i < text_.size(); ++i)
        if (whole || text_[i] != next[i]) slots.push_back((int)i);
    if (slots.empty()) return;

    std::uniform_real_distribution<double> u01(0.0, 1.0);
    const double gravity = GRAVITY[s_.gravity], spread = SPREAD[s_.speed];
    const double surface = H - level_;               // where a drop meets the pool (mean level)
    int n = 0;
    for (int i : slots) {
        auto cells = grains(font_, text_[i], boxes_[i], grid_);
        if (cells.empty()) continue;
        double low = -1e9, high = 1e9;
        for (const auto& c : cells) { low = std::max(low, c.y); high = std::min(high, c.y); }
        double span = std::max(1.0, low - high);
        for (const auto& c : cells) {
            double to_surface = surface - c.y;
            if (to_surface <= 0) continue;                 // the liquid is up to the glyph
            double fall_px = to_surface + SURFACE_MARGIN;  // carries on under the surface, hidden by the pool
            double delay = spread * (0.5 * u01(rng_) + 0.5 * (low - c.y) / span);   // lower cells let go first
            double fall_s = std::sqrt(2.0 * fall_px / gravity);
            drops_.push_back(make_instance(grid_.x(c.col), c.y, fall_px, delay, fall_s, t0, colours_[i],
                                           c.col * 131 + (int)c.y));
            drop_end_.push_back(t0 + delay + fall_s);
            Splash sp;
            sp.t = t0 + delay + std::sqrt(2.0 * to_surface / gravity);   // when it meets the surface
            sp.col = std::min(COLS - 1, std::max(0, (int)((grid_.x(c.col) + 0.5 * g_) / CELL)));
            sp.strength = (float)(0.6 + 0.4 * u01(rng_));
            for (int k = 0; k < 3; ++k) sp.rgb[k] = ((colours_[i] >> (16 - 8 * k)) & 255) / 255.f;
            splashes_.push(sp);
            ++n;
        }
    }
    inflow_.push_back({t0, n});
    hides_.push_back({t0, slots});
    drops_dirty_ = true;
}

void LiquidEngine::slosh(double t) {
    // Tilt the pool: displace the surface in the first standing-wave mode; it then rocks side to
    // side as the wave equation plays it out.
    std::uniform_real_distribution<double> u01(0.0, 1.0);
    float sc = SLOSH_SCALE[s_.slosh];
    double amp = std::min(95.0, 10.0 + 0.3 * level_) * sc;
    double dir = u01(rng_) < 0.5 ? -1.0 : 1.0, dir2 = u01(rng_) < 0.5 ? -0.4 : 0.4;
    for (int i = 0; i < COLS; ++i) {
        double x = M_PI * (i + 0.5) / COLS;
        h_[i] += (float)(amp * (dir * std::cos(x) + dir2 * std::cos(2.0 * x)));
    }
    next_slosh_ = t + (4.0 + 7.0 * u01(rng_)) / std::sqrt((double)sc);
}

void LiquidEngine::step_waves(double dt) {
    // Wave speed grows with depth, as in shallow water: c = sqrt(g d), scaled to screen px.
    double c = std::min(1400.0, std::max(500.0, std::sqrt(3735.0 * std::max(level_, 30.0))));
    float k = (float)((c / CELL) * (c / CELL));
    const float damp = (float)(1.0 - 0.22 * dt);
    for (int i = 0; i < COLS; ++i) {
        float l = h_[i > 0 ? i - 1 : 0], r = h_[i < COLS - 1 ? i + 1 : COLS - 1];
        v_[i] = (v_[i] + k * (l + r - 2.f * h_[i]) * (float)dt) * damp;
    }
    for (int i = 0; i < COLS; ++i) {   // a little viscosity keeps the fine ripples from jittering
        float l = v_[i > 0 ? i - 1 : 0], r = v_[i < COLS - 1 ? i + 1 : COLS - 1];
        vtmp_[i] = v_[i] + 0.02f * (l + r - 2.f * v_[i]);
    }
    float limit = (float)std::max(2.0, level_ * 0.9);
    for (int i = 0; i < COLS; ++i) {
        v_[i] = vtmp_[i];
        h_[i] = std::max(-limit, std::min(limit, h_[i] + v_[i] * (float)dt));
    }
}

void LiquidEngine::advance(double real) {
    if (last_sim_ < 0) last_sim_ = real;
    double dt = std::min(0.05, std::max(0.0, real - last_sim_));
    last_sim_ = real;

    // Drops that have landed: add their volume and a splash.
    const double cell_volume = g_ * g_ * FILL;
    while (!splashes_.empty() && splashes_.top().t <= real) {
        const Splash& sp = splashes_.top();
        level_ += cell_volume / W;
        float kick = SPLASH_KICK * sp.strength;
        v_[sp.col] -= kick;
        if (sp.col > 0) v_[sp.col - 1] += 0.5f * kick;
        if (sp.col < COLS - 1) v_[sp.col + 1] += 0.5f * kick;
        for (int k = 0; k < 3; ++k) pool_rgb_[k] += (sp.rgb[k] - pool_rgb_[k]) * COLOUR_MIX;
        splashes_.pop();
    }
    level_ = std::max(0.0, level_ - drain_ * dt);

    if (real >= next_slosh_ && level_ > 6.0) slosh(real);

    sim_acc_ += dt;
    while (sim_acc_ >= SUB_DT) {
        sim_acc_ -= SUB_DT;
        step_waves(SUB_DT);
    }
}

void LiquidEngine::build_pool() {
    for (int j = 0; j <= COLS; ++j) {
        float hj = j == 0 ? h_[0] : (j == COLS ? h_[COLS - 1] : 0.5f * (h_[j - 1] + h_[j]));
        float y = level_ < 0.5 ? (float)H : std::min((float)H, (float)(H - level_ - hj));
        float slope = 0.f;                                   // averaged over a few columns: no stripes
        if (j >= 3 && j <= COLS - 3) slope = (h_[j - 3] - h_[j + 2]) / (5.f * (float)CELL);
        float shade = std::max(-0.15f, std::min(0.15f, slope * 0.9f));
        float x = (float)(j * CELL);
        pool_[2 * j] = {x, y, 0.f, shade};
        pool_[2 * j + 1] = {x, (float)H, (float)H - y, shade};
    }
}

void LiquidEngine::housekeeping(double t) {
    // Forget drops that have landed.
    size_t keep = 0;
    for (size_t i = 0; i < drops_.size(); ++i) {
        if (drop_end_[i] < t - 0.2) continue;
        drops_[keep] = drops_[i];
        drop_end_[keep] = drop_end_[i];
        ++keep;
    }
    if (keep != drops_.size()) {
        drops_.resize(keep);
        drop_end_.resize(keep);
        drops_dirty_ = true;
    }
    // Drain faster when the pool is too deep, slower when it is shallow (as the sand pile sinks).
    inflow_.erase(std::remove_if(inflow_.begin(), inflow_.end(),
                                 [&](const std::pair<double, int>& e) { return e.first <= t - INFLOW_SECONDS; }),
                  inflow_.end());
    double cells = 0;
    for (auto& e : inflow_) cells += e.second;
    double rate = cells * g_ * g_ * FILL / W / std::min(INFLOW_SECONDS, std::max(1.0, t - start_));
    drain_ = rate * std::max(0.0, std::min(3.0, level_ / target_));
}

void LiquidEngine::update(double real, double clock) {
    if (!started_) {
        started_ = true;
        start_ = real;
        target_ = pile_target(s_, font_, g_);
        interval_ = s_.seconds ? 1 : 60;
        double dx, dy;
        drift(s_, 0, &dx, &dy);
        show(clock, dx, dy);
        boundary_ = std::floor(clock / interval_ + 1) * interval_;
        next_housekeeping_ = real + HOUSEKEEPING;
        next_slosh_ = real + 4.0;
    }
    double ld = lead(s_);
    if (std::fabs(boundary_ - clock) > 2 * interval_) {  // the clock jumped
        boundary_ = std::floor(clock / interval_ + 1) * interval_;
        double dx, dy;
        drift(s_, real - start_, &dx, &dy);
        show(clock, dx, dy);
    }
    if (crumbled_ != boundary_ && clock >= boundary_ - ld) {
        crumbled_ = boundary_;
        crumble(boundary_, real + (boundary_ - ld - clock) + LEAD_MARGIN);
    }
    if (clock >= boundary_) {
        double dx, dy;
        drift(s_, real - start_, &dx, &dy);
        show(boundary_, dx, dy);
        boundary_ += interval_;
    }
    for (int guard = 0; real >= next_housekeeping_ && guard < 100; ++guard) {
        housekeeping(next_housekeeping_ + LEAD_MARGIN);
        next_housekeeping_ += HOUSEKEEPING;
    }
    for (size_t k = 0; k < hides_.size();) {
        if (real >= hides_[k].at) {
            for (int i : hides_[k].slots) hidden_[i] = true;
            hides_.erase(hides_.begin() + k);
            rebuild_glyphs();
        } else {
            ++k;
        }
    }
    advance(real);
    build_pool();
}

}  // namespace sandclock
