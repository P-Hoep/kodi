#include "sand.hpp"

#include <algorithm>
#include <cmath>
#include <cstdio>
#include <stdexcept>

#include "json.hpp"

namespace sandclock {

const char* const FONT_FOLDERS[9] = {"inter", "montserrat", "orbitron", "pixelify", "doto",
                                     "jetbrains", "comfortaa", "playfair", "stencil"};

const std::vector<std::vector<uint32_t>> PALETTES = {
    {0xFF5FA2, 0xD45CFF, 0x5C9DFF, 0x3FE0E8, 0x45E07A, 0xFFB38A, 0xFF5C6C},  // Neon
    {0xE8C27A, 0xD9A25F, 0xC98A4B, 0xF2D7A0, 0xB5734A, 0xE3B58C, 0xA86A3D},  // Desert sand
    {0x3FA9F5, 0x1F6FD1, 0x45D6C9, 0x8FE3FF, 0x2A9D8F, 0x6C8CFF, 0xB8F2E6},  // Ocean
    {0xFF7A45, 0xFFB347, 0xFF4F70, 0xC2448F, 0x8A4FD1, 0xFFD166, 0xF25C54},  // Sunset
    {0xFF9CEE, 0xB28DFF, 0x85E3FF, 0xBFFCC6, 0xFFF5BA, 0xFFABAB, 0xACE7FF},  // Candy
    {0x6BBF59, 0x2E8B57, 0xA3D977, 0xD4C36A, 0x8C6A43, 0x4FA36C, 0xC9E4A6},  // Forest
    {0xFFFFFF, 0xD6F1FF, 0xA9DEFF, 0x7CC8F2, 0xC9D6FF, 0xE8F7FF, 0x9FB8D9},  // Ice
    {0xFFFFFF, 0xD9D9D9, 0xB3B3B3, 0x8C8C8C, 0xEDEDED, 0xA6A6A6, 0xC7C7C7},  // Greyscale
};

// ------------------------------------------------------------------ fonts and layout

Font Font::load(const std::string& path, const std::string& folder, int weight) {
    Json root = Json::parse(Json::read_file(path));
    const Json& d = root.at(folder).at(std::to_string(weight));
    Font f;
    f.h = d.at("h").num;
    const double digit_w = d.at("digit_w").num;
    f.widths[':'] = d.at("colon_w").num;
    for (const auto& kv : d.at("masks").obj) {
        char ch = kv.first[0];
        if (ch != ':') f.widths[ch] = digit_w;
        Mask m;
        m.w = (int)kv.second.arr[0].num;
        const Json& rows = kv.second.arr[1];
        m.h = (int)rows.arr.size();
        m.cells.assign((size_t)m.w * m.h, 0);
        for (int r = 0; r < m.h; ++r) {
            for (const Json& run : rows.arr[r].arr) {
                int start = (int)run.arr[0].num, len = (int)run.arr[1].num;
                for (int u = start; u < start + len && u < m.w; ++u) m.cells[(size_t)r * m.w + u] = 1;
            }
        }
        f.masks[ch] = std::move(m);
    }
    return f;
}

double Font::width(const std::string& text) const {
    double w = 0;
    for (char ch : text) w += widths.at(ch);
    return w;
}

double lead(const Settings& s) { return SPREAD[s.speed] + LEAD_EXTRA; }

std::string time_text(const Settings& s, int hour, int minute, int second) {
    int h = s.hours == 0 ? hour : (hour % 12 == 0 ? 12 : hour % 12);
    char buf[32];
    if (s.seconds)
        std::snprintf(buf, sizeof buf, s.hours == 0 ? "%02d:%02d:%02d" : "%d:%02d:%02d", h, minute, second);
    else
        std::snprintf(buf, sizeof buf, s.hours == 0 ? "%02d:%02d" : "%d:%02d", h, minute);
    return buf;
}

std::string widest_text(const Settings& s) { return s.seconds ? "88:88:88" : "88:88"; }

std::vector<Box> layout(const Settings& s, const Font& font, const std::string& text, double ox,
                        double oy) {
    double scale = std::min(W * s.size / 100.0 / font.width(widest_text(s)),
                            H * CLOCK_HEIGHT_MAX / font.h);
    double h = font.h * scale;
    double x = (W - font.width(text) * scale) / 2.0 + ox;
    double y = H * CLOCK_CENTRE_Y[s.position] - h / 2.0 + oy;
    std::vector<Box> boxes;
    for (char ch : text) {
        double w = font.widths.at(ch) * scale;
        boxes.push_back({x, y, w, h});
        x += w;
    }
    return boxes;
}

Grid::Grid(int grain) : g(grain), cols(W / grain), x0((W - (W / grain) * grain) / 2) {}
int Grid::col_at(double px) const { return (int)std::floor((px - x0) / g); }
int Grid::row_at(double py) const { return (int)std::floor((H - py) / g); }

std::vector<GrainCell> grains(const Font& font, char ch, const Box& box, const Grid& grid) {
    const Mask& mask = font.masks.at(ch);
    std::vector<GrainCell> out;
    const int g = grid.g;
    int c0 = std::max(0, grid.col_at(box.x)), c1 = std::min(grid.cols, grid.col_at(box.x + box.w) + 1);
    for (int col = c0; col < c1; ++col) {
        double cx = grid.x(col) + g / 2.0;
        int u = (int)((cx - box.x) / box.w * mask.w);
        if (u < 0 || u >= mask.w) continue;
        for (int row = grid.row_at(box.y + box.h); row < grid.row_at(box.y) + 1; ++row) {
            double cy = H - (row + 0.5) * g;
            int v = (int)((cy - box.y) / box.h * mask.h);
            if (v >= 0 && v < mask.h && mask.at(u, v)) out.push_back({col, (double)(H - (row + 1) * g)});
        }
    }
    return out;
}

int grain_px(const Settings& s, const Font& font) {
    int index = s.grain;
    while (index < 2 && s.crumble == 1) {
        std::string text = widest_text(s);
        Grid grid(GRAIN_PX[index]);
        auto boxes = layout(s, font, text);
        size_t n = 0;
        for (size_t i = 0; i < text.size(); ++i) n += grains(font, text[i], boxes[i], grid).size();
        if ((int)n <= GRAIN_BUDGET) break;
        ++index;
    }
    return GRAIN_PX[index];
}

double pile_target(const Settings& s, const Font& font, int g) {
    Box b = layout(s, font, widest_text(s), 0, DRIFT_PX)[0];
    return std::max(3.0 * g, std::min(H * s.pile / 100.0, H - (b.y + b.h) - 4.0 * g));
}

double sink_speed(double inflow, double height, double target, double footprint) {
    return inflow / std::max(footprint, 200.0) * std::max(0.0, std::min(3.0, height / target));
}

bool speed_changed(double now, double current) {
    return std::fabs(now - current) > std::max(3.0, 0.15 * current);
}

// ------------------------------------------------------------------ physics

double fall_ms(double px, double gravity) { return 1000.0 * std::sqrt(2.0 * std::max(0.0, px) / gravity); }

Pile::Pile(const Grid& g, std::mt19937* r, double t)
    : grid(g), heights(g.cols, 0), rng(r), base_t(t), base_sunk(0), speed(0) {}

double Pile::sunk(double t) const {
    if (has_change && t > change_t)
        return base_sunk + speed * (change_t - base_t) + change_speed * (t - change_t);
    return base_sunk + speed * (t - base_t);
}

double Pile::speed_at(double t) const { return has_change && t > change_t ? change_speed : speed; }

void Pile::schedule(double at, double sp) {
    commit(at);
    has_change = true;
    change_t = at;
    change_speed = sp;
}

void Pile::commit(double t) {
    if (has_change && t >= change_t) {
        base_sunk = sunk(change_t);
        base_t = change_t;
        speed = change_speed;
        has_change = false;
    }
}

double Pile::cell_y(int row, double t) const { return H - (row + 1) * grid.g + sunk(t); }
int Pile::floor_row(double t) const { return (int)std::ceil(sunk(t) / grid.g - 1e-9); }
int Pile::top_row(int col, double t) const { return std::max(heights[col], floor_row(t)); }

double Pile::footprint(double t) const {
    int floor = floor_row(t), n = 0;
    for (int top : heights) n += top > floor + 1;
    return std::max(1, n) * (double)grid.g;
}

double Pile::height_px(double t) const {
    double tallest = 0;
    for (const auto& col : cells) {
        int best = -1;
        for (const auto& rc : col.second)
            if (rc.second.landed <= t) best = std::max(best, rc.first);
        if (best >= 0) tallest = std::max(tallest, H - cell_y(best, t));
    }
    return tallest;
}

std::vector<Flight> Pile::drop(const std::vector<GrainCell>& in, uint32_t colour, double t0,
                               double gravity, double spread) {
    std::vector<Flight> flights;
    if (in.empty()) return flights;
    std::mt19937& r = *rng;
    std::uniform_real_distribution<double> u01(0.0, 1.0);
    const int g = grid.g;
    double low = -1e9, high = 1e9;
    for (const auto& c : in) { low = std::max(low, c.y); high = std::min(high, c.y); }
    double span = std::max(1.0, low - high);

    struct Planned { double est, tie; int col; double y; int land_col; double delay; };
    std::vector<Planned> planned;
    for (const auto& c : in) {
        double delay = 1000.0 * spread * (0.5 * u01(r) + 0.5 * (low - c.y) / span);
        std::normal_distribution<double> gauss(0.0, 0.6 + (H - c.y) / 900.0);
        int dr = (int)std::lround(gauss(r));
        int land_col = std::min(grid.cols - 1, std::max(0, c.col + dr));
        double est = delay + fall_ms(cell_y(top_row(land_col, t0), t0) - c.y, gravity);
        planned.push_back({est, u01(r), c.col, c.y, land_col, delay});
    }
    std::sort(planned.begin(), planned.end(), [](const Planned& a, const Planned& b) {
        return a.est != b.est ? a.est < b.est : a.tie < b.tie;
    });

    for (const auto& p : planned) {
        // Where it meets the pile: the pile sinks while the grain falls, so look twice.
        double t_hit = t0 + p.est / 1000.0, fall = 0;
        int top = 0;
        for (int k = 0; k < 2; ++k) {
            top = top_row(p.land_col, t_hit);
            fall = cell_y(top, t_hit) - p.y;
            t_hit = t0 + (p.delay + fall_ms(fall, gravity)) / 1000.0;
        }
        if (fall <= 0) continue;  // the pile is up to the glyph: this grain is lost
        Flight f;
        f.x = grid.x(p.col);
        f.y = p.y;
        f.colour = colour;
        f.delay = (int)p.delay;
        f.fall_px = fall;
        f.scatter_px = (p.land_col - p.col) * g;
        f.fall_ms = (int)fall_ms(fall, gravity);
        int cur = p.land_col, steps = 0, floor = floor_row(t_hit);
        while (true) {
            int here = std::max(heights[cur], floor);
            int lower[2], n = 0;
            for (int nb : {cur - 1, cur + 1})
                if (nb >= 0 && nb < (int)heights.size() && std::max(heights[nb], floor) < here) lower[n++] = nb;
            if (!n) break;
            cur = n == 1 ? lower[0] : lower[r() % 2];
            ++steps;
        }
        f.col = cur;
        f.row = std::max(heights[cur], floor);
        heights[cur] = f.row + 1;
        f.slide_ms = steps * SLIDE_MS + (steps ? (int)fall_ms((top - f.row) * (double)g, gravity) : 0);
        f.land_ms = f.delay + f.fall_ms + f.slide_ms;
        double t_land = t0 + f.land_ms / 1000.0;
        f.land_y = cell_y(f.row, t_land);
        f.dx = (cur - p.land_col) * g;
        f.dy = f.land_y - (p.y + fall);
        cells[cur][f.row] = {colour, t_land};
        flights.push_back(f);
    }
    std::stable_sort(flights.begin(), flights.end(),
                     [](const Flight& a, const Flight& b) { return a.land_ms < b.land_ms; });
    return flights;
}

void Pile::prune(double t) {
    int gone = floor_row(t) - RUN_BLOCK;
    for (auto it = cells.begin(); it != cells.end();) {
        auto& col = it->second;
        col.erase(col.begin(), col.lower_bound(gone));
        it = col.empty() ? cells.erase(it) : std::next(it);
    }
}

// ------------------------------------------------------------------ colour

uint32_t scale_colour(uint32_t c, double f) {
    auto ch = [&](int shift) {
        return (uint32_t)std::max(0.0, std::min(255.0, std::round(((c >> shift) & 255) * f)));
    };
    return (ch(16) << 16) | (ch(8) << 8) | ch(0);
}

bool is_night(const Settings& s, int t) {
    int day = s.day_start, night = s.night_start;
    if (day == night) return false;
    if (day < night) return !(day <= t && t < night);
    return night <= t && t < day;
}

double dim_factor(const Settings& s, int minute) {
    double f = 1.0 - s.dim / 100.0;
    if (is_night(s, minute)) f *= 1.0 - s.night_dim / 100.0;
    return f;
}

const std::vector<uint32_t>& palette(const Settings& s, int minute) {
    int index = s.palette;
    if (s.night_palette && is_night(s, minute)) index = s.night_palette - 1;
    return PALETTES[index];
}

uint32_t pick(const std::vector<uint32_t>& colours, uint32_t avoid, bool has_avoid, std::mt19937& rng) {
    std::vector<uint32_t> choices;
    for (uint32_t c : colours)
        if (!has_avoid || c != avoid) choices.push_back(c);
    if (choices.empty()) choices = colours;
    return choices[rng() % choices.size()];
}

uint32_t rainbow(double seconds) {
    double h = std::fmod(seconds / RAINBOW_SECONDS, 1.0) * 6.0, v = 1.0, sat = 0.65;
    int i = (int)h;
    double f = h - i, p = v * (1 - sat), q = v * (1 - sat * f), t = v * (1 - sat * (1 - f));
    double rgb[6][3] = {{v, t, p}, {q, v, p}, {p, v, t}, {p, q, v}, {t, p, v}, {v, p, q}};
    auto c = [&](int k) { return (uint32_t)std::lround(rgb[i % 6][k] * 255); };
    return (c(0) << 16) | (c(1) << 8) | c(2);
}

void drift(const Settings& s, double elapsed, double* dx, double* dy) {
    *dx = *dy = 0;
    if (!s.drift) return;
    long t = (long)(elapsed / 60);
    *dx = std::lround(DRIFT_PX * std::sin(2 * M_PI * t / 37.0));
    *dy = std::lround(DRIFT_PX * std::sin(2 * M_PI * t / 23.0 + 1.0));
}

}  // namespace sandclock
