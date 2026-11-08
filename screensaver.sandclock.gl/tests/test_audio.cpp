// Tests for the audio side of the Physarum visualisation: the analyser on known tones, the beat
// detector on a 120 bpm kick, and the way Reactivity changes the simulation's parameters. The GPU
// passes are checked by `physarum_audio_glfw --selftest`.
#include <cmath>
#include <cstdio>
#include <vector>

#include "audio_react.hpp"
#include "physarum_audio.hpp"

using namespace sandclock::physarum::audio;

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

namespace {

constexpr int SR = 44100;
constexpr double TAU = 6.283185307179586;

// Feeds `seconds` of a tone (or, with hz == 0, silence) in 735-frame blocks and updates at 60 fps.
void feed(AudioAnalyzer& a, double seconds, double hz, float amp = 0.6f) {
    const int frames = 735;
    std::vector<float> buf((size_t)frames * 2);
    double t = 0;
    const int blocks = (int)(seconds * 60.0);
    for (int b = 0; b < blocks; ++b) {
        for (int i = 0; i < frames; ++i) {
            float v = hz > 0 ? amp * (float)std::sin(TAU * hz * (t + (double)i / SR)) : 0.0f;
            buf[(size_t)i * 2] = buf[(size_t)i * 2 + 1] = v;
        }
        t += (double)frames / SR;
        a.push(buf.data(), buf.size());
        a.update(1.0 / 60.0);
    }
}

bool finite(const AudioState& s) {
    bool ok = std::isfinite(s.level) && std::isfinite(s.bass) && std::isfinite(s.low) && std::isfinite(s.mid) &&
              std::isfinite(s.treble) && std::isfinite(s.air) && std::isfinite(s.beat);
    for (float v : s.bands) ok = ok && std::isfinite(v);
    return ok;
}

}  // namespace

int main() {
    // A 55 Hz tone is bass, not air.
    {
        AudioAnalyzer a;
        a.configure(SR, 2);
        feed(a, 2.0, 55);
        const AudioState& s = a.state();
        CHECK(finite(s), "tone values");
        CHECK(s.level > 0.2f, "level %.3f", s.level);
        CHECK(s.bass > 0.3f, "bass %.3f", s.bass);
        CHECK(s.bass > s.air * 2, "bass %.3f air %.3f", s.bass, s.air);
    }

    // A 6 kHz tone is air.
    {
        AudioAnalyzer a;
        a.configure(SR, 2);
        feed(a, 2.0, 6000);
        const AudioState& s = a.state();
        CHECK(s.air > 0.3f && s.air > s.bass * 2, "air %.3f bass %.3f", s.air, s.bass);
    }

    // The display spectrum puts a 1 kHz tone in the right place (roughly band 17 of 32).
    {
        AudioAnalyzer a;
        a.configure(SR, 2);
        feed(a, 2.0, 1000);
        const AudioState& s = a.state();
        int best = 0;
        for (int i = 1; i < BAND_COUNT; ++i)
            if (s.bands[i] > s.bands[best]) best = i;
        CHECK(best >= 14 && best <= 20, "1 kHz peaked at band %d", best);
        CHECK(s.bands[best] > 0.3f, "band %.3f", s.bands[best]);
    }

    // Silence fades the state away instead of holding it.
    {
        AudioAnalyzer a;
        a.configure(SR, 2);
        feed(a, 2.0, 55);
        float loud = a.state().level;
        feed(a, 2.0, 0);
        CHECK(loud > 0.2f && a.state().level < loud * 0.2f, "%.3f -> %.3f", loud, a.state().level);
        CHECK(a.state().bass < 0.2f, "bass %.3f", a.state().bass);
    }

    // A 120 bpm kick produces beat impulses, not one per frame and not none.
    {
        AudioAnalyzer a;
        a.configure(SR, 2);
        const int frames = 735;
        std::vector<float> buf((size_t)frames * 2);
        double t = 0;
        int beats = 0;
        for (int b = 0; b < 600; ++b) {          // 10 seconds
            for (int i = 0; i < frames; ++i) {
                double bt = std::fmod(t + (double)i / SR, 0.5);
                float v = 0.7f * (float)(std::exp(-bt * 16) * std::sin(TAU * 55 * bt));
                buf[(size_t)i * 2] = buf[(size_t)i * 2 + 1] = v;
            }
            t += (double)frames / SR;
            a.push(buf.data(), buf.size());
            a.update(1.0 / 60.0);
            if (a.state().beat > 0.9f) ++beats;
        }
        CHECK(beats >= 8 && beats <= 60, "%d beat frames in 600", beats);
        CHECK(finite(a.state()), "beat values");
    }

    // Reactivity zero is the screensaver exactly; full reactivity moves every part of it.
    {
        Settings s;
        Params base;
        base.ss = 2.0f; base.deposit = 0.3f; base.decay = 0.9f; base.jitter = 0; base.ra = 0.5f;
        AudioState a;
        a.level = 1.0f; a.bass = 1.0f; a.treble = 0.5f; a.beat = 1.0f;

        s.reactivity = 0;
        Params off = reactive_params(base, s, a);
        CHECK(off.ss == base.ss && off.deposit == base.deposit && off.decay == base.decay &&
                  off.jitter == base.jitter && off.ra == base.ra, "zero reactivity changes nothing");

        s.reactivity = 100;
        Params on = reactive_params(base, s, a);
        CHECK(on.ss > base.ss, "speed %.2f -> %.2f", base.ss, on.ss);
        CHECK(on.deposit > base.deposit, "deposit %.2f -> %.2f", base.deposit, on.deposit);
        CHECK(on.decay > base.decay && on.decay < 1, "decay %.2f -> %.2f", base.decay, on.decay);
        CHECK(on.jitter > base.jitter, "jitter %.2f -> %.2f", base.jitter, on.jitter);
        CHECK(on.ra > base.ra, "turn %.2f -> %.2f", base.ra, on.ra);

        s.react_speed = s.react_trails = s.react_beat = false;
        Params none = reactive_params(base, s, a);
        CHECK(none.ss == base.ss && none.deposit == base.deposit && none.decay == base.decay &&
                  none.jitter == base.jitter && none.ra == base.ra, "the switches turn each kind off");
    }

    // Parameters stay sane at extreme audio and reactivity.
    {
        Settings s;
        s.reactivity = 150;
        Params base;
        base.ss = 5; base.deposit = 1; base.decay = 0.99f; base.ra = 1; base.jitter = 0.5f;
        AudioState a;
        a.level = 2; a.bass = 2; a.treble = 2; a.beat = 1;
        Params p = reactive_params(base, s, a);
        CHECK(p.ss > 0 && p.decay > 0.5f && p.decay < 1 && p.deposit > 0 && p.jitter <= 1.2f && p.ra > 0,
              "ss %.2f decay %.3f deposit %.2f jitter %.2f ra %.2f", p.ss, p.decay, p.deposit, p.jitter, p.ra);
    }

    if (failures) {
        std::printf("%d FAILED\n", failures);
        return 1;
    }
    std::printf("audio tests passed\n");
    return 0;
}
