// Plain-assert tests for the core: sand.cpp and engine.cpp. Run: test_sand path/to/fonts.json
#include <algorithm>
#include <cmath>
#include <cstdio>
#include <chrono>
#include <cstdlib>

#include "engine.hpp"
#include "sand.hpp"

using namespace sandclock;

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

int main(int argc, char** argv) {
    const char* path = argc > 1 ? argv[1] : "fonts.json";
    Settings s;
    if (argc > 2) s.grain = std::atoi(argv[2]);  // bench: 0 = finest
    Font font = Font::load(path, FONT_FOLDERS[s.font], s.weight);
    CHECK(font.h > 0 && font.masks.count('8') && font.masks.count(':'), "font loaded");

    // layout: the widest text fills at most `size` % of the width
    auto boxes = layout(s, font, widest_text(s));
    double span = boxes.back().x + boxes.back().w - boxes.front().x;
    CHECK(span <= W * s.size / 100.0 + 2, "span %.1f", span);

    CHECK(time_text(s, 9, 5, 7) == "09:05:07", "24h text");
    Settings t12;
    t12.hours = 1;
    t12.seconds = false;
    CHECK(time_text(t12, 0, 5, 7) == "12:05", "12h text %s", time_text(t12, 0, 5, 7).c_str());

    // grains: an 8 has plenty, and every grain sits on the grid inside the screen
    int g = grain_px(s, font);
    Grid grid(g);
    auto b = layout(s, font, "88:88:88");
    auto cells = grains(font, '8', b[0], grid);
    CHECK(cells.size() > 50, "%zu grains in an 8", cells.size());
    for (auto& c : cells) CHECK(c.col >= 0 && c.col < grid.cols && c.y >= -g && c.y <= H, "cell in range");

    // drop: heights add up, columns have no gaps
    std::mt19937 rng(1);
    Pile pile(grid, &rng, 0);
    int total = 0;
    for (int round = 0; round < 6; ++round) {
        auto fl = pile.drop(cells, 0xFFFFFF, round * 1.0, GRAVITY[1], SPREAD[1]);
        total += (int)fl.size();
        for (auto& f : fl) {
            CHECK(f.fall_ms >= 0 && f.slide_ms >= 0 && f.land_ms >= f.delay, "times");
            CHECK(f.row >= 0, "row %d", f.row);
        }
    }
    int stacked = 0;
    for (int h : pile.heights) stacked += h;
    CHECK(stacked == total, "heights %d vs flights %d", stacked, total);
    for (auto& col : pile.cells)
        CHECK((int)col.second.size() == pile.heights[col.first], "col %d gap", col.first);
    int steep = 0;
    for (int c = 1; c < grid.cols; ++c) steep += std::abs(pile.heights[c] - pile.heights[c - 1]) > 1;
    std::printf("pile: %d grains, %d steep neighbours\n", total, steep);

    // engine: run the clock for 5 simulated minutes at 60 fps
    auto wall0 = std::chrono::steady_clock::now();
    Engine engine(s, font, 42);
    double clock0 = 12 * 3600 + 59 * 60 + 50, maxh = 0;
    size_t maxn = 0, shown = 0;
    for (int frame = 0; frame < 60 * 300; ++frame) {
        double t = frame / 60.0;
        engine.update(t, clock0 + t);
        maxn = std::max(maxn, engine.pile().size());
        maxh = std::max(maxh, engine.pile_height_px());
        if (frame % 60 == 6) shown += !engine.glyphs().empty();  // just after a new time appears
    }
    double ms = std::chrono::duration<double, std::milli>(std::chrono::steady_clock::now() - wall0).count();
    std::printf("engine (grain %d px): 300 s simulated in %.0f ms (%.2f ms per frame)\n", g, ms, ms / 18000);
    std::printf("engine: %zu grains at most, pile %.0f px (now %.0f), sinking %.1f px/s\n", maxn, maxh,
                engine.pile_height_px(), engine.sink_speed_now());
    CHECK(maxn > 0 && maxn < 60000, "grain count %zu", maxn);
    CHECK(maxh < H * 0.6, "pile height %.0f", maxh);
    CHECK(shown >= 295, "clock showing after %zu of 300 changes", shown);
    for (const Instance& i : engine.pile())
        CHECK(std::isfinite(i.a0[0]) && std::isfinite(i.a0[1]) && std::isfinite(i.a1[1]), "finite");

    std::printf(failures ? "%d FAILED\n" : "all passed\n", failures);
    return failures ? 1 : 0;
}
