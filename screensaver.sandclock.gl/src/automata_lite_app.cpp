// Cellular Automata Lite: see automata_lite_app.hpp. The clock, its font, mask texture and overlay
// pass are gone. The update and draw shaders are specialised at init (wrap, rule state count,
// sparks, colour mode, view, background, shape, glow, screen effect), and the draw pass renders
// into a target at no more than twice the grid, scaled up once, so the per-screen-pixel work on a
// weak GPU is a fraction of the full add-on's.
#include "automata_lite_app.hpp"

#include <algorithm>
#include <cmath>
#include <cstring>

#include "gl_util.hpp"

namespace sandclock {
namespace automata {
namespace lite {

namespace {

int clamp_int(int v, int lo, int hi) { return v < lo ? lo : (v > hi ? hi : v); }

const char* kInit = R"(
uniform vec2 u_grid;
uniform float u_mode, u_density, u_seed;
float hash(vec2 p) { return fract(sin(dot(p + u_seed, vec2(12.9898, 78.233))) * 43758.5453); }
void main() {
    vec2 c = floor(gl_FragCoord.xy);
    float on = 0.0;
    if (u_mode < 0.5) {
        on = step(hash(c), u_density);
    } else if (u_mode < 1.5) {
        on = step(hash(c), u_density * 0.15);
    } else if (u_mode < 2.5) {
        vec2 blk = floor(c / 64.0);
        vec2 centre = (blk + 0.2 + 0.6 * vec2(hash(blk + 5.1), hash(blk + 9.7))) * 64.0;
        float radius = 8.0 + 20.0 * hash(blk + 3.3);
        on = (hash(blk * 7.3 + 1.0) < 0.55 && length(c - centre) < radius) ? step(hash(c), 0.5) : 0.0;
    } else if (u_mode < 3.5) {
        on = step(hash(floor(abs(c + 0.5 - u_grid * 0.5))), u_density);
    } else {
        float d = length((c + 0.5 - u_grid * 0.5) / (u_grid.y * 0.5));
        on = d < 0.22 ? step(hash(c), 0.5) : 0.0;
    }
    gl_FragColor = vec4(on / 255.0, 0.0, on, on);
}
)";

// Halve a grid, keeping both "is anything alive" (max) and "how much" (mean), so a lone glider
// on a 4K board still counts and a settled board can be told from a busy one.
const char* kReduce = R"(
uniform sampler2D u_src;
uniform vec2 u_srcsize;
uniform float u_first;
vec4 fetch(vec2 p) { return texture2D(u_src, (min(p, u_srcsize - 1.0) + 0.5) / u_srcsize); }
void main() {
    vec2 b = floor(gl_FragCoord.xy) * 2.0;
    vec4 a = fetch(b), c = fetch(b + vec2(1.0, 0.0)), d = fetch(b + vec2(0.0, 1.0)), e = fetch(b + vec2(1.0, 1.0));
    float m, v;
    if (u_first > 0.5) { m = max(max(a.a, c.a), max(d.a, e.a)); v = (a.a + c.a + d.a + e.a) * 0.25; }
    else { m = max(max(a.r, c.r), max(d.r, e.r)); v = (a.g + c.g + d.g + e.g) * 0.25; }
    gl_FragColor = vec4(m, v, 0.0, 1.0);
}
)";

double wrap01(double v) { return v - std::floor(v); }

}  // namespace

int App::draw_cap_w = 1920, App::draw_cap_h = 1080;

App::~App() { release(); }

int App::loc(unsigned prog, const char* name) const { return glGetUniformLocation(prog, name); }

bool App::make_target(Target* t, int w, int h, bool linear) {
    t->w = w;
    t->h = h;
    glGenTextures(1, &t->tex);
    glBindTexture(GL_TEXTURE_2D, t->tex);
    glTexImage2D(GL_TEXTURE_2D, 0, GL_RGBA, w, h, 0, GL_RGBA, GL_UNSIGNED_BYTE, nullptr);
    glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_MIN_FILTER, linear ? GL_LINEAR : GL_NEAREST);
    glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_MAG_FILTER, linear ? GL_LINEAR : GL_NEAREST);
    glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_WRAP_S, GL_CLAMP_TO_EDGE);
    glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_WRAP_T, GL_CLAMP_TO_EDGE);
    glGenFramebuffers(1, &t->fbo);
    glBindFramebuffer(GL_FRAMEBUFFER, t->fbo);
    glFramebufferTexture2D(GL_FRAMEBUFFER, GL_COLOR_ATTACHMENT0, GL_TEXTURE_2D, t->tex, 0);
    return glCheckFramebufferStatus(GL_FRAMEBUFFER) == GL_FRAMEBUFFER_COMPLETE;
}

// One generation. The rule, wrap, two-state versus Generations, and whether sparks exist are
// compiled in; the cell coordinates wrap with one fract (one multiply-add and a fract per
// neighbour) instead of a mod and a divide.
std::string App::update_source(const Settings& s, const Rule& rule) {
    std::string d;
    d += "#define WRAP " + std::to_string(s.wrap ? 1 : 0) + "\n";
    d += "#define TWO_STATE " + std::to_string(rule.states <= 2 ? 1 : 0) + "\n";
    d += "#define SPARKS " + std::to_string(s.sparks > 0 ? 1 : 0) + "\n";
    d += R"(
uniform sampler2D u_src;
uniform vec2 u_grid;
uniform vec2 u_inv;
uniform vec4 u_rules;      // birth mask, survive mask, trail kept, spark chance
uniform float u_states;
uniform float u_seed;

float bit(float mask, float n) { return mod(floor(mask / exp2(n) + 0.001), 2.0); }

#if WRAP
vec2 uv_at(vec2 c) { return fract((c + 0.5) * u_inv); }
float alive(vec2 c) { return texture2D(u_src, uv_at(c)).a; }
#else
vec2 uv_at(vec2 c) { return (c + 0.5) * u_inv; }
float alive(vec2 c) {
    if (c.x < 0.0 || c.y < 0.0 || c.x >= u_grid.x || c.y >= u_grid.y) return 0.0;
    return texture2D(u_src, uv_at(c)).a;
}
#endif

void main() {
    vec2 c = floor(gl_FragCoord.xy);
    vec4 s = texture2D(u_src, uv_at(c));
    float n = alive(c + vec2(-1.0, -1.0)) + alive(c + vec2(0.0, -1.0)) + alive(c + vec2(1.0, -1.0))
            + alive(c + vec2(-1.0, 0.0))                               + alive(c + vec2(1.0, 0.0))
            + alive(c + vec2(-1.0, 1.0))  + alive(c + vec2(0.0, 1.0))  + alive(c + vec2(1.0, 1.0));
    float birth = u_rules.x, survive = u_rules.y;
    float age = s.g;
    float ns;
    bool live;
#if TWO_STATE
    bool was = s.r > 0.00196078;               // 0.5 / 255
    ns = was ? (bit(survive, n) > 0.5 ? 1.0 : 0.0) : bit(birth, n);
    live = ns > 0.5;
    if (live) age = was ? min(age + 0.00392157, 1.0) : 0.0;
#else
    float cur = floor(s.r * 255.0 + 0.5);
    if (cur < 0.5) ns = bit(birth, n);
    else if (cur < 1.5) ns = bit(survive, n) > 0.5 ? 1.0 : 2.0;
    else ns = (cur + 1.0 < u_states) ? cur + 1.0 : 0.0;
    live = ns > 0.5 && ns < 1.5;
    if (live) age = (cur > 0.5 && cur < 1.5) ? min(age + 0.00392157, 1.0) : 0.0;
#endif
    float trail = live ? 1.0 : s.b * u_rules.z;
    trail = trail < 0.02 ? 0.0 : trail;
#if SPARKS
    if (u_rules.w > 0.0 && ns < 0.5) {
        float h = fract(sin(dot(c + vec2(u_seed, u_seed * 1.7), vec2(12.9898, 78.233))) * 43758.5453);
        if (h < u_rules.w) { ns = 1.0; age = 0.0; trail = 1.0; live = true; }
    }
#endif
    gl_FragColor = vec4(ns * 0.00392157, age, trail, live ? 1.0 : 0.0);
}
)";
    return d;
}

// What is on screen: each pixel is mapped to a point on the grid (flat with a camera, or one of
// the 3D-looking views), and that cell is coloured. Only the selected view, colour mode,
// background, shape, glow and screen effect are compiled in.
std::string App::draw_source(const Settings& s, const Rule& rule) {
    int view = clamp_int(s.view, 0, VIEW_COUNT - 1);
    std::string d;
    d += "#define WRAP " + std::to_string(s.wrap ? 1 : 0) + "\n";
    d += "#define VIEW_KIND " + std::to_string(view) + "\n";
    d += "#define PLANAR_KIND " + std::to_string(view < 2 ? 1 : 0) + "\n";
    d += "#define COLOUR_MODE " + std::to_string(clamp_int(s.colour_mode, 0, MODE_COUNT - 1)) + "\n";
    d += "#define BGSTYLE " + std::to_string(clamp_int(s.background_style, 0, 2)) + "\n";
    d += "#define SHAPE_KIND " + std::to_string(clamp_int(s.shape, 0, 2)) + "\n";
    d += "#define GLOW_ON " + std::to_string(s.glow > 0 ? 1 : 0) + "\n";
    d += "#define MULTI_STATE " + std::to_string(rule.states > 2 ? 1 : 0) + "\n";
    d += R"(
uniform sampler2D u_state;
uniform sampler2D u_pal;       // 8 x 1: the 7 palette colours and the first again, so it loops
uniform vec4 u_p0;             // cell px at the internal resolution, palette phase, dim, glow
uniform vec4 u_p1;             // age span, time, zoom, turn
uniform vec4 u_p2;             // camera x, y (grid uv), grid w, h
uniform vec4 u_p3;             // 1/grid w, 1/grid h, states
uniform vec3 u_colour, u_bg;
varying vec2 v_uv;

#define CELLPX u_p0.x
#define PHASE u_p0.y
#define DIM u_p0.z
#define GLOW u_p0.w
#define AGESPAN u_p1.x
#define TIME u_p1.y
#define ZOOM u_p1.z
#define ROT u_p1.w
#define CAM u_p2.xy
#define GRID u_p2.zw
#define INV u_p3.xy
#define STATES u_p3.z

vec3 pal(float t) { return texture2D(u_pal, vec2((fract(t) * 7.0 + 0.5) / 8.0, 0.5)).rgb; }
vec3 hsv(float h) {
    vec3 k = clamp(abs(fract(vec3(h) + vec3(1.0, 2.0 / 3.0, 1.0 / 3.0)) * 6.0 - 3.0) - 1.0, 0.0, 1.0);
    return mix(vec3(1.0), k, 0.75);
}
float plasma(vec2 q, float t) {
    return 0.5 + 0.25 * sin(q.x * 9.0 + t) + 0.25 * sin(q.y * 7.0 - t * 1.3 + 2.0 * sin(q.x * 3.0 + t * 0.5));
}
#if WRAP
vec4 cell(vec2 c) { return texture2D(u_state, fract((c + 0.5) * INV)); }
#else
vec4 cell(vec2 c) { return texture2D(u_state, (clamp(c, vec2(0.0), GRID - 1.0) + 0.5) * INV); }
#endif
vec2 turn(vec2 v, float a) { float s = sin(a), k = cos(a); return vec2(k * v.x - s * v.y, s * v.x + k * v.y); }

vec3 background(vec2 p) {
#if BGSTYLE == 0
    return u_bg;
#elif BGSTYLE == 1
    return u_bg + pal(PHASE) * 0.2 * clamp(0.6 - p.y, 0.0, 1.0);
#else
    return u_bg + pal(plasma(p * 0.8, TIME * 0.4) + PHASE) * 0.13;
#endif
}

// A cell's colour (rgb) and how strongly it shows (a). w: where on the grid (0..1).
vec4 shade_cell(vec4 s, vec2 c, vec2 w) {
    float cur = floor(s.r * 255.0 + 0.5);
    float fade = 0.0;
#if MULTI_STATE
    if (cur > 1.5) fade = 1.0 - (cur - 1.0) / (STATES - 1.0);   // dying states fade out
#endif
    float inten = max(s.a, max(fade * 0.85, s.b * 0.7));
    float age = s.g * 255.0 / AGESPAN;
    vec3 col;
#if COLOUR_MODE == 0
    col = pal(age + PHASE);
#elif COLOUR_MODE == 1
    col = pal(w.x * 0.7 + w.y * 0.5 + PHASE);
#elif COLOUR_MODE == 2
    col = pal(PHASE);
#elif COLOUR_MODE == 3
    col = u_colour;
#elif COLOUR_MODE == 4
    col = hsv(age * 0.5 + w.x * 0.3 + PHASE);
#elif COLOUR_MODE == 5
    float t = clamp(age * 0.6, 0.0, 1.0);
    col = mix(vec3(1.0, 0.97, 0.85), vec3(1.0, 0.72, 0.12), smoothstep(0.0, 0.3, t));
    col = mix(col, vec3(0.85, 0.16, 0.04), smoothstep(0.3, 0.9, t));
    if (s.a < 0.5) col = mix(vec3(0.45, 0.04, 0.0), vec3(1.0, 0.45, 0.05), s.b);   // embers
#elif COLOUR_MODE == 6
    float n = cell(c + vec2(-1.0, -1.0)).a + cell(c + vec2(0.0, -1.0)).a + cell(c + vec2(1.0, -1.0)).a
            + cell(c + vec2(-1.0, 0.0)).a + cell(c + vec2(1.0, 0.0)).a
            + cell(c + vec2(-1.0, 1.0)).a + cell(c + vec2(0.0, 1.0)).a + cell(c + vec2(1.0, 1.0)).a;
    col = pal(n / 8.0 + PHASE);
#elif COLOUR_MODE == 7
    col = s.a > 0.5 ? vec3(1.0) : hsv(s.b * 1.3 + PHASE);
#else
    col = pal(plasma(w * 1.5, TIME * 0.5) + PHASE);
#endif
    return vec4(col, inten);
}

void main() {
    vec2 p = (v_uv - 0.5) * vec2(1.7777778, 1.0);   // screen: height 1, centre 0
    vec3 bg = background(p);
    vec3 col = bg;
    float light = 1.0, fog = 0.0;
    vec3 fogcol = bg;
    vec2 w = vec2(0.0);
    bool hit = true;

#if PLANAR_KIND == 1
    w = CAM + turn(p / ZOOM, ROT) / vec2(1.7777778, 1.0);
#if !WRAP
    if (w.x < 0.0 || w.y < 0.0 || w.x > 1.0 || w.y > 1.0) { hit = false; col = bg * 0.5; }
#endif
#elif VIEW_KIND == 2                         // landscape: the grid as the ground, seen in perspective
    float horizon = 0.14;
    fogcol = bg + pal(PHASE) * 0.22;
    if (p.y > horizon - 0.003) {
        hit = false;
        col = mix(fogcol, bg, clamp((p.y - horizon) * 2.5, 0.0, 1.0));
    } else {
        float z = 0.3 / (horizon - p.y);
        w = CAM + turn(vec2(p.x * z, z), ROT) * 0.22 / ZOOM / vec2(1.7777778, 1.0);
        fog = 1.0 - exp(-z * 0.16);
    }
#elif VIEW_KIND == 3                         // tunnel: the grid wrapped round a tube
    float r = length(p);
    w = vec2(atan(p.y, p.x) / 6.2831853 + ROT, 0.16 / max(r, 0.01) / ZOOM) + CAM;
    fog = 1.0 - smoothstep(0.02, 0.5, r);
#else                                        // globe
    float R = 0.44;
    float r = length(p);
    if (r > R) {
        hit = false;
        col = bg + pal(PHASE) * 0.35 * smoothstep(R + 0.07, R, r);   // atmosphere
    } else {
        vec3 n = vec3(p, sqrt(R * R - r * r)) / R;
        w = vec2(atan(n.x, n.z) / 6.2831853 + CAM.x, asin(clamp(n.y, -1.0, 1.0)) / 3.14159265 + 0.5);
        light = 0.18 + 0.95 * max(dot(n, normalize(vec3(-0.45, 0.5, 0.75))), 0.0);
        fog = pow(1.0 - n.z, 3.0) * 0.55;
        fogcol = pal(PHASE) * 0.7 + 0.15;
    }
#endif

    if (hit) {
        vec2 g = w * GRID;
        vec2 c = floor(g);
        vec2 f = fract(g) - 0.5;
        vec4 s = cell(c);
        vec4 cc = shade_cell(s, c, fract(w));
        float mask = 1.0;
        float cellpx = CELLPX * ZOOM;
#if PLANAR_KIND == 1
        if (cellpx >= 4.0) {                   // cell shapes, once cells are big enough to see
            float px = 1.0 / cellpx;
#if SHAPE_KIND == 0
            mask = 1.0 - smoothstep(0.0, px, max(abs(f.x), abs(f.y)) - (0.5 - px * 0.5));
#else
            float r = SHAPE_KIND == 1 ? 0.25 : 0.5;
            float half_size = 0.5 - px * 0.25;
            vec2 q = abs(f) - vec2(half_size - r);
            float d = length(max(q, vec2(0.0))) + min(max(q.x, q.y), 0.0) - r;
            mask = 1.0 - smoothstep(0.0, px, d);
#endif
        }
#endif
        vec3 base = bg;
#if VIEW_KIND == 1                         // raised blocks, lit from the top left
        if (cc.a > 0.05) {
            vec2 e = smoothstep(0.3, 0.5, abs(f)) * sign(f);
            light *= 1.0 + 0.45 * (e.y - e.x);
        } else {
            float sh = 0.0;                    // shadows of the blocks up and to the left
            if (f.x < -0.15 && f.y > 0.15) sh = cell(c + vec2(-1.0, 1.0)).a;
            if (f.x < -0.15 && f.y <= 0.15) sh = max(sh, cell(c + vec2(-1.0, 0.0)).a);
            if (f.x >= -0.15 && f.y > 0.15) sh = max(sh, cell(c + vec2(0.0, 1.0)).a);
            base *= 1.0 - 0.6 * sh;
        }
#endif
#if GLOW_ON && PLANAR_KIND == 1
        if (s.a < 0.5) {                       // a soft halo from the live neighbours
            float halo = 0.0;
            for (int j = -1; j <= 1; j++) {
                for (int i = -1; i <= 1; i++) {
                    vec2 o = vec2(float(i), float(j));
                    halo += cell(c + o).a * max(0.0, 1.0 - length(f - o) / 1.6);
                }
            }
            base += cc.rgb * DIM * halo * GLOW * 0.45;   // the cell's own colour, not a second shade
        }
#endif
        col = mix(base, cc.rgb * DIM, cc.a * mask) * light;
        col = mix(col, fogcol, fog);
    }
    gl_FragColor = vec4(col, 1.0);
}
)";
    return d;
}

// The scale-up (and screen effect) pass: one texture read a pixel. The vignette and CRT are
// applied here, at the output resolution, so they stay sharp when the scene is drawn smaller.
std::string App::present_source(const Settings& s) {
    std::string d = "#define SCREENFX " + std::to_string(clamp_int(s.screen_fx, 0, 2)) + "\n";
    d += R"(
uniform sampler2D u_tex;
varying vec2 v_uv;
void main() {
    vec3 col = texture2D(u_tex, v_uv).rgb;
#if SCREENFX > 0
    vec2 p = (v_uv - 0.5) * vec2(1.7777778, 1.0);
    col *= 1.0 - 0.55 * dot(p * vec2(0.85, 1.25), p * vec2(0.85, 1.25));
#endif
#if SCREENFX > 1
    col *= 0.8 + 0.2 * sin(gl_FragCoord.y * 3.14159265);
#endif
    gl_FragColor = vec4(col, 1.0);
}
)";
    return d;
}

void App::shader_sources(const Settings& settings, std::string* update, std::string* draw,
                         std::string* present) {
    Rule rule = rule_for(settings);
    if (update) *update = update_source(settings, rule);
    if (draw) *draw = draw_source(settings, rule);
    if (present) *present = present_source(settings);
}

bool App::init(const Settings& settings, unsigned seed, std::string* error) {
    release();
    glu::SavedState saved;
    s_ = settings;
    rule_ = rule_for(s_);
    rng_.seed(seed);

    int max_tex = 2048;
    glGetIntegerv(GL_MAX_TEXTURE_SIZE, &max_tex);
    int index = std::max(0, std::min(GRID_COUNT - 1, s_.grid));
    while (index > 0 && GRID_COLS[index] > max_tex) --index;
    cols_ = GRID_COLS[index];
    rows_ = rows_for_cols(cols_);
    draw_pref_ = clamp_int(s_.draw, 0, 5);

    std::string update_src = update_source(s_, rule_), draw_src = draw_source(s_, rule_),
                present_src = present_source(s_);
    prog_update_ = glu::link(nullptr, update_src.c_str(), error);
    if (!prog_update_) return false;
    prog_init_ = glu::link(nullptr, kInit, error);
    if (!prog_init_) return false;
    prog_draw_ = glu::link(nullptr, draw_src.c_str(), error);
    if (!prog_draw_) return false;
    prog_reduce_ = glu::link(nullptr, kReduce, error);
    if (!prog_reduce_) return false;
    prog_present_ = glu::link(nullptr, present_src.c_str(), error);
    if (!prog_present_) return false;

    uu_ = {loc(prog_update_, "u_src"), loc(prog_update_, "u_grid"), loc(prog_update_, "u_inv"),
           loc(prog_update_, "u_rules"), loc(prog_update_, "u_states"), loc(prog_update_, "u_seed")};
    iu_ = {loc(prog_init_, "u_grid"), loc(prog_init_, "u_mode"), loc(prog_init_, "u_density"),
           loc(prog_init_, "u_seed")};
    du_ = {loc(prog_draw_, "u_state"), loc(prog_draw_, "u_pal"), loc(prog_draw_, "u_p0"),
           loc(prog_draw_, "u_p1"), loc(prog_draw_, "u_p2"), loc(prog_draw_, "u_p3"),
           loc(prog_draw_, "u_colour"), loc(prog_draw_, "u_bg")};
    ru_ = {loc(prog_reduce_, "u_src"), loc(prog_reduce_, "u_srcsize"), loc(prog_reduce_, "u_first")};
    pu_ = {loc(prog_present_, "u_tex")};

    static const float quad[8] = {-1, -1, 1, -1, -1, 1, 1, 1};
    glGenBuffers(1, &vbo_);
    glBindBuffer(GL_ARRAY_BUFFER, vbo_);
    glBufferData(GL_ARRAY_BUFFER, sizeof quad, quad, GL_STATIC_DRAW);
#ifdef SANDCLOCK_CORE
    glGenVertexArrays(1, &vao_);
#endif

    if (!make_target(&state_[0], cols_, rows_, false) || !make_target(&state_[1], cols_, rows_, false)) {
        *error = "cannot make a " + std::to_string(cols_) + "x" + std::to_string(rows_) + " texture to render to";
        return false;
    }
    for (int w = cols_, h = rows_; w > 8;) {
        w = (w + 1) / 2;
        h = (h + 1) / 2;
        Target t;
        if (!make_target(&t, w, h, false)) { *error = "cannot make a reduction target"; return false; }
        chain_.push_back(t);
    }
    glGenTextures(1, &pal_tex_);
    set_palette();

    max_steps_ = 4;
    ready_ = true;
    restart(0);
    return true;
}

void App::release() {
    for (Target& t : state_) {
        if (t.fbo) glDeleteFramebuffers(1, &t.fbo);
        if (t.tex) glDeleteTextures(1, &t.tex);
        t = Target();
    }
    for (Target& t : chain_) {
        if (t.fbo) glDeleteFramebuffers(1, &t.fbo);
        if (t.tex) glDeleteTextures(1, &t.tex);
    }
    chain_.clear();
    if (draw_.fbo) glDeleteFramebuffers(1, &draw_.fbo);
    if (draw_.tex) glDeleteTextures(1, &draw_.tex);
    draw_ = Target();
    if (pal_tex_) glDeleteTextures(1, &pal_tex_);
    if (vbo_) glDeleteBuffers(1, &vbo_);
#ifdef SANDCLOCK_CORE
    if (vao_) glDeleteVertexArrays(1, &vao_);
#endif
    for (unsigned* p : {&prog_update_, &prog_init_, &prog_draw_, &prog_reduce_, &prog_present_})
        if (*p) glDeleteProgram(*p);
    prog_update_ = prog_init_ = prog_draw_ = prog_reduce_ = prog_present_ = 0;
    vbo_ = vao_ = pal_tex_ = 0;
    draw_scaled_ = false;
    ready_ = false;
}

void App::set_palette() {
    const uint32_t* p = PALETTE[std::max(0, std::min(PALETTE_COUNT - 1, s_.palette))];
    unsigned char px[8 * 3];
    for (int i = 0; i < 8; ++i) {
        uint32_t c = p[i % 7];
        px[i * 3] = (c >> 16) & 255; px[i * 3 + 1] = (c >> 8) & 255; px[i * 3 + 2] = c & 255;
    }
    glActiveTexture(GL_TEXTURE1);
    glBindTexture(GL_TEXTURE_2D, pal_tex_);
    glPixelStorei(GL_UNPACK_ALIGNMENT, 1);
    glTexImage2D(GL_TEXTURE_2D, 0, GL_RGB, 8, 1, 0, GL_RGB, GL_UNSIGNED_BYTE, px);
    glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_MIN_FILTER, GL_LINEAR);
    glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_MAG_FILTER, GL_LINEAR);
    glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_WRAP_S, GL_CLAMP_TO_EDGE);
    glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_WRAP_T, GL_CLAMP_TO_EDGE);
    glActiveTexture(GL_TEXTURE0);
}

void App::draw_quad() {
#ifdef SANDCLOCK_CORE
    glBindVertexArray(vao_);
#endif
    glBindBuffer(GL_ARRAY_BUFFER, vbo_);
    glEnableVertexAttribArray(0);
    glVertexAttribPointer(0, 2, GL_FLOAT, GL_FALSE, 0, (const void*)0);
    glDrawArrays(GL_TRIANGLE_STRIP, 0, 4);
    glDisableVertexAttribArray(0);
#ifdef SANDCLOCK_CORE
    glBindVertexArray(0);
#endif
}

void App::upload_state(const std::vector<uint8_t>& states) {
    glu::SavedState saved;
    std::vector<uint8_t> rgba((size_t)cols_ * rows_ * 4, 0);
    for (size_t i = 0; i < states.size() && i < (size_t)cols_ * rows_; ++i) {
        uint8_t st = states[i];
        rgba[i * 4] = st;
        if (st == 1) { rgba[i * 4 + 2] = 255; rgba[i * 4 + 3] = 255; }
    }
    glBindTexture(GL_TEXTURE_2D, state_[cur_].tex);
    glPixelStorei(GL_UNPACK_ALIGNMENT, 1);
    glTexSubImage2D(GL_TEXTURE_2D, 0, 0, 0, cols_, rows_, GL_RGBA, GL_UNSIGNED_BYTE, rgba.data());
}

void App::reseed(double now) { restart(now); }

void App::restart(double now) {
    glu::SavedState saved;
    Start st = make_start(s_.start, cols_, rows_, rng_);
    glBindFramebuffer(GL_FRAMEBUFFER, state_[cur_].fbo);
    glViewport(0, 0, cols_, rows_);
    if (st.soup_mode >= 0) {
        glUseProgram(prog_init_);
        glUniform2f(iu_.grid, (float)cols_, (float)rows_);
        glUniform1f(iu_.mode, (float)st.soup_mode);
        glUniform1f(iu_.density, s_.density / 100.0f);
        glUniform1f(iu_.seed, (float)(rng_() % 1000));
        draw_quad();
    } else {
        glClearColor(0, 0, 0, 0);
        glClear(GL_COLOR_BUFFER_BIT);
    }
    glBindTexture(GL_TEXTURE_2D, state_[cur_].tex);
    glPixelStorei(GL_UNPACK_ALIGNMENT, 1);
    for (const Stamp& sp : st.stamps) {
        int w = sp.width(), h = sp.height();
        std::vector<uint8_t> px((size_t)w * h * 4, 0);
        for (int y = 0; y < h; ++y)
            for (int x = 0; x < w; ++x)
                if (sp.at(x, y)) {
                    uint8_t* p = &px[((size_t)y * w + x) * 4];
                    p[0] = 1; p[2] = 255; p[3] = 255;
                }
        glTexSubImage2D(GL_TEXTURE_2D, 0, sp.x, sp.y, w, h, GL_RGBA, GL_UNSIGNED_BYTE, px.data());
    }
    last_restart_ = now;
    next_check_ = now + 4.0;
    dead_checks_ = stagnant_checks_ = 0;
    history_.clear();
    gens_at_check_ = generation_;
}

void App::step_saved(int n) {
    if (n <= 0) return;
    glUseProgram(prog_update_);
    glViewport(0, 0, cols_, rows_);
    glUniform1i(uu_.src, 0);
    glUniform2f(uu_.grid, (float)cols_, (float)rows_);
    glUniform2f(uu_.inv, 1.0f / cols_, 1.0f / rows_);
    glUniform4f(uu_.rules, (float)rule_.birth, (float)rule_.survive, s_.trail / 100.0f,
                s_.sparks * 1e-6f);
    glUniform1f(uu_.states, (float)rule_.states);
    glActiveTexture(GL_TEXTURE0);
    for (int i = 0; i < n; ++i) {
        if (s_.sparks > 0) glUniform1f(uu_.seed, (float)(rng_() % 1000));
        glBindFramebuffer(GL_FRAMEBUFFER, state_[1 - cur_].fbo);
        glBindTexture(GL_TEXTURE_2D, state_[cur_].tex);
        draw_quad();
        cur_ = 1 - cur_;
        ++generation_;
    }
}

void App::step(int n) {
    glu::SavedState saved;
    step_saved(n);
}

void App::read_state(std::vector<uint8_t>* states) {
    glu::SavedState saved;
    std::vector<uint8_t> rgba((size_t)cols_ * rows_ * 4);
    glBindFramebuffer(GL_FRAMEBUFFER, state_[cur_].fbo);
    glPixelStorei(GL_PACK_ALIGNMENT, 1);
    glReadPixels(0, 0, cols_, rows_, GL_RGBA, GL_UNSIGNED_BYTE, rgba.data());
    states->resize((size_t)cols_ * rows_);
    for (size_t i = 0; i < states->size(); ++i) (*states)[i] = rgba[i * 4];
}

App::Measure App::measure() {
    glu::SavedState saved;
    glUseProgram(prog_reduce_);
    glUniform1i(ru_.src, 0);
    glActiveTexture(GL_TEXTURE0);
    const Target* src = &state_[cur_];
    for (size_t i = 0; i < chain_.size(); ++i) {
        glBindFramebuffer(GL_FRAMEBUFFER, chain_[i].fbo);
        glViewport(0, 0, chain_[i].w, chain_[i].h);
        glBindTexture(GL_TEXTURE_2D, src->tex);
        glUniform2f(ru_.srcsize, (float)src->w, (float)src->h);
        glUniform1f(ru_.first, i == 0 ? 1.f : 0.f);
        draw_quad();
        src = &chain_[i];
    }
    const Target& last = chain_.back();
    std::vector<uint8_t> px((size_t)last.w * last.h * 4);
    glPixelStorei(GL_PACK_ALIGNMENT, 1);
    glReadPixels(0, 0, last.w, last.h, GL_RGBA, GL_UNSIGNED_BYTE, px.data());
    Measure m{false, 2166136261u};
    for (size_t i = 0; i < px.size(); i += 4) {
        m.any_alive |= px[i] > 0;
        m.checksum = (m.checksum ^ px[i]) * 16777619u;          // presence map
        m.checksum = (m.checksum ^ px[i + 1]) * 16777619u;      // density map
    }
    return m;
}

// Moves the camera. Flat views pan, zoom and turn over the grid; the landscape and tunnel always
// travel forward; the globe spins.
void App::update_camera(double dt) {
    double speed = s_.camera_speed / 30.0;
    cam_t_ += dt * speed;
    double zmax = std::max(1, s_.zoom);
    switch (s_.camera) {
        case 0: zoom_ = 1; rot_ = 0; break;
        case 1: zoom_ = std::min(1.5, zmax); rot_ = 0; break;
        case 2: zoom_ = 1 + (zmax - 1) * (0.5 - 0.5 * std::cos(cam_t_ * 0.5)); rot_ = 0; break;
        default:
            zoom_ = 1 + (zmax - 1) * (0.5 - 0.5 * std::cos(cam_t_ * 0.37));
            rot_ = 0.7 * std::sin(cam_t_ * 0.13);
            break;
    }
    if (s_.view <= 1) {
        if (s_.camera == 0) {
            cam_x_ = cam_y_ = 0.5;
        } else {
            double heading = s_.camera == 3 ? rot_ : cam_t_ * 0.11;
            double v = 0.012 * speed / zoom_;
            cam_x_ += -std::sin(heading) * v * dt * (9.0 / 16.0);
            cam_y_ += std::cos(heading) * v * dt;
            if (s_.wrap) {
                cam_x_ = wrap01(cam_x_);
                cam_y_ = wrap01(cam_y_);
            } else {
                double hx = 0.5 / zoom_, hy = 0.5 / zoom_;
                cam_x_ = std::max(hx, std::min(1 - hx, cam_x_));
                cam_y_ = std::max(hy, std::min(1 - hy, cam_y_));
            }
        }
    } else if (s_.view == 2) {
        if (s_.camera == 0) rot_ = 0;
        else if (s_.camera == 1) rot_ = 0.4 * std::sin(cam_t_ * 0.05);
        cam_x_ = wrap01(cam_x_ - std::sin(rot_) * 0.03 * speed * dt * (9.0 / 16.0));
        cam_y_ = wrap01(cam_y_ + std::cos(rot_) * 0.03 * speed * dt);
    } else if (s_.view == 3) {
        cam_y_ = wrap01(cam_y_ + 0.06 * speed * dt);
        cam_x_ = wrap01(cam_x_ + (s_.camera == 0 ? 0.0 : 0.01 * speed * dt));
    } else {
        cam_x_ = wrap01(cam_x_ + 0.012 * speed * dt);
        cam_y_ = 0;
    }
}

void App::render(double now, int fb_w, int fb_h) {
    if (!ready_) return;
    glu::SavedState saved;
    double dt = last_now_ < 0 ? 0.016 : std::min(0.25, std::max(0.0, now - last_now_));
    last_now_ = now;
    ema_dt_ += 0.1 * (dt - ema_dt_);
    update_camera(dt);

    // Restarts: on a timer, or when the board has died out or settled.
    int minutes = RESTART_MINUTES[std::max(0, std::min(RESTART_COUNT - 1, s_.restart_every))];
    if (minutes > 0 && now - last_restart_ > minutes * 60.0) restart(now);
    if (s_.auto_restart && now >= next_check_) {
        next_check_ = now + 2.0;
        Measure m = measure();
        dead_checks_ = m.any_alive ? 0 : dead_checks_ + 1;
        if (generation_ - gens_at_check_ >= 12) {       // only compare boards some generations apart
            bool seen = std::find(history_.begin(), history_.end(), m.checksum) != history_.end();
            stagnant_checks_ = seen ? stagnant_checks_ + 1 : 0;
            history_.push_back(m.checksum);
            if (history_.size() > 6) history_.erase(history_.begin());
            gens_at_check_ = generation_;
        }
        if (dead_checks_ >= 2 || stagnant_checks_ >= 3) restart(now);
    }

    // Generations due. Maximum mode does as many per frame as keeps the display smooth; a fixed
    // speed is capped the same way, so a device that cannot keep up slows down instead of stalling.
    if (now >= next_governor_) {
        next_governor_ = now + 0.5;
        if (ema_dt_ > 0.045 && max_steps_ > 1) max_steps_ = std::max(1, max_steps_ / 2);
        else if (ema_dt_ < 0.019 && max_steps_ < steps_limit_) max_steps_ = std::min(steps_limit_, max_steps_ + 1 + max_steps_ / 4);
    }
    int gps = SPEED_GPS[std::max(0, std::min(SPEED_COUNT - 1, s_.speed))];
    int steps;
    if (gps < 0) {
        steps = max_steps_;
    } else {
        acc_ = std::min(acc_ + dt * gps, 8.0);
        steps = std::min((int)acc_, max_steps_);
        acc_ -= steps;
    }
    step_saved(steps);

    // Viewport: 16:9 letterboxed into the framebuffer.
    int vw = fb_w, vh = fb_w * 9 / 16;
    if (vh > fb_h) { vh = fb_h; vw = fb_h * 16 / 9; }
    int bar_x = saved.viewport[0] + (fb_w - vw) / 2, bar_y = saved.viewport[1] + (fb_h - vh) / 2;

    // The scene is drawn into a target no larger than twice the grid (and no larger than the
    // chosen cap), then scaled up. At the default grid that is 1280 x 720 whatever the output.
    int cap_w = vw, cap_h = vh;
    if (draw_pref_ != 5) {
        int lw = 1920, lh = 1080;
        if (draw_pref_ == 2) { lw = 1280; lh = 720; }
        else if (draw_pref_ == 3) { lw = 960; lh = 540; }
        else if (draw_pref_ == 4) { lw = 640; lh = 360; }
        else if (draw_pref_ == 0) { lw = draw_cap_w; lh = draw_cap_h; }
        if (draw_pref_ == 0) {                   // automatic: never more than twice the grid, and
            lw = std::min(lw, cols_ * 2);        // there is nothing to see beyond one sample per cell
            lh = std::min(lh, rows_ * 2);
        }
        cap_w = std::min(vw, lw);
        cap_h = std::min(vh, lh);
    }
    double scale = std::min(1.0, std::min((double)cap_w / vw, (double)cap_h / vh));
    int dw = std::max(1, (int)std::lround(vw * scale)), dh = std::max(1, (int)std::lround(vh * scale));
    bool scaled = dw < vw || dh < vh;
    bool use_target = scaled || s_.screen_fx != 0;
    if (use_target && (!draw_.tex || draw_.w != dw || draw_.h != dh)) {
        if (draw_.fbo) glDeleteFramebuffers(1, &draw_.fbo);
        if (draw_.tex) glDeleteTextures(1, &draw_.tex);
        draw_ = Target();
        if (!make_target(&draw_, dw, dh, true)) use_target = false;   // no target: draw direct
    }
    draw_scaled_ = use_target;

    if (use_target) {
        glBindFramebuffer(GL_FRAMEBUFFER, draw_.fbo);
        glViewport(0, 0, dw, dh);
    } else {
        glBindFramebuffer(GL_FRAMEBUFFER, (unsigned)saved.fbo);
        glViewport(saved.viewport[0], saved.viewport[1], fb_w, fb_h);
        glClearColor(0, 0, 0, 1);
        glClear(GL_COLOR_BUFFER_BIT);
        glViewport(bar_x, bar_y, vw, vh);
    }

    float phase = (float)std::fmod(now * s_.cycle / 100.0 * 0.5, 1.0);
    int draw_w = use_target ? dw : vw;
    glUseProgram(prog_draw_);
    glActiveTexture(GL_TEXTURE0);
    glBindTexture(GL_TEXTURE_2D, state_[cur_].tex);
    glActiveTexture(GL_TEXTURE1);
    glBindTexture(GL_TEXTURE_2D, pal_tex_);
    glActiveTexture(GL_TEXTURE0);
    glUniform1i(du_.state, 0);
    glUniform1i(du_.pal, 1);
    glUniform4f(du_.p0, (float)draw_w / cols_, phase, 1.0f - s_.dim / 100.0f, s_.glow / 100.0f);
    glUniform4f(du_.p1, (float)std::max(1, s_.age_span), (float)std::fmod(now, 3600.0), (float)zoom_,
                (float)rot_);
    glUniform4f(du_.p2, (float)cam_x_, (float)cam_y_, (float)cols_, (float)rows_);
    glUniform4f(du_.p3, 1.0f / cols_, 1.0f / rows_, (float)rule_.states, 0.f);
    glUniform3f(du_.colour, ((s_.colour >> 16) & 255) / 255.f, ((s_.colour >> 8) & 255) / 255.f,
                (s_.colour & 255) / 255.f);
    glUniform3f(du_.bg, ((s_.background >> 16) & 255) / 255.f, ((s_.background >> 8) & 255) / 255.f,
                (s_.background & 255) / 255.f);
    draw_quad();

    if (use_target) {
        glBindFramebuffer(GL_FRAMEBUFFER, (unsigned)saved.fbo);
        glViewport(saved.viewport[0], saved.viewport[1], fb_w, fb_h);
        glClearColor(0, 0, 0, 1);
        glClear(GL_COLOR_BUFFER_BIT);
        glViewport(bar_x, bar_y, vw, vh);
        glUseProgram(prog_present_);
        glActiveTexture(GL_TEXTURE0);
        glBindTexture(GL_TEXTURE_2D, draw_.tex);
        glUniform1i(pu_.tex, 0);
        draw_quad();
    }
}

}  // namespace lite
}  // namespace automata
}  // namespace sandclock
