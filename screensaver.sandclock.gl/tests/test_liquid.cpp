// Plain-assert tests for liquid.cpp. Run: test_liquid path/to/fonts.json [grain]
#include <algorithm>
#include <chrono>
#include <cmath>
#include <cstdio>
#include <cstdlib>

#include "liquid.hpp"

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
    s.pile = 20;
    if (argc > 2) s.grain = std::atoi(argv[2]);
    Font font = Font::load(path, FONT_FOLDERS[s.font], s.weight);

    auto t0 = std::chrono::steady_clock::now();
    LiquidEngine e(s, font, 7);
    double clock0 = 12 * 3600 + 59 * 60 + 50, maxlevel = 0, minsurface = 1e9, maxsurface = -1e9, maxdrops = 0;
    size_t shown = 0, frames = 0;
    for (int frame = 0; frame < 60 * 300; ++frame) {
        double t = frame / 60.0;
        e.update(t, clock0 + t);
        maxlevel = std::max(maxlevel, e.pile_height_px());
        maxdrops = std::max(maxdrops, (double)e.drops().size());
        if (frame > 60 * 60) {
            for (size_t j = 0; j < e.pool().size(); j += 2) {
                minsurface = std::min(minsurface, (double)e.pool()[j].y);
                maxsurface = std::max(maxsurface, (double)e.pool()[j].y);
            }
        }
        if (frame % 60 == 6) shown += !e.glyphs().empty();
        for (const PoolVertex& v : e.pool()) CHECK(std::isfinite(v.y) && std::isfinite(v.shade), "finite pool");
        ++frames;
    }
    double ms = std::chrono::duration<double, std::milli>(std::chrono::steady_clock::now() - t0).count();
    double target = pile_target(s, font, e.grain());
    std::printf("liquid (grain %d px): 300 s in %.0f ms (%.3f ms/frame); level max %.0f now %.0f (target %.0f), "
                "surface %.0f..%.0f px, %.0f drops at most, drain %.1f px/s\n",
                e.grain(), ms, ms / frames, maxlevel, e.pile_height_px(), target, minsurface, maxsurface, maxdrops,
                e.sink_speed_now());
    CHECK(maxlevel < H * 0.6, "level %.0f", maxlevel);
    CHECK(e.pile_height_px() > 5, "pool has liquid");
    CHECK(maxsurface - minsurface > 4, "the surface moves (%.1f px)", maxsurface - minsurface);
    CHECK(shown >= 295, "clock showing after %zu of 300 changes", shown);
    CHECK(maxdrops > 0 && maxdrops < 20000, "drops %.0f", maxdrops);
    std::printf(failures ? "%d FAILED\n" : "all passed\n", failures);
    return failures ? 1 : 0;
}
