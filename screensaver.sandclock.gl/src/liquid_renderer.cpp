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

// Digits and falling drops. A glyph cell is a soft rounded square; as it lets go it rounds into
// a capsule and stretches with its speed, so the cells of one column run together into a thread.
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
varying float v_kind;      // 0 = the clock, 1 = a falling drop
varying vec2 v_centre;

void main() {
    float g = u_grain;
    float age = u_now - a1.w - a1.x;
    vec2 p = a0.xy;
    float ext = 0.0;
    float r = 0.30;                       // a digit cell is a soft rounded square, not a block
    float w = u_wobble;
    float kind = 0.0;
    float jit = a0.w;                             // 0..1, one value for a whole column of liquid
    float jit2 = fract(a0.w * 7.13 + 0.37);
    float hx = 0.5 * g * 1.22 + 0.09 * g;          // a digit cell: the grid, slightly overlapped
    if (age > 0.0) {
        kind = 1.0;
        float fall = max(a1.y, 0.001);
        float e = clamp(age / fall, 0.0, 1.0);
        p.y += a0.z * e * e;                       // gravity
        p.x += (jit - 0.5) * 1.0 * g;              // each thread leaves from its own spot
        p.x += e * sin(age * 1.6 + jit * 9.0) * 1.8 * g;   // the thread meanders as it falls
        float vel = 2.0 * a0.z * e / fall;         // px/s
        float travelled = a0.z * e * e;
        // The thread trails behind the bead and can never reach back above where it started.
        ext = min(clamp(vel * 0.050, 0.0, g * 9.0) + 0.6 * g, travelled + 0.7 * g);
        r = mix(0.30, 1.0, smoothstep(0.0, 0.16, age));   // cell -> fully round capsule
        w *= exp(-age * 9.0);
        // It thins as it stretches, then swells into a bead at the leading end.
        hx = (0.34 + 0.16 * jit2) * g * (1.0 - 0.30 * e - 0.55 * smoothstep(0.72, 0.97, e)) + 0.05 * g;
        if (age >= fall) p.y = -10000.0;           // landed: the pool takes it
    }
    p.x += w * sin(u_now * 2.3 + a0.y * 0.045 + a0.x * 0.012);
    p.y += 0.5 * w * sin(u_now * 1.7 + a0.x * 0.05 + a0.y * 0.02);
    float pad = (1.0 - r) * 0.10 * g + 0.09 * g;
    float hy = 0.5 * (g + ext) + pad;
    float corner = r * min(hx + pad, hy);
    float s = 2.0 * max(hx, hy) + 2.0;
    vec2 c = vec2(p.x + 0.5 * g, p.y + 0.5 * g - 0.5 * ext);
    gl_Position = vec4(c.x / u_viewport.x * 2.0 - 1.0, 1.0 - c.y / u_viewport.y * 2.0, 0.0, 1.0);
    gl_PointSize = s * u_pxscale;
    v_col = a3.rgb;
    v_geo = vec4(hx, hy, corner, s);
    v_kind = kind;
    v_centre = c;
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
uniform float u_now;
uniform float u_look;      // 0 glossy, 1 flat, 2 glow
varying vec3 v_col;
varying vec4 v_geo;
varying float v_kind;
varying vec2 v_centre;

void main() {
    vec2 q = (gl_PointCoord - 0.5) * v_geo.w;
    vec2 n = q / max(v_geo.xy, vec2(0.001));        // -1 .. 1 across the shape
    // A falling thread is a teardrop: full at the leading end, tapering back to the tail, so a
    // drop pulls a thin filament out of the digit instead of reading as a rod.
    float taper = v_kind > 0.5 ? mix(0.55, 1.0, smoothstep(-0.95, 0.50, n.y)) : 1.0;
    vec2 hb = max(v_geo.xy - vec2(v_geo.z), vec2(0.0));
    vec2 d = abs(q) - vec2(hb.x * taper, hb.y);
    float dist = length(max(d, vec2(0.0))) + min(max(d.x, d.y), 0.0) - v_geo.z * taper;
    if (dist > 0.0) discard;
    vec3 c = v_col;
    if (v_kind < 0.5) {
        // The clock: one continuous film of liquid. Shade from the screen position so the sheen
        // runs across the whole digit, not once per cell.
        vec2 wp = v_centre + q;
        float sheen = 0.5 + 0.5 * sin((wp.y + wp.x * 0.35) * 0.010 + u_now * 0.9);
        c *= 0.92 + 0.10 * sheen;
        // One broad gloss travelling across the whole clock, not a highlight per cell.
        float band = sin((wp.y * 0.75 + wp.x * 0.55) * 0.0045 - u_now * 0.7);
        c += v_col * 0.10 * smoothstep(0.30, 1.0, band);
    } else {
        // A falling thread: a continuous glossy film, shaded from the screen position so the
        // cells of one stream melt into each other instead of reading as a chain of beads.
        vec2 wp = v_centre + q;
        float sheen = 0.5 + 0.5 * sin((wp.y * 0.85 + wp.x * 0.30) * 0.010 - u_now * 1.3 + v_col.g * 2.0);
        c *= 0.88 + 0.12 * sheen;
        // Round across its width, with a soft specular running down the thread. Both depend on
        // the horizontal position only, so the cells of one stream blend into a single thread.
        float across = clamp(1.0 - n.x * n.x, 0.0, 1.0);
        c *= 0.76 + 0.24 * sqrt(across);
        c += vec3(0.30) * smoothstep(0.42, 0.02, abs(n.x + 0.36)) * (0.55 + 0.45 * sheen);
        if (u_look > 1.5) c += (1.0 - min(length(n), 1.0)) * 0.25;
    }
    if (u_look > 1.5) c = min(c + 0.10, vec3(1.4));
    gl_FragColor = vec4(c, 1.0);
}
)";

// Splash spray and foam. Each fleck is thrown from where a drop met the pool and pulled down by
// gravity; the vertex shader evaluates the whole flight, so nothing is uploaded per frame.
const char* kSprayVertex = R"(
#ifdef GL_ES
precision highp float;
#endif
uniform float u_now;
uniform float u_pxscale;
uniform vec2  u_viewport;
attribute vec4 a0;         // x0, y0, vx, vy
attribute vec4 a1;         // born, life, size, gravity
attribute vec4 a2;         // r, g, b, alpha
attribute vec4 a3;         // seed, -, -, -
varying vec3 v_col;
varying float v_alpha;
void main() {
    float age = u_now - a1.x;
    if (age < 0.0 || age > a1.y) {
        gl_Position = vec4(3.0, 3.0, 0.0, 1.0);
        gl_PointSize = 0.0;
        v_alpha = 0.0;
        v_col = vec3(0.0);
        return;
    }
    vec2 p = a0.xy + a0.zw * age + vec2(0.0, 0.5 * a1.w * age * age);
    float t = age / a1.y;
    float size = a1.z * (1.0 - 0.45 * t);
    gl_Position = vec4(p.x / u_viewport.x * 2.0 - 1.0, 1.0 - p.y / u_viewport.y * 2.0, 0.0, 1.0);
    gl_PointSize = max(1.0, (2.0 * size + 2.0) * u_pxscale);
    v_col = a2.rgb;
    v_alpha = a2.a * (1.0 - smoothstep(0.65, 1.0, t));
}
)";

const char* kSprayFragment = R"(
#ifdef GL_ES
precision mediump float;
#endif
uniform float u_foam;      // 0 = droplets, 1 = foam flecks on the surface
varying vec3 v_col;
varying float v_alpha;
void main() {
    vec2 q = gl_PointCoord * 2.0 - 1.0;
    float r = length(q);
    if (r > 1.0) discard;
    if (u_foam < 0.5) {
        vec3 c = mix(v_col, vec3(1.0), 0.30);       // water catches the light
        float glint = smoothstep(0.60, 0.0, length(q - vec2(-0.30, -0.38)));
        c += glint * 0.55;
        c *= 0.86 + 0.22 * smoothstep(1.0, 0.35, r);
        float a = v_alpha * smoothstep(1.0, 0.70, r);
        gl_FragColor = vec4(c, a);
    } else {
        float n = 0.5 + 0.5 * sin(q.x * 9.0 + q.y * 7.0 + v_col.r * 30.0);
        vec3 c = mix(v_col, vec3(0.96, 0.98, 1.0), 0.80) + 0.08 * n;
        float a = v_alpha * smoothstep(1.0, 0.30, r) * (0.65 + 0.35 * n);
        gl_FragColor = vec4(c, a);
    }
}
)";

// The water body, one strip per coloured liquid. Both edges of a band carry the free surface,
// so every fragment knows how deep it is and how far below its own interface.
const char* kWaterVertex = R"(
#ifdef GL_ES
precision highp float;
#endif
uniform vec2 u_viewport;
attribute vec4 a0;         // x, y, surface y, band top y
attribute vec2 a1;         // surface slope
varying float v_x;
varying float v_y;
varying float v_surf;
varying float v_top;
varying float v_slope;
void main() {
    gl_Position = vec4(a0.x / u_viewport.x * 2.0 - 1.0, 1.0 - a0.y / u_viewport.y * 2.0, 0.0, 1.0);
    v_x = a0.x;
    v_y = a0.y;
    v_surf = a0.z;
    v_top = a0.w;
    v_slope = a1.x;
}
)";

const char* kWaterFragment = R"(
#ifdef GL_ES
#ifdef GL_FRAGMENT_PRECISION_HIGH
precision highp float;
#else
precision mediump float;
#endif
#endif
uniform vec3 u_colour;
uniform float u_now;
varying float v_x;
varying float v_y;
varying float v_surf;
varying float v_top;
varying float v_slope;

void main() {
    float d = max(0.0, v_y - v_surf);       // px below the free surface
    float db = max(0.0, v_y - v_top);       // px below this liquid's interface
    vec3 c = u_colour;
    // Light is absorbed with depth: the liquid gets deeper and richer, never muddy.
    c *= 0.62 + 0.38 * exp(-d * 0.0022);
    c = mix(c, c * 0.55 + vec3(0.010, 0.025, 0.055), clamp(d / 700.0, 0.0, 0.30));
    // Caustics: drifting webs of light inside the water.
    float cx = v_x * 0.012 + sin(v_y * 0.018 - u_now * 0.55) * 2.2;
    float ca = sin(cx + u_now * 0.6) + sin(cx * 1.83 + v_y * 0.013 + u_now * 0.31)
             + 0.5 * sin(v_x * 0.031 + v_y * 0.011 - u_now * 1.10);
    float caus = smoothstep(1.10, 1.75, ca);
    c += caus * (u_colour * 0.55 + 0.08) * (0.45 + 0.55 * exp(-d * 0.004));
    // The meniscus between two liquids: a bright refractive line.
    float edge = smoothstep(2.2, 0.0, db) * smoothstep(3.0, 9.0, d);
    c = mix(c, c * 1.22 + vec3(0.10), 0.34 * edge);
    // The waterline: a specular sheen that follows the wave slope.
    float surf = smoothstep(5.0, 0.0, d);
    vec2 n2 = normalize(vec2(v_slope, -1.0));
    float spec = pow(max(dot(n2, vec2(-0.42, -0.91)), 0.0), 22.0);
    float glint = 0.5 + 0.5 * sin(v_x * 0.075 + u_now * 2.1 + sin(v_x * 0.019 - u_now * 1.4) * 3.0);
    c += (vec3(0.95, 0.98, 1.0) * (spec * 0.85 + 0.12 * glint) + vec3(0.10, 0.16, 0.22)) * surf;
    c = mix(c, vec3(0.42, 0.60, 0.85), 0.10 * surf);
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
    spray_prog_ = link(kSprayVertex, kSprayFragment, 4, error);
    if (!spray_prog_) return false;
    water_prog_ = link(kWaterVertex, kWaterFragment, 2, error);
    if (!water_prog_) return false;
    u_now_ = glGetUniformLocation(drop_prog_, "u_now");
    u_grain_ = glGetUniformLocation(drop_prog_, "u_grain");
    u_pxscale_ = glGetUniformLocation(drop_prog_, "u_pxscale");
    u_wobble_ = glGetUniformLocation(drop_prog_, "u_wobble");
    u_look_ = glGetUniformLocation(drop_prog_, "u_look");
    u_viewport_ = glGetUniformLocation(drop_prog_, "u_viewport");
    s_now_ = glGetUniformLocation(spray_prog_, "u_now");
    s_pxscale_ = glGetUniformLocation(spray_prog_, "u_pxscale");
    s_viewport_ = glGetUniformLocation(spray_prog_, "u_viewport");
    s_foam_ = glGetUniformLocation(spray_prog_, "u_foam");
    w_now_ = glGetUniformLocation(water_prog_, "u_now");
    w_viewport_ = glGetUniformLocation(water_prog_, "u_viewport");
    w_colour_ = glGetUniformLocation(water_prog_, "u_colour");
    glGenBuffers(1, &vbo_drops_);
    glGenBuffers(1, &vbo_glyph_);
    glGenBuffers(1, &vbo_spray_);
    glGenBuffers(1, &vbo_foam_);
    glGenBuffers(1, &vbo_water_);
#ifdef SANDCLOCK_CORE
    glGenVertexArrays(1, &vao_);
#endif
    return true;
}

void LiquidRenderer::release() {
    if (vbo_drops_) glDeleteBuffers(1, &vbo_drops_);
    if (vbo_glyph_) glDeleteBuffers(1, &vbo_glyph_);
    if (vbo_spray_) glDeleteBuffers(1, &vbo_spray_);
    if (vbo_foam_) glDeleteBuffers(1, &vbo_foam_);
    if (vbo_water_) glDeleteBuffers(1, &vbo_water_);
    if (drop_prog_) glDeleteProgram(drop_prog_);
    if (spray_prog_) glDeleteProgram(spray_prog_);
    if (water_prog_) glDeleteProgram(water_prog_);
#ifdef SANDCLOCK_CORE
    if (vao_) glDeleteVertexArrays(1, &vao_);
    vao_ = 0;
#endif
    vbo_drops_ = vbo_glyph_ = vbo_spray_ = vbo_foam_ = vbo_water_ = 0;
    drop_prog_ = spray_prog_ = water_prog_ = 0;
}

void LiquidRenderer::upload(unsigned buf, const void* data, size_t bytes, size_t elem, size_t* count) {
    glBindBuffer(GL_ARRAY_BUFFER, buf);
    glBufferData(GL_ARRAY_BUFFER, (GLsizeiptr)bytes, data, GL_DYNAMIC_DRAW);
    *count = elem ? bytes / elem : 0;
}

void LiquidRenderer::draw(LiquidEngine& engine, double now, int fb_w, int fb_h) {
    if (engine.take_drops_dirty()) {
        const auto& v = engine.drops();
        upload(vbo_drops_, v.empty() ? nullptr : v.data(), v.size() * sizeof(Instance), sizeof(Instance), &n_drops_);
    }
    if (engine.take_glyph_dirty()) {
        const auto& v = engine.glyphs();
        upload(vbo_glyph_, v.empty() ? nullptr : v.data(), v.size() * sizeof(Instance), sizeof(Instance), &n_glyph_);
    }
    if (engine.take_spray_dirty()) {
        const auto& s = engine.spray();
        upload(vbo_spray_, s.empty() ? nullptr : s.data(), s.size() * sizeof(SprayInstance), sizeof(SprayInstance), &n_spray_);
        const auto& f = engine.foam();
        upload(vbo_foam_, f.empty() ? nullptr : f.data(), f.size() * sizeof(SprayInstance), sizeof(SprayInstance), &n_foam_);
    }

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

    GLboolean depth = glIsEnabled(GL_DEPTH_TEST), cull = glIsEnabled(GL_CULL_FACE),
              blend = glIsEnabled(GL_BLEND);
    if (depth) glDisable(GL_DEPTH_TEST);
    if (cull) glDisable(GL_CULL_FACE);

#if !defined(SANDCLOCK_GLES)
    glEnable(GL_PROGRAM_POINT_SIZE);
#endif
#if !defined(SANDCLOCK_GLES) && !defined(SANDCLOCK_CORE)
    glEnable(GL_POINT_SPRITE);
#endif
#ifdef SANDCLOCK_CORE
    glBindVertexArray(vao_);
#endif

    // Digits and falling drops.
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
    for (int k = 0; k < 4; ++k) glDisableVertexAttribArray(k);

    // Splash droplets, before the water so the ones that fall back are hidden by it.
    auto bind_spray = [&](unsigned buf) {
        glBindBuffer(GL_ARRAY_BUFFER, buf);
        for (int k = 0; k < 4; ++k) {
            if (k == 2) continue;
            glEnableVertexAttribArray(k);
            glVertexAttribPointer(k, 4, GL_FLOAT, GL_FALSE, sizeof(SprayInstance),
                                  (const void*)(sizeof(float) * 4 * k));
        }
        glEnableVertexAttribArray(2);
        glVertexAttribPointer(2, 4, GL_FLOAT, GL_FALSE, sizeof(SprayInstance),
                              (const void*)(sizeof(float) * 8));
    };
    if (n_spray_ || n_foam_) {
        glEnable(GL_BLEND);
        glBlendFunc(GL_SRC_ALPHA, GL_ONE_MINUS_SRC_ALPHA);
        glUseProgram(spray_prog_);
        glUniform1f(s_now_, (float)now);
        glUniform1f(s_pxscale_, (float)vw / W);
        glUniform2f(s_viewport_, (float)W, (float)H);
        glUniform1f(s_foam_, 0.0f);
        bind_spray(vbo_spray_);
        if (n_spray_) glDrawArrays(GL_POINTS, 0, (GLsizei)n_spray_);
    }

    // The pool: one strip per coloured liquid, deepest first. Opaque.
    const std::vector<WaterVertex>& water = engine.water();
    const std::vector<WaterBand>& bands = engine.bands();
    if (!water.empty() && !bands.empty()) {
        glDisable(GL_BLEND);
        glUseProgram(water_prog_);
        glUniform1f(w_now_, (float)now);
        glUniform2f(w_viewport_, (float)W, (float)H);
        glBindBuffer(GL_ARRAY_BUFFER, vbo_water_);
        glBufferData(GL_ARRAY_BUFFER, (GLsizeiptr)(water.size() * sizeof(WaterVertex)),
                     water.data(), GL_STREAM_DRAW);
        glEnableVertexAttribArray(0);
        glVertexAttribPointer(0, 4, GL_FLOAT, GL_FALSE, sizeof(WaterVertex), (const void*)0);
        glEnableVertexAttribArray(1);
        glVertexAttribPointer(1, 2, GL_FLOAT, GL_FALSE, sizeof(WaterVertex),
                              (const void*)(sizeof(float) * 4));
        for (const WaterBand& b : bands) {
            glUniform3f(w_colour_, b.rgb[0], b.rgb[1], b.rgb[2]);
            glDrawArrays(GL_TRIANGLE_STRIP, (GLint)b.first, (GLsizei)b.count);
        }
        glDisableVertexAttribArray(0);
        glDisableVertexAttribArray(1);
    }

    // Foam rides on top of the water.
    if (n_foam_) {
        glEnable(GL_BLEND);
        glBlendFunc(GL_SRC_ALPHA, GL_ONE_MINUS_SRC_ALPHA);
        glUseProgram(spray_prog_);
        glUniform1f(s_now_, (float)now);
        glUniform1f(s_pxscale_, (float)vw / W);
        glUniform2f(s_viewport_, (float)W, (float)H);
        glUniform1f(s_foam_, 1.0f);
        bind_spray(vbo_foam_);
        glDrawArrays(GL_POINTS, 0, (GLsizei)n_foam_);
        for (int k = 0; k < 4; ++k) glDisableVertexAttribArray(k);
    }
    // The digits last: their own melt falls behind them, and the pool never covers the clock.
    glDisable(GL_BLEND);
    glUseProgram(drop_prog_);
    glUniform1f(u_now_, (float)now);
    glUniform1f(u_grain_, (float)engine.grain());
    glUniform1f(u_pxscale_, (float)vw / W);
    glUniform1f(u_wobble_, engine.wobble());
    glUniform1f(u_look_, (float)engine.settings().grain_look);
    glUniform2f(u_viewport_, (float)W, (float)H);
    glBindBuffer(GL_ARRAY_BUFFER, vbo_glyph_);
    for (int k = 0; k < 4; ++k) {
        glEnableVertexAttribArray(k);
        glVertexAttribPointer(k, 4, GL_FLOAT, GL_FALSE, sizeof(Instance), (const void*)(sizeof(float) * 4 * k));
    }
    if (n_glyph_) glDrawArrays(GL_POINTS, 0, (GLsizei)n_glyph_);
    for (int k = 0; k < 4; ++k) glDisableVertexAttribArray(k);
    if (!blend) glDisable(GL_BLEND);

    // Leave the context as Kodi expects it.
    glBindBuffer(GL_ARRAY_BUFFER, 0);
#ifdef SANDCLOCK_CORE
    glBindVertexArray(0);
#endif
    glUseProgram(0);
    glDisable(GL_SCISSOR_TEST);
    if (depth) glEnable(GL_DEPTH_TEST);
    if (cull) glEnable(GL_CULL_FACE);
}

}  // namespace sandclock
