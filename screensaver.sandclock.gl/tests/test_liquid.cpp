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
    double clock0 = 12 * 3600 + 59 * 60 + 50, maxlevel = 0, minlevel = 1e9;
    double minsurface = 1e9, maxsurface = -1e9, maxdrops = 0, maxspray = 0, maxfoam = 0, maxfluids = 0;
    size_t shown = 0, frames = 0;
    double band_volumes = 0;
    for (int frame = 0; frame < 60 * 300; ++frame) {
        double t = frame / 60.0;
        e.update(t, clock0 + t);
        maxlevel = std::max(maxlevel, e.pile_height_px());
        minlevel = std::min(minlevel, e.pile_height_px());
        maxdrops = std::max(maxdrops, (double)e.drops().size());
        maxspray = std::max(maxspray, (double)e.spray_count());
        maxfoam = std::max(maxfoam, (double)e.foam_count());
        maxfluids = std::max(maxfluids, (double)e.fluid_count());
        if (frame > 60 * 60) {
            for (const WaterVertex& v : e.water()) {
                minsurface = std::min(minsurface, (double)v.surf_y);
                maxsurface = std::max(maxsurface, (double)v.surf_y);
            }
        }
        if (frame % 60 == 6) shown += !e.glyphs().empty();
        for (const WaterVertex& v : e.water())
            CHECK(std::isfinite(v.y) && std::isfinite(v.surf_y) && std::isfinite(v.slope), "finite water");
        if (frame % 60 == 0) {
            // The coloured liquids stay separate: every active fluid owns real volume, and the
            // volumes add up to the pool's mean depth across the screen.
            double sum = 0;
            int active = 0;
            for (int k = 0; k < LiquidEngine::MAX_FLUIDS; ++k) {
                if (!e.fluid_colour(k)) continue;
                float vol = e.fluid_volume(k);
                if (vol > 1.f) {
                    ++active;
                    CHECK(vol > 0.f, "fluid %d volume %.1f", k, vol);
                    sum += vol;
                }
            }
            CHECK(active == e.fluid_count(), "fluid count %d vs %d", active, e.fluid_count());
            if (active > 0) {
                double expected = e.pile_height_px() * W;
                CHECK(std::fabs(sum - expected) < 0.05 * expected + 2.0 * W,
                      "fluid volume %.0f vs pool %.0f", sum, expected);
                band_volumes = sum;
            }
        }
        ++frames;
    }
    double ms = std::chrono::duration<double, std::milli>(std::chrono::steady_clock::now() - t0).count();
    double target = pile_target(s, font, e.grain());
    std::printf("liquid (grain %d px): 300 s in %.0f ms (%.3f ms/frame); level max %.0f now %.0f (target %.0f), "
                "surface %.0f..%.0f px, %.0f drops, %.0f spray, %.0f foam, %d fluids (up to %.0f), "
                "drain %.1f px/s, volume %.0f\n",
                e.grain(), ms, ms / frames, maxlevel, e.pile_height_px(), target, minsurface, maxsurface, maxdrops,
                maxspray, maxfoam, e.fluid_count(), maxfluids, e.sink_speed_now(), band_volumes);
    CHECK(maxlevel < H * 0.6, "level %.0f", maxlevel);
    CHECK(e.pile_height_px() > 5, "pool has liquid");
    CHECK(maxsurface - minsurface > 4, "the surface moves (%.1f px)", maxsurface - minsurface);
    CHECK(shown >= 295, "clock showing after %zu of 300 changes", shown);
    CHECK(maxdrops > 0 && maxdrops < 20000, "drops %.0f", maxdrops);
    CHECK(maxspray > 0, "splashes throw spray");
    CHECK(maxfluids >= 2, "colours stay separate (%.0f fluids)", maxfluids);
    CHECK(minlevel >= 0, "level never negative");
    std::printf(failures ? "%d FAILED\n" : "all passed\n", failures);
    return failures ? 1 : 0;
}
