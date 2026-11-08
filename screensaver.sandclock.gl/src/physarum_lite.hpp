// Physarum Lite: the same agent model as the Physarum screensaver (Jones 2010, drawn as Sage
// Jenson does), with everything but the simulation and its drawing stripped out.
//
// There is no clock and no font: the trail map's fourth channel carries food sources only. There
// are no timers either: the screensaver does not restart itself every so many minutes and the
// behaviour never wanders on its own; it runs the one behaviour the user picked for as long as
// Kodi shows it. The defaults in Settings are deliberately light, because this build is meant for
// low-resource devices; every one of them can be raised in the add-on settings.
#pragma once
#include <cstdint>
#include <string>

#include "physarum.hpp"          // Params, from_def, for_species, encode16 / decode16
#include "physarum_tables.hpp"

namespace sandclock {
namespace physarum {
namespace lite {

using Params = sandclock::physarum::Params;

// The shared tables are generated for the Physarum add-on (tools/make_settings_physarum.py); the
// Lite settings use the same lists. Re-export the counts so the wrapper and the harness can write
// `using namespace lite` and still see them. (Lite does not use the steps-per-second list: it
// steps once per displayed frame; see Settings::pace.)
using sandclock::physarum::PRESET_COUNT;
using sandclock::physarum::AGENT_COUNT;
using sandclock::physarum::FOOD_COUNT;
using sandclock::physarum::MODE_COUNT;
using sandclock::physarum::PALETTE_COUNT;
using sandclock::physarum::VIEW_COUNT;
using sandclock::physarum::CAMERA_COUNT;

// The start options: the original list without "From the clock digits" (its index 5); the last
// one (each species in its own third) moves down into that slot.
constexpr int LITE_START_COUNT = 6;

// The trail sizes: the shared list (so indices 0..6 mean what they mean in the full add-on) plus a
// smaller map for very weak GPUs. The extra one is appended rather than inserted so a saved trail
// index never changes meaning. tools/make_settings_physarum_lite.py mirrors this list.
constexpr Size LITE_TRAIL_SIZES[] = {{480, 270}, {640, 360}, {960, 540}, {1280, 720}, {1920, 1080},
                                     {2560, 1440}, {3840, 2160}, {320, 180}};
constexpr int LITE_TRAIL_COUNT = 8;

struct Settings {
    // Behaviour. preset 0..PRESET_COUNT-1 is a fixed preset; PRESET_COUNT is Custom.
    int preset = 0;
    int species = 0;                 // 0..2: one, two or three species
    bool species_differ = true;
    int scale = 100;                 // pattern scale, %
    // The Custom behaviour, in the PresetDef units.
    float sa = 22.5f, ra = 45, so = 9, ss = 10, decay = 90, diffuse = 100, deposit = 30, jitter = 0, repel = 50;

    // Size and speed. The light defaults: 16 thousand agents on a 480 x 270 trail. The scene is
    // drawn at twice the trail resolution and scaled up, so the draw pass stays cheap on any screen.
    // The simulation is locked to the display: one step on every pace-th rendered frame (1 = every
    // frame). At pace 1 every frame does exactly the same amount of GPU work, which is what keeps
    // the frame rate even; a steps-per-second accumulator makes some frames do twice the work of
    // others, which shows up as judder. At 60 Hz, pace 1 is 60 steps/s and pace 2 is 30.
    int agents = 0;                  // index into AGENT_SIZES
    int trail = 0;                   // index into LITE_TRAIL_SIZES
    int pace = 1;                    // frames per step: 1..4 (1 = every frame, the smoothest)

    // Start and food.
    int start = 0;                   // index into the lite start list
    int food = 0;                    // none, scattered, ring, grid
    int food_nodes = 12;

    // Colours.
    int colour_mode = 0;             // species, density, fire, neon, ink, one colour, rainbow, plasma
    int palette = 0;
    uint32_t colour = 0xFFD36B;
    uint32_t background = 0x000000;
    int brightness = 100;            // %
    int cycle = 20;
    int glow = 0;                    // off by default: it costs speed
    int screen_fx = 0;               // none by default
    int dim = 0;

    // Camera and 3D.
    int view = 0;                    // flat, relief, landscape, tunnel, globe
    int camera = 0;                  // still, drift, zoom in and out, fly through
    int camera_speed = 30;
    int zoom = 3;
};

// The behaviour to run: the fixed preset or the Custom sliders, converted to simulation units.
// px_scale: trail width / 960 * pattern scale.
Params params_for(const Settings& s, float px_scale);

}  // namespace lite
}  // namespace physarum
}  // namespace sandclock
