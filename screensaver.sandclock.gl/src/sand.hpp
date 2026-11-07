// Port of screensaver.sandclock/resources/lib/sand.py + config.py: layout, glyph grains,
// falling-sand planner and colours. No GL and no Kodi in here, so it is testable on its own.
//
// Geometry is in 1920x1080 "skin pixels". Sand lives on a grid of square cells g px wide that
// is fixed to the screen: column 0 starts at x0, row 0 sits on the floor, rows count upward.
#pragma once
#include <cstdint>
#include <map>
#include <random>
#include <string>
#include <vector>

namespace sandclock {

constexpr int W = 1920, H = 1080;
constexpr int GRAIN_PX[3] = {6, 9, 14};
constexpr double GRAVITY[3] = {1400.0, 3000.0, 6000.0};
constexpr double SPREAD[3] = {0.7, 0.45, 0.3};
constexpr double LEAD_EXTRA = 0.12;
constexpr int SLIDE_MS = 45;
constexpr int RUN_BLOCK = 32;
constexpr int DRIFT_PX = 30;
// Most grains one crumble may drop before grains step up to a coarser size. The Python add-on
// needs 1000 for weak boxes; the GPU draws tens of thousands, so this only guards absurd cases.
constexpr int GRAIN_BUDGET = 40000;
constexpr double RAINBOW_SECONDS = 120.0;
constexpr double CLOCK_HEIGHT_MAX = 0.42;
constexpr double CLOCK_CENTRE_Y[2] = {0.30, 0.42};

enum ColourMode { COLOUR_EVERY_CHANGE, COLOUR_PER_DIGIT, COLOUR_ONE, COLOUR_RAINBOW };

// Colours are 0xRRGGBB.
struct Settings {
    bool seconds = true;
    int hours = 0;          // 0 = 24 h, 1 = 12 h
    int crumble = 1;        // 0 = only changing digits, 1 = whole clock
    int speed = 1;          // crumble speed: slow, normal, quick
    int font = 0;
    int weight = 2;         // light, regular, bold
    int size = 80;          // % of the screen width
    int position = 0;       // 0 upper part, 1 centre
    int grain = 1;          // fine, medium, coarse
    int grain_look = 0;     // sand, flat squares, round beads
    int gravity = 1;
    int pile = 30;          // % of the screen height
    int colour_mode = 0;
    int palette = 0;
    uint32_t colour = 0xE8C27A;
    uint32_t background = 0x000000;
    int night_palette = 0;  // 0 = same as day, n = palette n-1
    int night_dim = 0;
    int day_start = 7 * 60;     // minutes since midnight
    int night_start = 21 * 60;
    int dim = 0;
    bool drift = true;
};

extern const char* const FONT_FOLDERS[9];
extern const std::vector<std::vector<uint32_t>> PALETTES;

// ---- fonts and layout

struct Mask {
    int w = 0, h = 0;
    std::vector<uint8_t> cells;  // h rows of w
    bool at(int u, int v) const { return cells[v * w + u] != 0; }
};

struct Font {
    double h = 0;
    std::map<char, double> widths;
    std::map<char, Mask> masks;

    // fonts.json as written by tools/make_sandclock_media.py
    static Font load(const std::string& path, const std::string& folder, int weight);
    double width(const std::string& text) const;
};

struct Box { double x, y, w, h; };

double lead(const Settings& s);
std::string time_text(const Settings& s, int hour, int minute, int second);
std::string widest_text(const Settings& s);
std::vector<Box> layout(const Settings& s, const Font& font, const std::string& text,
                        double ox = 0, double oy = 0);

struct Grid {
    int g, cols, x0;
    explicit Grid(int grain);
    int x(int col) const { return x0 + col * g; }
    int col_at(double px) const;
    int row_at(double py) const;
};

struct GrainCell { int col; double y; };  // y: top of the cell on screen

std::vector<GrainCell> grains(const Font& font, char ch, const Box& box, const Grid& grid);
int grain_px(const Settings& s, const Font& font);
double pile_target(const Settings& s, const Font& font, int g);
double sink_speed(double inflow, double height, double target, double footprint);
bool speed_changed(double now, double current);

// ---- physics

// One grain's trip, in ms after its batch starts: it waits `delay`, falls `fall_px` while
// drifting `scatter_px` sideways (`fall_ms`), slides (dx, dy) down the side of the pile
// (`slide_ms`) and lands at `land_ms` in cell (col, row), then sinks with the pile.
struct Flight {
    double x, y;
    int col, row;
    uint32_t colour;
    int delay;
    double fall_px, scatter_px;
    int fall_ms;
    double dx, dy;
    int slide_ms, land_ms;
    double land_y;
};

double fall_ms(double px, double gravity);

class Pile {
public:
    struct Cell { uint32_t colour; double landed; };

    Pile(const Grid& grid, std::mt19937* rng, double t);

    double sunk(double t) const;
    double speed_at(double t) const;
    void schedule(double at, double speed);
    void commit(double t);
    double cell_y(int row, double t) const;
    int floor_row(double t) const;
    int top_row(int col, double t) const;
    double footprint(double t) const;
    double height_px(double t) const;
    std::vector<Flight> drop(const std::vector<GrainCell>& cells, uint32_t colour, double t0,
                             double gravity, double spread);
    void prune(double t);

    Grid grid;
    std::vector<int> heights;
    std::map<int, std::map<int, Cell>> cells;
    std::mt19937* rng;
    double base_t, base_sunk, speed;
    bool has_change = false;
    double change_t = 0, change_speed = 0;
};

// ---- colour

uint32_t scale_colour(uint32_t c, double f);
bool is_night(const Settings& s, int minute_of_day);
double dim_factor(const Settings& s, int minute_of_day);
const std::vector<uint32_t>& palette(const Settings& s, int minute_of_day);
uint32_t pick(const std::vector<uint32_t>& colours, uint32_t avoid, bool has_avoid, std::mt19937& rng);
uint32_t rainbow(double seconds);
void drift(const Settings& s, double elapsed, double* dx, double* dy);

}  // namespace sandclock
