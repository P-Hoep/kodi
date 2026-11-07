// Cellular Automata screensaver, the part with no GL: settings, rules, starting patterns and a
// CPU reference of one generation (what the shader must match; used by the tests and --selftest).
//
// A cell has a state 0..states-1: 0 dead, 1 alive, 2.. dying (Generations rules: a live cell that
// does not survive fades through the remaining states before it is dead again). Only state 1
// counts as a neighbour. A rule is two 9-bit masks: bit n of `birth` set = a dead cell with n live
// neighbours is born, bit n of `survive` = a live cell with n live neighbours stays alive.
#pragma once
#include <cstdint>
#include <random>
#include <string>
#include <vector>

#include "automata_tables.hpp"

namespace sandclock {
namespace automata {

struct Settings {
    int rule = 0;                    // index into RULES; RULE_COUNT = the custom rule
    std::string custom_rule = "B3/S23";
    bool wrap = true;
    int grid = 4;                    // index into GRID_COLS
    int speed = 5;                   // index into SPEED_GPS
    int sparks = 0;                  // random births per generation per million cells
    int start = 0;
    int density = 30;                // % alive for the soups
    bool auto_restart = true;
    int restart_every = 4;           // index into RESTART_MINUTES
    int colour_mode = 0;             // age, position, time, one colour, rainbow
    int palette = 0;
    uint32_t colour = 0xFFB347;      // 0xRRGGBB
    uint32_t background = 0x000000;
    int cycle = 25;                  // colour cycling speed, 0..100
    int age_span = 96;               // generations over which the age gradient runs
    int trail = 60;                  // % of a dead cell's glow kept each generation
    int shape = 0;                   // square, rounded, dots
    int dim = 0;                     // %
};

struct Rule {
    int birth = 1 << 3;
    int survive = (1 << 2) | (1 << 3);
    int states = 2;
};

// "B3/S23", "B2/S/C3" (letters in any case, parts in any order; a lone number after C is the
// state count). Returns false and leaves *out alone if it cannot be read.
bool parse_rule(const std::string& text, Rule* out);
Rule rule_for(const Settings& s);
int cols_for(const Settings& s);                 // from the grid index
inline int rows_for_cols(int cols) { return cols * 9 / 16; }

// ---- patterns (run-length encoded, as the Life community writes them)

struct Pattern {
    int w = 0, h = 0;
    std::vector<uint8_t> cells;                  // h rows of w, 1 = alive
    int count() const;
};
Pattern parse_rle(const std::string& rle);
const Pattern& glider();
const Pattern& r_pentomino();
const Pattern& acorn();
const Pattern& gosper_gun();                     // emits a glider every 30 generations

// A pattern placed on the grid. orient: bit 0 flip x, bit 1 flip y, bit 2 transpose.
struct Stamp {
    const Pattern* pattern;
    int x, y;                                    // top-left cell
    int orient;
    int width() const;
    int height() const;
    bool at(int dx, int dy) const;               // is stamp cell (dx, dy) alive
};

// How a starting pattern is made: either a soup the init shader draws (soup_mode >= 0), stamps
// placed from the CPU, or both (soup and guns).
struct Start {
    int soup_mode = -1;                          // 0 soup, 1 sparse, 2 clusters, 3 kaleidoscope, 4 centre blob
    std::vector<Stamp> stamps;
};
Start make_start(int start, int cols, int rows, std::mt19937& rng);

// ---- reference implementation

// state: w*h bytes, row-major. out gets the next generation.
void step_cpu(const std::vector<uint8_t>& state, std::vector<uint8_t>& out, int w, int h, const Rule& rule,
              bool wrap);

}  // namespace automata
}  // namespace sandclock
