// Tests for the GL-free part of the automata screensaver: rule parsing, patterns, the CPU
// reference. The GPU is checked against the same reference by `automata_glfw --selftest`.
#include <cstdio>

#include "automata.hpp"

using namespace sandclock::automata;

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
    for (uint8_t c : s) n += c == 1;
    return n;
}

int main() {
    Rule r;
    CHECK(parse_rule("B3/S23", &r) && r.birth == 8 && r.survive == 12 && r.states == 2, "life");
    CHECK(parse_rule("b36/s23", &r) && r.birth == ((1 << 3) | (1 << 6)), "case");
    CHECK(parse_rule("B2/S/C3", &r) && r.birth == 4 && r.survive == 0 && r.states == 3, "brian");
    CHECK(parse_rule("B234/S345/C24", &r) && r.states == 24, "bloomerang");
    CHECK(!parse_rule("hello", &r) && !parse_rule("B9/S1", &r) && !parse_rule("B3/S2/C1", &r), "rejects bad rules");
    for (int i = 0; i < RULE_COUNT; ++i) CHECK(parse_rule(RULES[i].rule, &r), "rule %d (%s) parses", i, RULES[i].rule);

    CHECK(glider().count() == 5, "glider %d", glider().count());
    CHECK(r_pentomino().count() == 5, "r-pentomino");
    CHECK(acorn().count() == 7, "acorn %d", acorn().count());
    CHECK(gosper_gun().w == 36 && gosper_gun().h == 9 && gosper_gun().count() == 36, "gun %dx%d %d",
          gosper_gun().w, gosper_gun().h, gosper_gun().count());

    // The reference: a glider moves one cell diagonally every 4 generations, a blinker has period 2.
    Rule life;
    parse_rule("B3/S23", &life);
    const int W = 40, H = 30;
    std::vector<uint8_t> a((size_t)W * H, 0), b;
    Stamp g{&glider(), 5, 5, 0};
    for (int y = 0; y < 3; ++y) for (int x = 0; x < 3; ++x) a[(size_t)(5 + y) * W + 5 + x] = g.at(x, y);
    std::vector<uint8_t> start = a;
    for (int i = 0; i < 4; ++i) { step_cpu(a, b, W, H, life, true); a = b; }
    bool moved = true;
    for (int y = 0; y < 3; ++y) for (int x = 0; x < 3; ++x) moved &= a[(size_t)(6 + y) * W + 6 + x] == g.at(x, y);
    CHECK(moved && population(a) == 5, "glider moves (1,1) in 4 generations");
    std::vector<uint8_t> blink((size_t)W * H, 0);
    blink[10 * W + 10] = blink[10 * W + 11] = blink[10 * W + 12] = 1;
    step_cpu(blink, b, W, H, life, true);
    CHECK(b[9 * W + 11] && b[10 * W + 11] && b[11 * W + 11] && population(b) == 3, "blinker flips");
    step_cpu(b, a, W, H, life, true);
    CHECK(a == blink, "blinker period 2");

    // The Gosper gun makes a glider every 30 generations: population 36 -> 41 -> 46.
    std::vector<uint8_t> field(120 * 60, 0), nxt;
    Stamp gun{&gosper_gun(), 2, 2, 0};
    for (int y = 0; y < 9; ++y) for (int x = 0; x < 36; ++x) field[(size_t)(2 + y) * 120 + 2 + x] = gun.at(x, y);
    CHECK(population(field) == 36, "gun population");
    for (int i = 0; i < 60; ++i) { step_cpu(field, nxt, 120, 60, life, false); field = nxt; }
    CHECK(population(field) == 46, "two gliders after 60 generations: population %d", population(field));

    // Orientations stay inside their bounding box and keep the cell count.
    for (int o = 0; o < 8; ++o) {
        Stamp s{&gosper_gun(), 0, 0, o};
        int n = 0;
        for (int y = 0; y < s.height(); ++y) for (int x = 0; x < s.width(); ++x) n += s.at(x, y);
        CHECK(n == 36, "orientation %d keeps 36 cells (%d)", o, n);
    }

    // Brian's Brain: a lone live cell has no neighbours, so it passes through the dying state.
    Rule brain;
    parse_rule("B2/S/C3", &brain);
    std::vector<uint8_t> one((size_t)W * H, 0);
    one[15 * W + 15] = 1;
    step_cpu(one, b, W, H, brain, true);
    CHECK(b[15 * W + 15] == 2, "dying");
    step_cpu(b, a, W, H, brain, true);
    CHECK(a[15 * W + 15] == 0, "dead");

    std::mt19937 rng(3);
    for (int s = 0; s < START_COUNT; ++s) {
        Start st = make_start(s, 960, 540, rng);
        CHECK(st.soup_mode >= 0 || !st.stamps.empty(), "start %d makes something", s);
        for (const Stamp& sp : st.stamps)
            CHECK(sp.x >= 0 && sp.y >= 0 && sp.x + sp.width() <= 960 && sp.y + sp.height() <= 540, "start %d in bounds", s);
    }
    std::printf(failures ? "%d FAILED\n" : "all passed\n", failures);
    return failures ? 1 : 0;
}
