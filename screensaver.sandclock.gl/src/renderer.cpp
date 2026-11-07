#include "renderer.hpp"

#include <algorithm>
#include <vector>

#include "gl_include.hpp"

#ifndef GL_PROGRAM_POINT_SIZE
#define GL_PROGRAM_POINT_SIZE 0x8642
#endif
#ifndef GL_POINT_SPRITE
#define GL_POINT_SPRITE 0x8861
#endif

namespace sandclock {

namespace {

// Three dialects of the same shaders: GLES 2 (Android, Pi, Wayland), desktop GL 2.1 / compat
// (Linux, Windows via ANGLE) and the 3.2 core profile Kodi uses on macOS (needs a VAO).
#if defined(SANDCLOCK_GLES)
const char* kVersionVertex = "";
const char* kVersionFragment = "";
#elif defined(SANDCLOCK_CORE)
const char* kVersionVertex = "#version 150\n#define attribute in\n#define varying out\n";
const char* kVersionFragment =
    "#version 150\n#define varying in\nout vec4 sc_fragColor;\n#define gl_FragColor sc_fragColor\n";
#else
const char* kVersionVertex = "#version 120\n";
const char* kVersionFragment = "#version 120\n";
#endif

const char* kVertex = R"(
#ifdef GL_ES
precision highp float;
#endif
uniform float u_now;       // seconds, same clock as the grains' `born`
uniform float u_grain;     // cell size, screen px (1920x1080 space)
uniform float u_pxscale;   // framebuffer px per screen px
uniform vec3  u_base;      // pile sinking: base_t, base_sunk, speed
uniform vec2  u_chg;       // scheduled speed change: at, speed (at = 1e30: none)
uniform vec2  u_viewport;  // 1920, 1080
attribute vec4 a0;         // x0, y0, fall_px, scatter_px
attribute vec4 a1;         // delay, fall_s, slide_s, born
attribute vec4 a2;         // dx, dy, base_y
attribute vec4 a3;         // r, g, b, seed
varying vec3 v_col;
varying float v_seed;

float sunk(float t) {
    if (t > u_chg.x)
        return u_base.y + u_base.z * (u_chg.x - u_base.x) + u_chg.y * (t - u_chg.x);
    return u_base.y + u_base.z * (t - u_base.x);
}

void main() {
    float age = u_now - a1.w - a1.x;
    vec2 p = a0.xy;
    if (age > 0.0) {
        float e = a1.y > 0.0 ? clamp(age / a1.y, 0.0, 1.0) : 1.0;
        p.y += a0.z * e * e;                      // quadratic ease-in: gravity
        p.x += a0.w * sin(e * 1.5707963);         // sideways drift, easing out
        if (a1.z > 0.0) p += a2.xy * clamp((age - a1.y) / a1.z, 0.0, 1.0);
        if (age >= a1.y + a1.z) {                 // landed: it rides the sinking pile
            p = vec2(a0.x + a0.w + a2.x, a2.z + sunk(u_now));
        }
    }
    vec2 centre = p + vec2(u_grain * 0.5);
    gl_Position = vec4(centre.x / u_viewport.x * 2.0 - 1.0, 1.0 - centre.y / u_viewport.y * 2.0, 0.0, 1.0);
    gl_PointSize = u_grain * u_pxscale;
    v_col = a3.rgb;
    v_seed = a3.a;
}
)";

const char* kFragment = R"(
#ifdef GL_ES
precision mediump float;
#endif
uniform float u_look;      // 0 sand, 1 flat squares, 2 round beads
varying vec3 v_col;
varying float v_seed;

float hash(vec2 p) { return fract(sin(dot(p, vec2(12.9898, 78.233))) * 43758.5453); }

void main() {
    vec2 uv = gl_PointCoord;
    vec3 c = v_col;
    if (u_look < 0.5) {                       // sand: a little grain in the shade
        float n = hash(floor(uv * 3.0) + v_seed);
        c *= 0.82 + 0.28 * n;
    } else if (u_look > 1.5) {                // beads: round, lit from the top left
        vec2 d = uv * 2.0 - 1.0;
        if (dot(d, d) > 1.0) discard;
        float light = 0.75 + 0.35 * (1.0 - length(d - vec2(-0.35, -0.35)) * 0.7);
        c *= clamp(light, 0.5, 1.15);
    }
    gl_FragColor = vec4(c, 1.0);
}
)";

unsigned compile(unsigned type, const char* body, std::string* error) {
    const char* src[2] = {type == GL_VERTEX_SHADER ? kVersionVertex : kVersionFragment, body};
    unsigned sh = glCreateShader(type);
    glShaderSource(sh, 2, src, nullptr);
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

}  // namespace

Renderer::~Renderer() { release(); }

bool Renderer::init(std::string* error) {
    unsigned vs = compile(GL_VERTEX_SHADER, kVertex, error);
    if (!vs) return false;
    unsigned fs = compile(GL_FRAGMENT_SHADER, kFragment, error);
    if (!fs) return false;
    program_ = glCreateProgram();
    glAttachShader(program_, vs);
    glAttachShader(program_, fs);
    glBindAttribLocation(program_, 0, "a0");
    glBindAttribLocation(program_, 1, "a1");
    glBindAttribLocation(program_, 2, "a2");
    glBindAttribLocation(program_, 3, "a3");
    glLinkProgram(program_);
    int ok = 0;
    glGetProgramiv(program_, GL_LINK_STATUS, &ok);
    glDeleteShader(vs);
    glDeleteShader(fs);
    if (!ok) {
        char log[2048];
        glGetProgramInfoLog(program_, sizeof log, nullptr, log);
        *error = std::string("link: ") + log;
        return false;
    }
    u_now_ = glGetUniformLocation(program_, "u_now");
    u_grain_ = glGetUniformLocation(program_, "u_grain");
    u_pxscale_ = glGetUniformLocation(program_, "u_pxscale");
    u_base_ = glGetUniformLocation(program_, "u_base");
    u_chg_ = glGetUniformLocation(program_, "u_chg");
    u_look_ = glGetUniformLocation(program_, "u_look");
    u_viewport_ = glGetUniformLocation(program_, "u_viewport");
    glGenBuffers(1, &vbo_pile_);
    glGenBuffers(1, &vbo_glyph_);
#ifdef SANDCLOCK_CORE
    glGenVertexArrays(1, &vao_);
#endif
    return true;
}

void Renderer::release() {
    if (vbo_pile_) glDeleteBuffers(1, &vbo_pile_);
    if (vbo_glyph_) glDeleteBuffers(1, &vbo_glyph_);
    if (program_) glDeleteProgram(program_);
#ifdef SANDCLOCK_CORE
    if (vao_) glDeleteVertexArrays(1, &vao_);
    vao_ = 0;
#endif
    vbo_pile_ = vbo_glyph_ = program_ = 0;
}

void Renderer::upload(unsigned buf, const std::vector<Instance>& v, size_t* count) {
    glBindBuffer(GL_ARRAY_BUFFER, buf);
    glBufferData(GL_ARRAY_BUFFER, (GLsizeiptr)(v.size() * sizeof(Instance)),
                 v.empty() ? nullptr : v.data(), GL_DYNAMIC_DRAW);
    *count = v.size();
}

void Renderer::draw(Engine& engine, double now, int fb_w, int fb_h) {
    if (engine.take_pile_dirty()) upload(vbo_pile_, engine.pile(), &n_pile_);
    if (engine.take_glyph_dirty()) upload(vbo_glyph_, engine.glyphs(), &n_glyph_);

    // Letterbox 16:9 inside the window.
    int vw = fb_w, vh = fb_w * 9 / 16;
    if (vh > fb_h) { vh = fb_h; vw = fb_h * 16 / 9; }
    uint32_t bg = engine.background();
    glDisable(GL_SCISSOR_TEST);
    glViewport(0, 0, fb_w, fb_h);
    glClearColor(0, 0, 0, 1);
    glClear(GL_COLOR_BUFFER_BIT);
    glViewport((fb_w - vw) / 2, (fb_h - vh) / 2, vw, vh);
    glEnable(GL_SCISSOR_TEST);
    glScissor((fb_w - vw) / 2, (fb_h - vh) / 2, vw, vh);
    glClearColor(((bg >> 16) & 255) / 255.f, ((bg >> 8) & 255) / 255.f, (bg & 255) / 255.f, 1);
    glClear(GL_COLOR_BUFFER_BIT);

#if !defined(SANDCLOCK_GLES)
    glEnable(GL_PROGRAM_POINT_SIZE);
#endif
#if !defined(SANDCLOCK_GLES) && !defined(SANDCLOCK_CORE)
    glEnable(GL_POINT_SPRITE);
#endif
#ifdef SANDCLOCK_CORE
    glBindVertexArray(vao_);
#endif
    glUseProgram(program_);
    SinkState s = engine.sink();
    glUniform1f(u_now_, (float)now);
    glUniform1f(u_grain_, (float)engine.grain());
    glUniform1f(u_pxscale_, (float)vw / W);
    glUniform3f(u_base_, s.base_t, s.base_sunk, s.speed);
    glUniform2f(u_chg_, s.change_t, s.change_speed);
    glUniform1f(u_look_, (float)engine.settings().grain_look);
    glUniform2f(u_viewport_, (float)W, (float)H);

    auto bind = [&](unsigned buf) {
        glBindBuffer(GL_ARRAY_BUFFER, buf);
        for (int k = 0; k < 4; ++k) {
            glEnableVertexAttribArray(k);
            glVertexAttribPointer(k, 4, GL_FLOAT, GL_FALSE, sizeof(Instance),
                                  (const void*)(sizeof(float) * 4 * k));
        }
    };
    bind(vbo_pile_);
    if (n_pile_) glDrawArrays(GL_POINTS, 0, (GLsizei)n_pile_);
    bind(vbo_glyph_);
    if (n_glyph_) glDrawArrays(GL_POINTS, 0, (GLsizei)n_glyph_);
    // Leave the context as Kodi expects it.
    for (int k = 0; k < 4; ++k) glDisableVertexAttribArray(k);
    glBindBuffer(GL_ARRAY_BUFFER, 0);
#ifdef SANDCLOCK_CORE
    glBindVertexArray(0);
#endif
    glUseProgram(0);
    glDisable(GL_SCISSOR_TEST);
}

}  // namespace sandclock
