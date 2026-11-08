// Cellular Automata 3D (voxel Life), the part with no GL: settings, 3D rules, the padded atlas
// layout, starting patterns and a CPU reference of one generation (what the shader must match;
// used by the tests and by --selftest).
//
// A cell has a state 0 (dead) or 1 (alive) and looks at all 26 neighbours (the Moore
// neighbourhood in three dimensions). A rule is two 27-bit masks: bit n of `birth` set = a dead
// cell with n live neighbours is born, bit n of `survive` = a live cell with n live neighbours
// stays alive. Rules are written "B4/S45" or with several counts "B6,7/S3,4".
//
// The volume is kept in a 2D texture so it works on OpenGL ES 2.0, which has no 3D textures: the
// N x N x N grid is cut into N slices of N x N, laid out in a grid 8 slices wide. Every slice is
// surrounded by a one-cell border (so the padded volume is (N+2)^3), which the update shader fills
// with either the wrapped opposite face or zeros. That lets every interior cell read its 26
// neighbours from fixed offsets with no wrap arithmetic and no bounds tests.
#pragma once
#include <cstdint>
#include <random>
#include <string>
#include <vector>

#include "voxel_tables.hpp"

namespace sandclock {
namespace voxel {

struct Settings {
    int preset = 0;                  // 0 = Custom, 1..VOXEL_PRESET_COUNT, VOXEL_PRESET_COUNT+1 = rotate
    int rotate_time = 1;             // index into VOXEL_ROTATE_SECONDS
    int rule = 0;                    // index into VOXEL_RULES; VOXEL_RULE_COUNT = the custom rule
    std::string custom_rule = "B6,7/S3,4";
    bool wrap = true;
    bool infinite = false;           // repeat the cube for ever (drawn as a torus; needs wrap)
    int grid = 2;                    // index into VOXEL_GRIDS (24, 32, 40, 48, 56, 64)
    int speed = 4;                   // index into automata::SPEED_GPS (15 generations/s)
    int sparks = 0;                  // random births per generation per million cells
    int start = 0;                   // index into the start list
    int density = 22;                // % alive for the soups
    bool auto_restart = true;
    int restart_every = 4;           // index into automata::RESTART_MINUTES
    int colour_mode = 1;             // age, position, time, one colour, rainbow, fire, neighbours, plasma
    int palette = 2;
    uint32_t colour = 0xFFB347;      // 0xRRGGBB
    uint32_t background = 0x000000;
    int cycle = 25;                  // colour cycling speed, 0..100
    int age_span = 64;               // generations over which the age gradient runs
    int background_style = 0;        // solid, gradient, plasma
    int glow = 0;                    // 0..100
    int screen_fx = 0;               // none, vignette, CRT
    int dim = 0;                     // %
    int draw = 0;                    // auto, 1080p, 720p, 540p, 360p, 270p, full screen
    int camera = 1;                  // still, orbit, tumble, zoom, inside (drift), inside (tumble)
    int camera_speed = 25;           // 5..100
    int zoom = 4;                    // closeness, 1..8
};

struct Rule3D {
    uint32_t birth = 1u << 4;
    uint32_t survive = (1u << 4) | (1u << 5);
};

// "B4/S45", "B6,7/S3,4", letters in any case, parts in any order, counts 0..26. Returns false
// and leaves *out alone if it cannot be read.
bool parse_rule3d(const std::string& text, Rule3D* out);
Rule3D rule_for(const Settings& s);
int grid_for(const Settings& s);                 // the volume edge, from the grid index

// Presets. A preset replaces the look -- rule, wrap, cube, starting pattern, colours, background,
// glow, screen effect and camera -- and leaves the performance settings alone (speed, sparks,
// draw resolution, restart timers, camera speed, colour cycling), so no preset can make a weak
// device stutter. resolve_preset returns the settings a preset stands for; for Custom (0) and
// Rotate it returns them unchanged.
constexpr int VOXEL_PRESET_CUSTOM = 0;
constexpr int VOXEL_PRESET_ROTATE = VOXEL_PRESET_COUNT + 1;   // pick one at random, change on a timer
Settings resolve_preset(const Settings& user);
bool rotating_presets(const Settings& user);

// The padded atlas the GPU keeps the volume in.
struct Atlas {
    int n = 0;                                   // interior edge (cells)
    int p = 0;                                   // padded edge (n + 2)
    int w = 0, h = 0;                            // texture size
    int slices = 0;                              // slice slots (a multiple of 8)
};
Atlas atlas_for(int n);
size_t atlas_texel(const Atlas& a, int x, int y, int z);   // padded coordinates, layer-major
// n^3 bytes of state -> w*h RGBA texels (state in R and A). Border cells duplicate the opposite
// face when wrap is on and are zero otherwise.
void build_atlas(const Atlas& a, const std::vector<uint8_t>& state, bool wrap, std::vector<uint8_t>* rgba);
void extract_state(const Atlas& a, const std::vector<uint8_t>& rgba, std::vector<uint8_t>* state);

// Fills state with an n^3 starting pattern (start is an index in the settings list).
void make_start(int start, int n, int density, std::mt19937& rng, std::vector<uint8_t>* state);

// One generation on the CPU: the reference the shader must match.
void step_cpu(const std::vector<uint8_t>& in, std::vector<uint8_t>& out, int n, const Rule3D& rule,
              bool wrap);

}  // namespace voxel
}  // namespace sandclock
