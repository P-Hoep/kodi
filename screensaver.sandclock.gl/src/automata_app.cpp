#include "automata_app.hpp"

#include <algorithm>
#include <cmath>
#include <cstring>

#include "gl_include.hpp"

namespace sandclock {
namespace automata {

namespace {

#if defined(SANDCLOCK_GLES)
const char* kVersionVertex = "";
const char* kVersionFragment = "";
#elif defined(SANDCLOCK_CORE)
const char* kVersionVertex = "#version 150\n#define attribute in\n#define varying out\n";
const char* kVersionFragment =
    "#version 150\n#define varying in\n#define texture2D texture\nout vec4 sc_fragColor;\n"
    "#define gl_FragColor sc_fragColor\n";
#else
const char* kVersionVertex = "#version 120\n";
const char* kVersionFragment = "#version 120\n";
#endif

const char* kFragmentHeader = R"(
#ifdef GL_ES
#ifdef GL_FRAGMENT_PRECISION_HIGH
precision highp float;
#else
precision mediump float;
#endif
#endif
)";

const char* kVertex = R"(
#ifdef GL_ES
precision highp float;
#endif
attribute vec2 a0;
varying vec2 v_uv;
void main() {
    v_uv = a0 * 0.5 + 0.5;
    gl_Position = vec4(a0, 0.0, 1.0);
}
)";

// One generation. A cell is read at integer cell coordinates, (c + 0.5) / grid, so nothing here
// depends on filtering; the target is exactly grid-sized, so gl_FragCoord is the cell.
const char* kUpdate = R"(
uniform sampler2D u_src;
uniform vec2 u_grid;
uniform float u_birth, u_survive, u_states, u_wrap, u_trail, u_spark, u_seed;

float alive(vec2 p) {
    if (u_wrap > 0.5) p = mod(p + u_grid, u_grid);
    else if (p.x < 0.0 || p.y < 0.0 || p.x >= u_grid.x || p.y >= u_grid.y) return 0.0;
    return texture2D(u_src, (p + 0.5) / u_grid).a;
}
float bit(float mask, float n) { return mod(floor(mask / exp2(n) + 0.001), 2.0); }

void main() {
    vec2 c = floor(gl_FragCoord.xy);
    vec4 s = texture2D(u_src, (c + 0.5) / u_grid);
    float n = alive(c + vec2(-1.0, -1.0)) + alive(c + vec2(0.0, -1.0)) + alive(c + vec2(1.0, -1.0))
            + alive(c + vec2(-1.0, 0.0))                              + alive(c + vec2(1.0, 0.0))
            + alive(c + vec2(-1.0, 1.0))  + alive(c + vec2(0.0, 1.0))  + alive(c + vec2(1.0, 1.0));
    float cur = floor(s.r * 255.0 + 0.5);
    float ns;
    if (cur < 0.5) ns = bit(u_birth, n);
    else if (cur < 1.5) ns = bit(u_survive, n) > 0.5 ? 1.0 : (u_states > 2.5 ? 2.0 : 0.0);
    else ns = (cur + 1.0 < u_states) ? cur + 1.0 : 0.0;

    float age = s.g;
    bool live = ns > 0.5 && ns < 1.5;
    if (live) age = (cur > 0.5 && cur < 1.5) ? min(age + 1.0 / 255.0, 1.0) : 0.0;
    float trail = live ? 1.0 : s.b * u_trail;
    if (trail < 0.02) trail = 0.0;
    if (u_spark > 0.0 && ns < 0.5) {
        float h = fract(sin(dot(c + vec2(u_seed, u_seed * 1.7), vec2(12.9898, 78.233))) * 43758.5453);
        if (h < u_spark) { ns = 1.0; age = 0.0; trail = 1.0; live = true; }
    }
    gl_FragColor = vec4(ns / 255.0, age, trail, live ? 1.0 : 0.0);
}
)";

// The soups, drawn on the GPU (a 4K soup is 8 million cells; no CPU upload of that).
const char* kInit = R"(
uniform vec2 u_grid;
uniform float u_mode, u_density, u_seed;
float hash(vec2 p) { return fract(sin(dot(p + u_seed, vec2(12.9898, 78.233))) * 43758.5453); }
void main() {
    vec2 c = floor(gl_FragCoord.xy);
    float on = 0.0;
    if (u_mode < 0.5) {                                   // soup
        on = step(hash(c), u_density);
    } else if (u_mode < 1.5) {                            // sparse soup
        on = step(hash(c), u_density * 0.15);
    } else if (u_mode < 2.5) {                            // clusters: round blobs of soup
        vec2 blk = floor(c / 64.0);
        vec2 centre = (blk + 0.2 + 0.6 * vec2(hash(blk + 5.1), hash(blk + 9.7))) * 64.0;
        float radius = 8.0 + 20.0 * hash(blk + 3.3);
        on = (hash(blk * 7.3 + 1.0) < 0.55 && length(c - centre) < radius) ? step(hash(c), 0.5) : 0.0;
    } else if (u_mode < 3.5) {                            // kaleidoscope: soup mirrored four ways
        on = step(hash(floor(abs(c + 0.5 - u_grid * 0.5))), u_density);
    } else {                                              // a blob in the middle
        float d = length((c + 0.5 - u_grid * 0.5) / (u_grid.y * 0.5));
        on = d < 0.22 ? step(hash(c), 0.5) : 0.0;
    }
    gl_FragColor = vec4(on / 255.0, 0.0, on, on);
}
)";

// What is on screen.
const char* kDraw = R"(
uniform sampler2D u_state;
uniform sampler2D u_pal;       // 8 x 1: the 7 palette colours and the first again, so it loops
uniform vec2 u_grid;
uniform float u_mode, u_shape, u_cellpx, u_phase, u_agespan, u_dim, u_states;
uniform vec3 u_colour, u_bg;
varying vec2 v_uv;

vec3 pal(float t) { return texture2D(u_pal, vec2((fract(t) * 7.0 + 0.5) / 8.0, 0.5)).rgb; }
vec3 hsv(float h) {
    vec3 k = clamp(abs(fract(vec3(h) + vec3(1.0, 2.0 / 3.0, 1.0 / 3.0)) * 6.0 - 3.0) - 1.0, 0.0, 1.0);
    return mix(vec3(1.0), k, 0.75);
}

void main() {
    vec2 g = v_uv * u_grid;
    vec2 c = floor(g);
    vec4 s = texture2D(u_state, (c + 0.5) / u_grid);
    float cur = floor(s.r * 255.0 + 0.5);
    float fade = 0.0;
    if (u_states > 2.5 && cur > 1.5) fade = 1.0 - (cur - 1.0) / (u_states - 1.0);   // dying states fade out
    float inten = max(s.a, max(fade * 0.85, s.b * 0.7));
    if (inten < 0.004) { gl_FragColor = vec4(u_bg, 1.0); return; }

    float age = s.g * 255.0 / u_agespan;
    vec3 col;
    if (u_mode < 0.5) col = pal(age + u_phase);
    else if (u_mode < 1.5) col = pal(v_uv.x * 0.7 + v_uv.y * 0.5 + u_phase);
    else if (u_mode < 2.5) col = pal(u_phase);
    else if (u_mode < 3.5) col = u_colour;
    else col = hsv(age * 0.5 + v_uv.x * 0.3 + u_phase);

    float mask = 1.0;
    if (u_cellpx >= 4.0) {
        vec2 f = abs(fract(g) - 0.5);
        float px = 1.0 / u_cellpx;
        float r = u_shape < 0.5 ? 0.0 : (u_shape < 1.5 ? 0.25 : 0.5);
        float half_size = 0.5 - px * (u_shape < 0.5 ? 0.5 : 0.25);
        vec2 q = f - vec2(half_size - r);
        float d = length(max(q, vec2(0.0))) + min(max(q.x, q.y), 0.0) - r;
        mask = 1.0 - smoothstep(0.0, px, d);
    }
    gl_FragColor = vec4(mix(u_bg, col * u_dim, inten * mask), 1.0);
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

unsigned compile(unsigned type, const char* body, std::string* error) {
    const char* src[3] = {type == GL_VERTEX_SHADER ? kVersionVertex : kVersionFragment,
                          type == GL_VERTEX_SHADER ? "" : kFragmentHeader, body};
    unsigned sh = glCreateShader(type);
    glShaderSource(sh, 3, src, nullptr);
    glCompileShader(sh);
    int ok = 0;
    glGetShaderiv(sh, GL_COMPILE_STATUS, &ok);
    if (!ok) {
        char log[2048];
        glGetShaderInfoLog(sh, sizeof log, nullptr, log);
        *error = std::string(type == GL_VERTEX_SHADER ? "vertex: " : "fragment: ") + log;
        glDeleteShader(sh);
        return 0;
    }
    return sh;
}

unsigned link(const char* fragment, std::string* error) {
    unsigned vs = compile(GL_VERTEX_SHADER, kVertex, error);
    if (!vs) return 0;
    unsigned fs = compile(GL_FRAGMENT_SHADER, fragment, error);
    if (!fs) return 0;
    unsigned prog = glCreateProgram();
    glAttachShader(prog, vs);
    glAttachShader(prog, fs);
    glBindAttribLocation(prog, 0, "a0");
    glLinkProgram(prog);
    int ok = 0;
    glGetProgramiv(prog, GL_LINK_STATUS, &ok);
    glDeleteShader(vs);
    glDeleteShader(fs);
    if (!ok) {
        char log[2048];
        glGetProgramInfoLog(prog, sizeof log, nullptr, log);
        *error = std::string("link: ") + log;
        glDeleteProgram(prog);
        return 0;
    }
    return prog;
}

// Saves what Kodi (or the harness) had bound, and puts it back.
struct SavedState {
    int fbo = 0, viewport[4] = {0, 0, 0, 0}, active_texture = 0, program = 0, array_buffer = 0;
    bool blend, depth, cull, scissor;
    SavedState() {
        glGetIntegerv(GL_FRAMEBUFFER_BINDING, &fbo);
        glGetIntegerv(GL_VIEWPORT, viewport);
        glGetIntegerv(GL_ACTIVE_TEXTURE, &active_texture);
        glGetIntegerv(GL_CURRENT_PROGRAM, &program);
        glGetIntegerv(GL_ARRAY_BUFFER_BINDING, &array_buffer);
        blend = glIsEnabled(GL_BLEND); depth = glIsEnabled(GL_DEPTH_TEST);
        cull = glIsEnabled(GL_CULL_FACE); scissor = glIsEnabled(GL_SCISSOR_TEST);
        glDisable(GL_BLEND); glDisable(GL_DEPTH_TEST); glDisable(GL_CULL_FACE); glDisable(GL_SCISSOR_TEST);
    }
    ~SavedState() {
        glBindFramebuffer(GL_FRAMEBUFFER, (unsigned)fbo);
        glViewport(viewport[0], viewport[1], viewport[2], viewport[3]);
        glActiveTexture(GL_TEXTURE1);
        glBindTexture(GL_TEXTURE_2D, 0);
        glActiveTexture((unsigned)active_texture);
        glBindTexture(GL_TEXTURE_2D, 0);
        glUseProgram((unsigned)program);
        glBindBuffer(GL_ARRAY_BUFFER, (unsigned)array_buffer);
        if (blend) glEnable(GL_BLEND);
        if (depth) glEnable(GL_DEPTH_TEST);
        if (cull) glEnable(GL_CULL_FACE);
        if (scissor) glEnable(GL_SCISSOR_TEST);
    }
};

}  // namespace

App::~App() { release(); }

int App::u(unsigned prog, const char* name) const { return glGetUniformLocation(prog, name); }

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

bool App::init(const Settings& settings, unsigned seed, std::string* error) {
    release();
    SavedState saved;
    s_ = settings;
    rule_ = rule_for(s_);
    rng_.seed(seed);

    int max_tex = 2048;
    glGetIntegerv(GL_MAX_TEXTURE_SIZE, &max_tex);
    int index = std::max(0, std::min(GRID_COUNT - 1, s_.grid));
    while (index > 0 && GRID_COLS[index] > max_tex) --index;       // the device cannot hold that many columns
    cols_ = GRID_COLS[index];
    rows_ = rows_for_cols(cols_);

    prog_update_ = link(kUpdate, error);
    if (!prog_update_) return false;
    prog_init_ = link(kInit, error);
    if (!prog_init_) return false;
    prog_draw_ = link(kDraw, error);
    if (!prog_draw_) return false;
    prog_reduce_ = link(kReduce, error);
    if (!prog_reduce_) return false;

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
    for (int w = cols_, h = rows_; w > 40;) {
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
    if (pal_tex_) glDeleteTextures(1, &pal_tex_);
    if (vbo_) glDeleteBuffers(1, &vbo_);
#ifdef SANDCLOCK_CORE
    if (vao_) glDeleteVertexArrays(1, &vao_);
#endif
    for (unsigned* p : {&prog_update_, &prog_init_, &prog_draw_, &prog_reduce_})
        if (*p) glDeleteProgram(*p);
    prog_update_ = prog_init_ = prog_draw_ = prog_reduce_ = vbo_ = vao_ = pal_tex_ = 0;
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
    SavedState saved;
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
    SavedState saved;
    Start st = make_start(s_.start, cols_, rows_, rng_);
    glBindFramebuffer(GL_FRAMEBUFFER, state_[cur_].fbo);
    glViewport(0, 0, cols_, rows_);
    if (st.soup_mode >= 0) {
        glUseProgram(prog_init_);
        glUniform2f(u(prog_init_, "u_grid"), (float)cols_, (float)rows_);
        glUniform1f(u(prog_init_, "u_mode"), (float)st.soup_mode);
        glUniform1f(u(prog_init_, "u_density"), s_.density / 100.0f);
        glUniform1f(u(prog_init_, "u_seed"), (float)(rng_() % 1000));
        draw_quad();
    } else {
        glClearColor(0, 0, 0, 0);
        glClear(GL_COLOR_BUFFER_BIT);
    }
    glBindTexture(GL_TEXTURE_2D, state_[cur_].tex);
    glPixelStorei(GL_UNPACK_ALIGNMENT, 1);
    for (const Stamp& sp : st.stamps) {                  // clears the stamp's box, then draws the pattern in it
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
    next_check_ = now + 3.0;
    dead_checks_ = stagnant_checks_ = 0;
    history_.clear();
    gens_at_check_ = generation_;
}

void App::step(int n) {
    if (n <= 0) return;
    SavedState saved;
    glUseProgram(prog_update_);
    glViewport(0, 0, cols_, rows_);
    glUniform1i(u(prog_update_, "u_src"), 0);
    glUniform2f(u(prog_update_, "u_grid"), (float)cols_, (float)rows_);
    glUniform1f(u(prog_update_, "u_birth"), (float)rule_.birth);
    glUniform1f(u(prog_update_, "u_survive"), (float)rule_.survive);
    glUniform1f(u(prog_update_, "u_states"), (float)rule_.states);
    glUniform1f(u(prog_update_, "u_wrap"), s_.wrap ? 1.f : 0.f);
    glUniform1f(u(prog_update_, "u_trail"), s_.trail / 100.0f);
    glUniform1f(u(prog_update_, "u_spark"), s_.sparks * 1e-6f);
    int seed_loc = u(prog_update_, "u_seed");
    glActiveTexture(GL_TEXTURE0);
    for (int i = 0; i < n; ++i) {
        glUniform1f(seed_loc, (float)(rng_() % 1000));
        glBindFramebuffer(GL_FRAMEBUFFER, state_[1 - cur_].fbo);
        glBindTexture(GL_TEXTURE_2D, state_[cur_].tex);
        draw_quad();
        cur_ = 1 - cur_;
        ++generation_;
    }
}

void App::read_state(std::vector<uint8_t>* states) {
    SavedState saved;
    std::vector<uint8_t> rgba((size_t)cols_ * rows_ * 4);
    glBindFramebuffer(GL_FRAMEBUFFER, state_[cur_].fbo);
    glPixelStorei(GL_PACK_ALIGNMENT, 1);
    glReadPixels(0, 0, cols_, rows_, GL_RGBA, GL_UNSIGNED_BYTE, rgba.data());
    states->resize((size_t)cols_ * rows_);
    for (size_t i = 0; i < states->size(); ++i) (*states)[i] = rgba[i * 4];
}

App::Measure App::measure() {
    SavedState saved;
    glUseProgram(prog_reduce_);
    glUniform1i(u(prog_reduce_, "u_src"), 0);
    glActiveTexture(GL_TEXTURE0);
    const Target* src = &state_[cur_];
    for (size_t i = 0; i < chain_.size(); ++i) {
        glBindFramebuffer(GL_FRAMEBUFFER, chain_[i].fbo);
        glViewport(0, 0, chain_[i].w, chain_[i].h);
        glBindTexture(GL_TEXTURE_2D, src->tex);
        glUniform2f(u(prog_reduce_, "u_srcsize"), (float)src->w, (float)src->h);
        glUniform1f(u(prog_reduce_, "u_first"), i == 0 ? 1.f : 0.f);
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

void App::render(double now, int fb_w, int fb_h) {
    if (!ready_) return;
    double dt = last_now_ < 0 ? 0.016 : std::min(0.25, std::max(0.0, now - last_now_));
    last_now_ = now;
    ema_dt_ += 0.1 * (dt - ema_dt_);

    // Restarts: on a timer, or when the board has died out or settled.
    int minutes = RESTART_MINUTES[std::max(0, std::min(RESTART_COUNT - 1, s_.restart_every))];
    if (minutes > 0 && now - last_restart_ > minutes * 60.0) restart(now);
    if (s_.auto_restart && now >= next_check_) {
        next_check_ = now + 1.5;
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
    step(steps);

    // Draw.
    SavedState saved;
    glBindFramebuffer(GL_FRAMEBUFFER, (unsigned)saved.fbo);
    int vw = fb_w, vh = fb_w * 9 / 16;
    if (vh > fb_h) { vh = fb_h; vw = fb_h * 16 / 9; }
    glViewport(saved.viewport[0], saved.viewport[1], fb_w, fb_h);
    glClearColor(0, 0, 0, 1);
    glClear(GL_COLOR_BUFFER_BIT);
    glViewport(saved.viewport[0] + (fb_w - vw) / 2, saved.viewport[1] + (fb_h - vh) / 2, vw, vh);

    glUseProgram(prog_draw_);
    glActiveTexture(GL_TEXTURE0);
    glBindTexture(GL_TEXTURE_2D, state_[cur_].tex);
    glActiveTexture(GL_TEXTURE1);
    glBindTexture(GL_TEXTURE_2D, pal_tex_);
    glActiveTexture(GL_TEXTURE0);
    glUniform1i(u(prog_draw_, "u_state"), 0);
    glUniform1i(u(prog_draw_, "u_pal"), 1);
    glUniform2f(u(prog_draw_, "u_grid"), (float)cols_, (float)rows_);
    glUniform1f(u(prog_draw_, "u_mode"), (float)s_.colour_mode);
    glUniform1f(u(prog_draw_, "u_shape"), (float)s_.shape);
    glUniform1f(u(prog_draw_, "u_cellpx"), (float)vw / cols_);
    glUniform1f(u(prog_draw_, "u_phase"), (float)std::fmod(now * s_.cycle / 100.0 * 0.5, 1.0));
    glUniform1f(u(prog_draw_, "u_agespan"), (float)std::max(1, s_.age_span));
    glUniform1f(u(prog_draw_, "u_dim"), 1.0f - s_.dim / 100.0f);
    glUniform1f(u(prog_draw_, "u_states"), (float)rule_.states);
    glUniform3f(u(prog_draw_, "u_colour"), ((s_.colour >> 16) & 255) / 255.f, ((s_.colour >> 8) & 255) / 255.f, (s_.colour & 255) / 255.f);
    glUniform3f(u(prog_draw_, "u_bg"), ((s_.background >> 16) & 255) / 255.f, ((s_.background >> 8) & 255) / 255.f, (s_.background & 255) / 255.f);
    draw_quad();
}

}  // namespace automata
}  // namespace sandclock
