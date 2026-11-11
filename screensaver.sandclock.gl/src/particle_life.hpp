// Particle Life: particles of a few species attract or repel each other by a square matrix of
// pairwise forces. No collision detection: every particle within the interaction radius pulls on
// every other one, and the whole system self-organises into cells, worms, membranes and swirls.
//
// This is the GL-free model, shared by the renderer, the Kodi wrapper and the CPU tests. The
// neighbour search is a uniform grid rebuilt every step (a counting sort), so a step costs
// O(particles + pairs within the radius) rather than O(particles²): the same simulation that is
// quadratic in the original demo runs with tens of thousands of particles on a TV box.
//
// World coordinates: x in [0, aspect), y in [0, 1). One unit is the screen height.
#pragma once

#include <cstdint>
#include <random>
#include <string>
#include <vector>

#include "particle_life_tables.hpp"

namespace sandclock {
namespace particlelife {

constexpr int MAX_SPECIES = 8;
constexpr int MAX_PARTICLES = 32768;

// Settings exactly as the Kodi wrapper reads them, using the indices in particle_life_tables.hpp.
struct Settings {
    int matrix_mode = 0;          // 0 preset, 1 custom, 2 a new random matrix each start
    int preset = 0;
    std::string custom_matrix;    // row-major values, comma or whitespace separated
    int species = 6;              // 2..8, for custom and random matrices
    int particles = 3;            // index into kParticles
    int radius = 12;              // interaction radius, % of the screen height
    int force = 70;               // force strength, %
    int friction = 30;            // damping, %
    int speed = 2;                // index into kSpeeds
    bool wrap = true;
    int start = 0;                // index into kStartNames
    int palette = 0;
    int colour_mode = 0;          // 0 species, 1 heat, 2 shimmer
    int size = 65;                // particle size, %
    int glow = 60;                // glow, %
    int trail = 50;               // trail length, %
    uint32_t background = 0x05060A;
    int dim = 0;                  // %
    int draw = 0;                 // index into kDrawCaps
    int vary = 0;                 // what changes when it starts over: 0 same, 1 rules, 2 everything
    int restart = 3;              // index into kRestarts (300 s)
    int evolve = 0;               // index into kEvolveSeconds
    std::string seed_text;        // blank = a seed from the clock
};

// The square interaction matrix. m[subject][other]: > 0 attracts, < 0 repels.
struct Rules {
    int species = 0;
    float m[MAX_SPECIES][MAX_SPECIES] = {};

    // Parse "a,b,c,d, ..." (commas, spaces, semicolons or newlines) into a square matrix. Any
    // number of values from 4 (2 species) to 64 (8 species) is accepted; species is inferred
    // from the count. A hint is only used when the count does not decide it. False = bad text.
    bool parse(const std::string& text, int species_hint);
    void randomize(int species, std::mt19937& rng);
    void mutate(float amount, std::mt19937& rng);
    std::string to_string() const;
};

// Load one of kPresets (4 species). Returns false for an out-of-range index.
bool load_preset(int index, Rules* rules);

// The editable text for a custom matrix setting: "0.37,-0.5,...". Empty rules gives "".
std::string matrix_text(const Rules& rules);

// Build the rules the settings ask for. Custom text falls back to the chosen preset when it
// cannot be parsed, and *note says why. A random matrix is generated from seed.
Rules rules_for(const Settings& settings, unsigned seed, std::string* note);

// The floating-point model. Clamps nothing: callers pass settings that have already been
// clamped (the wrapper, the harness and Tools::sanitise all do).
class World {
public:
    // seed drives the starting positions (and species assignment).
    void init(const Settings& settings, float aspect, unsigned seed);

    void reset_positions(unsigned seed);
    void set_rules(const Rules& rules);
    void randomize_rules(unsigned seed);
    void mutate_rules(float amount, unsigned seed);

    void step();

    // Interpolated positions for rendering, as (x, y, speed) per particle. t is the fraction of
    // the way from the previous step to the current one; wrap-aware, so nothing streaks across
    // the screen when a particle crosses an edge. out must hold count() * 3 floats.
    void interpolate(float* out, float t) const;

    int count() const { return count_; }
    float aspect() const { return aspect_; }
    float radius() const { return radius_; }
    float force() const { return force_; }
    float friction() const { return friction_; }
    float speed_limit() const { return speed_limit_; }
    const Rules& rules() const { return rules_; }
    const std::vector<float>& positions() const { return x_; }
    const std::vector<float>& velocities() const { return v_; }
    const std::vector<uint8_t>& species() const { return species_; }

    // Tests: one step with the forces summed over every pair (the grid must agree), and the
    // resulting acceleration of a particle, for direct comparison.
    void step_brute_force();
    void copy_positions(std::vector<float>* out) const;
    void set_positions(const std::vector<float>& x);

    // Test aid: the largest difference between the gridded and brute-force forces on a copy of
    // the current state, in world units per second squared. Costs one brute-force factor only.
    float force_difference();

    struct Stats {
        float mean_speed = 0;
        float max_speed = 0;
        float density_variation = 0;   // spread of the particle count over a coarse grid
        bool finite = true;
    };
    Stats stats() const;

private:
    void build_grid();
    void add_pair(int i, int j, float xi, float yi, float* sx, float* sy) const;
    void forces_grid(int i, float* fx, float* fy) const;
    void forces_brute(int i, float* fx, float* fy) const;
    void integrate(float fx, float fy, int i);

    int count_ = 0;
    int start_ = 0;                 // kStartNames index, kept for reset_positions
    float aspect_ = 16.0f / 9.0f;
    float radius_ = 0.1f;
    float beta_ = 0.3f;             // inner repulsion core, as a fraction of the radius
    float force_ = 0.036f;          // acceleration per unit of summed force
    float friction_ = 1.25f;        // velocity damping rate, 1/s
    float damping_ = 0.99f;         // velocity multiplier per step
    float dt_ = 1.0f / 120.0f;
    float speed_limit_ = 0.25f;
    bool wrap_ = true;

    Rules rules_;
    std::vector<float> x_, v_, prev_;         // x and v interleaved xy
    std::vector<uint8_t> species_;

    // Uniform grid over the world, one cell wide. Rebuilt each step by a counting sort.
    int cols_ = 0, rows_ = 0, cells_ = 0;
    std::vector<int> cell_start_, cell_index_, cursor_;
    std::vector<float> force_sum_;
};

// A Settings with every value inside the ranges settings.xml offers (the wrapper calls this, and
// so does the harness after parsing its arguments). Text fields are left alone.
Settings sanitise(Settings s);

}  // namespace particlelife
}  // namespace sandclock
