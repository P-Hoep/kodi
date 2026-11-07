// Physarum screensaver, the part with no GL: settings, behaviour parameters, wandering between
// behaviours, the clock text and the agent-state encoding the shaders use.
//
// The model is Jeff Jones's agent approximation of Physarum polycephalum transport networks
// ("Characteristics of pattern formation and evolution in approximations of Physarum transport
// networks", Artificial Life 16(2), 2010), as Sage Jenson and nicoptere/physarum draw it on the GPU:
// every agent senses the trail map at three points ahead of it (ahead, ahead-left, ahead-right,
// SO px away and SA degrees apart), turns RA degrees towards the strongest, steps forward and
// deposits; then the whole trail map diffuses (3x3 mean) and decays. Up to three species each lay
// and follow their own trail channel and avoid the others'.
#pragma once
#include <cstdint>
#include <string>

#include "physarum_tables.hpp"

namespace sandclock {
namespace physarum {

struct Settings {
    // Behaviour.
    int preset = PRESET_COUNT;       // index into PRESETS; PRESET_COUNT = wander, PRESET_COUNT + 1 = custom
    int wander_minutes = 1;          // index into WANDER_MINUTES
    int species = 0;                 // 0..2: one, two or three species
    bool species_differ = true;
    int scale = 100;                 // pattern scale, %
    // The Custom behaviour, in the PresetDef units.
    float sa = 22.5f, ra = 45, so = 9, ss = 10, decay = 90, diffuse = 100, deposit = 30, jitter = 0, repel = 50;

    // Size and speed.
    int agents = 3;                  // index into AGENT_SIZES
    int trail = 2;                   // index into TRAIL_SIZES
    int speed = 2;                   // index into SPEED_SPS

    // Start and food.
    int start = 0;
    int food = 0;                    // none, scattered, ring, grid
    int food_nodes = 12;
    int restart_every = 3;           // index into RESTART_MINUTES

    // Colours.
    int colour_mode = 0;             // species, density, fire, neon, ink, one colour, rainbow, plasma
    int palette = 0;
    uint32_t colour = 0xFFD36B;
    uint32_t background = 0x000000;
    int brightness = 100;            // %
    int cycle = 20;
    int glow = 40;
    int screen_fx = 1;
    int dim = 0;

    // The clock in the middle.
    int clock = 2;                   // off, on top, grows into, grows into + faint, made of slime, flows around
    int food_strength = 50;          // %
    int clock_font = 0;
    int clock_weight = 2;
    bool seconds = false;
    int hours = 0;
    int clock_size = 60;
    int clock_colour_mode = 0;
    uint32_t clock_colour = 0xFFFFFF;
    int clock_opacity = 85;

    // Camera and 3D.
    int view = 0;                    // flat, relief, landscape, tunnel, globe
    int camera = 0;                  // still, drift, zoom in and out, fly through
    int camera_speed = 30;
    int zoom = 3;
};

enum Clock { CLOCK_OFF, CLOCK_ON_TOP, CLOCK_GROWS, CLOCK_GROWS_FAINT, CLOCK_SLIME, CLOCK_AROUND };

// One behaviour, in simulation units: angles in radians, distances in trail px (already scaled to
// the trail resolution and the pattern scale), decay as the fraction kept, diffuse 0..1.
struct Params {
    float sa = 0, ra = 0, so = 0, ss = 0, decay = 0, diffuse = 0, deposit = 0, jitter = 0, repel = 0;
};

// px_scale: trail width / 960 * pattern scale.
Params from_def(const PresetDef& d, float px_scale);
Params custom_def_params(const Settings& s, float px_scale);
Params lerp(const Params& a, const Params& b, float t);
// The behaviour of species i (0..2) when species differ: longer reach and other angles.
Params for_species(const Params& p, int species, bool differ);

// Which behaviour is on now. Fixed presets and Custom never change; Wander holds one for
// WANDER_MINUTES, then morphs into a random other one over MORPH seconds.
class Behaviour {
public:
    static constexpr double MORPH = 25.0;
    Behaviour(const Settings& s, float px_scale, unsigned seed);
    Params at(double now);
    int current() const { return to_; }           // preset index being shown (or morphed into)
    bool wandering() const { return wander_; }

private:
    Params def(int i) const;
    bool wander_;
    float px_scale_;
    Params custom_;
    double hold_;
    int from_ = 0, to_ = 0;
    double changed_ = -1e9, next_ = 0;
    unsigned rng_;
};

std::string clock_text(const Settings& s, double seconds);

// Agent positions and headings are fractions 0..1 stored as 16 bits in two 8-bit channels
// (RGBA8 textures are the only ones every GLES 2 device can render to). These match the shaders.
inline void encode16(double v, uint8_t* hi, uint8_t* lo) {
    v -= (long)v;
    if (v < 0) v += 1;
    unsigned e = (unsigned)(v * 65535.0 + 0.5);
    if (e > 65535) e = 65535;
    *hi = (uint8_t)(e >> 8);
    *lo = (uint8_t)(e & 255);
}
inline double decode16(uint8_t hi, uint8_t lo) { return (hi * 256 + lo) / 65535.0; }

}  // namespace physarum
}  // namespace sandclock
