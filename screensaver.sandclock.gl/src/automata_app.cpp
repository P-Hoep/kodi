#include "automata_app.hpp"

#include <algorithm>
#include <cmath>
#include <cstring>

#include "gl_include.hpp"

#ifndef GL_BLEND_SRC_RGB
#define GL_BLEND_SRC_RGB 0x80C9
#define GL_BLEND_DST_RGB 0x80C8
#define GL_BLEND_SRC_ALPHA 0x80CB
#define GL_BLEND_DST_ALPHA 0x80CA
#endif

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
// The clock mask (u_mask, placed at u_maskrect in grid uv) can force cells: mode 1 alive once
// (the digits burst into life), 2 dead (cut out), 3 alive every generation (living digits).
const char* kUpdate = R"(
uniform sampler2D u_src;
uniform sampler2D u_mask;
uniform vec4 u_a;          // grid w, grid h, birth mask, survive mask
uniform vec4 u_b;          // states, wrap, trail, spark
uniform vec4 u_c;          // seed, mask mode
uniform vec4 u_maskrect;   // x, y, w, h in grid uv

float alive(vec2 p) {
    if (u_b.y > 0.5) p = mod(p + u_a.xy, u_a.xy);
    else if (p.x < 0.0 || p.y < 0.0 || p.x >= u_a.x || p.y >= u_a.y) return 0.0;
    return texture2D(u_src, (p + 0.5) / u_a.xy).a;
}
float bit(float mask, float n) { return mod(floor(mask / exp2(n) + 0.001), 2.0); }

void main() {
    vec2 c = floor(gl_FragCoord.xy);
    vec4 s = texture2D(u_src, (c + 0.5) / u_a.xy);
    float n = alive(c + vec2(-1.0, -1.0)) + alive(c + vec2(0.0, -1.0)) + alive(c + vec2(1.0, -1.0))
            + alive(c + vec2(-1.0, 0.0))                              + alive(c + vec2(1.0, 0.0))
            + alive(c + vec2(-1.0, 1.0))  + alive(c + vec2(0.0, 1.0))  + alive(c + vec2(1.0, 1.0));
    float states = u_b.x;
    float cur = floor(s.r * 255.0 + 0.5);
    float ns;
    if (cur < 0.5) ns = bit(u_a.z, n);
    else if (cur < 1.5) ns = bit(u_a.w, n) > 0.5 ? 1.0 : (states > 2.5 ? 2.0 : 0.0);
    else ns = (cur + 1.0 < states) ? cur + 1.0 : 0.0;

    float age = s.g;
    bool live = ns > 0.5 && ns < 1.5;
    if (live) age = (cur > 0.5 && cur < 1.5) ? min(age + 1.0 / 255.0, 1.0) : 0.0;
    float trail = live ? 1.0 : s.b * u_b.z;
    if (trail < 0.02) trail = 0.0;
    if (u_b.w > 0.0 && ns < 0.5) {
        float h = fract(sin(dot(c + vec2(u_c.x, u_c.x * 1.7), vec2(12.9898, 78.233))) * 43758.5453);
        if (h < u_b.w) { ns = 1.0; age = 0.0; trail = 1.0; live = true; }
    }
    if (u_c.y > 0.5) {
        vec2 q = ((c + 0.5) / u_a.xy - u_maskrect.xy) / u_maskrect.zw;
        if (q.x >= 0.0 && q.y >= 0.0 && q.x <= 1.0 && q.y <= 1.0 && texture2D(u_mask, q).r > 0.5) {
            if (u_c.y > 1.5 && u_c.y < 2.5) { ns = 0.0; live = false; }
            else { if (!live) age = 0.0; ns = 1.0; live = true; trail = 1.0; }
        }
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

// What is on screen: each pixel is mapped to a point on the grid (flat with a camera, or one of
// the 3D-looking views), and that cell is coloured.
const char* kDraw = R"(
uniform sampler2D u_state;
uniform sampler2D u_pal;       // 8 x 1: the 7 palette colours and the first again, so it loops
uniform vec4 u_p0;             // colour mode, cell shape, cell px at zoom 1, palette phase
uniform vec4 u_p1;             // age span, dim, states, time
uniform vec4 u_p2;             // view, zoom, turn, wrap
uniform vec4 u_p3;             // glow, background style, screen effect
uniform vec4 u_cg;             // camera x, y (grid uv), grid w, h
uniform vec3 u_colour, u_bg;
varying vec2 v_uv;

#define MODE u_p0.x
#define SHAPE u_p0.y
#define CELLPX u_p0.z
#define PHASE u_p0.w
#define AGESPAN u_p1.x
#define DIM u_p1.y
#define STATES u_p1.z
#define TIME u_p1.w
#define VIEW u_p2.x
#define ZOOM u_p2.y
#define ROT u_p2.z
#define WRAP u_p2.w
#define GLOW u_p3.x
#define BGSTYLE u_p3.y
#define SCREENFX u_p3.z
#define CAM u_cg.xy
#define GRID u_cg.zw

vec3 pal(float t) { return texture2D(u_pal, vec2((fract(t) * 7.0 + 0.5) / 8.0, 0.5)).rgb; }
vec3 hsv(float h) {
    vec3 k = clamp(abs(fract(vec3(h) + vec3(1.0, 2.0 / 3.0, 1.0 / 3.0)) * 6.0 - 3.0) - 1.0, 0.0, 1.0);
    return mix(vec3(1.0), k, 0.75);
}
float plasma(vec2 q, float t) {
    return 0.5 + 0.25 * sin(q.x * 9.0 + t) + 0.25 * sin(q.y * 7.0 - t * 1.3 + 2.0 * sin(q.x * 3.0 + t * 0.5));
}
vec4 cell(vec2 c) { return texture2D(u_state, (mod(c, GRID) + 0.5) / GRID); }
vec2 turn(vec2 v, float a) { float s = sin(a), k = cos(a); return vec2(k * v.x - s * v.y, s * v.x + k * v.y); }

vec3 background(vec2 p) {
    if (BGSTYLE < 0.5) return u_bg;
    if (BGSTYLE < 1.5) return u_bg + pal(PHASE) * 0.2 * clamp(0.6 - p.y, 0.0, 1.0);
    return u_bg + pal(plasma(p * 0.8, TIME * 0.4) + PHASE) * 0.13;
}

// A cell's colour (rgb) and how strongly it shows (a). w: where on the grid (0..1).
vec4 shade_cell(vec4 s, vec2 c, vec2 w) {
    float cur = floor(s.r * 255.0 + 0.5);
    float fade = 0.0;
    if (STATES > 2.5 && cur > 1.5) fade = 1.0 - (cur - 1.0) / (STATES - 1.0);   // dying states fade out
    float inten = max(s.a, max(fade * 0.85, s.b * 0.7));
    float age = s.g * 255.0 / AGESPAN;
    vec3 col;
    if (MODE < 0.5) col = pal(age + PHASE);
    else if (MODE < 1.5) col = pal(w.x * 0.7 + w.y * 0.5 + PHASE);
    else if (MODE < 2.5) col = pal(PHASE);
    else if (MODE < 3.5) col = u_colour;
    else if (MODE < 4.5) col = hsv(age * 0.5 + w.x * 0.3 + PHASE);
    else if (MODE < 5.5) {                                              // fire
        float t = clamp(age * 0.6, 0.0, 1.0);
        col = mix(vec3(1.0, 0.97, 0.85), vec3(1.0, 0.72, 0.12), smoothstep(0.0, 0.3, t));
        col = mix(col, vec3(0.85, 0.16, 0.04), smoothstep(0.3, 0.9, t));
        if (s.a < 0.5) col = mix(vec3(0.45, 0.04, 0.0), vec3(1.0, 0.45, 0.05), s.b);   // embers
    } else if (MODE < 6.5) {                                            // neighbours
        float n = cell(c + vec2(-1.0, -1.0)).a + cell(c + vec2(0.0, -1.0)).a + cell(c + vec2(1.0, -1.0)).a
                + cell(c + vec2(-1.0, 0.0)).a + cell(c + vec2(1.0, 0.0)).a
                + cell(c + vec2(-1.0, 1.0)).a + cell(c + vec2(0.0, 1.0)).a + cell(c + vec2(1.0, 1.0)).a;
        col = pal(n / 8.0 + PHASE);
    } else if (MODE < 7.5) {                                            // rainbow ghosts
        col = s.a > 0.5 ? vec3(1.0) : hsv(s.b * 1.3 + PHASE);
    } else {                                                            // plasma
        col = pal(plasma(w * 1.5, TIME * 0.5) + PHASE);
    }
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
    bool planar = VIEW < 1.5;

    if (planar) {
        w = CAM + turn(p / ZOOM, ROT) / vec2(1.7777778, 1.0);
        if (WRAP < 0.5 && (w.x < 0.0 || w.y < 0.0 || w.x > 1.0 || w.y > 1.0)) { hit = false; col = bg * 0.5; }
    } else if (VIEW < 2.5) {                         // landscape: the grid as the ground, seen in perspective
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
    } else if (VIEW < 3.5) {                         // tunnel: the grid wrapped round a tube
        float r = length(p);
        w = vec2(atan(p.y, p.x) / 6.2831853 + ROT, 0.16 / max(r, 0.01) / ZOOM) + CAM;
        fog = 1.0 - smoothstep(0.02, 0.5, r);
    } else {                                         // globe
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
    }

    if (hit) {
        vec2 g = w * GRID;
        vec2 c = floor(g);
        vec2 f = fract(g) - 0.5;
        vec4 s = cell(c);
        vec4 cc = shade_cell(s, c, fract(w));
        float mask = 1.0;
        float cellpx = CELLPX * ZOOM;
        if (planar && cellpx >= 4.0) {                 // cell shapes, once cells are big enough to see
            vec2 a = abs(f);
            float px = 1.0 / cellpx;
            float r = SHAPE < 0.5 ? 0.0 : (SHAPE < 1.5 ? 0.25 : 0.5);
            float half_size = 0.5 - px * (SHAPE < 0.5 ? 0.5 : 0.25);
            vec2 q = a - vec2(half_size - r);
            float d = length(max(q, vec2(0.0))) + min(max(q.x, q.y), 0.0) - r;
            mask = 1.0 - smoothstep(0.0, px, d);
        }
        vec3 base = bg;
        if (VIEW > 0.5 && VIEW < 1.5) {               // raised blocks, lit from the top left
            if (cc.a > 0.05) {
                vec2 e = smoothstep(0.3, 0.5, abs(f)) * sign(f);
                light *= 1.0 + 0.45 * (e.y - e.x);
            } else {
                float sh = 0.0;                       // shadows of the blocks up and to the left
                if (f.x < -0.15 && f.y > 0.15) sh = cell(c + vec2(-1.0, 1.0)).a;
                if (f.x < -0.15 && f.y <= 0.15) sh = max(sh, cell(c + vec2(-1.0, 0.0)).a);
                if (f.x >= -0.15 && f.y > 0.15) sh = max(sh, cell(c + vec2(0.0, 1.0)).a);
                base *= 1.0 - 0.6 * sh;
            }
        }
        if (GLOW > 0.0 && planar && s.a < 0.5) {       // a soft halo from the live neighbours
            float halo = 0.0;
            for (int j = -1; j <= 1; j++) {
                for (int i = -1; i <= 1; i++) {
                    vec2 o = vec2(float(i), float(j));
                    halo += cell(c + o).a * max(0.0, 1.0 - length(f - o) / 1.6);
                }
            }
            base += shade_cell(vec4(1.0 / 255.0, s.g, 1.0, 1.0), c, fract(w)).rgb * DIM * halo * GLOW * 0.45;
        }
        col = mix(base, cc.rgb * DIM, cc.a * mask) * light;
        col = mix(col, fogcol, fog);
    }

    if (SCREENFX > 0.5) col *= 1.0 - 0.55 * dot(p * vec2(0.85, 1.25), p * vec2(0.85, 1.25));
    if (SCREENFX > 1.5) col *= 0.8 + 0.2 * sin(gl_FragCoord.y * 3.14159265);
    gl_FragColor = vec4(col, 1.0);
}
)";

// The clock on top: a soft-edged mask scaled up from the font masks, with a drop shadow.
// Premultiplied alpha.
const char* kClock = R"(
uniform sampler2D u_mask;
uniform vec4 u_rect;           // x, y, w, h in viewport uv
uniform vec4 u_ccol;           // rgb, opacity
varying vec2 v_uv;
float inside(vec2 q) { return step(0.0, q.x) * step(0.0, q.y) * step(q.x, 1.0) * step(q.y, 1.0); }
void main() {
    vec2 q = (v_uv - u_rect.xy) / u_rect.zw;
    vec2 sq = q + vec2(-0.006, 0.03);
    float m = inside(q) * smoothstep(0.4, 0.6, texture2D(u_mask, q).r);
    float s = inside(sq) * smoothstep(0.15, 0.85, texture2D(u_mask, sq).r);
    float a = clamp(m + s * 0.6 * (1.0 - m), 0.0, 1.0) * u_ccol.a;
    if (a < 0.003) discard;
    gl_FragColor = vec4(u_ccol.rgb * m * u_ccol.a, a);
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

// Saves what Kodi (or the harness) had bound and enabled, and puts it back.
struct SavedState {
    int fbo = 0, viewport[4] = {0, 0, 0, 0}, active_texture = 0, program = 0, array_buffer = 0;
    int blend_src_rgb = 0, blend_dst_rgb = 0, blend_src_a = 0, blend_dst_a = 0;
    bool blend, depth, cull, scissor;
    SavedState() {
        glGetIntegerv(GL_FRAMEBUFFER_BINDING, &fbo);
        glGetIntegerv(GL_VIEWPORT, viewport);
        glGetIntegerv(GL_ACTIVE_TEXTURE, &active_texture);
        glGetIntegerv(GL_CURRENT_PROGRAM, &program);
        glGetIntegerv(GL_ARRAY_BUFFER_BINDING, &array_buffer);
        glGetIntegerv(GL_BLEND_SRC_RGB, &blend_src_rgb);
        glGetIntegerv(GL_BLEND_DST_RGB, &blend_dst_rgb);
        glGetIntegerv(GL_BLEND_SRC_ALPHA, &blend_src_a);
        glGetIntegerv(GL_BLEND_DST_ALPHA, &blend_dst_a);
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
        glBlendFuncSeparate((unsigned)blend_src_rgb, (unsigned)blend_dst_rgb, (unsigned)blend_src_a, (unsigned)blend_dst_a);
        if (blend) glEnable(GL_BLEND); else glDisable(GL_BLEND);
        if (depth) glEnable(GL_DEPTH_TEST);
        if (cull) glEnable(GL_CULL_FACE);
        if (scissor) glEnable(GL_SCISSOR_TEST);
    }
};

double wrap01(double v) { return v - std::floor(v); }

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

bool App::init(const Settings& settings, unsigned seed, const std::string& fonts_json, std::string* error) {
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

    for (auto pf : {std::make_pair(&prog_update_, kUpdate), std::make_pair(&prog_init_, kInit),
                    std::make_pair(&prog_draw_, kDraw), std::make_pair(&prog_reduce_, kReduce),
                    std::make_pair(&prog_clock_, kClock)}) {
        *pf.first = link(pf.second, error);
        if (!*pf.first) return false;
    }

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

    // The clock: its font, and a texture its mask is drawn into whenever the time changes.
    has_font_ = false;
    if (s_.clock > 0 && !fonts_json.empty()) {
        try {
            font_ = sandclock::Font::load(fonts_json, sandclock::FONT_FOLDERS[std::max(0, std::min(8, s_.clock_font))],
                                          std::max(0, std::min(2, s_.clock_weight)));
            has_font_ = true;
        } catch (const std::exception& e) {
            *error = std::string("clock font: ") + e.what();   // not fatal: no clock
        }
    }
    glGenTextures(1, &clock_tex_);
    glBindTexture(GL_TEXTURE_2D, clock_tex_);
    unsigned char blank[4] = {0, 0, 0, 0};
    glTexImage2D(GL_TEXTURE_2D, 0, GL_RGBA, 1, 1, 0, GL_RGBA, GL_UNSIGNED_BYTE, blank);
    glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_MIN_FILTER, GL_LINEAR);
    glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_MAG_FILTER, GL_LINEAR);
    glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_WRAP_S, GL_CLAMP_TO_EDGE);
    glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_WRAP_T, GL_CLAMP_TO_EDGE);
    clock_text_.clear();

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
    if (clock_tex_) glDeleteTextures(1, &clock_tex_);
    if (vbo_) glDeleteBuffers(1, &vbo_);
#ifdef SANDCLOCK_CORE
    if (vao_) glDeleteVertexArrays(1, &vao_);
#endif
    for (unsigned* p : {&prog_update_, &prog_init_, &prog_draw_, &prog_reduce_, &prog_clock_})
        if (*p) glDeleteProgram(*p);
    prog_update_ = prog_init_ = prog_draw_ = prog_reduce_ = prog_clock_ = 0;
    vbo_ = vao_ = pal_tex_ = clock_tex_ = 0;
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
    if (s_.clock == 2) seed_pending_ = true;             // a fresh board starts with the time in it
}

void App::step(int n) {
    if (n <= 0) return;
    SavedState saved;
    glUseProgram(prog_update_);
    glViewport(0, 0, cols_, rows_);
    glUniform1i(u(prog_update_, "u_src"), 0);
    glUniform1i(u(prog_update_, "u_mask"), 1);
    glUniform4f(u(prog_update_, "u_a"), (float)cols_, (float)rows_, (float)rule_.birth, (float)rule_.survive);
    glUniform4f(u(prog_update_, "u_b"), (float)rule_.states, s_.wrap ? 1.f : 0.f, s_.trail / 100.0f, s_.sparks * 1e-6f);
    glUniform4f(u(prog_update_, "u_maskrect"), clock_rect_[0], clock_rect_[1], clock_rect_[2], clock_rect_[3]);
    int c_loc = u(prog_update_, "u_c");
    glActiveTexture(GL_TEXTURE1);
    glBindTexture(GL_TEXTURE_2D, clock_tex_);
    glActiveTexture(GL_TEXTURE0);
    bool clock_live = has_font_ && !clock_text_.empty();
    for (int i = 0; i < n; ++i) {
        float mode = 0;
        if (clock_live) {
            if (s_.clock == 2 && seed_pending_) { mode = 1; seed_pending_ = false; }
            else if (s_.clock == 3) mode = 2;
            else if (s_.clock == 4) mode = 3;
        }
        glUniform4f(c_loc, (float)(rng_() % 1000), mode, 0, 0);
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

// Draws the time into the mask texture (from the font's glyph masks, 128 px high plus a margin)
// and places it in the middle of the grid. The rect is sized from the widest time, so the clock
// does not change size when 9:59 becomes 10:00.
void App::update_clock(double clock) {
    if (!has_font_) return;
    std::string text = clock_text(s_, clock);
    if (text == clock_text_) return;
    clock_text_ = text;
    const int HC = 128, MARGIN = 6;
    double tw = font_.width(text), widest = font_.width(s_.seconds ? "88:88:88" : "88:88");
    int wc = (int)std::ceil(HC * tw / font_.h) + 2 * MARGIN, hc = HC + 2 * MARGIN;
    std::vector<uint8_t> px((size_t)wc * hc * 4, 0);
    double x0 = MARGIN;
    for (char ch : text) {
        double cw = font_.widths.at(ch) * HC / font_.h;
        const sandclock::Mask& m = font_.masks.at(ch);
        for (int x = (int)x0; x < (int)(x0 + cw) && x < wc; ++x) {
            int mu = std::min(m.w - 1, std::max(0, (int)((x + 0.5 - x0) / cw * m.w)));
            for (int y = 0; y < HC; ++y) {
                int mv = std::min(m.h - 1, (int)((y + 0.5) / HC * m.h));
                if (m.at(mu, mv)) {
                    int row = hc - 1 - (MARGIN + y);                 // texture rows go up
                    uint8_t* p = &px[((size_t)row * wc + x) * 4];
                    p[0] = p[1] = p[2] = p[3] = 255;
                }
            }
        }
        x0 += cw;
    }
    glActiveTexture(GL_TEXTURE1);
    glBindTexture(GL_TEXTURE_2D, clock_tex_);
    glPixelStorei(GL_UNPACK_ALIGNMENT, 1);
    glTexImage2D(GL_TEXTURE_2D, 0, GL_RGBA, wc, hc, 0, GL_RGBA, GL_UNSIGNED_BYTE, px.data());
    glActiveTexture(GL_TEXTURE0);

    double w = s_.clock_size / 100.0 * tw / widest;
    double h = w * hc / (double)wc * (16.0 / 9.0);
    if (h > 0.6) { w *= 0.6 / h; h = 0.6; }
    clock_rect_[0] = (float)(0.5 - w / 2);
    clock_rect_[1] = (float)(0.5 - h / 2);
    clock_rect_[2] = (float)w;
    clock_rect_[3] = (float)h;
    if (s_.clock == 2) seed_pending_ = true;
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
            } else {                                   // keep the view on the board
                double hx = 0.5 / zoom_, hy = 0.5 / zoom_;
                cam_x_ = std::max(hx, std::min(1 - hx, cam_x_));
                cam_y_ = std::max(hy, std::min(1 - hy, cam_y_));
            }
        }
    } else if (s_.view == 2) {                         // landscape: fly forward, turning with the camera
        if (s_.camera == 0) rot_ = 0;
        else if (s_.camera == 1) rot_ = 0.4 * std::sin(cam_t_ * 0.05);
        cam_x_ = wrap01(cam_x_ - std::sin(rot_) * 0.03 * speed * dt * (9.0 / 16.0));
        cam_y_ = wrap01(cam_y_ + std::cos(rot_) * 0.03 * speed * dt);
    } else if (s_.view == 3) {                         // tunnel: forward, and a slow roll
        cam_y_ = wrap01(cam_y_ + 0.06 * speed * dt);
        cam_x_ = wrap01(cam_x_ + (s_.camera == 0 ? 0.0 : 0.01 * speed * dt));
    } else {                                           // globe: spin
        cam_x_ = wrap01(cam_x_ + 0.012 * speed * dt);
        cam_y_ = 0;
    }
}

void App::render(double now, double clock, int fb_w, int fb_h) {
    if (!ready_) return;
    double dt = last_now_ < 0 ? 0.016 : std::min(0.25, std::max(0.0, now - last_now_));
    last_now_ = now;
    ema_dt_ += 0.1 * (dt - ema_dt_);
    if (s_.clock > 0) update_clock(clock);
    update_camera(dt);

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

    float phase = (float)std::fmod(now * s_.cycle / 100.0 * 0.5, 1.0);
    glUseProgram(prog_draw_);
    glActiveTexture(GL_TEXTURE0);
    glBindTexture(GL_TEXTURE_2D, state_[cur_].tex);
    glActiveTexture(GL_TEXTURE1);
    glBindTexture(GL_TEXTURE_2D, pal_tex_);
    glActiveTexture(GL_TEXTURE0);
    glUniform1i(u(prog_draw_, "u_state"), 0);
    glUniform1i(u(prog_draw_, "u_pal"), 1);
    glUniform4f(u(prog_draw_, "u_p0"), (float)s_.colour_mode, (float)s_.shape, (float)vw / cols_, phase);
    glUniform4f(u(prog_draw_, "u_p1"), (float)std::max(1, s_.age_span), 1.0f - s_.dim / 100.0f, (float)rule_.states,
                (float)std::fmod(now, 3600.0));
    glUniform4f(u(prog_draw_, "u_p2"), (float)s_.view, (float)zoom_, (float)rot_, s_.wrap ? 1.f : 0.f);
    glUniform4f(u(prog_draw_, "u_p3"), s_.glow / 100.0f, (float)s_.background_style, (float)s_.screen_fx, 0.f);
    glUniform4f(u(prog_draw_, "u_cg"), (float)cam_x_, (float)cam_y_, (float)cols_, (float)rows_);
    glUniform3f(u(prog_draw_, "u_colour"), ((s_.colour >> 16) & 255) / 255.f, ((s_.colour >> 8) & 255) / 255.f, (s_.colour & 255) / 255.f);
    glUniform3f(u(prog_draw_, "u_bg"), ((s_.background >> 16) & 255) / 255.f, ((s_.background >> 8) & 255) / 255.f, (s_.background & 255) / 255.f);
    draw_quad();

    // The clock on top (not for "made of living cells", where the cells are the clock).
    bool overlay = has_font_ && !clock_text_.empty() && (s_.clock == 1 || s_.clock == 2 || s_.clock == 3);
    if (overlay) {
        float r = 1, g = 1, b = 1;
        if (s_.clock_colour_mode == 1) {
            const uint32_t* p = PALETTE[std::max(0, std::min(PALETTE_COUNT - 1, s_.palette))];
            double t = phase * 7.0;
            int i0 = (int)t % 7, i1 = (i0 + 1) % 7;
            double f = t - std::floor(t);
            auto ch = [&](int shift) {
                return (float)((((p[i0] >> shift) & 255) * (1 - f) + ((p[i1] >> shift) & 255) * f) / 255.0);
            };
            r = ch(16); g = ch(8); b = ch(0);
        } else if (s_.clock_colour_mode == 2) {
            r = ((s_.clock_colour >> 16) & 255) / 255.f; g = ((s_.clock_colour >> 8) & 255) / 255.f; b = (s_.clock_colour & 255) / 255.f;
        }
        float dimf = 1.0f - s_.dim / 100.0f;
        float opacity = s_.clock_opacity / 100.0f * (s_.clock == 3 ? 0.35f : 1.0f);   // a cut-out clock is mostly the hole
        glEnable(GL_BLEND);
        glBlendFunc(GL_ONE, GL_ONE_MINUS_SRC_ALPHA);
        glUseProgram(prog_clock_);
        glActiveTexture(GL_TEXTURE1);
        glBindTexture(GL_TEXTURE_2D, clock_tex_);
        glActiveTexture(GL_TEXTURE0);
        glUniform1i(u(prog_clock_, "u_mask"), 1);
        glUniform4f(u(prog_clock_, "u_rect"), clock_rect_[0], clock_rect_[1], clock_rect_[2], clock_rect_[3]);
        glUniform4f(u(prog_clock_, "u_ccol"), r * dimf, g * dimf, b * dimf, opacity);
        draw_quad();
        glDisable(GL_BLEND);
    }
}

}  // namespace automata
}  // namespace sandclock
