#include "liquid.hpp"

#include <algorithm>
#include <cmath>
#include <cstdio>

namespace sandclock {

namespace {
constexpr double HOUSEKEEPING = 1.5;        // s between clean-ups and drain-speed updates
constexpr double LEAD_MARGIN = 0.12;        // s between planning a melt and starting it
constexpr double INFLOW_SECONDS = 20.0;
constexpr double FILL = 0.6;                // how much of a cell's area is liquid
constexpr double SUB_DT = 1.0 / 240.0;      // water step
constexpr float WAVE_GRAV = 4200.0f;        // px/s^2, the gravity the surface waves feel
constexpr float VEL_DAMP = 0.90f;           // 1/s, linear drag on the water
constexpr float VEL_VISC = 0.30f;           // 1/s, sideways smoothing of the velocity field
constexpr float MAX_VEL = 3200.0f;
constexpr float IMPACT_KICK = 0.045f;       // share of the impact speed that throws water aside
constexpr float MAX_FRAC = 0.85f;           // most of a column that may cross a face in one step
constexpr double CELL = (double)W / LiquidEngine::COLS;
constexpr double SURFACE_MARGIN = 70.0;     // drops run this far under the pool, which is drawn over them
constexpr int MAX_SPRAY = 5000;
constexpr int MAX_FOAM = 900;
constexpr float SLOSH_SCALE[3] = {0.6f, 1.0f, 1.7f};

Instance make_instance(double x, double y, double fall_px, double delay_s, double fall_s, double born,
                       uint32_t c, int seed, double jitter = 0.0) {
    Instance i;
    i.a0[0] = (float)x; i.a0[1] = (float)y; i.a0[2] = (float)fall_px; i.a0[3] = (float)jitter;
    i.a1[0] = (float)delay_s; i.a1[1] = (float)fall_s; i.a1[2] = 0; i.a1[3] = (float)born;
    i.a2[0] = i.a2[1] = i.a2[2] = i.a2[3] = 0;
    i.a3[0] = ((c >> 16) & 255) / 255.f; i.a3[1] = ((c >> 8) & 255) / 255.f;
    i.a3[2] = (c & 255) / 255.f; i.a3[3] = (float)(seed % 997);
    return i;
}

// Hue 0..1 (red 0, green 1/3, blue 2/3). A liquid's hue decides how heavy it is, so the pool
// settles into a stable stack of coloured layers: warm reds sink, cool magentas float.
float hue_of(uint32_t c) {
    float r = ((c >> 16) & 255) / 255.f, g = ((c >> 8) & 255) / 255.f, b = (c & 255) / 255.f;
    float mx = std::max(r, std::max(g, b)), mn = std::min(r, std::min(g, b)), d = mx - mn;
    if (d < 1e-5f) return 0.5f;
    float h;
    if (mx == r) h = (g - b) / d + (g < b ? 6.f : 0.f);
    else if (mx == g) h = (b - r) / d + 2.f;
    else h = (r - g) / d + 4.f;
    return h / 6.f;
}

float density_of(uint32_t c) {
    float hue = hue_of(c);
    float luma = 0.2126f * ((c >> 16) & 255) / 255.f + 0.7152f * ((c >> 8) & 255) / 255.f +
                 0.0722f * (c & 255) / 255.f;
    return 1.0f - hue + 0.05f * (1.0f - luma);
}

float spray_alpha(float a) { return std::max(0.05f, std::min(1.0f, a)); }

// Deterministic 0..1 noise from an integer, so every cell of one column draws the same numbers.
double hash01(int n) {
    double s = std::sin(n * 12.9898 + 0.7) * 43758.5453;
    return s - std::floor(s);
}
}  // namespace

LiquidEngine::LiquidEngine(const Settings& s, const Font& font, unsigned seed)
    : s_(s), font_(font), g_(grain_px(s, font)), grid_(g_), rng_(seed), bg_(s.background) {
    for (int k = 0; k < MAX_FLUIDS; ++k)
        for (int i = 0; i < COLS; ++i) thick_[k][i] = 0.f;
    for (int i = 0; i <= COLS; ++i) u_[i] = 0.f;
    for (int i = 0; i < COLS; ++i) h_[i] = 0.f;
    order_.reserve(MAX_FLUIDS);
    bands_.reserve(MAX_FLUIDS);
    water_.reserve((size_t)MAX_FLUIDS * 2 * (COLS + 1));
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
    double mean_level = 0;
    for (int i = 0; i < COLS; ++i) mean_level += h_[i];
    mean_level /= COLS;
    const double surface = H - mean_level;             // where a drop meets the pool (mean level)
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
            // Lower cells let go first and the ones above follow, so a column leaves as a
            // continuous thread; only a little jitter keeps neighbouring threads apart.
            // A whole column of the glyph shares its timing and its small sideways offset, so
            // the cells overlap into one continuous thread; neighbouring columns leave at
            // different moments and widths, so the melt reads as separate streams, not a curtain.
            double h1 = hash01(c.col * 2 + 1), h2 = hash01(c.col * 2 + 2);
            double delay = spread * (0.10 + 0.90 * (low - c.y) / span) + 0.45 * spread * (h1 - 0.5) +
                           0.02 * spread * u01(rng_);
            double fall_s = std::sqrt(2.0 * fall_px / gravity) * (0.92 + 0.18 * h2);
            drops_.push_back(make_instance(grid_.x(c.col), c.y, fall_px, delay, fall_s, t0, colours_[i],
                                           c.col * 131 + (int)c.y, h1));
            drop_end_.push_back(t0 + delay + fall_s);
            double fall_speed = std::sqrt(2.0 * std::max(0.0, to_surface) * gravity);
            Splash sp;
            sp.t = t0 + delay + fall_s;
            sp.col = std::min(COLS - 1, std::max(0, (int)((grid_.x(c.col) + 0.5 * g_) / CELL)));
            sp.strength = (float)(0.55 + 0.45 * u01(rng_));
            sp.speed = (float)fall_speed;
            sp.colour = colours_[i];
            splashes_.push(sp);
            ++n;
        }
    }
    inflow_.push_back({t0, n});
    last_crumble_cells_ = std::max(1, n);
    hides_.push_back({t0, slots});
    drops_dirty_ = true;
}

int LiquidEngine::fluid_for(uint32_t colour) {
    uint32_t key = (colour >> 4) & 0x0F0F0F;   // a coarse key, so a rainbow's slowly drifting hue stays one fluid
    for (int k = 0; k < MAX_FLUIDS; ++k)
        if (fluids_[k].active && fluids_[k].key == key) return k;
    int slot = -1;
    for (int k = 0; k < MAX_FLUIDS; ++k)
        if (!fluids_[k].active) { slot = k; break; }
    if (slot < 0) {   // full: the coloured liquid with the least volume makes way (its water is recoloured)
        float best = 0;
        for (int k = 0; k < MAX_FLUIDS; ++k) {
            float v = fluid_volume(k);
            if (slot < 0 || v < best) { best = v; slot = k; }
        }
    }
    Fluid& f = fluids_[slot];
    f.active = true;
    f.key = key;
    f.colour = colour;
    f.rgb[0] = ((colour >> 16) & 255) / 255.f;
    f.rgb[1] = ((colour >> 8) & 255) / 255.f;
    f.rgb[2] = (colour & 255) / 255.f;
    f.density = density_of(colour);
    return slot;
}

float LiquidEngine::fluid_volume(int slot) const {
    if (slot < 0 || slot >= MAX_FLUIDS || !fluids_[slot].active) return 0.f;
    double v = 0;
    for (int i = 0; i < COLS; ++i) v += thick_[slot][i];
    return (float)(v * CELL);
}

int LiquidEngine::fluid_count() const {
    int n = 0;
    for (int k = 0; k < MAX_FLUIDS; ++k) n += fluids_[k].active && fluid_volume(k) > 1.f;
    return n;
}

float LiquidEngine::column_depth(int col) const {
    col = std::max(0, std::min(COLS - 1, col));
    float d = 0;
    for (int k = 0; k < MAX_FLUIDS; ++k)
        if (fluids_[k].active) d += thick_[k][col];
    return d;
}

void LiquidEngine::add_spray(const Splash& sp, double now, bool foam) {
    std::uniform_real_distribution<double> u01(0.0, 1.0);
    float sx = (float)((sp.col + 0.5) * CELL);
    float surface = (float)H - column_depth(sp.col);
    float r = ((sp.colour >> 16) & 255) / 255.f, g = ((sp.colour >> 8) & 255) / 255.f,
          b = (sp.colour & 255) / 255.f;
    if (foam) {
        // A short-lived crown thrown out sideways where a stream meets the pool: small, bright
        // flecks that sit on the waterline, not a haze that hangs above it.
        SprayInstance p{};
        float size = (float)(2.0 + 3.5 * u01(rng_));
        p.a0[0] = sx + (float)(6.0 * (u01(rng_) - 0.5));
        p.a0[1] = surface + 2.0f;
        p.a0[2] = (float)((u01(rng_) - 0.5) * 200.0);
        p.a0[3] = -(float)(15.0 + 55.0 * u01(rng_));
        p.a1[0] = (float)now;
        p.a1[1] = (float)(0.12 + 0.14 * u01(rng_));
        p.a1[2] = size;
        p.a1[3] = 1500.0f;
        p.a2[0] = 0.72f + 0.28f * r;
        p.a2[1] = 0.78f + 0.22f * g;
        p.a2[2] = 0.82f + 0.18f * b;
        p.a2[3] = spray_alpha((float)(0.38 + 0.30 * u01(rng_)));
        p.a3[0] = (float)(u01(rng_) * 100.0);
        if (foam_.size() >= (size_t)MAX_FOAM) foam_.erase(foam_.begin());
        foam_.push_back(p);
    } else {
        int count = 1 + (int)(rng_() % 3);
        for (int j = 0; j < count; ++j) {
            SprayInstance p{};
            float speed = sp.speed;
            p.a0[0] = sx + (float)(11.0 * (u01(rng_) - 0.5));
            p.a0[1] = surface - 2.0f;
            p.a0[2] = (float)((u01(rng_) - 0.5) * 0.30 * speed);
            p.a0[3] = -(float)((0.20 + 0.30 * u01(rng_)) * speed);   // thrown up in a plume
            p.a1[0] = (float)now;
            p.a1[1] = (float)(0.25 + 0.35 * u01(rng_));
            p.a1[2] = (float)(1.6 + 3.4 * u01(rng_));
            p.a1[3] = 3300.0f;
            p.a2[0] = r; p.a2[1] = g; p.a2[2] = b;
            p.a2[3] = spray_alpha((float)(0.75 + 0.25 * u01(rng_)));
            p.a3[0] = (float)(u01(rng_) * 100.0);
            if (spray_.size() >= (size_t)MAX_SPRAY) spray_.erase(spray_.begin());
            spray_.push_back(p);
        }
    }
    spray_dirty_ = true;
}

void LiquidEngine::slosh(double t) {
    std::uniform_real_distribution<double> u01(0.0, 1.0);
    float sc = SLOSH_SCALE[std::max(0, std::min(2, s_.slosh))];
    double amp = std::min(260.0, 70.0 + 0.55 * level_) * sc;
    double dir = u01(rng_) < 0.5 ? -1.0 : 1.0;
    for (int f = 1; f < COLS; ++f) {
        double x = M_PI * f / COLS;
        u_[f] += (float)(dir * amp * std::sin(x));
    }
    next_slosh_ = t + (4.0 + 7.0 * u01(rng_)) / std::sqrt((double)sc);
}

void LiquidEngine::step_waves(double dt) {
    // Recompute the free surface from the fluid columns.
    for (int i = 0; i < COLS; ++i) {
        float d = 0;
        for (int k = 0; k < MAX_FLUIDS; ++k)
            if (fluids_[k].active) d += thick_[k][i];
        h_[i] = d;
    }
    const float fdt = (float)dt;
    u_[0] = u_[COLS] = 0.f;
    for (int f = 1; f < COLS; ++f) {
        float hl = h_[f - 1], hr = h_[f];
        float slope = (hr - hl) / (float)CELL;
        float u = u_[f];
        // Pressure from the surface slope, plus a little momentum advection so waves steepen.
        float acc = -WAVE_GRAV * slope;
        float dudx = u > 0 ? (u - u_[f - 1]) / (float)CELL : (u_[f + 1] - u) / (float)CELL;
        acc -= u * dudx;
        u += acc * fdt;
        float hm = 0.5f * (hl + hr);
        float drag = VEL_DAMP + 0.0022f * std::fabs(u) / std::max(hm, 40.f);
        u *= std::max(0.f, 1.f - drag * fdt);
        // A touch of sideways viscosity keeps the ripples smooth rather than jagged.
        float smooth = u + VEL_VISC * (u_[f - 1] + u_[f + 1] - 2.f * u) * fdt;
        u_[f] = std::max(-MAX_VEL, std::min(MAX_VEL, smooth));
    }
}

void LiquidEngine::transport(double dt) {
    for (int f = 1; f < COLS; ++f) {
        float frac = u_[f] * (float)dt / (float)CELL;
        frac = std::max(-MAX_FRAC, std::min(MAX_FRAC, frac));
        int donor = frac >= 0 ? f - 1 : f;
        int recv = frac >= 0 ? f : f - 1;
        float a = std::fabs(frac);
        if (a < 1e-6f) continue;
        for (int k = 0; k < MAX_FLUIDS; ++k) {
            if (!fluids_[k].active) continue;
            float m = thick_[k][donor] * a;
            thick_[k][donor] -= m;
            thick_[k][recv] += m;
        }
    }
    for (int i = 0; i < COLS; ++i) {
        float d = 0;
        for (int k = 0; k < MAX_FLUIDS; ++k)
            if (fluids_[k].active) d += thick_[k][i];
        h_[i] = d;
    }
}

void LiquidEngine::drain(double dt) {
    if (drain_ <= 0 || level_ <= 0.2) return;
    order_.clear();
    for (int k = 0; k < MAX_FLUIDS; ++k)
        if (fluids_[k].active) order_.push_back(k);
    std::stable_sort(order_.begin(), order_.end(),
                     [&](int a, int b) { return fluids_[a].density > fluids_[b].density; });
    double drop = drain_ * dt;   // mean level fall, px
    for (int i = 0; i < COLS; ++i) {
        float want = (float)drop;   // px of thickness to take out of this column
        // The floor drain takes the deepest liquid first, so the layers above stay intact.
        for (size_t b = 0; b < order_.size() && want > 0; ++b) {
            int k = order_[b];
            float take = std::min(thick_[k][i], want);
            thick_[k][i] -= take;
            want -= take;
        }
    }
}

void LiquidEngine::advance(double real) {
    if (last_sim_ < 0) last_sim_ = real;
    double dt = std::min(0.05, std::max(0.0, real - last_sim_));
    last_sim_ = real;

    std::uniform_real_distribution<double> u01(0.0, 1.0);
    // Drops that have met the surface: add their volume where they land and throw water aside.
    const float cell_volume = (float)(g_ * g_ * FILL);
    const double spray_prob = std::min(0.18, 420.0 / std::max(1, last_crumble_cells_));
    while (!splashes_.empty() && splashes_.top().t <= real) {
        const Splash& sp = splashes_.top();
        int k = fluid_for(sp.colour);
        static const float WEIGHT[5] = {0.06f, 0.20f, 0.48f, 0.20f, 0.06f};
        for (int d = -2; d <= 2; ++d) {
            int c = sp.col + d;
            if (c < 0 || c >= COLS) continue;
            thick_[k][c] += cell_volume / (float)CELL * WEIGHT[d + 2];
        }
        float kick = IMPACT_KICK * sp.speed * sp.strength;
        if (sp.col > 0) u_[sp.col] -= kick;
        if (sp.col < COLS) u_[sp.col + 1] += kick;
        if (u01(rng_) < spray_prob) add_spray(sp, real, false);
        if (u01(rng_) < spray_prob * 0.80) add_spray(sp, real, true);
        splashes_.pop();
    }

    level_ = 0;
    for (int i = 0; i < COLS; ++i) level_ += h_[i];
    level_ /= COLS;

    if (real >= next_slosh_ && level_ > 6.0) slosh(real);

    sim_acc_ += dt;
    int guard = 0;
    while (sim_acc_ >= SUB_DT && guard++ < 40) {
        sim_acc_ -= SUB_DT;
        step_waves(SUB_DT);
        transport(SUB_DT);
    }
    drain(dt);

    level_ = 0;
    for (int i = 0; i < COLS; ++i) level_ += h_[i];
    level_ /= COLS;

    // Spray and foam have short lives; drop the dead ones.
    auto prune = [&](std::vector<SprayInstance>& v) {
        size_t before = v.size();
        v.erase(std::remove_if(v.begin(), v.end(),
                               [&](const SprayInstance& p) { return p.a1[0] + p.a1[1] < (float)real; }),
                v.end());
        if (v.size() != before) spray_dirty_ = true;
    };
    prune(spray_);
    prune(foam_);
}

void LiquidEngine::build_water() {
    order_.clear();
    for (int k = 0; k < MAX_FLUIDS; ++k)
        if (fluids_[k].active && fluid_volume(k) > 1.0f) order_.push_back(k);
    std::stable_sort(order_.begin(), order_.end(),
                     [&](int a, int b) { return fluids_[a].density > fluids_[b].density; });
    const int nb = (int)order_.size();

    // Thickness at each column boundary, and the surface there.
    for (int j = 0; j <= COLS; ++j) {
        float total = 0;
        for (int b = 0; b < nb; ++b) {
            int k = order_[b];
            float t;
            if (j == 0) t = thick_[k][0];
            else if (j == COLS) t = thick_[k][COLS - 1];
            else t = 0.5f * (thick_[k][j - 1] + thick_[k][j]);
            tb_[b][j] = t;
            total += t;
        }
        surfy_[j] = (float)H - total;
    }
    // A little render-only smoothing so the waterline reads as a curve, not a polyline.
    for (int pass = 0; pass < 2; ++pass) {
        for (int b = 0; b < nb; ++b)
            std::copy(tb_[b], tb_[b] + COLS + 1, tb2_[b]);
        for (int j = 1; j < COLS; ++j)
            for (int b = 0; b < nb; ++b)
                tb_[b][j] = 0.25f * tb2_[b][j - 1] + 0.5f * tb2_[b][j] + 0.25f * tb2_[b][j + 1];
    }
    for (int j = 0; j <= COLS; ++j) {
        float total = 0;
        for (int b = 0; b < nb; ++b) total += tb_[b][j];
        surfy_[j] = (float)H - total;
    }

    water_.resize((size_t)nb * 2 * (COLS + 1));
    bands_.clear();
    bands_.reserve(nb);
    if (nb == 0) return;

    for (int j = 0; j <= COLS; ++j) {
        int l = std::max(0, j - 1), r = std::min(COLS, j + 1);
        float slope = (surfy_[r] - surfy_[l]) / (float)(std::max(1, r - l) * CELL);
        float x = (float)(j * CELL);
        float cum = 0;
        for (int b = 0; b < nb; ++b) {
            float t = tb_[b][j];
            float ytop = (float)H - (cum + t);
            float ybot = (float)H - cum;
            size_t idx = (size_t)b * 2 * (COLS + 1) + (size_t)2 * j;
            water_[idx] = {x, ytop, surfy_[j], ytop, slope, 0};
            water_[idx + 1] = {x, ybot, surfy_[j], ytop, slope, 0};
            cum += t;
        }
    }
    for (int b = 0; b < nb; ++b) {
        int k = order_[b];
        WaterBand band;
        band.first = (size_t)b * 2 * (COLS + 1);
        band.count = (size_t)2 * (COLS + 1);
        band.rgb[0] = fluids_[k].rgb[0];
        band.rgb[1] = fluids_[k].rgb[1];
        band.rgb[2] = fluids_[k].rgb[2];
        bands_.push_back(band);
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
    // Retire liquids that have drained away.
    for (int k = 0; k < MAX_FLUIDS; ++k) {
        if (fluids_[k].active && fluid_volume(k) <= 1.0f) {
            fluids_[k].active = false;
            for (int i = 0; i < COLS; ++i) thick_[k][i] = 0.f;
        }
    }
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
    build_water();
}

}  // namespace sandclock
