// Tests for the GL-free part of the Cellular Automata 3D screensaver: rule parsing, the padded
// atlas, starting patterns, the CPU reference. The GPU is checked against the same reference by
// `voxel_glfw --selftest`.
#include <cstdio>
#include <string>

#include "automata_tables.hpp"
#include "voxel.hpp"

using namespace sandclock::voxel;

static int failures = 0;
#define CHECK(cond, ...)                                                \
    do {                                                                \
        if (!(cond)) {                                                  \
            std::printf("FAIL %s:%d  %s  ", __FILE__, __LINE__, #cond); \
            std::printf(__VA_ARGS__);                                   \
            std::printf("\n");                                          \
            ++failures;                                                 \
        }                                                               \
    } while (0)

static int population(const std::vector<uint8_t>& s) {
    int n = 0;
    for (uint8_t c : s) n += c != 0;
    return n;
}

int main() {
    Rule3D r;
    CHECK(parse_rule3d("B4/S45", &r) && r.birth == (1u << 4) &&
              r.survive == ((1u << 4) | (1u << 5)), "Bays' Life");
    CHECK(parse_rule3d("b6,7/s3,4", &r) && r.birth == ((1u << 6) | (1u << 7)) &&
              r.survive == ((1u << 3) | (1u << 4)), "case and several counts");
    CHECK(parse_rule3d(" S2,3 / B0 ", &r) && r.birth == 1u && r.survive == ((1u << 2) | (1u << 3)),
          "parts in any order");
    CHECK(parse_rule3d("B26/S0,26", &r) && r.birth == (1u << 26) &&
              r.survive == (1u | (1u << 26)), "the ends of the range");
    CHECK(parse_rule3d("S1,2", &r) && r.birth == 0 && r.survive == ((1u << 1) | (1u << 2)),
          "survive only");
    CHECK(parse_rule3d("B3", &r) && r.birth == (1u << 3) && r.survive == 0, "birth only");
    CHECK(!parse_rule3d("hello", &r) && !parse_rule3d("B4/Sx", &r) && !parse_rule3d("", &r),
          "rejects bad rules");
    CHECK(parse_rule3d("B27/S1", &r) && r.birth == ((1u << 2) | (1u << 7)),
          "a run above 26 is read as single counts");
    Rule3D before = r;
    CHECK(!parse_rule3d("Bx/S1", &r) && r.birth == before.birth && r.survive == before.survive,
          "a rejected rule leaves the output alone");
    for (int i = 0; i < VOXEL_RULE_COUNT; ++i)
        CHECK(parse_rule3d(VOXEL_RULES[i].rule, &r), "rule %d (%s) parses", i, VOXEL_RULES[i].rule);

    Settings s;
    s.rule = 0;
    Rule3D bays = rule_for(s);
    CHECK(bays.birth == (1u << 4) && bays.survive == ((1u << 4) | (1u << 5)), "rule_for index 0");
    s.rule = VOXEL_RULE_COUNT;
    s.custom_rule = "B7,8/S5,6,7,8";
    Rule3D custom = rule_for(s);
    CHECK(custom.birth == ((1u << 7) | (1u << 8)) &&
              custom.survive == ((1u << 5) | (1u << 6) | (1u << 7) | (1u << 8)), "custom rule");
    s.custom_rule = "nonsense";
    Rule3D fallback = rule_for(s);
    CHECK(fallback.birth == bays.birth && fallback.survive == bays.survive, "bad custom falls back");

    // Presets: every one a complete, valid look, and Custom/Rotate left alone.
    for (int i = 0; i < VOXEL_PRESET_COUNT; ++i) {
        const PresetDef3D& p = VOXEL_PRESETS[i];
        CHECK(p.name && p.name[0], "preset %d has a name", i);
        CHECK(p.rule >= 0 && p.rule < VOXEL_RULE_COUNT && p.grid >= 0 && p.grid < VOXEL_GRID_COUNT &&
                  p.start >= 0 && p.start < VOXEL_START_COUNT &&
                  p.colour_mode >= 0 && p.colour_mode < VOXEL_MODE_COUNT &&
                  p.palette >= 0 && p.palette < sandclock::automata::PALETTE_COUNT &&
                  p.density >= 1 && p.density <= 90 && p.background_style >= 0 &&
                  p.background_style <= 2 && p.glow >= 0 && p.glow <= 100 &&
                  p.screen_fx >= 0 && p.screen_fx <= 2 && p.dim >= 0 && p.dim <= 80 &&
                  p.camera >= 0 && p.camera < VOXEL_CAMERA_COUNT && p.zoom >= 1 && p.zoom <= 8,
              "preset %d (%s) is in range", i, p.name);
        CHECK(!p.infinite || p.wrap, "preset %d only goes endless with wrapping on", i);
        for (int j = 0; j < i; ++j) CHECK(std::string(p.name) != VOXEL_PRESETS[j].name, "preset names differ");
    }
    Settings u;
    u.preset = 3;                                   // Ice Crystal
    Settings res = resolve_preset(u);
    const PresetDef3D& crystal = VOXEL_PRESETS[2];
    CHECK(res.rule == crystal.rule && res.grid == crystal.grid && res.camera == crystal.camera &&
              res.palette == crystal.palette && res.zoom == crystal.zoom, "resolve_preset applies it");
    CHECK(res.speed == u.speed && res.draw == u.draw && res.sparks == u.sparks &&
              res.restart_every == u.restart_every, "a preset leaves the performance settings alone");
    u.preset = VOXEL_PRESET_CUSTOM;
    CHECK(resolve_preset(u).rule == u.rule && !rotating_presets(u), "custom is unchanged");
    u.preset = VOXEL_PRESET_ROTATE;
    CHECK(rotating_presets(u) && resolve_preset(u).rule == u.rule,
          "rotate shows the custom settings until it turns");

    // The atlas: 8 slices a row, one cell of padding all round, interior at +1.
    Atlas a1 = atlas_for(24);
    CHECK(a1.p == 26 && a1.w == 208 && a1.slices == 32 && a1.h == 104, "atlas 24 (%dx%d)", a1.w, a1.h);
    for (int i = 0; i < VOXEL_GRID_COUNT; ++i) {
        Atlas a = atlas_for(VOXEL_GRIDS[i]);
        CHECK(a.w > 0 && a.h > 0 && a.slices >= a.p && a.w == 8 * a.p && a.h % a.p == 0,
              "atlas %d (%dx%d)", VOXEL_GRIDS[i], a.w, a.h);
    }
    CHECK(atlas_texel(a1, 1, 1, 1) == (0 * a1.p + 1) * a1.w + 1 * a1.p + 1, "texel of cell (0,0,0)");
    CHECK(atlas_texel(a1, 1, 1, 8) == (1 * a1.p + 1) * a1.w + 0 * a1.p + 1, "slice 8 starts a row");
    CHECK(atlas_texel(a1, 1, 1, 9) == (1 * a1.p + 1) * a1.w + 1 * a1.p + 1, "slice 9 is the next column");

    // A state survives the trip through the atlas and back, with and without wrapping.
    const int n = 8;
    Atlas a = atlas_for(n);
    std::mt19937 rng(7);
    std::vector<uint8_t> state((size_t)n * n * n);
    for (auto& v : state) v = (rng() % 100) < 40;
    for (int wrap = 1; wrap >= 0; --wrap) {
        std::vector<uint8_t> rgba, back;
        build_atlas(a, state, wrap != 0, &rgba);
        CHECK(rgba.size() == (size_t)a.w * a.h * 4, "atlas size");
        extract_state(a, rgba, &back);
        CHECK(back == state, "atlas round trip, wrap=%d", wrap);
        // Every interior texel is live exactly when its cell is.
        for (int z = 0; z < n; ++z)
            for (int y = 0; y < n; ++y)
                for (int x = 0; x < n; ++x) {
                    size_t t = atlas_texel(a, x + 1, y + 1, z + 1);
                    CHECK((rgba[t * 4 + 3] > 127) == (state[((size_t)z * n + y) * n + x] != 0),
                          "interior texel %d,%d,%d", x, y, z);
                }
    }
    std::vector<uint8_t> one((size_t)n * n * n, 0), rgba;
    one[0] = 1;                                    // cell (0,0,0)
    build_atlas(a, one, false, &rgba);
    CHECK(rgba[atlas_texel(a, 1, 1, 1) * 4 + 3] == 255, "corner cell at +1");
    CHECK(rgba[atlas_texel(a, 0, 0, 0) * 4 + 3] == 0, "no border without wrapping");
    build_atlas(a, one, true, &rgba);
    CHECK(rgba[atlas_texel(a, a.p - 1, 1, 1) * 4 + 3] == 255 &&
              rgba[atlas_texel(a, 1, a.p - 1, 1) * 4 + 3] == 255 &&
              rgba[atlas_texel(a, 1, 1, a.p - 1) * 4 + 3] == 255,
          "wrapped borders duplicate the opposite face");

    // Starting patterns: every one of them fills the cube and leaves something alive.
    for (int st = 0; st < VOXEL_START_COUNT; ++st) {
        std::mt19937 r(100 + st);
        std::vector<uint8_t> p;
        make_start(st, 16, 22, r, &p);
        CHECK(p.size() == 16 * 16 * 16, "start %d size %zu", st, p.size());
        bool binary = true;
        for (uint8_t v : p) binary &= v <= 1;
        CHECK(binary && population(p) > 0, "start %d is non-empty and binary (%d)", st, population(p));
    }
    std::mt19937 rng2(5);
    std::vector<uint8_t> empty;
    make_start(0, 16, 0, rng2, &empty);          // density 0 still has its centre cell
    CHECK(population(empty) >= 1, "density 0 still leaves cells (%d)", population(empty));

    // The reference. A dead volume stays dead.
    Rule3D life;
    parse_rule3d("B4/S45", &life);
    std::vector<uint8_t> dead((size_t)6 * 6 * 6, 0), next;
    step_cpu(dead, next, 6, life, true);
    CHECK(population(next) == 0, "dead stays dead");

    // One live cell, B1/S: all 26 neighbours are born.
    std::vector<uint8_t> seed((size_t)5 * 5 * 5, 0);
    seed[((size_t)2 * 5 + 2) * 5 + 2] = 1;
    Rule3D b1s;
    parse_rule3d("B1/S", &b1s);
    step_cpu(seed, next, 5, b1s, false);
    CHECK(population(next) == 26, "B1/S grows a 26-cell shell (%d)", population(next));

    // A full 4^3 cube under B26/S26. Wrapped, every cell has 26 neighbours and all survive;
    // without wrapping only the 2 x 2 x 2 interior cells have 26.
    std::vector<uint8_t> full((size_t)4 * 4 * 4, 1);
    Rule3D b26s26;
    parse_rule3d("B26/S26", &b26s26);
    step_cpu(full, next, 4, b26s26, true);
    CHECK(population(next) == 64, "B26/S26 keeps a wrapped full cube alive (%d)", population(next));
    step_cpu(full, next, 4, b26s26, false);
    CHECK(population(next) == 8, "B26/S26 keeps only the interior of an open full cube (%d)",
          population(next));
    for (int z = 1; z <= 2; ++z)
        for (int y = 1; y <= 2; ++y)
            for (int x = 1; x <= 2; ++x)
                CHECK(next[((size_t)z * 4 + y) * 4 + x] == 1, "interior %d,%d,%d survives", x, y, z);

    // A dead cell inside a full wrapped cube is born under B26/S26 (it sees all 26 other cells),
    // but its 26 neighbours now see only 25 and die: 63 - 26 alive, plus the hole = 38.
    full[((size_t)1 * 4 + 1) * 4 + 1] = 0;
    step_cpu(full, next, 4, b26s26, true);
    CHECK(population(next) == 38, "B26/S26 fills the hole and starves its neighbours (%d)",
          population(next));

    // Wrapping makes the edges neighbours: a single cell at a corner is equidistant on a torus.
    std::vector<uint8_t> corner((size_t)6 * 6 * 6, 0);
    corner[0] = 1;
    step_cpu(corner, next, 6, b1s, true);
    int near = 0;                                   // cells a king move away, wrapped
    for (int z = 0; z < 6; ++z)
        for (int y = 0; y < 6; ++y)
            for (int x = 0; x < 6; ++x) {
                bool adj = (x <= 1 || x == 5) && (y <= 1 || y == 5) && (z <= 1 || z == 5) &&
                           !(x == 0 && y == 0 && z == 0);
                near += adj;
            }
    CHECK(population(next) == near, "corner cell has %d wrapped neighbours (%d)", near,
          population(next));

    std::printf(failures ? "%d FAILED\n" : "all voxel tests passed\n", failures);
    return failures ? 1 : 0;
}
