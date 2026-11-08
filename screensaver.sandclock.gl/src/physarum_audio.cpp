#include "physarum_audio.hpp"

#include <algorithm>
#include <cmath>

namespace sandclock {
namespace physarum {
namespace audio {

namespace {

constexpr float DEG = 3.14159265f / 180.0f;

// The Custom sliders, in the units tools/make_settings_physarum_audio.py uses (the same units as
// the Physarum add-on).
Params from_custom(const Settings& s, float px) {
    Params p;
    p.sa = s.sa * DEG;
    p.ra = s.ra * DEG;
    p.so = std::max(1.0f, s.so * px);
    p.ss = std::max(0.05f, s.ss / 10.0f * px);
    p.decay = std::min(0.999f, std::max(0.5f, s.decay / 100.0f));
    p.diffuse = std::min(1.0f, std::max(0.0f, s.diffuse / 100.0f));
    p.deposit = std::max(0.01f, s.deposit / 100.0f);
    p.jitter = s.jitter * DEG;
    p.repel = std::min(1.0f, std::max(0.0f, s.repel / 100.0f));
    return p;
}

}  // namespace

Params params_for(const Settings& s, float px_scale) {
    if (s.preset >= PRESET_COUNT) return from_custom(s, px_scale);
    return from_def(PRESETS[std::max(0, std::min(PRESET_COUNT - 1, s.preset))], px_scale);
}

// The music moves the simulation as well as the picture. All of it is proportional to the
// Reactivity slider, and each kind can be switched off on its own, so a listener who wants the
// screensaver they know can set Reactivity to zero.
Params reactive_params(const Params& base, const Settings& s, const AudioState& a) {
    const float r = std::max(0.0f, std::min(1.5f, s.reactivity / 100.0f));
    Params p = base;
    if (r <= 0.0f) return p;

    if (s.react_speed) {
        // Loud music, and especially bass, makes the agents travel further each step. The step is
        // the only thing changed: sensor angles and distances keep the pattern's character.
        p.ss *= 1.0f + r * (0.8f * a.bass + 0.35f * a.level);
    }
    if (s.react_trails) {
        // Bass strengthens the deposit and slows the fade, so the network thickens and lingers.
        p.deposit *= 1.0f + 1.4f * r * a.level;
        p.decay += (1.0f - p.decay) * std::min(1.0f, 0.5f * r * a.bass);
    }
    if (s.react_beat) {
        // A beat is a jolt: a little wander on every agent and a wider turn. The overall reaction
        // is small on purpose; the visible beat is the camera pulse and the ring in the shader.
        p.jitter += r * (a.treble * 0.18f + a.beat * 0.12f);
        p.ra *= 1.0f + 0.35f * r * a.beat;
    }

    p.ss = std::max(0.02f, p.ss);
    p.decay = std::min(0.999f, std::max(0.5f, p.decay));
    p.deposit = std::max(0.01f, p.deposit);
    p.jitter = std::min(1.2f, std::max(0.0f, p.jitter));
    return p;
}

}  // namespace audio
}  // namespace physarum
}  // namespace sandclock
