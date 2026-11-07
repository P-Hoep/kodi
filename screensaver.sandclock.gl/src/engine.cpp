#include "engine.hpp"

#include <algorithm>
#include <cmath>

namespace sandclock {

namespace {
constexpr double REBUILD = 1.5;        // s between prunes / sink-speed updates
constexpr double LEAD_MARGIN = 0.12;   // s between planning a crumble and starting it
constexpr double INFLOW_SECONDS = 20.0;
}  // namespace

Engine::Engine(const Settings& s, const Font& font, unsigned seed)
    : s_(s), font_(font), g_(grain_px(s, font)), grid_(g_), rng_(seed), bg_(s.background) {}

Instance Engine::make(double x, double y, double fall_px, double scatter, double delay_s,
                      double fall_s, double slide_s, double born, double dx, double dy,
                      double base_y, uint32_t c, int seed) {
    Instance i;
    i.a0[0] = (float)x; i.a0[1] = (float)y; i.a0[2] = (float)fall_px; i.a0[3] = (float)scatter;
    i.a1[0] = (float)delay_s; i.a1[1] = (float)fall_s; i.a1[2] = (float)slide_s; i.a1[3] = (float)born;
    i.a2[0] = (float)dx; i.a2[1] = (float)dy; i.a2[2] = (float)base_y; i.a2[3] = 0;
    i.a3[0] = ((c >> 16) & 255) / 255.f; i.a3[1] = ((c >> 8) & 255) / 255.f;
    i.a3[2] = (c & 255) / 255.f; i.a3[3] = (float)(seed % 997);
    return i;
}

SinkState Engine::sink() const {
    if (!sim_) return {0, 0, 0, 1e30f, 0};
    return {(float)sim_->base_t, (float)sim_->base_sunk, (float)sim_->speed,
            sim_->has_change ? (float)sim_->change_t : 1e30f, (float)sim_->change_speed};
}

std::string Engine::text_at(double seconds) const {
    long t = (long)seconds % 86400;
    if (t < 0) t += 86400;
    return time_text(s_, (int)(t / 3600), (int)(t / 60 % 60), (int)(t % 60));
}

std::vector<uint32_t> Engine::colours_for(double seconds, const std::string& text,
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

void Engine::rebuild_glyphs() {
    glyph_inst_.clear();
    for (size_t i = 0; i < text_.size(); ++i) {
        if (hidden_[i]) continue;
        for (const GrainCell& c : grains(font_, text_[i], boxes_[i], grid_)) {
            // delay far in the future: the shader leaves it at its start cell
            glyph_inst_.push_back(make(grid_.x(c.col), c.y, 0, 0, 1e6, 0, 0, 0, 0, 0, 0, colours_[i],
                                      c.col * 131 + (int)c.y));
        }
    }
    glyph_dirty_ = true;
}

void Engine::show(double seconds, double ox, double oy) {
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
}

void Engine::crumble(double boundary, double t0) {
    std::string next = text_at(boundary);
    bool whole = s_.crumble == 1 || next.size() != text_.size();
    std::vector<int> slots;
    for (size_t i = 0; i < text_.size(); ++i)
        if (whole || text_[i] != next[i]) slots.push_back((int)i);
    if (slots.empty()) return;

    double gravity = GRAVITY[s_.gravity], spread = SPREAD[s_.speed];
    int n = 0;
    for (int i : slots) {
        auto cells = grains(font_, text_[i], boxes_[i], grid_);
        for (const Flight& f : sim_->drop(cells, colours_[i], t0, gravity, spread)) {
            pile_.push_back(make(f.x, f.y, f.fall_px, f.scatter_px, f.delay / 1000.0, f.fall_ms / 1000.0,
                                 f.slide_ms / 1000.0, t0, f.dx, f.dy, H - (f.row + 1) * g_, f.colour,
                                 f.col * 131 + f.row));
            double t_land = t0 + f.land_ms / 1000.0;
            meta_.push_back({t_land, (double)(H - (f.row + 1) * g_)});
            land_times_.push_back(t_land);
            ++n;
        }
    }
    inflow_.push_back({t0, n});
    hides_.push_back({t0, slots});
    pile_dirty_ = true;
}

void Engine::rebuild(double t) {
    Pile& pile = *sim_;
    if (pile.has_change && t >= pile.change_t - 0.05) pile.commit(pile.change_t);
    pile.prune(t);

    // Forget grains that have landed and sunk out of sight.
    size_t keep = 0;
    double sunk = pile.sunk(t);
    for (size_t i = 0; i < pile_.size(); ++i) {
        if (t >= meta_[i].t_land && meta_[i].base_y + sunk >= H + g_) continue;
        pile_[keep] = pile_[i];
        meta_[keep] = meta_[i];
        ++keep;
    }
    if (keep != pile_.size()) {
        pile_.resize(keep);
        meta_.resize(keep);
        pile_dirty_ = true;
    }
    land_times_.erase(std::remove_if(land_times_.begin(), land_times_.end(), [&](double v) { return v <= t; }),
                      land_times_.end());

    // Sink faster when the pile is too tall, slower when it is low.
    inflow_.erase(std::remove_if(inflow_.begin(), inflow_.end(),
                                 [&](const std::pair<double, int>& e) { return e.first <= t - INFLOW_SECONDS; }),
                  inflow_.end());
    double total = 0;
    for (auto& e : inflow_) total += e.second;
    double rate = total * g_ * g_ / std::min(INFLOW_SECONDS, std::max(1.0, t - start_));
    height_ = pile.height_px(t);
    double speed = sink_speed(rate, height_, target_, pile.footprint(t));
    if (!pile.has_change && speed_changed(speed, pile.speed)) {
        double last = t;
        for (double v : land_times_) last = std::max(last, v);
        pile.schedule(t + REBUILD * std::max(1.0, std::ceil((last - t) / REBUILD)), speed);
    }
}

void Engine::update(double real, double clock) {
    if (!started_) {
        started_ = true;
        start_ = real;
        sim_ = std::make_unique<Pile>(grid_, &rng_, real);
        target_ = pile_target(s_, font_, g_);
        interval_ = s_.seconds ? 1 : 60;
        double dx, dy;
        drift(s_, 0, &dx, &dy);
        show(clock, dx, dy);
        boundary_ = std::floor(clock / interval_ + 1) * interval_;
        next_rebuild_ = real + REBUILD;
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
    for (int guard = 0; real >= next_rebuild_ && guard < 100; ++guard) {
        rebuild(next_rebuild_ + LEAD_MARGIN);
        next_rebuild_ += REBUILD;
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
}

}  // namespace sandclock
