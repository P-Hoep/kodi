// Tests for the GL-free part of the Physarum screensaver: the 16-bit encoding, behaviours and
// wandering between them, the clock text. The GPU passes are checked by `physarum_glfw --selftest`.
#include <cmath>
#include <cstdio>

#include "physarum.hpp"

using namespace sandclock::physarum;

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

static bool same(const Params& a, const Params& b) {
    return a.sa == b.sa && a.ra == b.ra && a.so == b.so && a.ss == b.ss && a.decay == b.decay &&
           a.diffuse == b.diffuse && a.deposit == b.deposit && a.jitter == b.jitter && a.repel == b.repel;
}

int main() {
    // Encoding: round trip within half a step, wraps into 0..1.
    for (double v : {0.0, 0.25, 0.5, 0.999, 0.123456, 1.25, -0.25}) {
        uint8_t hi, lo;
        encode16(v, &hi, &lo);
        double w = v - std::floor(v);
        double d = std::fabs(decode16(hi, lo) - w);
        CHECK(d <= 0.5 / 65535 + 1e-12 || std::fabs(d - 1) < 1e-4, "v=%g got %g", v, decode16(hi, lo));
    }

    // Presets: units converted, the first matches the Custom defaults.
    Settings s;
    Params a = from_def(PRESETS[0], 1.0f);
    CHECK(std::fabs(a.sa - 22.5f * 3.14159265f / 180) < 1e-5, "sa %g", a.sa);
    CHECK(std::fabs(a.ss - 1.0f) < 1e-6 && std::fabs(a.decay - 0.9f) < 1e-6, "ss %g decay %g", a.ss, a.decay);
    CHECK(same(a, custom_def_params(s, 1.0f)), "custom defaults are preset 0");
    Params b = from_def(PRESETS[0], 2.0f);
    CHECK(std::fabs(b.so - 2 * a.so) < 1e-5 && std::fabs(b.ss - 2 * a.ss) < 1e-5 && b.sa == a.sa, "scaling");
    for (int i = 0; i < PRESET_COUNT; ++i) {
        Params p = from_def(PRESETS[i], 1.0f);
        CHECK(p.decay > 0.5f && p.decay < 1 && p.so >= 1 && p.ss > 0 && p.diffuse <= 1, "preset %d", i);
    }
    CHECK(same(for_species(a, 0, true), a) && same(for_species(a, 2, false), a), "species 0 / not differing");
    CHECK(for_species(a, 1, true).so > a.so, "species 1 reaches further");

    // Fixed behaviours never change; Custom uses the sliders.
    s.preset = 3;
    Behaviour fixed(s, 1.0f, 9);
    CHECK(same(fixed.at(0), from_def(PRESETS[3], 1)) && same(fixed.at(1e6), from_def(PRESETS[3], 1)), "fixed");
    s.preset = PRESET_COUNT + 1;
    s.so = 33;
    Behaviour custom(s, 1.0f, 9);
    CHECK(std::fabs(custom.at(50).so - 33) < 1e-5, "custom so %g", custom.at(50).so);

    // Wander: holds, then morphs smoothly to a different one, and arrives exactly.
    s.preset = PRESET_COUNT;
    s.wander_minutes = 0;                         // 1 minute
    Behaviour w(s, 1.0f, 12345);
    CHECK(w.wandering(), "wandering");
    int first = w.current();
    Params p0 = w.at(0), p30 = w.at(30);
    CHECK(same(p0, p30) && w.current() == first, "holds for the minute");
    w.at(60);
    int second = w.current();
    CHECK(second != first && second >= 0 && second < PRESET_COUNT, "moves on: %d -> %d", first, second);
    Params mid = w.at(60 + Behaviour::MORPH / 2);
    Params from = from_def(PRESETS[first], 1), to = from_def(PRESETS[second], 1);
    CHECK(std::fabs(mid.decay - (from.decay + to.decay) / 2) < 1e-4, "halfway decay %g", mid.decay);
    CHECK(same(w.at(60 + Behaviour::MORPH + 1), to), "arrives");
    float last = w.at(60).so, max_jump = 0;
    for (double t = 60; t < 60 + Behaviour::MORPH; t += 0.25) {
        float v = w.at(t).so;
        max_jump = std::fmax(max_jump, std::fabs(v - last));
        last = v;
    }
    CHECK(max_jump < 0.05f * std::fmax(1.0f, std::fabs(to.so - from.so)) + 1e-4f, "smooth: jump %g", max_jump);

    // Clock text.
    Settings c;
    CHECK(clock_text(c, 17 * 3600 + 52 * 60 + 9) == "17:52", "%s", clock_text(c, 17 * 3600 + 52 * 60 + 9).c_str());
    c.seconds = true;
    c.hours = 1;
    CHECK(clock_text(c, 17 * 3600 + 52 * 60 + 9) == "5:52:09", "%s", clock_text(c, 17 * 3600 + 52 * 60 + 9).c_str());
    CHECK(clock_text(c, 0) == "12:00:00", "%s", clock_text(c, 0).c_str());

    std::printf(failures ? "%d FAILED\n" : "physarum tests passed\n", failures);
    return failures ? 1 : 0;
}
