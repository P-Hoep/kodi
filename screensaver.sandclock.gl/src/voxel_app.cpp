// Cellular Automata 3D: see voxel_app.hpp. One fragment shader per generation over the padded
// atlas (26 neighbour reads, a 32-entry birth/survive lookup), one ray-marched draw pass at no
// more than the chosen resolution, one scale-up. The rule lives in a texture so it can change
// without recompiling; everything else that is constant for a run is compiled in.
#include "voxel_app.hpp"

#include <algorithm>
#include <cmath>

#include "automata_tables.hpp"
#include "gl_util.hpp"

namespace sandclock {
namespace voxel {

namespace {

int clamp_int(int v, int lo, int hi) { return v < lo ? lo : (v > hi ? hi : v); }
std::string f1(int v) { return std::to_string(v) + ".0"; }

// Halves the atlas (presence in r, density in g), for the dead/settled check.
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

}  // namespace

int App::draw_cap_w = 640, App::draw_cap_h = 360;

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

// One generation over the whole padded atlas. Interior texels count their 26 neighbours at fixed
// offsets; border texels recompute the wrapped opposite face, so the borders stay in step and no
// neighbour read needs any wrap arithmetic. Without wrapping the borders (and anything outside)
// are written dead. The birth/survive pair comes from a 32 x 1 texture at x = neighbour count, so
// the rule can be switched without recompiling.
std::string App::update_source(const Settings& s, const Atlas& a) {
    std::string d;
    d += "#define GRID_N " + f1(a.n) + "\n";
    d += "#define GRID_P " + f1(a.p) + "\n";
    d += "#define INV_W (1.0 / " + f1(a.w) + ")\n";
    d += "#define INV_H (1.0 / " + f1(a.h) + ")\n";
    d += "#define WRAP " + std::to_string(s.wrap ? 1 : 0) + "\n";
    d += "#define SPARKS " + std::to_string(s.sparks > 0 ? 1 : 0) + "\n";
    d += R"(
uniform sampler2D u_src;
uniform sampler2D u_rule;
uniform float u_seed;
uniform float u_sparks;

vec2 at(float x, float y, float z) {
    float row = floor(z * 0.125);                  // the atlas is 8 slices wide
    float col = z - row * 8.0;
    return vec2((col * GRID_P + x + 0.5) * INV_W, (row * GRID_P + y + 0.5) * INV_H);
}
float alive(float x, float y, float z) { return texture2D(u_src, at(x, y, z)).a; }

void main() {
    float ix = floor(gl_FragCoord.x);
    float iy = floor(gl_FragCoord.y);
    float col = floor(ix / GRID_P);
    float row = floor(iy / GRID_P);
    vec3 pc = vec3(ix - col * GRID_P, iy - row * GRID_P, row * 8.0 + col);
    vec3 lc = pc - 1.0;                            // the cell this texel stands for
#if WRAP
    lc = mod(lc, vec3(GRID_N));
    pc = lc + 1.0;
#else
    if (lc.x < 0.0 || lc.y < 0.0 || lc.z < 0.0 ||
        lc.x > GRID_N - 1.0 || lc.y > GRID_N - 1.0 || lc.z > GRID_N - 1.0) {
        gl_FragColor = vec4(0.0);
        return;
    }
#endif
    vec4 s = texture2D(u_src, at(pc.x, pc.y, pc.z));
    float nb = 0.0;
    for (int dz = -1; dz <= 1; ++dz)
        for (int dy = -1; dy <= 1; ++dy)
            for (int dx = -1; dx <= 1; ++dx) {
                if (dx == 0 && dy == 0 && dz == 0) continue;
                nb += alive(pc.x + float(dx), pc.y + float(dy), pc.z + float(dz));
            }
    float n = floor(nb + 0.5);
    vec2 rule = texture2D(u_rule, vec2((n + 0.5) / 32.0, 0.5)).rg;
    float was = s.a > 0.5 ? 1.0 : 0.0;
    float ns = was > 0.5 ? step(0.5, rule.g) : step(0.5, rule.r);
    float age = s.g;
    if (ns > 0.5) age = was > 0.5 ? min(age + 0.00392157, 1.0) : 0.0;
#if SPARKS
    if (u_sparks > 0.0 && ns < 0.5) {
        float h = fract(sin(dot(pc + vec3(u_seed, u_seed * 1.7, u_seed * 0.37),
                                vec3(12.9898, 78.233, 37.719))) * 43758.5453);
        if (h < u_sparks) { ns = 1.0; age = 0.0; }
    }
#endif
    gl_FragColor = vec4(ns, age, n / 26.0, ns);
}
)";
    return d;
}

// The 3D view: a ray through a cube of voxels, one sample every 0.75 cells, stopping at the first
// live one. Its entry face gives a normal, and the depth gives fog. Colours are the same modes as
// the 2D add-ons, with the voxel's age and neighbour count read from the state texture. With
// INFINITE the cube is the repeating unit of a toroidal world: the ray starts where the camera is,
// every sample is wrapped into the cube, and there is no box to enter or leave -- the fog is what
// ends it. The camera modes "Inside" put the eye in the middle of the volume, so this is a view
// from within the automaton instead of around it.
std::string App::draw_source(const Settings& s, const Atlas& a) {
    int mode = clamp_int(s.colour_mode, 0, VOXEL_MODE_COUNT - 1);
    int bg = clamp_int(s.background_style, 0, 2);
    bool infinite = s.infinite && s.wrap;
    double step = 0.75 / a.n;
    int max_steps = (int)std::ceil(1.7320508 / step) + 2;
    std::string d;
    d += "#define GRID_N " + f1(a.n) + "\n";
    d += "#define GRID_P " + f1(a.p) + "\n";
    d += "#define INV_W (1.0 / " + f1(a.w) + ")\n";
    d += "#define INV_H (1.0 / " + f1(a.h) + ")\n";
    d += "#define STEP (0.75 / GRID_N)\n";
    d += "#define MAX_STEPS " + std::to_string(max_steps) + "\n";
    d += "#define COLOUR_MODE " + std::to_string(mode) + "\n";
    d += "#define BGSTYLE " + std::to_string(bg) + "\n";
    d += "#define GLOW_ON " + std::to_string(s.glow > 0 ? 1 : 0) + "\n";
    d += "#define INFINITE " + std::to_string(infinite ? 1 : 0) + "\n";
    d += "#define AGESPAN " + f1(std::max(1, s.age_span)) + "\n";
    d += R"(
uniform sampler2D u_state;
uniform sampler2D u_pal;       // 8 x 1: the 7 palette colours and the first again, so it loops
uniform vec3 u_colour, u_bg;
uniform vec4 u_eye;            // xyz, time
uniform vec4 u_right;          // xyz (screen right, scaled), palette phase
uniform vec4 u_up;             // xyz (screen up, scaled), glow
uniform vec4 u_fwd;            // xyz
varying vec2 v_uv;

#define TIME u_eye.w
#define PHASE u_right.w
#define GLOW u_up.w

vec2 at(float x, float y, float z) {
    float row = floor(z * 0.125);
    float col = z - row * 8.0;
    return vec2((col * GRID_P + x + 0.5) * INV_W, (row * GRID_P + y + 0.5) * INV_H);
}
vec4 voxel(float x, float y, float z) { return texture2D(u_state, at(x, y, z)); }
vec3 pal(float t) { return texture2D(u_pal, vec2((fract(t) * 7.0 + 0.5) / 8.0, 0.5)).rgb; }
vec3 hsv(float h) {
    vec3 k = clamp(abs(fract(vec3(h) + vec3(1.0, 2.0 / 3.0, 1.0 / 3.0)) * 6.0 - 3.0) - 1.0, 0.0, 1.0);
    return mix(vec3(1.0), k, 0.75);
}
float plasma(vec3 q, float t) {
    return 0.5 + 0.25 * sin(q.x * 9.0 + t) + 0.25 * sin(q.y * 7.0 - t * 1.3 + 2.0 * sin(q.z * 5.0 + t * 0.5));
}

vec3 bgcolour(vec2 p) {
#if BGSTYLE == 0
    return u_bg;
#elif BGSTYLE == 1
    return u_bg + pal(PHASE) * 0.2 * clamp(0.6 - p.y, 0.0, 1.0);
#else
    return u_bg + pal(plasma(vec3(p, 0.0), TIME * 0.4) + PHASE) * 0.13;
#endif
}

// w: the cell's place in the cube (0..1 on each axis).
vec3 voxel_colour(vec4 v, vec3 w) {
    float age = v.g * 255.0 / AGESPAN;
#if COLOUR_MODE == 0
    return pal(age + PHASE);
#elif COLOUR_MODE == 1
    return pal(w.x * 0.7 + w.y * 0.5 + w.z * 0.3 + PHASE);
#elif COLOUR_MODE == 2
    return pal(PHASE);
#elif COLOUR_MODE == 3
    return u_colour;
#elif COLOUR_MODE == 4
    return hsv(age * 0.5 + w.x * 0.3 + w.z * 0.2 + PHASE);
#elif COLOUR_MODE == 5
    float t = clamp(age * 0.6, 0.0, 1.0);
    vec3 c = mix(vec3(1.0, 0.97, 0.85), vec3(1.0, 0.72, 0.12), smoothstep(0.0, 0.3, t));
    return mix(c, vec3(0.85, 0.16, 0.04), smoothstep(0.3, 0.9, t));
#elif COLOUR_MODE == 6
    return pal(v.b + PHASE);
#else
    return pal(plasma(w * 1.5, TIME * 0.5) + PHASE);
#endif
}

void main() {
    vec2 p = (v_uv - 0.5) * vec2(1.7777778, 1.0);   // screen: height 1, centre 0
    vec3 bg = bgcolour(p);
    vec3 ro = u_eye.xyz;
    vec3 rd = normalize(u_fwd.xyz + u_right.xyz * p.x + u_up.xyz * p.y);
    vec3 col = bg;

    float t0, t1;
#if INFINITE
    t0 = 0.0;                                       // the world has no outside; start at the eye
    t1 = STEP * float(MAX_STEPS);
#else
    vec3 inv = 1.0 / rd;
    vec3 b0 = (vec3(-0.5) - ro) * inv;
    vec3 b1 = (vec3(0.5) - ro) * inv;
    vec3 tmn = min(b0, b1), tmx = max(b0, b1);
    t0 = max(max(tmn.x, tmn.y), max(tmn.z, 0.0));   // 0 when the eye is inside the cube
    t1 = min(min(tmx.x, tmx.y), tmx.z);
    if (t1 <= t0) { gl_FragColor = vec4(col, 1.0); return; }
#endif
    for (int i = 0; i < MAX_STEPS; ++i) {
        float t = t0 + (float(i) + 0.5) * STEP;
        if (t > t1) break;
        vec3 q = ro + rd * t;
        vec3 cf = floor((q + 0.5) * GRID_N);
#if INFINITE
        cf = mod(cf, vec3(GRID_N));                 // the torus: every copy is the same cube
#endif
        vec3 c = clamp(cf, vec3(0.0), vec3(GRID_N - 1.0));
        vec4 v = voxel(c.x + 1.0, c.y + 1.0, c.z + 1.0);
        if (v.a > 0.5) {
            // The face the ray entered through: the nearest side of the cell.
            vec3 local = (q + 0.5) * GRID_N - c;
            vec3 e = min(local, 1.0 - local);
            vec3 nrm = vec3(0.0);
            if (e.x <= e.y && e.x <= e.z) nrm.x = local.x < 0.5 ? -1.0 : 1.0;
            else if (e.y <= e.z) nrm.y = local.y < 0.5 ? -1.0 : 1.0;
            else nrm.z = local.z < 0.5 ? -1.0 : 1.0;
            float depth = clamp((t - t0) / max(t1 - t0, 0.001), 0.0, 1.0);
            float light = 0.42 + 0.72 * max(dot(nrm, normalize(vec3(-0.45, 0.75, 0.5))), 0.0);
            light *= 1.0 - 0.35 * depth;
            vec3 lit = voxel_colour(v, (c + 0.5) / GRID_N) * light;
#if GLOW_ON
            vec4 outv = voxel(c.x + 1.0 + nrm.x, c.y + 1.0 + nrm.y, c.z + 1.0 + nrm.z);
            if (outv.a < 0.5) lit += voxel_colour(v, (c + 0.5) / GRID_N) * GLOW * 0.5 * (1.0 - depth);
#endif
            col = mix(lit, bg, depth * 0.55);
            break;
        }
    }
    gl_FragColor = vec4(col, 1.0);
}
)";
    return d;
}

// The scale-up (and screen effect) pass: one texture read a pixel, at output resolution, so the
// vignette and scanlines stay sharp when the 3D view is drawn smaller.
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
    Settings s = resolve_preset(settings);
    Atlas a = atlas_for(grid_for(s));
    if (update) *update = update_source(s, a);
    if (draw) *draw = draw_source(s, a);
    if (present) *present = present_source(s);
}

bool App::init(const Settings& settings, unsigned seed, std::string* error) {
    user_ = settings;
    rotating_ = rotating_presets(user_);
    rotation_.clear();
    rotation_pos_ = 0;
    next_rotate_ = 0;
    Settings first = user_;
    if (rotating_) {
        // A shuffled order, so every preset is seen before any repeats; start on the first of them.
        for (int i = 1; i <= VOXEL_PRESET_COUNT; ++i) rotation_.push_back(i);
        std::mt19937 order(seed ^ 0x9e3779b9u);
        std::shuffle(rotation_.begin(), rotation_.end(), order);
        first.preset = rotation_[0];
        rotation_pos_ = 1;
    }
    return build(resolve_preset(first), seed, error);
}

// Everything GL: shaders, textures, the first generation. init() and the preset rotation call it.
bool App::build(const Settings& settings, unsigned seed, std::string* error) {
    release();
    glu::SavedState saved;
    s_ = settings;
    s_.infinite = s_.infinite && s_.wrap;
    rule_ = rule_for(s_);
    rng_.seed(seed);
    n_ = grid_for(s_);
    atlas_ = atlas_for(n_);
    draw_pref_ = clamp_int(s_.draw, 0, VOXEL_DRAW_COUNT - 1);

    int max_tex = 2048;
    glGetIntegerv(GL_MAX_TEXTURE_SIZE, &max_tex);
    if (atlas_.w > max_tex || atlas_.h > max_tex) {
        *error = "the " + std::to_string(n_) + " cube needs a " + std::to_string(atlas_.w) + "x" +
                 std::to_string(atlas_.h) + " texture, but this device allows " + std::to_string(max_tex);
        return false;
    }

    std::string update_src = update_source(s_, atlas_), draw_src = draw_source(s_, atlas_),
                present_src = present_source(s_);
    prog_update_ = glu::link(nullptr, update_src.c_str(), error);
    if (!prog_update_) return false;
    prog_draw_ = glu::link(nullptr, draw_src.c_str(), error);
    if (!prog_draw_) return false;
    prog_reduce_ = glu::link(nullptr, kReduce, error);
    if (!prog_reduce_) return false;
    prog_present_ = glu::link(nullptr, present_src.c_str(), error);
    if (!prog_present_) return false;

    uu_ = {loc(prog_update_, "u_src"), loc(prog_update_, "u_rule"), loc(prog_update_, "u_seed"),
           loc(prog_update_, "u_sparks")};
    du_ = {loc(prog_draw_, "u_state"), loc(prog_draw_, "u_pal"), loc(prog_draw_, "u_colour"),
           loc(prog_draw_, "u_bg"), loc(prog_draw_, "u_eye"), loc(prog_draw_, "u_right"),
           loc(prog_draw_, "u_up"), loc(prog_draw_, "u_fwd")};
    ru_ = {loc(prog_reduce_, "u_src"), loc(prog_reduce_, "u_srcsize"), loc(prog_reduce_, "u_first")};
    pu_ = {loc(prog_present_, "u_tex")};

    static const float quad[8] = {-1, -1, 1, -1, -1, 1, 1, 1};
    glGenBuffers(1, &vbo_);
    glBindBuffer(GL_ARRAY_BUFFER, vbo_);
    glBufferData(GL_ARRAY_BUFFER, sizeof quad, quad, GL_STATIC_DRAW);
#ifdef SANDCLOCK_CORE
    glGenVertexArrays(1, &vao_);
#endif

    if (!make_target(&state_[0], atlas_.w, atlas_.h, false) ||
        !make_target(&state_[1], atlas_.w, atlas_.h, false)) {
        *error = "cannot make a " + std::to_string(atlas_.w) + "x" + std::to_string(atlas_.h) +
                 " texture to render to";
        return false;
    }
    for (int w = atlas_.w, h = atlas_.h; w > 8 || h > 8;) {
        w = (w + 1) / 2;
        h = (h + 1) / 2;
        Target t;
        if (!make_target(&t, w, h, false)) { *error = "cannot make a reduction target"; return false; }
        chain_.push_back(t);
    }

    glGenTextures(1, &pal_tex_);
    set_palette();
    glGenTextures(1, &rule_tex_);
    upload_rule();

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
    if (rule_tex_) glDeleteTextures(1, &rule_tex_);
    if (vbo_) glDeleteBuffers(1, &vbo_);
#ifdef SANDCLOCK_CORE
    if (vao_) glDeleteVertexArrays(1, &vao_);
#endif
    for (unsigned* p : {&prog_update_, &prog_draw_, &prog_reduce_, &prog_present_})
        if (*p) glDeleteProgram(*p);
    prog_update_ = prog_draw_ = prog_reduce_ = prog_present_ = 0;
    vbo_ = vao_ = pal_tex_ = rule_tex_ = 0;
    cur_ = 0;
    draw_scaled_ = false;
    ready_ = false;
}

void App::set_palette() {
    const uint32_t* p = automata::PALETTE[std::max(0, std::min(automata::PALETTE_COUNT - 1, s_.palette))];
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

// A 32 x 1 RGBA texture: red = born, green = survives. NEAREST, so a count picks exactly one texel.
void App::upload_rule() {
    unsigned char px[32 * 4] = {0};
    for (int n = 0; n <= 26; ++n) {
        px[n * 4] = ((rule_.birth >> n) & 1u) ? 255 : 0;
        px[n * 4 + 1] = ((rule_.survive >> n) & 1u) ? 255 : 0;
        px[n * 4 + 3] = 255;
    }
    glActiveTexture(GL_TEXTURE1);
    glBindTexture(GL_TEXTURE_2D, rule_tex_);
    glPixelStorei(GL_UNPACK_ALIGNMENT, 1);
    glTexImage2D(GL_TEXTURE_2D, 0, GL_RGBA, 32, 1, 0, GL_RGBA, GL_UNSIGNED_BYTE, px);
    glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_MIN_FILTER, GL_NEAREST);
    glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_MAG_FILTER, GL_NEAREST);
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
    std::vector<uint8_t> rgba;
    build_atlas(atlas_, states, s_.wrap, &rgba);
    glBindTexture(GL_TEXTURE_2D, state_[cur_].tex);
    glPixelStorei(GL_UNPACK_ALIGNMENT, 1);
    glTexSubImage2D(GL_TEXTURE_2D, 0, 0, 0, atlas_.w, atlas_.h, GL_RGBA, GL_UNSIGNED_BYTE, rgba.data());
}

void App::reseed(double now) { restart(now); }

// The presets rotate in a shuffled order. A switch rebuilds everything the preset changes -- the
// shaders are compiled again for its cube, rule, colours and camera -- and the simulation starts
// from that preset's starting pattern, which is the point of the change. The user's speed, draw
// resolution and restart timers survive, because a preset must not cost a weak device its frame
// rate.
void App::rotate_if_due(double now) {
    if (!rotating_ || rotation_.empty()) return;
    double interval = VOXEL_ROTATE_SECONDS[clamp_int(user_.rotate_time, 0, VOXEL_ROTATE_COUNT - 1)];
    if (next_rotate_ <= 0.0) {
        next_rotate_ = now + interval;
        return;
    }
    if (now < next_rotate_) return;
    next_rotate_ = now + interval;
    if (rotation_pos_ >= rotation_.size()) {          // all seen: shuffle again, no immediate repeat
        int last = rotation_[rotation_pos_ - 1];
        std::mt19937 order(rng_());
        std::shuffle(rotation_.begin(), rotation_.end(), order);
        if (rotation_.size() > 1 && rotation_[0] == last) std::swap(rotation_[0], rotation_[1]);
        rotation_pos_ = 0;
    }
    Settings prev = s_;
    Settings next = user_;
    next.preset = rotation_[rotation_pos_++];
    cam_t_ = 0;
    std::string error;
    if (!build(resolve_preset(next), rng_(), &error) && !build(prev, rng_(), &error)) ready_ = false;
    last_restart_ = now;                        // build() seeded the volume at time zero
    next_check_ = now + 4.0;
    last_now_ = now;
}

void App::restart(double now) {
    glu::SavedState saved;
    std::vector<uint8_t> state, rgba;
    make_start(s_.start, n_, s_.density, rng_, &state);
    build_atlas(atlas_, state, s_.wrap, &rgba);
    glBindTexture(GL_TEXTURE_2D, state_[cur_].tex);
    glPixelStorei(GL_UNPACK_ALIGNMENT, 1);
    glTexSubImage2D(GL_TEXTURE_2D, 0, 0, 0, atlas_.w, atlas_.h, GL_RGBA, GL_UNSIGNED_BYTE, rgba.data());
    last_restart_ = now;
    next_check_ = now + 4.0;
    dead_checks_ = stagnant_checks_ = 0;
    history_.clear();
    gens_at_check_ = generation_;
}

void App::step_saved(int n) {
    if (n <= 0) return;
    glUseProgram(prog_update_);
    glViewport(0, 0, atlas_.w, atlas_.h);
    glUniform1i(uu_.src, 0);
    glUniform1i(uu_.rule, 1);
    glUniform1f(uu_.seed, 0.0f);
    glUniform1f(uu_.sparks, s_.sparks * 1e-6f);
    glActiveTexture(GL_TEXTURE0);
    for (int i = 0; i < n; ++i) {
        if (s_.sparks > 0) glUniform1f(uu_.seed, (float)(rng_() % 1000));
        glBindFramebuffer(GL_FRAMEBUFFER, state_[1 - cur_].fbo);
        glBindTexture(GL_TEXTURE_2D, state_[cur_].tex);
        glActiveTexture(GL_TEXTURE1);
        glBindTexture(GL_TEXTURE_2D, rule_tex_);
        glActiveTexture(GL_TEXTURE0);
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
    std::vector<uint8_t> rgba((size_t)atlas_.w * atlas_.h * 4);
    glBindFramebuffer(GL_FRAMEBUFFER, state_[cur_].fbo);
    glPixelStorei(GL_PACK_ALIGNMENT, 1);
    glReadPixels(0, 0, atlas_.w, atlas_.h, GL_RGBA, GL_UNSIGNED_BYTE, rgba.data());
    extract_state(atlas_, rgba, states);
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
        m.checksum = (m.checksum ^ px[i]) * 16777619u;
        m.checksum = (m.checksum ^ px[i + 1]) * 16777619u;
    }
    return m;
}

// The camera: azimuth, elevation and distance from the middle of the cube. Still, orbit, tumble
// (orbit plus a rock) and zoom in and out look at the cube from outside; the two "inside" modes
// put the eye in the volume and look outward, drifting (or tumbling) through the cells.
// "Closeness" scales the distance outside; inside it only affects the shader's fog.
void App::update_camera(double dt) {
    double speed = std::max(5, s_.camera_speed) / 30.0;
    cam_t_ += dt * speed;
    double base = 2.35 - 0.10 * (clamp_int(s_.zoom, 1, 8) - 1);
    switch (clamp_int(s_.camera, 0, VOXEL_CAMERA_COUNT - 1)) {
        case 0:
            yaw_ = 0.7;
            pitch_ = 0.45;
            dist_ = base;
            break;
        case 1:
            yaw_ = 0.7 + cam_t_ * 0.10;
            pitch_ = 0.40 + 0.12 * std::sin(cam_t_ * 0.05);
            dist_ = base;
            break;
        case 2:
            yaw_ = cam_t_ * 0.09;
            pitch_ = 0.28 + 0.55 * std::sin(cam_t_ * 0.055);
            dist_ = base;
            break;
        case 3:
            yaw_ = 0.7 + cam_t_ * 0.07;
            pitch_ = 0.35;
            dist_ = base - 0.5 * (0.5 - 0.5 * std::cos(cam_t_ * 0.3));
            break;
        case 4:                                   // inside, drifting
            yaw_ = 0.7 + cam_t_ * 0.05;
            pitch_ = 0.12 * std::sin(cam_t_ * 0.07);
            dist_ = base;
            break;
        default:                                  // inside, tumbling
            yaw_ = cam_t_ * 0.16;
            pitch_ = 0.55 * std::sin(cam_t_ * 0.11);
            dist_ = base;
            break;
    }
}

void App::render(double now, int fb_w, int fb_h) {
    if (!ready_) return;
    rotate_if_due(now);                          // rebuilds for the next preset, if it is due
    if (!ready_) return;
    glu::SavedState saved;
    double dt = last_now_ < 0 ? 0.016 : std::min(0.25, std::max(0.0, now - last_now_));
    last_now_ = now;
    ema_dt_ += 0.1 * (dt - ema_dt_);
    update_camera(dt);

    // Restarts: on a timer, or when the volume has died out or settled.
    int minutes = automata::RESTART_MINUTES[std::max(
        0, std::min(automata::RESTART_COUNT - 1, s_.restart_every))];
    if (minutes > 0 && now - last_restart_ > minutes * 60.0) restart(now);
    if (s_.auto_restart && now >= next_check_) {
        next_check_ = now + 2.0;
        Measure m = measure();
        dead_checks_ = m.any_alive ? 0 : dead_checks_ + 1;
        if (generation_ - gens_at_check_ >= 12) {
            bool seen = std::find(history_.begin(), history_.end(), m.checksum) != history_.end();
            stagnant_checks_ = seen ? stagnant_checks_ + 1 : 0;
            history_.push_back(m.checksum);
            if (history_.size() > 6) history_.erase(history_.begin());
            gens_at_check_ = generation_;
        }
        if (dead_checks_ >= 2 || stagnant_checks_ >= 3) restart(now);
    }

    // Generations due. A fixed speed is capped by the governor, so a device that cannot keep up
    // slows the simulation down instead of stalling the screensaver.
    if (now >= next_governor_) {
        next_governor_ = now + 0.5;
        if (ema_dt_ > 0.045 && max_steps_ > 1) max_steps_ = std::max(1, max_steps_ / 2);
        else if (ema_dt_ < 0.019 && max_steps_ < steps_limit_)
            max_steps_ = std::min(steps_limit_, max_steps_ + 1 + max_steps_ / 4);
    }
    int gps = automata::SPEED_GPS[std::max(0, std::min(automata::SPEED_COUNT - 1, s_.speed))];
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

    // The 3D view goes into a target at the chosen cap, then one pass scales it up. Every pixel of
    // the raymarch costs about a voxel's worth of texture reads, so this is the main speed dial.
    int cap_w = vw, cap_h = vh;
    if (draw_pref_ != 6) {
        int lw = draw_cap_w, lh = draw_cap_h;
        if (draw_pref_ == 1) { lw = 1920; lh = 1080; }
        else if (draw_pref_ == 2) { lw = 1280; lh = 720; }
        else if (draw_pref_ == 3) { lw = 960; lh = 540; }
        else if (draw_pref_ == 4) { lw = 640; lh = 360; }
        else if (draw_pref_ == 5) { lw = 480; lh = 270; }
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
        if (!make_target(&draw_, dw, dh, true)) use_target = false;
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

    // Camera vectors. Outside, the eye sits on a sphere around the cube and looks at its middle;
    // inside, the eye is in the volume and looks out, drifting slowly so the view has parallax.
    // The cube is the unit box, so its corner is sqrt(3)/2 from the centre. The screen-space p
    // below runs to +/-0.5 vertically, so both axes are scaled by 2*tan(25 deg).
    bool inside = clamp_int(s_.camera, 0, VOXEL_CAMERA_COUNT - 1) >= 4;
    double cp = std::cos(pitch_), sp = std::sin(pitch_);
    double ux = cp * std::sin(yaw_), uy = sp, uz = cp * std::cos(yaw_);
    double ex, ey, ez, fx, fy, fz;
    if (inside) {
        ex = 0.10 * std::sin(cam_t_ * 0.13);
        ey = 0.08 * std::sin(cam_t_ * 0.09 + 1.7);
        ez = 0.10 * std::sin(cam_t_ * 0.11 + 3.1);
        fx = ux; fy = uy; fz = uz;                              // forward, looking out
    } else {
        ex = dist_ * ux; ey = dist_ * uy; ez = dist_ * uz;
        fx = -ux; fy = -uy; fz = -uz;                           // forward = -eye direction
    }
    double rx = -fz, ry = 0.0, rz = fx;
    double rl = std::sqrt(rx * rx + ry * ry + rz * rz);
    rx /= rl; ry /= rl; rz /= rl;
    double upx = ry * fz - rz * fy, upy = rz * fx - rx * fz, upz = rx * fy - ry * fx;
    // A wider lens inside: the cells around the eye are close, and a 76-degree field shows more
    // of the world instead of a few wall-sized blocks.
    const double PI = 3.14159265358979323846;
    const double TH = 2.0 * std::tan((inside ? 38.0 : 25.0) * PI / 180.0);
    float phase = (float)std::fmod(now * s_.cycle / 100.0 * 0.5, 1.0);

    glUseProgram(prog_draw_);
    glActiveTexture(GL_TEXTURE0);
    glBindTexture(GL_TEXTURE_2D, state_[cur_].tex);
    glActiveTexture(GL_TEXTURE1);
    glBindTexture(GL_TEXTURE_2D, pal_tex_);
    glActiveTexture(GL_TEXTURE0);
    glUniform1i(du_.state, 0);
    glUniform1i(du_.pal, 1);
    glUniform3f(du_.colour, ((s_.colour >> 16) & 255) / 255.f, ((s_.colour >> 8) & 255) / 255.f,
                (s_.colour & 255) / 255.f);
    glUniform3f(du_.bg, ((s_.background >> 16) & 255) / 255.f,
                ((s_.background >> 8) & 255) / 255.f, (s_.background & 255) / 255.f);
    glUniform4f(du_.eye, (float)ex, (float)ey, (float)ez, (float)std::fmod(now, 3600.0));
    glUniform4f(du_.right, (float)(rx * TH), (float)(ry * TH), (float)(rz * TH), phase);
    glUniform4f(du_.up, (float)(upx * TH), (float)(upy * TH), (float)(upz * TH),
                s_.glow / 100.0f);
    glUniform4f(du_.fwd, (float)fx, (float)fy, (float)fz, 0.f);
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

}  // namespace voxel
}  // namespace sandclock
