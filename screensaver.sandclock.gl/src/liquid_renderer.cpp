#include "liquid_renderer.hpp"

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

// Digits and drops. A cell is a rounded box: a square (a bit padded, so the shimmering digits
// stay solid) that rounds into a capsule as it lets go, then stretches upward with its speed, so
// the drops of one digit run together into streams.
const char* kDropVertex = R"(
#ifdef GL_ES
precision highp float;
#endif
uniform float u_now;
uniform float u_grain;     // cell size, screen px
uniform float u_pxscale;   // framebuffer px per screen px
uniform float u_wobble;    // how far the liquid digits shimmer, screen px
uniform vec2  u_viewport;
attribute vec4 a0;         // x0, y0, fall_px, -
attribute vec4 a1;         // delay (1e6 = a digit cell), fall_s, -, born
attribute vec4 a2;
attribute vec4 a3;         // r, g, b, seed
varying vec3 v_col;
varying vec4 v_geo;        // half width, half height, corner radius, sprite size (screen px)

void main() {
    float g = u_grain;
    float age = u_now - a1.w - a1.x;
    vec2 p = a0.xy;
    float ext = 0.0;
    float r = 0.0;
    float w = u_wobble;
    if (age > 0.0) {
        float fall = max(a1.y, 0.001);
        float e = clamp(age / fall, 0.0, 1.0);
        p.y += a0.z * e * e;                       // gravity
        float vel = 2.0 * a0.z * e / fall;         // px/s
        ext = clamp(vel * 0.045, 0.0, g * 6.0);     // stretches as it speeds up
        r = clamp(age * 8.0, 0.0, 1.0);            // square cell -> round drop
        w *= exp(-age * 8.0);
        if (age >= fall) p.y = -10000.0;           // landed: the pool takes it
    }
    p.x += w * sin(u_now * 2.3 + a0.y * 0.045 + a0.x * 0.012);
    p.y += 0.5 * w * sin(u_now * 1.7 + a0.x * 0.05 + a0.y * 0.02);
    float pad = (1.0 - r) * 0.18 * g;
    float hx = 0.5 * g * (1.0 + 0.3 * r) + pad;     // drops are a little wider than cells, so streams merge
    float hy = 0.5 * (g + ext) + pad;
    float s = 2.0 * max(hx, hy) + 2.0;
    vec2 c = vec2(p.x + 0.5 * g, p.y + 0.5 * g - 0.5 * ext);
    gl_Position = vec4(c.x / u_viewport.x * 2.0 - 1.0, 1.0 - c.y / u_viewport.y * 2.0, 0.0, 1.0);
    gl_PointSize = s * u_pxscale;
    v_col = a3.rgb;
    v_geo = vec4(hx, hy, r * 0.5 * g * (1.0 + 0.3 * r), s);
}
)";

const char* kDropFragment = R"(
#ifdef GL_ES
#ifdef GL_FRAGMENT_PRECISION_HIGH
precision highp float;
#else
precision mediump float;
#endif
#endif
uniform float u_look;      // 0 glossy, 1 flat, 2 glow
varying vec3 v_col;
varying vec4 v_geo;

void main() {
    vec2 q = (gl_PointCoord - 0.5) * v_geo.w;
    vec2 hb = max(v_geo.xy - vec2(v_geo.z), vec2(0.0));
    vec2 d = abs(q) - hb;
    float dist = length(max(d, vec2(0.0))) + min(max(d.x, d.y), 0.0) - v_geo.z;
    if (dist > 0.0) discard;
    vec3 c = v_col;
    vec2 n = q / v_geo.xy;                          // -1 .. 1 across the shape
    float roundness = v_geo.z / max(v_geo.x, 0.001);    // 0 for a cell, 1 for a drop
    if (u_look < 0.5) {                             // glossy: lit from the top left
        c *= 0.92 - 0.14 * n.y * roundness;
        float spot = smoothstep(0.55, 0.0, length(n - vec2(-0.35, -0.45)));
        c += spot * 0.38 * roundness;
    } else if (u_look > 1.5) {                      // glow: bright core
        c += (1.0 - min(length(n), 1.0)) * 0.35 * roundness + 0.08;
    }
    gl_FragColor = vec4(c, 1.0);
}
)";

const char* kPoolVertex = R"(
#ifdef GL_ES
precision highp float;
#endif
uniform vec2 u_viewport;
attribute vec4 a0;         // x, y, depth below the surface, slope shade
varying float v_depth;
varying float v_shade;
void main() {
    gl_Position = vec4(a0.x / u_viewport.x * 2.0 - 1.0, 1.0 - a0.y / u_viewport.y * 2.0, 0.0, 1.0);
    v_depth = a0.z;
    v_shade = a0.w;
}
)";

const char* kPoolFragment = R"(
#ifdef GL_ES
precision mediump float;
#endif
uniform vec3 u_colour;
varying float v_depth;
varying float v_shade;
void main() {
    float top = 1.0 - smoothstep(0.0, 9.0, v_depth);          // bright skin on the surface
    vec3 c = u_colour * (1.0 - 0.5 * clamp(v_depth / 300.0, 0.0, 1.0));   // darker with depth
    c = mix(c, vec3(1.0), 0.3 * top);
    c *= 1.0 + v_shade;
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

unsigned link(const char* vs_src, const char* fs_src, int attributes, std::string* error) {
    unsigned vs = compile(GL_VERTEX_SHADER, vs_src, error);
    if (!vs) return 0;
    unsigned fs = compile(GL_FRAGMENT_SHADER, fs_src, error);
    if (!fs) return 0;
    unsigned prog = glCreateProgram();
    glAttachShader(prog, vs);
    glAttachShader(prog, fs);
    static const char* names[4] = {"a0", "a1", "a2", "a3"};
    for (int k = 0; k < attributes; ++k) glBindAttribLocation(prog, k, names[k]);
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

}  // namespace

LiquidRenderer::~LiquidRenderer() { release(); }

bool LiquidRenderer::init(std::string* error) {
    drop_prog_ = link(kDropVertex, kDropFragment, 4, error);
    if (!drop_prog_) return false;
    pool_prog_ = link(kPoolVertex, kPoolFragment, 1, error);
    if (!pool_prog_) return false;
    u_now_ = glGetUniformLocation(drop_prog_, "u_now");
    u_grain_ = glGetUniformLocation(drop_prog_, "u_grain");
    u_pxscale_ = glGetUniformLocation(drop_prog_, "u_pxscale");
    u_wobble_ = glGetUniformLocation(drop_prog_, "u_wobble");
    u_look_ = glGetUniformLocation(drop_prog_, "u_look");
    u_viewport_ = glGetUniformLocation(drop_prog_, "u_viewport");
    p_viewport_ = glGetUniformLocation(pool_prog_, "u_viewport");
    p_colour_ = glGetUniformLocation(pool_prog_, "u_colour");
    glGenBuffers(1, &vbo_drops_);
    glGenBuffers(1, &vbo_glyph_);
    glGenBuffers(1, &vbo_pool_);
#ifdef SANDCLOCK_CORE
    glGenVertexArrays(1, &vao_);
#endif
    return true;
}

void LiquidRenderer::release() {
    if (vbo_drops_) glDeleteBuffers(1, &vbo_drops_);
    if (vbo_glyph_) glDeleteBuffers(1, &vbo_glyph_);
    if (vbo_pool_) glDeleteBuffers(1, &vbo_pool_);
    if (drop_prog_) glDeleteProgram(drop_prog_);
    if (pool_prog_) glDeleteProgram(pool_prog_);
#ifdef SANDCLOCK_CORE
    if (vao_) glDeleteVertexArrays(1, &vao_);
    vao_ = 0;
#endif
    vbo_drops_ = vbo_glyph_ = vbo_pool_ = drop_prog_ = pool_prog_ = 0;
}

void LiquidRenderer::upload(unsigned buf, const std::vector<Instance>& v, size_t* count) {
    glBindBuffer(GL_ARRAY_BUFFER, buf);
    glBufferData(GL_ARRAY_BUFFER, (GLsizeiptr)(v.size() * sizeof(Instance)),
                 v.empty() ? nullptr : v.data(), GL_DYNAMIC_DRAW);
    *count = v.size();
}

void LiquidRenderer::draw(LiquidEngine& engine, double now, int fb_w, int fb_h) {
    if (engine.take_drops_dirty()) upload(vbo_drops_, engine.drops(), &n_drops_);
    if (engine.take_glyph_dirty()) upload(vbo_glyph_, engine.glyphs(), &n_glyph_);

    int vw = fb_w, vh = fb_w * 9 / 16;   // letterbox 16:9
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

    // Digits and drops.
    glUseProgram(drop_prog_);
    glUniform1f(u_now_, (float)now);
    glUniform1f(u_grain_, (float)engine.grain());
    glUniform1f(u_pxscale_, (float)vw / W);
    glUniform1f(u_wobble_, engine.wobble());
    glUniform1f(u_look_, (float)engine.settings().grain_look);
    glUniform2f(u_viewport_, (float)W, (float)H);
    auto bind_instances = [&](unsigned buf) {
        glBindBuffer(GL_ARRAY_BUFFER, buf);
        for (int k = 0; k < 4; ++k) {
            glEnableVertexAttribArray(k);
            glVertexAttribPointer(k, 4, GL_FLOAT, GL_FALSE, sizeof(Instance),
                                  (const void*)(sizeof(float) * 4 * k));
        }
    };
    bind_instances(vbo_drops_);
    if (n_drops_) glDrawArrays(GL_POINTS, 0, (GLsizei)n_drops_);
    bind_instances(vbo_glyph_);
    if (n_glyph_) glDrawArrays(GL_POINTS, 0, (GLsizei)n_glyph_);
    for (int k = 1; k < 4; ++k) glDisableVertexAttribArray(k);

    // The pool, over the drops that have reached it.
    const std::vector<PoolVertex>& pool = engine.pool();
    glUseProgram(pool_prog_);
    glUniform2f(p_viewport_, (float)W, (float)H);
    const float* rgb = engine.pool_colour();
    glUniform3f(p_colour_, rgb[0], rgb[1], rgb[2]);
    glBindBuffer(GL_ARRAY_BUFFER, vbo_pool_);
    glBufferData(GL_ARRAY_BUFFER, (GLsizeiptr)(pool.size() * sizeof(PoolVertex)), pool.data(), GL_STREAM_DRAW);
    glEnableVertexAttribArray(0);
    glVertexAttribPointer(0, 4, GL_FLOAT, GL_FALSE, sizeof(PoolVertex), (const void*)0);
    glDrawArrays(GL_TRIANGLE_STRIP, 0, (GLsizei)pool.size());

    // Leave the context as Kodi expects it.
    glDisableVertexAttribArray(0);
    glBindBuffer(GL_ARRAY_BUFFER, 0);
#ifdef SANDCLOCK_CORE
    glBindVertexArray(0);
#endif
    glUseProgram(0);
    glDisable(GL_SCISSOR_TEST);
}

}  // namespace sandclock
