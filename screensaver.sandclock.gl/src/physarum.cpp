#include "physarum.hpp"

#include <algorithm>
#include <cmath>
#include <cstdio>

namespace sandclock {
namespace physarum {

namespace {
constexpr float DEG = 3.14159265f / 180.0f;

Params make(float sa, float ra, float so, float ss, float decay, float diffuse, float deposit, float jitter,
            float repel, float px) {
    Params p;
    p.sa = sa * DEG;
    p.ra = ra * DEG;
    p.so = std::max(1.0f, so * px);
    p.ss = std::max(0.05f, ss / 10.0f * px);
    p.decay = std::min(0.999f, std::max(0.5f, decay / 100.0f));
    p.diffuse = std::min(1.0f, std::max(0.0f, diffuse / 100.0f));
    p.deposit = std::max(0.01f, deposit / 100.0f);
    p.jitter = jitter * DEG;
    p.repel = std::min(1.0f, std::max(0.0f, repel / 100.0f));
    return p;
}

unsigned next_rand(unsigned* s) {
    *s = *s * 1664525u + 1013904223u;
    return *s >> 8;
}
}  // namespace

Params from_def(const PresetDef& d, float px) {
    return make(d.sa, d.ra, d.so, d.ss, d.decay, d.diffuse, d.deposit, d.jitter, d.repel, px);
}

Params custom_def_params(const Settings& s, float px) {
    return make(s.sa, s.ra, s.so, s.ss, s.decay, s.diffuse, s.deposit, s.jitter, s.repel, px);
}

Params lerp(const Params& a, const Params& b, float t) {
    auto m = [t](float x, float y) { return x + (y - x) * t; };
    Params p;
    p.sa = m(a.sa, b.sa); p.ra = m(a.ra, b.ra); p.so = m(a.so, b.so); p.ss = m(a.ss, b.ss);
    p.decay = m(a.decay, b.decay); p.diffuse = m(a.diffuse, b.diffuse); p.deposit = m(a.deposit, b.deposit);
    p.jitter = m(a.jitter, b.jitter); p.repel = m(a.repel, b.repel);
    return p;
}

Params for_species(const Params& p, int i, bool differ) {
    if (!differ || i <= 0) return p;
    static const float SO[3] = {1.0f, 1.6f, 0.65f};
    static const float SA[3] = {1.0f, 0.75f, 1.4f};
    static const float SS[3] = {1.0f, 1.3f, 0.8f};
    static const float RA[3] = {1.0f, 1.2f, 0.8f};
    Params q = p;
    i = std::min(2, i);
    q.so *= SO[i];
    q.sa = std::min(2.0f, q.sa * SA[i]);
    q.ss *= SS[i];
    q.ra = std::min(2.0f, q.ra * RA[i]);
    return q;
}

Behaviour::Behaviour(const Settings& s, float px, unsigned seed)
    : wander_(s.preset == PRESET_COUNT), px_scale_(px), custom_(custom_def_params(s, px)), rng_(seed | 1) {
    hold_ = WANDER_MINUTES[std::max(0, std::min(WANDER_COUNT - 1, s.wander_minutes))] * 60.0;
    if (s.preset > PRESET_COUNT) to_ = -1;                         // custom
    else if (wander_) to_ = (int)(next_rand(&rng_) % PRESET_COUNT);
    else to_ = std::max(0, s.preset);
    from_ = to_;
    next_ = hold_;
}

Params Behaviour::def(int i) const { return i < 0 ? custom_ : from_def(PRESETS[i], px_scale_); }

Params Behaviour::at(double now) {
    if (!wander_) return def(to_);
    if (now >= next_) {
        from_ = to_;
        int n = (int)(next_rand(&rng_) % (PRESET_COUNT - 1));
        to_ = n >= from_ ? n + 1 : n;                               // never the same one again
        changed_ = now;
        next_ = now + hold_;
    }
    double t = (now - changed_) / MORPH;
    if (t >= 1) return def(to_);
    float k = (float)(t * t * (3 - 2 * t));
    return lerp(def(from_), def(to_), k);
}

std::string clock_text(const Settings& s, double seconds) {
    long t = (long)seconds % 86400;
    if (t < 0) t += 86400;
    int h = (int)(t / 3600), m = (int)(t / 60 % 60), sec = (int)(t % 60);
    if (s.hours == 1) h = h % 12 == 0 ? 12 : h % 12;
    char buf[16];
    if (s.seconds) std::snprintf(buf, sizeof buf, s.hours == 1 ? "%d:%02d:%02d" : "%02d:%02d:%02d", h, m, sec);
    else std::snprintf(buf, sizeof buf, s.hours == 1 ? "%d:%02d" : "%02d:%02d", h, m);
    return buf;
}

}  // namespace physarum
}  // namespace sandclock
