// Particle Life model: see particle_life.hpp.
#include "particle_life.hpp"

#include <algorithm>
#include <cmath>
#include <cstdio>
#include <cstdlib>
#include <utility>

namespace sandclock {
namespace particlelife {
namespace {

int clamp_int(int v, int lo, int hi) { return v < lo ? lo : (v > hi ? hi : v); }
float clamp_f(float v, float lo, float hi) { return v < lo ? lo : (v > hi ? hi : v); }

bool separator(char c) {
    return c == '\0' || c == ' ' || c == '\t' || c == '\r' || c == '\n' || c == ',' || c == ';';
}

}  // namespace

bool Rules::parse(const std::string& text, int species_hint) {
    std::vector<float> values;
    const char* p = text.c_str();
    while (*p) {
        while (*p == ' ' || *p == '\t' || *p == '\r' || *p == '\n' || *p == ',' || *p == ';') ++p;
        if (!*p) break;
        char* end = nullptr;
        float v = std::strtof(p, &end);
        if (end == p || !std::isfinite(v)) return false;
        if (!separator(*end)) return false;
        values.push_back(v);
        p = end;
        if (values.size() > MAX_SPECIES * MAX_SPECIES) return false;
    }
    if (values.size() < 4) return false;
    int k = (int)std::lround(std::sqrt((double)values.size()));
    if (k * k != (int)values.size() || k < 2 || k > MAX_SPECIES) return false;
    (void)species_hint;   // the count is authoritative; a hint would only hide a typo
    species = k;
    for (int i = 0; i < k; ++i)
        for (int j = 0; j < k; ++j) m[i][j] = clamp_f(values[i * k + j], -2.0f, 2.0f);
    return true;
}

void Rules::randomize(int k, std::mt19937& rng) {
    species = clamp_int(k, 2, MAX_SPECIES);
    std::uniform_real_distribution<float> u(-0.9f, 0.9f);
    for (int i = 0; i < species; ++i) {
        for (int j = 0; j < species; ++j) {
            // Uniform random rules are what the original's randomise button makes; a slightly
            // stronger, usually positive diagonal gives more self-cohesion and fewer lonely
            // scatterings, which reads better as a screensaver.
            float v = u(rng);
            if (i == j) v = v * 0.45f + 0.22f;
            m[i][j] = clamp_f(v, -1.0f, 1.0f);
        }
    }
}

void Rules::mutate(float amount, std::mt19937& rng) {
    std::normal_distribution<float> n(0.0f, amount);
    for (int i = 0; i < species; ++i)
        for (int j = 0; j < species; ++j) m[i][j] = clamp_f(m[i][j] + n(rng), -1.0f, 1.0f);
}

std::string Rules::to_string() const {
    std::string out;
    char buf[24];
    for (int i = 0; i < species; ++i) {
        for (int j = 0; j < species; ++j) {
            std::snprintf(buf, sizeof buf, "%.3g", (double)m[i][j]);
            if (!out.empty()) out += ',';
            out += buf;
        }
    }
    return out;
}

std::string matrix_text(const Rules& rules) { return rules.to_string(); }

bool load_preset(int index, Rules* rules) {
    if (!rules || index < 0 || index >= kPresetCount) return false;
    rules->species = 4;
    for (int i = 0; i < 4; ++i)
        for (int j = 0; j < 4; ++j) rules->m[i][j] = kPresets[index][i][j];
    return true;
}

Rules rules_for(const Settings& s, unsigned seed, std::string* note) {
    Rules rules;
    std::mt19937 rng(seed ? seed : 1u);
    if (s.matrix_mode == 1) {
        if (rules.parse(s.custom_matrix, s.species)) return rules;
        if (note) *note = "Custom matrix not understood; using preset '" + std::string(kPresetNames[0]) + "'";
        load_preset(0, &rules);
        return rules;
    }
    if (s.matrix_mode == 2) {
        rules.randomize(clamp_int(s.species, 2, MAX_SPECIES), rng);
        return rules;
    }
    if (!load_preset(clamp_int(s.preset, 0, kPresetCount - 1), &rules)) load_preset(0, &rules);
    return rules;
}

Settings sanitise(Settings s) {
    s.matrix_mode = clamp_int(s.matrix_mode, 0, 2);
    s.preset = clamp_int(s.preset, 0, kPresetCount - 1);
    s.species = clamp_int(s.species, 2, MAX_SPECIES);
    s.particles = clamp_int(s.particles, 0, kParticlesCount - 1);
    s.radius = clamp_int(s.radius, 5, 25);
    s.force = clamp_int(s.force, 10, 200);
    s.friction = clamp_int(s.friction, 0, 90);
    s.speed = clamp_int(s.speed, 0, kSpeedCount - 1);
    s.start = clamp_int(s.start, 0, kStartCount - 1);
    s.palette = clamp_int(s.palette, 0, kPaletteCount - 1);
    s.colour_mode = clamp_int(s.colour_mode, 0, 2);
    s.size = clamp_int(s.size, 10, 100);
    s.glow = clamp_int(s.glow, 0, 100);
    s.trail = clamp_int(s.trail, 0, 95);
    s.dim = clamp_int(s.dim, 0, 80);
    s.draw = clamp_int(s.draw, 0, kDrawCount - 1);
    s.vary = clamp_int(s.vary, 0, 2);
    s.restart = clamp_int(s.restart, 0, kRestartCount - 1);
    s.evolve = clamp_int(s.evolve, 0, kEvolveCount - 1);
    return s;
}

void World::init(const Settings& settings, float aspect, unsigned seed) {
    Settings s = sanitise(settings);
    count_ = kParticles[s.particles];
    start_ = s.start;
    aspect_ = clamp_f(aspect, 0.5f, 4.0f);
    radius_ = s.radius / 100.0f;
    force_ = (s.force / 100.0f) * 0.05f;
    friction_ = (s.friction / 100.0f) * 5.0f;      // 1/s
    damping_ = std::exp(-friction_ * dt_);
    speed_limit_ = 0.25f;
    wrap_ = s.wrap;

    std::string note;
    rules_ = rules_for(s, seed, &note);
    reset_positions(seed);
}

void World::reset_positions(unsigned seed) {
    std::mt19937 rng(seed ? seed : 1u);
    std::uniform_real_distribution<float> u(0.0f, 1.0f);
    x_.assign((size_t)count_ * 2, 0.0f);
    v_.assign((size_t)count_ * 2, 0.0f);
    species_.resize((size_t)count_);

    const int k = std::max(1, rules_.species);
    // Species round-robin, then shuffled for the patterns that do not use the species index.
    for (int i = 0; i < count_; ++i) species_[i] = (uint8_t)(i % k);
    for (int i = count_ - 1; i > 0; --i) std::swap(species_[i], species_[rng() % (unsigned)(i + 1)]);

    auto put = [&](int i, float px, float py) {
        px = std::fmod(px, aspect_);
        if (px < 0) px += aspect_;
        py = std::fmod(py, 1.0f);
        if (py < 0) py += 1.0f;
        x_[(size_t)i * 2] = px;
        x_[(size_t)i * 2 + 1] = py;
    };
    auto disk = [&](float cx, float cy, float radius) {
        float a = u(rng) * 6.2831853f;
        float r = radius * std::sqrt(u(rng));
        return std::pair<float, float>(cx + std::cos(a) * r, cy + std::sin(a) * r);
    };

    switch (start_) {
        default:
        case 0:   // scattered over the whole world
            for (int i = 0; i < count_; ++i) put(i, u(rng) * aspect_, u(rng));
            break;
        case 1:   // one disk in the middle
            for (int i = 0; i < count_; ++i) {
                auto p = disk(aspect_ * 0.5f, 0.5f, 0.34f);
                put(i, p.first, p.second);
            }
            break;
        case 2:   // a ring
            for (int i = 0; i < count_; ++i) {
                float a = u(rng) * 6.2831853f;
                float r = 0.29f + 0.07f * (u(rng) * 2 - 1);
                put(i, aspect_ * 0.5f + std::cos(a) * r, 0.5f + std::sin(a) * r);
            }
            break;
        case 3: {  // a disk per species, arranged in a circle
            for (int i = 0; i < count_; ++i) {
                float a = 6.2831853f * (species_[i] / (float)k);
                float cx = aspect_ * 0.5f + std::cos(a) * 0.27f;
                float cy = 0.5f + std::sin(a) * 0.27f;
                auto p = disk(cx, cy, 0.075f + 0.02f * (float)(k > 4));
                put(i, p.first, p.second);
            }
            break;
        }
        case 4: {  // a jittered grid
            int gx = std::max(1, (int)std::sqrt((double)count_ * aspect_));
            int gy = (count_ + gx - 1) / gx;
            for (int i = 0; i < count_; ++i) {
                int cx = i % gx, cy = i / gx;
                put(i, (cx + u(rng)) / gx * aspect_, (cy + u(rng)) / gy);
            }
            break;
        }
        case 5: {  // two blobs, species split between them
            for (int i = 0; i < count_; ++i) {
                bool left = species_[i] < (k + 1) / 2;
                auto p = disk(left ? aspect_ * 0.3f : aspect_ * 0.7f, 0.5f, 0.24f);
                put(i, p.first, p.second);
            }
            break;
        }
    }
    prev_ = x_;
}

void World::set_rules(const Rules& rules) {
    rules_ = rules;
    if (rules_.species < 1) rules_.species = 1;
}

void World::randomize_rules(unsigned seed) {
    std::mt19937 rng(seed ? seed : 1u);
    rules_.randomize(rules_.species, rng);
    // Existing species labels are still valid: randomize keeps the species count.
}

void World::mutate_rules(float amount, unsigned seed) {
    std::mt19937 rng(seed ? seed : 1u);
    rules_.mutate(amount, rng);
}

void World::build_grid() {
    cols_ = std::max(1, (int)std::ceil(aspect_ / radius_));
    rows_ = std::max(1, (int)std::ceil(1.0f / radius_));
    cells_ = cols_ * rows_;
    cell_start_.assign((size_t)cells_ + 1, 0);
    cursor_.assign((size_t)cells_, 0);
    cell_index_.resize((size_t)count_);
    for (int i = 0; i < count_; ++i) {
        int cx = clamp_int((int)(x_[(size_t)i * 2] / aspect_ * cols_), 0, cols_ - 1);
        int cy = clamp_int((int)(x_[(size_t)i * 2 + 1] * rows_), 0, rows_ - 1);
        ++cell_start_[(size_t)cy * cols_ + cx + 1];
    }
    for (int c = 0; c < cells_; ++c) cell_start_[c + 1] += cell_start_[c];
    for (int c = 0; c < cells_; ++c) cursor_[c] = cell_start_[c];
    for (int i = 0; i < count_; ++i) {
        int cx = clamp_int((int)(x_[(size_t)i * 2] / aspect_ * cols_), 0, cols_ - 1);
        int cy = clamp_int((int)(x_[(size_t)i * 2 + 1] * rows_), 0, rows_ - 1);
        cell_index_[(size_t)cursor_[(size_t)cy * cols_ + cx]++] = i;
    }
}

// The force particle j exerts on particle i, added to (sx, sy). Extracted so the grid step and
// the brute-force reference in the tests run the very same arithmetic.
void World::add_pair(int i, int j, float xi, float yi, float* sx, float* sy) const {
    float dx = xi - x_[(size_t)j * 2];
    float dy = yi - x_[(size_t)j * 2 + 1];
    if (wrap_) {
        if (dx > aspect_ * 0.5f) dx -= aspect_;
        else if (dx < -aspect_ * 0.5f) dx += aspect_;
        if (dy > 0.5f) dy -= 1.0f;
        else if (dy < -0.5f) dy += 1.0f;
    }
    float d2 = dx * dx + dy * dy;
    if (d2 <= 1e-12f || d2 >= radius_ * radius_) return;
    float d = std::sqrt(d2);
    float a = rules_.m[species_[i]][species_[j]];
    float f;
    float core = beta_ * radius_;
    if (d < core) {
        f = d / core - 1.0f;                        // hard core: always repels
    } else {
        f = a * (1.0f - std::fabs(2.0f * d / radius_ - 1.0f - beta_) / (1.0f - beta_));
    }
    float inv = f / d;
    *sx += dx * inv;
    *sy += dy * inv;
}

void World::forces_grid(int i, float* sx, float* sy) const {
    *sx = *sy = 0.0f;
    float xi = x_[(size_t)i * 2], yi = x_[(size_t)i * 2 + 1];
    int cx = clamp_int((int)(xi / aspect_ * cols_), 0, cols_ - 1);
    int cy = clamp_int((int)(yi * rows_), 0, rows_ - 1);
    for (int oy = -1; oy <= 1; ++oy) {
        for (int ox = -1; ox <= 1; ++ox) {
            int nx = cx + ox, ny = cy + oy;
            if (wrap_) {
                nx = (nx % cols_ + cols_) % cols_;
                ny = (ny % rows_ + rows_) % rows_;
            } else if (nx < 0 || nx >= cols_ || ny < 0 || ny >= rows_) {
                continue;
            }
            int c = ny * cols_ + nx;
            for (int n = cell_start_[c]; n < cell_start_[c + 1]; ++n) {
                int j = cell_index_[n];
                if (j != i) add_pair(i, j, xi, yi, sx, sy);
            }
        }
    }
}

void World::forces_brute(int i, float* sx, float* sy) const {
    *sx = *sy = 0.0f;
    float xi = x_[(size_t)i * 2], yi = x_[(size_t)i * 2 + 1];
    for (int j = 0; j < count_; ++j)
        if (j != i) add_pair(i, j, xi, yi, sx, sy);
}

void World::integrate(float fx, float fy, int i) {
    float vx = (v_[(size_t)i * 2] + fx * force_ * dt_) * damping_;
    float vy = (v_[(size_t)i * 2 + 1] + fy * force_ * dt_) * damping_;
    float sp2 = vx * vx + vy * vy;
    if (sp2 > speed_limit_ * speed_limit_) {
        float sc = speed_limit_ / std::sqrt(sp2);
        vx *= sc;
        vy *= sc;
    }
    float px = x_[(size_t)i * 2] + vx * dt_;
    float py = x_[(size_t)i * 2 + 1] + vy * dt_;
    if (wrap_) {
        px = std::fmod(px, aspect_);
        if (px < 0) px += aspect_;
        py = std::fmod(py, 1.0f);
        if (py < 0) py += 1.0f;
    } else {
        // Bounce off the edges: reflect the position and the velocity, and clamp so a particle
        // that leaves in one frame cannot get stuck outside.
        if (px < 0) { px = -px; vx = -vx; }
        else if (px > aspect_) { px = 2.0f * aspect_ - px; vx = -vx; }
        if (py < 0) { py = -py; vy = -vy; }
        else if (py > 1.0f) { py = 2.0f - py; vy = -vy; }
        px = clamp_f(px, 0.0f, aspect_);
        py = clamp_f(py, 0.0f, 1.0f);
    }
    v_[(size_t)i * 2] = vx;
    v_[(size_t)i * 2 + 1] = vy;
    x_[(size_t)i * 2] = px;
    x_[(size_t)i * 2 + 1] = py;
}

void World::step() {
    prev_ = x_;
    build_grid();
    force_sum_.assign((size_t)count_ * 2, 0.0f);
    for (int i = 0; i < count_; ++i) {
        float fx, fy;
        forces_grid(i, &fx, &fy);
        force_sum_[(size_t)i * 2] = fx;
        force_sum_[(size_t)i * 2 + 1] = fy;
    }
    for (int i = 0; i < count_; ++i) integrate(force_sum_[(size_t)i * 2], force_sum_[(size_t)i * 2 + 1], i);
}

void World::step_brute_force() {
    prev_ = x_;
    force_sum_.assign((size_t)count_ * 2, 0.0f);
    for (int i = 0; i < count_; ++i) {
        float fx, fy;
        forces_brute(i, &fx, &fy);
        force_sum_[(size_t)i * 2] = fx;
        force_sum_[(size_t)i * 2 + 1] = fy;
    }
    for (int i = 0; i < count_; ++i) integrate(force_sum_[(size_t)i * 2], force_sum_[(size_t)i * 2 + 1], i);
}

float World::force_difference() {
    build_grid();
    std::vector<float> a((size_t)count_ * 2), b((size_t)count_ * 2);
    for (int i = 0; i < count_; ++i) {
        forces_grid(i, &a[(size_t)i * 2], &a[(size_t)i * 2 + 1]);
        forces_brute(i, &b[(size_t)i * 2], &b[(size_t)i * 2 + 1]);
    }
    float worst = 0;
    for (size_t i = 0; i < a.size(); ++i) worst = std::max(worst, std::fabs(a[i] - b[i]));
    return worst;
}

void World::interpolate(float* out, float t) const {
    t = clamp_f(t, 0.0f, 1.0f);
    for (int i = 0; i < count_; ++i) {
        float dx = x_[(size_t)i * 2] - prev_[(size_t)i * 2];
        float dy = x_[(size_t)i * 2 + 1] - prev_[(size_t)i * 2 + 1];
        if (wrap_) {
            if (dx > aspect_ * 0.5f) dx -= aspect_;
            else if (dx < -aspect_ * 0.5f) dx += aspect_;
            if (dy > 0.5f) dy -= 1.0f;
            else if (dy < -0.5f) dy += 1.0f;
        }
        float px = prev_[(size_t)i * 2] + dx * t;
        float py = prev_[(size_t)i * 2 + 1] + dy * t;
        if (wrap_) {
            px = std::fmod(px, aspect_);
            if (px < 0) px += aspect_;
            py = std::fmod(py, 1.0f);
            if (py < 0) py += 1.0f;
        }
        float vx = v_[(size_t)i * 2], vy = v_[(size_t)i * 2 + 1];
        float speed = std::sqrt(vx * vx + vy * vy) / speed_limit_;
        out[(size_t)i * 3] = px;
        out[(size_t)i * 3 + 1] = py;
        out[(size_t)i * 3 + 2] = clamp_f(speed, 0.0f, 1.0f);
    }
}

void World::copy_positions(std::vector<float>* out) const { *out = x_; }

void World::set_positions(const std::vector<float>& x) {
    if (x.size() != (size_t)count_ * 2) return;
    x_ = x;
    prev_ = x;
}

World::Stats World::stats() const {
    Stats st;
    if (count_ == 0) return st;
    for (int i = 0; i < count_; ++i) {
        float vx = v_[(size_t)i * 2], vy = v_[(size_t)i * 2 + 1];
        float s = std::sqrt(vx * vx + vy * vy);
        st.mean_speed += s;
        st.max_speed = std::max(st.max_speed, s);
        if (!std::isfinite(x_[(size_t)i * 2]) || !std::isfinite(x_[(size_t)i * 2 + 1]) ||
            !std::isfinite(vx) || !std::isfinite(vy))
            st.finite = false;
    }
    st.mean_speed /= count_;
    // 8 x 8 occupancy: how clustered the particles are (coefficient of variation).
    int bins[64] = {};
    for (int i = 0; i < count_; ++i) {
        int bx = clamp_int((int)(x_[(size_t)i * 2] / aspect_ * 8.0f), 0, 7);
        int by = clamp_int((int)(x_[(size_t)i * 2 + 1] * 8.0f), 0, 7);
        ++bins[by * 8 + bx];
    }
    float mean = count_ / 64.0f, var = 0;
    for (int b : bins) var += (b - mean) * (b - mean);
    st.density_variation = mean > 0 ? std::sqrt(var / 64.0f) / mean : 0;
    return st;
}

}  // namespace particlelife
}  // namespace sandclock
