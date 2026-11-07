#include "automata.hpp"

#include <algorithm>
#include <cctype>
#include <cstdlib>

namespace sandclock {
namespace automata {

bool parse_rule(const std::string& text, Rule* out) {
    Rule r;
    r.birth = r.survive = 0;
    r.states = 2;
    bool have_b = false, have_s = false;
    size_t i = 0;
    while (i < text.size()) {
        char c = (char)std::toupper((unsigned char)text[i]);
        if (c == '/' || c == ' ' || c == ',') { ++i; continue; }
        if (c != 'B' && c != 'S' && c != 'C' && c != 'G') return false;
        ++i;
        size_t j = i;
        while (j < text.size() && std::isdigit((unsigned char)text[j])) ++j;
        std::string digits = text.substr(i, j - i);
        i = j;
        if (c == 'C' || c == 'G') {
            if (digits.empty()) return false;
            r.states = std::atoi(digits.c_str());
            if (r.states < 2 || r.states > 255) return false;
        } else {
            int mask = 0;
            for (char d : digits) {
                if (d > '8') return false;
                mask |= 1 << (d - '0');
            }
            (c == 'B' ? r.birth : r.survive) = mask;
            (c == 'B' ? have_b : have_s) = true;
        }
    }
    if (!have_b && !have_s) return false;
    *out = r;
    return true;
}

Rule rule_for(const Settings& s) {
    Rule r;
    if (s.rule >= 0 && s.rule < RULE_COUNT) {
        parse_rule(RULES[s.rule].rule, &r);
    } else if (!parse_rule(s.custom_rule, &r)) {
        parse_rule(RULES[0].rule, &r);   // a custom rule that does not parse: Conway's
    }
    return r;
}

int cols_for(const Settings& s) { return GRID_COLS[std::max(0, std::min(GRID_COUNT - 1, s.grid))]; }

// ------------------------------------------------------------------ patterns

int Pattern::count() const {
    int n = 0;
    for (uint8_t c : cells) n += c != 0;
    return n;
}

Pattern parse_rle(const std::string& rle) {
    // Header "x = 3, y = 3" is optional; comment lines start with '#'.
    Pattern p;
    std::vector<std::vector<uint8_t>> rows(1);
    int run = 0;
    bool body = false;
    size_t i = 0;
    while (i < rle.size()) {
        char c = rle[i];
        if (!body && (c == '#' || c == 'x' || c == 'X')) {          // skip a comment or header line
            while (i < rle.size() && rle[i] != '\n') ++i;
            continue;
        }
        body = true;
        ++i;
        if (std::isdigit((unsigned char)c)) { run = run * 10 + (c - '0'); continue; }
        int n = run ? run : 1;
        run = 0;
        if (c == 'b' || c == 'o') {
            rows.back().insert(rows.back().end(), (size_t)n, c == 'o' ? 1 : 0);
        } else if (c == '$') {
            for (int k = 0; k < n; ++k) rows.emplace_back();
        } else if (c == '!') {
            break;
        }
    }
    for (auto& r : rows) p.w = std::max(p.w, (int)r.size());
    p.h = (int)rows.size();
    p.cells.assign((size_t)p.w * p.h, 0);
    for (int y = 0; y < p.h; ++y)
        for (size_t x = 0; x < rows[y].size(); ++x) p.cells[(size_t)y * p.w + x] = rows[y][x];
    return p;
}

const Pattern& glider() { static Pattern p = parse_rle("bob$2bo$3o!"); return p; }
const Pattern& r_pentomino() { static Pattern p = parse_rle("b2o$2ob$bo!"); return p; }
const Pattern& acorn() { static Pattern p = parse_rle("bo5b$3bo3b$2o2b3o!"); return p; }
const Pattern& gosper_gun() {
    static Pattern p = parse_rle(
        "24bo11b$22bobo11b$12b2o6b2o12b2o$11bo3bo4b2o12b2o$2o8bo5bo3b2o14b$2o8bo3bob2o4bobo11b$"
        "10bo5bo7bo11b$11bo3bo20b$12b2o!");
    return p;
}

int Stamp::width() const { return (orient & 4) ? pattern->h : pattern->w; }
int Stamp::height() const { return (orient & 4) ? pattern->w : pattern->h; }
bool Stamp::at(int dx, int dy) const {
    if (dx < 0 || dy < 0 || dx >= width() || dy >= height()) return false;
    if (orient & 1) dx = width() - 1 - dx;
    if (orient & 2) dy = height() - 1 - dy;
    if (orient & 4) std::swap(dx, dy);
    return pattern->cells[(size_t)dy * pattern->w + dx] != 0;
}

Start make_start(int start, int cols, int rows, std::mt19937& rng) {
    Start s;
    auto rnd = [&](int lo, int hi) { return lo + (int)(rng() % (unsigned)std::max(1, hi - lo + 1)); };
    auto place = [&](const Pattern* p, int x, int y, int orient) {
        Stamp st{p, x, y, orient};
        st.x = std::max(0, std::min(cols - st.width(), st.x));
        st.y = std::max(0, std::min(rows - st.height(), st.y));
        s.stamps.push_back(st);
    };
    auto guns = [&] {
        const Pattern* g = &gosper_gun();
        int mx = cols / 12, my = rows / 12;
        place(g, mx, my, 0);                                   // each shoots toward the centre
        place(g, cols - mx - g->w, my, 1);
        place(g, mx, rows - my - g->h, 2);
        place(g, cols - mx - g->w, rows - my - g->h, 3);
    };
    switch (start) {
        case 0: s.soup_mode = 0; break;
        case 1: s.soup_mode = 1; break;
        case 2: s.soup_mode = 2; break;
        case 3: s.soup_mode = 3; break;
        case 4: s.soup_mode = 4; break;
        case 5: place(&r_pentomino(), cols / 2 - 1, rows / 2 - 1, 0); break;
        case 6: place(&acorn(), cols / 2 - 3, rows / 2 - 1, 0); break;
        case 7: guns(); break;
        case 8: {
            int n = std::max(20, std::min(4000, cols * rows / 20000));
            for (int i = 0; i < n; ++i) place(&glider(), rnd(2, cols - 6), rnd(2, rows - 6), rnd(0, 7));
            break;
        }
        default: s.soup_mode = 1; guns(); break;
    }
    return s;
}

// ------------------------------------------------------------------ reference

void step_cpu(const std::vector<uint8_t>& in, std::vector<uint8_t>& out, int w, int h, const Rule& rule,
              bool wrap) {
    out.assign(in.size(), 0);
    for (int y = 0; y < h; ++y) {
        for (int x = 0; x < w; ++x) {
            int n = 0;
            for (int dy = -1; dy <= 1; ++dy) {
                for (int dx = -1; dx <= 1; ++dx) {
                    if (!dx && !dy) continue;
                    int xx = x + dx, yy = y + dy;
                    if (wrap) {
                        xx = (xx + w) % w;
                        yy = (yy + h) % h;
                    } else if (xx < 0 || yy < 0 || xx >= w || yy >= h) {
                        continue;
                    }
                    n += in[(size_t)yy * w + xx] == 1;
                }
            }
            int cur = in[(size_t)y * w + x], ns;
            if (cur == 0) ns = (rule.birth >> n) & 1;
            else if (cur == 1) ns = ((rule.survive >> n) & 1) ? 1 : (rule.states > 2 ? 2 : 0);
            else ns = cur + 1 < rule.states ? cur + 1 : 0;
            out[(size_t)y * w + x] = (uint8_t)ns;
        }
    }
}

}  // namespace automata
}  // namespace sandclock
