// CPU tests for the Particle Life model: matrix parsing, the presets, the settings ranges, the
// grid against a brute-force reference, determinism, the boundaries and the start patterns.
#include <cmath>
#include <cstdio>
#include <string>
#include <vector>

#include "particle_life.hpp"

using namespace sandclock::particlelife;

static int failures = 0;

static void check(bool ok, const char* what) {
    std::printf("%-72s %s\n", what, ok ? "ok" : "FAIL");
    if (!ok) ++failures;
}

static void test_parse() {
    Rules r;
    check(r.parse("0.5,-0.25,0.75,0.1", 4) && r.species == 2, "parse a 2-species (4-value) matrix");
    check(r.m[0][0] == 0.5f && r.m[0][1] == -0.25f && r.m[1][0] == 0.75f && r.m[1][1] == 0.1f,
          "values land row-major");
    check(r.parse("1 2 3 4 5 6 7 8 9", 9) && r.species == 3, "whitespace-separated 3-species matrix");
    std::string eight;
    for (int i = 0; i < 64; ++i) eight += (i ? "," : "") + std::string(i % 2 ? "-0.5" : "0.5");
    check(r.parse(eight, 8) && r.species == 8, "8-species (64-value) matrix");
    check(!r.parse("1,2,3,4,5", 4), "reject a non-square count (5)");
    check(!r.parse("1,2,3,4,5,6,7,8,9,10,11,12,13,14,15,16,17", 4), "reject 17 values");
    check(!r.parse("hello", 4), "reject text");
    check(!r.parse("1,2,3,x", 4), "reject a partly numeric matrix");
    check(!r.parse("", 4), "reject empty text");
    check(r.parse(" 0.2 ; 0.3 , 0.4\n0.5 ; ", 4), "accept mixed separators");
    std::string round = Rules{}.to_string();
    check(round.empty(), "empty rules print as empty text");
}

static void test_rules_for() {
    Settings s;
    s.matrix_mode = 1;
    s.custom_matrix = "0.1,0.2,0.3,0.4,0.5,0.6,0.7,0.8,0.9";
    std::string note;
    Rules r = rules_for(s, 7, &note);
    check(r.species == 3 && r.m[2][2] == 0.9f, "rules_for uses the custom matrix");

    s.custom_matrix = "nonsense";
    note.clear();
    r = rules_for(s, 7, &note);
    check(r.species == 4 && !note.empty(), "bad custom text falls back to a preset with a note");

    s.matrix_mode = 2;
    s.species = 6;
    note.clear();
    r = rules_for(s, 1234, &note);
    check(r.species == 6 && note.empty(), "random mode uses the species count");
    bool varied = false, in_range = true;
    for (int i = 0; i < r.species; ++i)
        for (int j = 0; j < r.species; ++j) {
            varied |= r.m[i][j] != r.m[0][0];
            in_range &= r.m[i][j] >= -1.0f && r.m[i][j] <= 1.0f;
        }
    check(varied && in_range, "random matrix is varied and within [-1, 1]");
    Rules with_rule = r;
    r = rules_for(s, 1234, &note);
    bool same = true;
    for (int i = 0; i < r.species; ++i)
        for (int j = 0; j < r.species; ++j) same &= r.m[i][j] == with_rule.m[i][j];
    check(same, "random mode is deterministic in the seed");

    Rules preset;
    check(load_preset(kPresetCount - 1, &preset) && preset.species == 4, "last preset loads");
    check(!load_preset(kPresetCount, &preset), "preset index out of range is rejected");
}

static void test_sanitise() {
    Settings s;
    s.matrix_mode = 99; s.preset = -5; s.species = 1; s.particles = 99; s.radius = 100;
    s.force = 0; s.friction = -2; s.speed = 99; s.start = 99; s.palette = 99; s.colour_mode = 9;
    s.size = 0; s.glow = 999; s.trail = -1; s.dim = 999; s.draw = 99; s.vary = 99;
    s.restart = 99; s.evolve = 99;
    Settings c = sanitise(s);
    check(c.matrix_mode == 2 && c.preset == 0 && c.species == 2, "sanitise clamps rules indices");
    check(c.particles == kParticlesCount - 1 && c.radius == 25 && c.force == 10, "sanitise clamps size");
    check(c.friction == 0 && c.speed == kSpeedCount - 1 && c.start == kStartCount - 1,
          "sanitise clamps speed and start");
    check(c.palette == kPaletteCount - 1 && c.colour_mode == 2 && c.size == 10, "sanitise clamps look");
    check(c.glow == 100 && c.trail == 0 && c.dim == 80, "sanitise clamps glow, trail, dim");
    check(c.draw == kDrawCount - 1 && c.vary == 2 && c.restart == kRestartCount - 1 &&
          c.evolve == kEvolveCount - 1, "sanitise clamps draw and timers");
}

static Settings small_settings() {
    Settings s;
    s.particles = 0;       // 1024
    s.preset = 0;
    s.radius = 10;
    s.start = 0;
    return s;
}

static void test_grid_against_brute_force() {
    Settings s = small_settings();
    World w;
    w.init(s, 16.0f / 9.0f, 42);
    float diff = w.force_difference();
    check(diff < 1e-4f, "grid forces agree with brute force");
    std::printf("        largest force difference: %.3g\n", (double)diff);

    World brute;
    brute.init(s, 16.0f / 9.0f, 42);
    std::vector<float> reference;
    brute.copy_positions(&reference);
    w.set_positions(reference);
    for (int step = 0; step < 12; ++step) {
        w.step();
        brute.step_brute_force();
        std::vector<float> a, b;
        w.copy_positions(&a);
        brute.copy_positions(&b);
        float worst = 0;
        for (size_t i = 0; i < a.size(); ++i) worst = std::max(worst, std::fabs(a[i] - b[i]));
        if (worst > 1e-3f) {
            std::printf("        step %d diverged by %.3g\n", step, (double)worst);
            check(false, "grid step tracks the brute-force step");
            return;
        }
    }
    check(true, "grid step tracks the brute-force step");

    Settings no_wrap = s;
    no_wrap.wrap = false;
    World nw, nb;
    nw.init(no_wrap, 16.0f / 9.0f, 7);
    nb.init(no_wrap, 16.0f / 9.0f, 7);
    check(nw.force_difference() < 1e-4f, "grid forces agree without wrapping");
    nb.copy_positions(&reference);
    nw.set_positions(reference);
    for (int step = 0; step < 8; ++step) { nw.step(); nb.step_brute_force(); }
    std::vector<float> a, b;
    nw.copy_positions(&a);
    nb.copy_positions(&b);
    float worst = 0;
    for (size_t i = 0; i < a.size(); ++i) worst = std::max(worst, std::fabs(a[i] - b[i]));
    check(worst < 1e-3f, "grid step tracks brute force without wrapping");
}

static void test_determinism_and_bounds() {
    Settings s = small_settings();
    World a, b;
    a.init(s, 16.0f / 9.0f, 99);
    b.init(s, 16.0f / 9.0f, 99);
    std::vector<float> pa, pb;
    a.copy_positions(&pa);
    b.copy_positions(&pb);
    check(pa == pb, "the same seed starts identically");
    for (int i = 0; i < 300; ++i) a.step();
    b.init(s, 16.0f / 9.0f, 100);
    b.copy_positions(&pb);
    check(pa != pb, "a different seed starts differently");

    bool inside = true;
    const std::vector<float>& x = a.positions();
    for (size_t i = 0; i < x.size(); i += 2)
        inside &= x[i] >= 0 && x[i] <= a.aspect() && x[i + 1] >= 0 && x[i + 1] <= 1.0f;
    check(inside, "wrapped positions stay inside the world");
    check(a.stats().finite, "wrapped simulation stays finite");
    check(a.stats().max_speed <= a.speed_limit() * 1.001f, "the speed limit holds");

    Settings nw = s;
    nw.wrap = false;
    World c;
    c.init(nw, 16.0f / 9.0f, 3);
    for (int i = 0; i < 600; ++i) c.step();
    inside = true;
    const std::vector<float>& y = c.positions();
    for (size_t i = 0; i < y.size(); i += 2)
        inside &= y[i] >= 0 && y[i] <= c.aspect() && y[i + 1] >= 0 && y[i + 1] <= 1.0f;
    check(inside && c.stats().finite, "bounced positions stay inside the world and finite");
}

static void test_interpolation() {
    Settings s = small_settings();
    s.wrap = false;
    World w;
    w.init(s, 16.0f / 9.0f, 5);
    w.step();
    std::vector<float> at0((size_t)w.count() * 3), at1((size_t)w.count() * 3);
    w.interpolate(at0.data(), 0.0f);
    w.interpolate(at1.data(), 1.0f);
    const std::vector<float>& x = w.positions();
    float e1 = 0;
    for (int i = 0; i < w.count(); ++i)
        e1 = std::max(e1, std::fabs(at1[(size_t)i * 3] - x[(size_t)i * 2]) +
                            std::fabs(at1[(size_t)i * 3 + 1] - x[(size_t)i * 2 + 1]));
    check(e1 < 1e-5f, "interpolation at t=1 reaches the current position");
    bool in_world = true;
    for (int i = 0; i < w.count(); ++i)
        in_world &= at0[(size_t)i * 3] >= 0 && at0[(size_t)i * 3] <= w.aspect() &&
                    at0[(size_t)i * 3 + 1] >= 0 && at0[(size_t)i * 3 + 1] <= 1.0f;
    check(in_world, "interpolated positions stay inside the world");
}

static void test_starts_and_rules() {
    Settings s = small_settings();
    for (int start = 0; start < kStartCount; ++start) {
        s.start = start;
        World w;
        w.init(s, 16.0f / 9.0f, 21 + start);
        bool ok = w.count() == kParticles[0] && w.stats().finite;
        const std::vector<float>& x = w.positions();
        for (size_t i = 0; i < x.size(); i += 2)
            ok &= x[i] >= 0 && x[i] <= w.aspect() && x[i + 1] >= 0 && x[i + 1] <= 1.0f;
        check(ok, kStartNames[start]);
    }

    s.start = 0;
    World w;
    w.init(s, 16.0f / 9.0f, 8);
    int counts[MAX_SPECIES] = {};
    for (uint8_t sp : w.species()) ++counts[sp];
    bool balanced = true;
    int k = w.rules().species;
    for (int i = 0; i < k; ++i)
        balanced &= std::abs(counts[i] - w.count() / k) <= k;
    check(balanced, "species are evenly populated");

    w.randomize_rules(77);
    check(w.rules().species == 4, "randomize_rules keeps the species count");
    Rules before = w.rules();
    w.mutate_rules(0.02f, 88);
    bool changed = false;
    for (int i = 0; i < before.species; ++i)
        for (int j = 0; j < before.species; ++j) changed |= before.m[i][j] != w.rules().m[i][j];
    check(changed, "mutate_rules changes the matrix");
    bool in_range = true;
    for (int i = 0; i < w.rules().species; ++i)
        for (int j = 0; j < w.rules().species; ++j)
            in_range &= w.rules().m[i][j] >= -1.0f && w.rules().m[i][j] <= 1.0f;
    check(in_range, "mutation keeps the matrix in [-1, 1]");
}

static void test_density() {
    // A working simulation gathers particles: the 8 x 8 occupancy spread should be well above
    // the uniform value after a few seconds, and the mean speed should not be enormous.
    Settings s = small_settings();
    World w;
    w.init(s, 16.0f / 9.0f, 2024);
    for (int i = 0; i < 3000; ++i) {
        w.step();
        if ((i + 1) % 600 == 0) {
            World::Stats st = w.stats();
            std::printf("        step %d: mean speed %.4f, density variation %.2f\n", i + 1,
                        (double)st.mean_speed, (double)st.density_variation);
        }
    }
    World::Stats st = w.stats();
    std::printf("        after 3000 steps: mean speed %.4f, density variation %.2f\n",
                (double)st.mean_speed, (double)st.density_variation);
    check(st.finite && st.mean_speed < 0.12f, "long run stays slow enough to look calm");
    check(st.density_variation > 0.7f, "long run clusters the particles");
}

int main() {
    test_parse();
    test_rules_for();
    test_sanitise();
    test_grid_against_brute_force();
    test_determinism_and_bounds();
    test_interpolation();
    test_starts_and_rules();
    test_density();
    std::printf(failures ? "\n%d FAILED\n" : "\nall particle life tests passed\n", failures);
    return failures ? 1 : 0;
}
