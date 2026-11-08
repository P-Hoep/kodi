#include "voxel.hpp"

#include <algorithm>
#include <cctype>

namespace sandclock {
namespace voxel {

bool parse_rule3d(const std::string& text, Rule3D* out) {
    Rule3D r;
    r.birth = r.survive = 0;
    bool have_b = false, have_s = false;
    size_t i = 0;
    while (i < text.size()) {
        char c = (char)std::toupper((unsigned char)text[i]);
        if (c == '/' || c == ' ' || c == ',') { ++i; continue; }
        if (c != 'B' && c != 'S') return false;
        ++i;
        uint32_t mask = 0;
        while (i < text.size()) {
            char d = text[i];
            if (d == ' ' || d == ',') { ++i; continue; }
            if (!std::isdigit((unsigned char)d)) break;
            int v = 0, digits = 0, vals[16] = {0};
            while (i < text.size() && std::isdigit((unsigned char)text[i])) {
                int dv = text[i] - '0';
                if (digits < 16) vals[digits] = dv;
                ++digits;
                if (v <= 1000) v = v * 10 + dv;   // keep the value bounded; only > 26 matters
                ++i;
            }
            if (v <= 26) {
                mask |= 1u << v;
            } else {
                // 3D counts run to 26, so a plain number is a count ("B26" = a birth at 26), but
                // a run too large to be one is the conventional shorthand for its digits: "S45"
                // means S4,S5. (Write counts of 10-26 as the number, e.g. "B26/S10,11".)
                for (int k = 0; k < digits && k < 16; ++k) mask |= 1u << vals[k];
            }
        }
        if (c == 'B') { r.birth = mask; have_b = true; }
        else { r.survive = mask; have_s = true; }
    }
    if (!have_b && !have_s) return false;
    *out = r;
    return true;
}

Rule3D rule_for(const Settings& s) {
    Rule3D r;
    if (s.rule >= 0 && s.rule < VOXEL_RULE_COUNT) parse_rule3d(VOXEL_RULES[s.rule].rule, &r);
    else if (!parse_rule3d(s.custom_rule, &r)) parse_rule3d(VOXEL_RULES[0].rule, &r);
    return r;
}

int grid_for(const Settings& s) {
    return VOXEL_GRIDS[std::max(0, std::min(VOXEL_GRID_COUNT - 1, s.grid))];
}

bool rotating_presets(const Settings& user) { return user.preset == VOXEL_PRESET_ROTATE; }

Settings resolve_preset(const Settings& user) {
    if (user.preset < 1 || user.preset > VOXEL_PRESET_COUNT) return user;
    const PresetDef3D& p = VOXEL_PRESETS[user.preset - 1];
    Settings s = user;
    s.rule = p.rule;
    s.wrap = p.wrap;
    s.grid = p.grid;
    s.start = p.start;
    s.density = p.density;
    s.colour_mode = p.colour_mode;
    s.palette = p.palette;
    s.colour = p.colour;
    s.background_style = p.background_style;
    s.glow = p.glow;
    s.screen_fx = p.screen_fx;
    s.dim = p.dim;
    s.camera = p.camera;
    s.zoom = p.zoom;
    s.infinite = p.infinite && p.wrap;
    return s;
}

Atlas atlas_for(int n) {
    Atlas a;
    a.n = n;
    a.p = n + 2;
    a.w = 8 * a.p;
    int rows = (a.p + 7) / 8;
    a.h = rows * a.p;
    a.slices = rows * 8;
    return a;
}

size_t atlas_texel(const Atlas& a, int x, int y, int z) {
    int row = z / 8, col = z % 8;
    return ((size_t)row * a.p + y) * a.w + (size_t)col * a.p + x;
}

void build_atlas(const Atlas& a, const std::vector<uint8_t>& state, bool wrap, std::vector<uint8_t>* rgba) {
    rgba->assign((size_t)a.w * a.h * 4, 0);
    const int n = a.n;
    for (int z = 0; z < a.p; ++z) {
        for (int y = 0; y < a.p; ++y) {
            for (int x = 0; x < a.p; ++x) {
                int ix = x - 1, iy = y - 1, iz = z - 1;
                if (ix < 0 || ix >= n || iy < 0 || iy >= n || iz < 0 || iz >= n) {
                    if (!wrap) continue;
                    ix = (ix + n) % n;
                    iy = (iy + n) % n;
                    iz = (iz + n) % n;
                }
                if (!state[((size_t)iz * n + iy) * n + ix]) continue;
                uint8_t* px = &(*rgba)[atlas_texel(a, x, y, z) * 4];
                px[0] = 255;
                px[3] = 255;
            }
        }
    }
}

void extract_state(const Atlas& a, const std::vector<uint8_t>& rgba, std::vector<uint8_t>* state) {
    const int n = a.n;
    state->assign((size_t)n * n * n, 0);
    for (int z = 0; z < n; ++z)
        for (int y = 0; y < n; ++y)
            for (int x = 0; x < n; ++x)
                (*state)[((size_t)z * n + y) * n + x] =
                    rgba[atlas_texel(a, x + 1, y + 1, z + 1) * 4 + 3] > 127;
}

void make_start(int start, int n, int density, std::mt19937& rng, std::vector<uint8_t>* state) {
    state->assign((size_t)n * n * n, 0);
    std::vector<uint8_t>& s = *state;
    auto rnd = [&](int lo, int hi) { return lo + (int)(rng() % (unsigned)std::max(1, hi - lo + 1)); };
    auto put = [&](int x, int y, int z) {
        if (x < 0 || y < 0 || z < 0 || x >= n || y >= n || z >= n) return;
        s[((size_t)z * n + y) * n + x] = 1;
    };
    const int d = std::max(1, std::min(90, density));
    const int c = n / 2;
    switch (start) {
        case 0:
            for (auto& v : s) v = (int)(rng() % 100) < d;
            break;
        case 1:
            for (auto& v : s) v = (int)(rng() % 100) < std::max(1, d / 3);
            break;
        case 2: {                                     // clusters: blobs of soup
            int count = std::max(3, std::min(24, n / 6));
            for (int i = 0; i < count; ++i) {
                int cx = rnd(0, n - 1), cy = rnd(0, n - 1), cz = rnd(0, n - 1);
                int r = rnd(std::max(2, n / 10), std::max(3, n / 4));
                for (int z = std::max(0, cz - r); z <= std::min(n - 1, cz + r); ++z)
                    for (int y = std::max(0, cy - r); y <= std::min(n - 1, cy + r); ++y)
                        for (int x = std::max(0, cx - r); x <= std::min(n - 1, cx + r); ++x) {
                            int dx = x - cx, dy = y - cy, dz = z - cz;
                            if (dx * dx + dy * dy + dz * dz > r * r) continue;
                            if ((int)(rng() % 100) < d) put(x, y, z);
                        }
            }
            break;
        }
        case 3: {                                     // a sphere of soup in the middle
            int r = std::max(2, n * 3 / 10);
            for (int z = c - r; z <= c + r; ++z)
                for (int y = c - r; y <= c + r; ++y)
                    for (int x = c - r; x <= c + r; ++x) {
                        int dx = x - c, dy = y - c, dz = z - c;
                        if (dx * dx + dy * dy + dz * dz <= r * r && (int)(rng() % 100) < d) put(x, y, z);
                    }
            break;
        }
        case 4: {                                     // a hollow sphere
            int r = std::max(3, n * 2 / 5), t = std::max(2, n / 12);
            int lo = r - t, hi = r + t;
            for (int z = c - hi; z <= c + hi; ++z)
                for (int y = c - hi; y <= c + hi; ++y)
                    for (int x = c - hi; x <= c + hi; ++x) {
                        int dx = x - c, dy = y - c, dz = z - c;
                        int dd = dx * dx + dy * dy + dz * dz;
                        if (dd >= lo * lo && dd <= hi * hi && (int)(rng() % 100) < 70) put(x, y, z);
                    }
            break;
        }
        case 5: {                                     // a 3D lattice of lines
            int step = std::max(3, n / 6);
            for (int z = 0; z < n; ++z)
                for (int y = 0; y < n; ++y)
                    for (int x = 0; x < n; ++x)
                        if ((x % step == 0 || y % step == 0 || z % step == 0) && (int)(rng() % 100) < d)
                            put(x, y, z);
            break;
        }
        case 6: {                                     // a few thick random walks
            for (int w = 0; w < 10; ++w) {
                int x = rnd(0, n - 1), y = rnd(0, n - 1), z = rnd(0, n - 1);
                for (int k = 0; k < n * 2; ++k) {
                    put(x, y, z);
                    put(x + 1, y, z);
                    int axis = rnd(0, 2);
                    int dir = rnd(0, 1) ? 1 : -1;
                    if (axis == 0) x += dir;
                    else if (axis == 1) y += dir;
                    else z += dir;
                    x = std::max(0, std::min(n - 1, x));
                    y = std::max(0, std::min(n - 1, y));
                    z = std::max(0, std::min(n - 1, z));
                }
            }
            break;
        }
        case 7: {                                     // the 12 edges of an inset cube
            int lo = std::max(1, n / 8), hi = n - 1 - lo, t = std::max(1, n / 24);
            for (int z = 0; z < n; ++z)
                for (int y = 0; y < n; ++y)
                    for (int x = 0; x < n; ++x) {
                        auto near = [&](int v) { return (v >= lo && v < lo + t) + (v <= hi && v > hi - t); };
                        if (near(x) + near(y) + near(z) >= 2) put(x, y, z);
                    }
            break;
        }
        case 8: {                                     // a solid crystal seed
            int r = std::max(2, n / 12);
            for (int z = c - r; z <= c + r; ++z)
                for (int y = c - r; y <= c + r; ++y)
                    for (int x = c - r; x <= c + r; ++x) {
                        int dx = x - c, dy = y - c, dz = z - c;
                        if (dx * dx + dy * dy + dz * dz <= r * r) put(x, y, z);
                    }
            break;
        }
        default:
            for (auto& v : s) v = (int)(rng() % 100) < d;
            break;
    }
    bool any = false;
    for (uint8_t v : s) any |= v != 0;
    if (!any) s[((size_t)c * n + c) * n + c] = 1;
}

void step_cpu(const std::vector<uint8_t>& in, std::vector<uint8_t>& out, int n, const Rule3D& rule,
              bool wrap) {
    out.assign(in.size(), 0);
    for (int z = 0; z < n; ++z) {
        for (int y = 0; y < n; ++y) {
            for (int x = 0; x < n; ++x) {
                int count = 0;
                for (int dz = -1; dz <= 1; ++dz) {
                    for (int dy = -1; dy <= 1; ++dy) {
                        for (int dx = -1; dx <= 1; ++dx) {
                            if (!dx && !dy && !dz) continue;
                            int xx = x + dx, yy = y + dy, zz = z + dz;
                            if (wrap) {
                                xx = (xx + n) % n;
                                yy = (yy + n) % n;
                                zz = (zz + n) % n;
                            } else if (xx < 0 || yy < 0 || zz < 0 || xx >= n || yy >= n || zz >= n) {
                                continue;
                            }
                            count += in[((size_t)zz * n + yy) * n + xx] != 0;
                        }
                    }
                }
                bool alive = in[((size_t)z * n + y) * n + x] != 0;
                uint32_t mask = alive ? rule.survive : rule.birth;
                out[((size_t)z * n + y) * n + x] = (uint8_t)((mask >> count) & 1u);
            }
        }
    }
}

}  // namespace voxel
}  // namespace sandclock
