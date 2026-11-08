#include "physarum_lite_app.hpp"

#include <algorithm>
#include <cmath>
#include <cstring>

#include "gl_util.hpp"

#ifndef GL_HALF_FLOAT_OES
#define GL_HALF_FLOAT_OES 0x8D61
#endif
#ifndef GL_RGBA16F
#define GL_RGBA16F 0x881A
#endif

namespace sandclock {
namespace physarum {
namespace lite {

using glu::SavedState;

namespace {

constexpr int FOOD_W = 640, FOOD_H = 360;
constexpr float DEG = 3.14159265f / 180.0f;

// The Custom sliders, in the units tools/make_settings_physarum_lite.py uses (the same units as
// the Physarum add-on).
Params from_custom(const Settings& s, float px) {
    Params p;
    p.sa = s.sa * DEG;
    p.ra = s.ra * DEG;
    p.so = std::max(1.0f, s.so * px);
    p.ss = std::max(0.05f, s.ss / 10.0f * px);
    p.decay = std::min(0.999f, std::max(0.5f, s.decay / 100.0f));
    p.diffuse = std::min(1.0f, std::max(0.0f, s.diffuse / 100.0f));
    p.deposit = std::max(0.01f, s.deposit / 100.0f);
    p.jitter = s.jitter * DEG;
    p.repel = std::min(1.0f, std::max(0.0f, s.repel / 100.0f));
    return p;
}

// Shared by the agent shaders: 16-bit fractions in two 8-bit channels, and a hash (Dave
// Hoskins's "hash without sine", which stays random with large inputs on mobile GPUs).
#define COMMON                                                                                       \
    "const float TAU = 6.2831853;\n"                                                                 \
    "float dec(vec2 v) { return (v.x * 65280.0 + v.y * 255.0) / 65535.0; }\n"                        \
    "vec2 enc(float v) { float e = floor(v * 65535.0 + 0.5); float hi = floor(e / 256.0);\n"         \
    "                    return vec2(hi, e - hi * 256.0) / 255.0; }\n"                               \
    "float hash(vec2 p, float s) {\n"                                                                \
    "    vec3 p3 = fract(vec3(p.xyx + s) * vec3(0.1031, 0.1030, 0.0973));\n"                         \
    "    p3 += dot(p3, p3.yzx + 33.33);\n"                                                           \
    "    return fract((p3.x + p3.y) * p3.z);\n"                                                      \
    "}\n"                                                                                            \
    "float pick(vec4 v, float s) { return s < 0.5 ? v.x : (s < 1.5 ? v.y : v.z); }\n"

// Sense and turn (Jones 2010): read the trail ahead, ahead-left and ahead-right; keep going if
// ahead is strongest, turn at random if it is weakest, else turn towards the stronger side. A
// species follows its own channel, avoids the others' (repel) and is drawn to food (alpha).
const char* kSense = COMMON R"(
uniform sampler2D u_pos;
uniform sampler2D u_head;
uniform sampler2D u_trail;
uniform vec4 u_a;      // agents w, h; trail w, h
uniform vec4 u_sa;     // sensor angle per species (radians)
uniform vec4 u_ra;     // turn per species
uniform vec4 u_so;     // sensor distance per species (trail px)
uniform vec4 u_b;      // species, repel, jitter (radians), seed
uniform vec4 u_ss;     // step per species (trail px)

float sense(vec2 p, float a, float d, vec4 w) {
    return dot(texture2D(u_trail, fract(p + vec2(cos(a), sin(a)) * d / u_a.zw)), w);
}

void main() {
    vec2 c = floor(gl_FragCoord.xy);
    vec2 uv = (c + 0.5) / u_a.xy;
    vec4 P = texture2D(u_pos, uv);
    vec2 p = vec2(dec(P.rg), dec(P.ba));
    float h = dec(texture2D(u_head, uv).rg) * TAU;
    float s = mod(c.y, u_b.x);
    float r = -u_b.y;
    vec4 w = s < 0.5 ? vec4(1.0, r, r, 1.0) : (s < 1.5 ? vec4(r, 1.0, r, 1.0) : vec4(r, r, 1.0, 1.0));
    float sa = pick(u_sa, s), ra = pick(u_ra, s), so = pick(u_so, s);
    float F = sense(p, h, so, w), L = sense(p, h + sa, so, w), R = sense(p, h - sa, so, w);
    if (!(F > L && F > R)) {
        if (F < L && F < R) h += hash(c, u_b.w) < 0.5 ? ra : -ra;
        else if (L > R) h += ra;
        else if (R > L) h -= ra;
    }
    h += (hash(c + 17.0, u_b.w) - 0.5) * 2.0 * u_b.z;
    gl_FragColor = vec4(enc(fract(h / TAU)), 0.0, 1.0);
}
)";

// Move one step along the (new) heading; the trail map wraps round.
const char* kMove = COMMON R"(
uniform sampler2D u_pos;
uniform sampler2D u_head;
uniform vec4 u_a;      // agents w, h; trail w, h
uniform vec4 u_ss;     // step per species (trail px)
uniform vec4 u_m;      // species

void main() {
    vec2 c = floor(gl_FragCoord.xy);
    vec2 uv = (c + 0.5) / u_a.xy;
    vec4 P = texture2D(u_pos, uv);
    vec2 p = vec2(dec(P.rg), dec(P.ba));
    float h = dec(texture2D(u_head, uv).rg) * TAU;
    float s = mod(c.y, u_m.x);
    vec2 np = fract(p + vec2(cos(h), sin(h)) * pick(u_ss, s) / u_a.zw);
    gl_FragColor = vec4(enc(np.x), enc(np.y));
}
)";

// Deposit: every agent is a 1 px point at its position, added into its species' channel.
const char* kDepositVertex = R"(
attribute vec2 a0;     // the agent's texel, within the block
uniform sampler2D u_pos;
uniform vec4 u_d;      // agents w, h, first row of the block, species
uniform float u_amt;
varying vec4 v_col;
float dec(vec2 v) { return (v.x * 65280.0 + v.y * 255.0) / 65535.0; }
void main() {
    vec2 t = a0 + vec2(0.0, u_d.z);
    vec4 P = texture2D(u_pos, (t + 0.5) / u_d.xy);
    vec2 p = vec2(dec(P.rg), dec(P.ba));
    float s = mod(t.y, u_d.w);
    v_col = (s < 0.5 ? vec4(1.0, 0.0, 0.0, 0.0) : (s < 1.5 ? vec4(0.0, 1.0, 0.0, 0.0) : vec4(0.0, 0.0, 1.0, 0.0))) * u_amt;
    gl_Position = vec4(p * 2.0 - 1.0, 0.0, 1.0);
#ifdef GL_ES
    gl_PointSize = 1.0;
#endif
}
)";
const char* kDepositFragment = R"(
varying vec4 v_col;
void main() { gl_FragColor = v_col; }
)";

// Diffuse (3x3 mean, mixed in by u_t.w), decay, and feed: food sources (food G) add to the food
// channel, which always diffuses fully and fades slowly so its scent reaches the slime. u_q is the
// 8-bit floor that lets faint trails reach 0.
const char* kDiffuse = R"(
uniform sampler2D u_trail;
uniform sampler2D u_food;
uniform vec4 u_t;      // trail w, h, kept per step, diffusion
uniform float u_node_food;
uniform vec4 u_q;      // 8-bit floor, food kept per step
void main() {
    vec2 px = 1.0 / u_t.xy;
    vec2 uv = (floor(gl_FragCoord.xy) + 0.5) * px;
    vec4 centre = texture2D(u_trail, uv);
    vec4 sum = vec4(0.0);
    for (int j = -1; j <= 1; j++)
        for (int i = -1; i <= 1; i++)
            sum += texture2D(u_trail, fract(uv + vec2(float(i), float(j)) * px));
    vec4 v = mix(centre, sum / 9.0, u_t.w) * u_t.z - u_q.x;
    v.a = sum.a / 9.0 * u_q.y - u_q.x;            // food spreads on its own terms
    vec4 f = texture2D(u_food, uv);
    v.a += f.g * u_node_food;
    gl_FragColor = clamp(v, 0.0, 1.0);
}
)";

// Starting positions (u_j.x 0) and headings (1), computed from the same hashes so they agree.
// Unlike the full Physarum add-on there is no clock to start from.
const char* kInit = COMMON R"(
uniform vec4 u_i;      // agents w, h, start mode, seed
uniform vec4 u_j;      // what (0 position, 1 heading), species, trail aspect (w / h)
void main() {
    vec2 c = floor(gl_FragCoord.xy);
    float sd = u_i.w;
    float r1 = hash(c, sd), r2 = hash(c + 11.0, sd), r3 = hash(c + 23.0, sd), r4 = hash(c + 37.0, sd);
    float m = u_i.z, n = u_j.y, s = mod(c.y, n);
    vec2 asp = vec2(1.0 / u_j.z, 1.0);              // a circle on screen
    float a = r1 * TAU;
    vec2 dir = vec2(cos(a), sin(a)) * asp;
    vec2 p = vec2(r1, r2);
    float h = r3;
    if (m < 0.5) {
        p = vec2(r1, r2);
    } else if (m < 1.5) {                           // disc
        p = 0.5 + dir * sqrt(r2) * 0.22;
    } else if (m < 2.5) {                           // ring, facing in
        p = 0.5 + dir * (0.4 + 0.03 * r2);
        h = fract(r1 + 0.5);
    } else if (m < 3.5) {                           // colonies
        float k = floor(r4 * 9.0);
        vec2 o = vec2(hash(vec2(k, 1.0), sd), hash(vec2(k, 2.0), sd));
        p = 0.1 + 0.8 * o + dir * sqrt(r2) * 0.05;
    } else if (m < 4.5) {                           // big bang, facing out
        p = 0.5 + dir * 0.004 * r2;
        h = r1;
    } else {                                        // each species in its own third
        p = vec2((s + r1) / n, r2);
    }
    p = fract(p);
    gl_FragColor = u_j.x < 0.5 ? vec4(enc(p.x), enc(p.y)) : vec4(enc(fract(h)), 0.0, 1.0);
}
)";

// What is on screen: each pixel maps to a point on the trail map (flat with a camera, or a
// 3D-looking view) and the trail there is coloured.
const char* kDraw = R"(
uniform sampler2D u_trail;
uniform sampler2D u_pal;       // 8 x 1: the 7 palette colours and the first again
uniform vec4 u_p0;             // colour mode, palette phase, gain, time
uniform vec4 u_p1;             // view, zoom, turn, glow
uniform vec4 u_p2;             // camera x, y (trail uv), trail w, h
uniform vec4 u_p3;             // species, dim, screen effect, food shown
uniform vec3 u_c0;
uniform vec3 u_c1;
uniform vec3 u_c2;
uniform vec3 u_colour;
uniform vec3 u_bg;
varying vec2 v_uv;

#define MODE u_p0.x
#define PHASE u_p0.y
#define GAIN u_p0.z
#define TIME u_p0.w
#define VIEW u_p1.x
#define ZOOM u_p1.y
#define ROT u_p1.z
#define GLOW u_p1.w
#define CAM u_p2.xy
#define GRID u_p2.zw
#define SPECIES u_p3.x
#define DIM u_p3.y
#define SCREENFX u_p3.z
#define FOODSHOW u_p3.w

vec3 pal(float t) { return texture2D(u_pal, vec2((fract(t) * 7.0 + 0.5) / 8.0, 0.5)).rgb; }
vec3 hsv(float h) {
    vec3 k = clamp(abs(fract(vec3(h) + vec3(1.0, 2.0 / 3.0, 1.0 / 3.0)) * 6.0 - 3.0) - 1.0, 0.0, 1.0);
    return mix(vec3(1.0), k, 0.8);
}
float plasma(vec2 q, float t) {
    return 0.5 + 0.25 * sin(q.x * 9.0 + t) + 0.25 * sin(q.y * 7.0 - t * 1.3 + 2.0 * sin(q.x * 3.0 + t * 0.5));
}
vec2 turn(vec2 v, float a) { float s = sin(a), k = cos(a); return vec2(k * v.x - s * v.y, s * v.x + k * v.y); }
vec4 tr(vec2 w) { return texture2D(u_trail, fract(w)); }
float tone(float x) { return 1.0 - exp(-x * GAIN * 2.5); }
bool ink() { return MODE > 3.5 && MODE < 4.5; }

// Light given off by trail t at w (rgb) and how dense it is (a).
vec4 emit(vec4 t, vec2 w) {
    vec3 v = vec3(tone(t.r), tone(t.g), tone(t.b));
    float d = tone(t.r + t.g + t.b);
    vec3 sp = SPECIES < 1.5 ? u_c0 * v.x : u_c0 * v.x + u_c1 * v.y + u_c2 * v.z;
    vec3 col;
    if (MODE < 0.5) col = SPECIES < 1.5 ? pal(d * 0.85 + PHASE) * d : sp + vec3(pow(d, 4.0) * 0.4);
    else if (MODE < 1.5) col = sp + vec3(pow(d, 4.0) * 0.5);
    else if (MODE < 2.5) col = clamp(vec3(d * 1.7, d * d * 1.5, pow(d, 4.0) * 1.3), 0.0, 1.0);
    else if (MODE < 3.5) col = sp * 0.85 + vec3(pow(d, 3.0) * 0.9);
    else if (MODE < 4.5) col = SPECIES < 1.5 ? vec3(0.06, 0.08, 0.16) : sp / max(d, 0.001) * 0.4;
    else if (MODE < 5.5) col = u_colour * d + vec3(pow(d, 5.0) * 0.4);
    else if (MODE < 6.5) col = hsv(w.x * 0.6 + w.y * 0.35 + PHASE + d * 0.15) * d;
    else col = pal(plasma(w * 2.0, TIME * 0.5) + PHASE) * d;
    if (!ink()) col += u_c0 * tone(t.a) * FOODSHOW;
    return vec4(col, d);
}

float height(vec2 w) { vec4 t = tr(w); return tone(t.r + t.g + t.b + t.a * 0.5); }

void main() {
    vec2 p = (v_uv - 0.5) * vec2(1.7777778, 1.0);   // screen: height 1, centre 0
    vec3 bg = ink() ? vec3(0.93, 0.91, 0.85) : u_bg;
    vec3 col = bg;
    float light = 1.0, fog = 0.0;
    vec3 fogcol = bg;
    vec2 w = vec2(0.0);
    bool hit = true, lit = VIEW > 0.5 && VIEW < 2.5;

    if (VIEW < 1.5) {
        w = CAM + turn(p / ZOOM, ROT) / vec2(1.7777778, 1.0);
    } else if (VIEW < 2.5) {                         // landscape
        float horizon = 0.14;
        fogcol = bg + u_c0 * 0.2;
        if (p.y > horizon - 0.003) {
            hit = false;
            col = mix(fogcol, bg, clamp((p.y - horizon) * 2.5, 0.0, 1.0));
        } else {
            float z = 0.3 / (horizon - p.y);
            w = CAM + turn(vec2(p.x * z, z), ROT) * 0.8 / ZOOM / vec2(1.7777778, 1.0);
            fog = 1.0 - exp(-z * 0.12);
        }
    } else if (VIEW < 3.5) {                         // tunnel
        float r = length(p);
        w = vec2(atan(p.y, p.x) / 6.2831853 + ROT, 0.16 / max(r, 0.01) / ZOOM) + CAM;
        fog = 1.0 - smoothstep(0.02, 0.5, r);
    } else {                                         // globe
        float R = 0.44;
        float r = length(p);
        if (r > R) {
            hit = false;
            col = bg + u_c0 * 0.35 * smoothstep(R + 0.07, R, r);
        } else {
            vec3 n = vec3(p, sqrt(R * R - r * r)) / R;
            w = vec2(atan(n.x, n.z) / 6.2831853 + CAM.x, asin(clamp(n.y, -1.0, 1.0)) / 3.14159265 + 0.5);
            light = 0.2 + 0.95 * max(dot(n, normalize(vec3(-0.45, 0.5, 0.75))), 0.0);
            fog = pow(1.0 - n.z, 3.0) * 0.55;
            fogcol = u_c0 * 0.5 + 0.1;
        }
    }

    if (hit) {
        vec4 t = tr(w);
        vec4 e = emit(t, w);
        vec3 g = vec3(0.0);
        float ga = 0.0;
        if (GLOW > 0.0) {                            // a soft halo
            vec4 b = vec4(0.0);
            vec2 px = 1.0 / GRID;
            for (int i = 0; i < 8; i++) {            // one ring; bilinear filtering softens it
                float a = float(i) * 0.785398 + 0.39;
                b += tr(w + vec2(cos(a), sin(a)) * px * 5.0);
            }
            vec4 ge = emit(b / 8.0, w);
            g = ge.rgb * GLOW;
            ga = ge.a * GLOW;
        }
        if (ink()) {
            col = mix(bg, e.rgb, e.a);
            col = mix(col, e.rgb, ga * 0.25 * (1.0 - e.a));
        } else {
            col = bg + e.rgb + g * 0.9;
        }
        if (lit) {                                   // relief: light the trail as a surface
            vec2 o = 1.5 / GRID;
            float hl = height(w - vec2(o.x, 0.0)), hr = height(w + vec2(o.x, 0.0));
            float hd = height(w - vec2(0.0, o.y)), hu = height(w + vec2(0.0, o.y));
            vec3 n = normalize(vec3(hl - hr, hd - hu, 0.35));
            vec3 L = normalize(vec3(-0.5, 0.6, 0.65));
            float diff = max(dot(n, L), 0.0);
            float spec = pow(max(dot(reflect(-L, n), vec3(0.0, 0.0, 1.0)), 0.0), 24.0);
            light *= 0.25 + 0.95 * diff;
            col += vec3(spec * 0.35 * e.a);
        }
        col = mix(col * light, fogcol, fog);
    }
    col *= DIM;
    if (SCREENFX > 0.5) col *= 1.0 - 0.55 * dot(p * vec2(0.85, 1.25), p * vec2(0.85, 1.25));
    if (SCREENFX > 1.5) col *= 0.8 + 0.2 * sin(gl_FragCoord.y * 3.14159265);
    gl_FragColor = vec4(col, 1.0);
}
)";

double wrap01(double v) { return v - std::floor(v); }

// The draw pass renders into a small target (the trail map is far smaller than the screen); this
// scales it up to the framebuffer with one bilinear sample a pixel.
const char* kUpscale = R"(
uniform sampler2D u_tex;
varying vec2 v_uv;
void main() { gl_FragColor = texture2D(u_tex, v_uv); }
)";

bool has_extension(const char* name) {
#if defined(SANDCLOCK_GLES) || (defined(SANDCLOCK_KODI) && defined(HAS_GLES))
    const char* e = (const char*)glGetString(GL_EXTENSIONS);
    return e && std::strstr(e, name);
#else
    (void)name;
    return true;   // desktop GL 2.1 (ARB_texture_float on every Mac) and 3.2 core have RGBA16F
#endif
}

bool gles() {
#if defined(SANDCLOCK_GLES) || (defined(SANDCLOCK_KODI) && defined(HAS_GLES))
    return true;
#else
    return false;
#endif
}

void colour3(uint32_t c, float* out) {
    out[0] = ((c >> 16) & 255) / 255.f;
    out[1] = ((c >> 8) & 255) / 255.f;
    out[2] = (c & 255) / 255.f;
}

void palette_at(const uint32_t* p, double t, float* out) {
    t = wrap01(t) * 7.0;
    int i0 = (int)t % 7, i1 = (i0 + 1) % 7;
    double f = t - std::floor(t);
    for (int k = 0; k < 3; ++k) {
        int sh = 16 - 8 * k;
        out[k] = (float)((((p[i0] >> sh) & 255) * (1 - f) + ((p[i1] >> sh) & 255) * f) / 255.0);
    }
}

}  // namespace

Params params_for(const Settings& s, float px_scale) {
    if (s.preset >= PRESET_COUNT) return from_custom(s, px_scale);
    return from_def(PRESETS[std::max(0, std::min(PRESET_COUNT - 1, s.preset))], px_scale);
}

bool App::force_rgba8 = false;
int App::draw_cap_w = 1920, App::draw_cap_h = 1080;

App::~App() { release(); }

int App::u(unsigned prog, const char* name) const { return glGetUniformLocation(prog, name); }

bool App::make_target(Target* t, int w, int h, bool linear, bool half) {
    t->w = w;
    t->h = h;
    glGenTextures(1, &t->tex);
    glBindTexture(GL_TEXTURE_2D, t->tex);
    if (half) {
        if (gles()) glTexImage2D(GL_TEXTURE_2D, 0, GL_RGBA, w, h, 0, GL_RGBA, GL_HALF_FLOAT_OES, nullptr);
        else glTexImage2D(GL_TEXTURE_2D, 0, GL_RGBA16F, w, h, 0, GL_RGBA, GL_FLOAT, nullptr);
    } else {
        glTexImage2D(GL_TEXTURE_2D, 0, GL_RGBA, w, h, 0, GL_RGBA, GL_UNSIGNED_BYTE, nullptr);
    }
    glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_MIN_FILTER, linear ? GL_LINEAR : GL_NEAREST);
    glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_MAG_FILTER, linear ? GL_LINEAR : GL_NEAREST);
    glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_WRAP_S, GL_CLAMP_TO_EDGE);
    glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_WRAP_T, GL_CLAMP_TO_EDGE);
    glGenFramebuffers(1, &t->fbo);
    glBindFramebuffer(GL_FRAMEBUFFER, t->fbo);
    glFramebufferTexture2D(GL_FRAMEBUFFER, GL_COLOR_ATTACHMENT0, GL_TEXTURE_2D, t->tex, 0);
    bool ok = glCheckFramebufferStatus(GL_FRAMEBUFFER) == GL_FRAMEBUFFER_COMPLETE && glGetError() == GL_NO_ERROR;
    if (ok) {
        glViewport(0, 0, w, h);
        glClearColor(0, 0, 0, 0);
        glClear(GL_COLOR_BUFFER_BIT);
    }
    return ok;
}

static void free_target(unsigned* tex, unsigned* fbo) {
    if (*fbo) glDeleteFramebuffers(1, fbo);
    if (*tex) glDeleteTextures(1, tex);
    *tex = *fbo = 0;
}

bool App::init(const Settings& settings, unsigned seed, std::string* error) {
    release();
    SavedState saved;
    s_ = settings;
    rng_.seed(seed);
    species_ = std::max(1, std::min(3, s_.species + 1));
    preset_ = std::max(0, std::min(PRESET_COUNT, s_.preset));
    while (glGetError() != GL_NO_ERROR) {}

    int vtf = 0;
    glGetIntegerv(GL_MAX_VERTEX_TEXTURE_IMAGE_UNITS, &vtf);
    if (vtf < 1) {
        *error = "this GPU cannot read textures in vertex shaders, which drawing the agents needs";
        return false;
    }

    int max_tex = 2048;
    glGetIntegerv(GL_MAX_TEXTURE_SIZE, &max_tex);

    const char* frag[] = {kSense, kMove, kDiffuse, kInit, kDraw, kUpscale};
    unsigned* progs[] = {&prog_sense_, &prog_move_, &prog_diffuse_, &prog_init_, &prog_draw_, &prog_upscale_};
    for (int i = 0; i < 6; ++i) {
        *progs[i] = glu::link(nullptr, frag[i], error);
        if (!*progs[i]) return false;
    }
    prog_deposit_ = glu::link(kDepositVertex, kDepositFragment, error);
    if (!prog_deposit_) return false;

    static const float quad[8] = {-1, -1, 1, -1, -1, 1, 1, 1};
    glGenBuffers(1, &vbo_);
    glBindBuffer(GL_ARRAY_BUFFER, vbo_);
    glBufferData(GL_ARRAY_BUFFER, sizeof quad, quad, GL_STATIC_DRAW);
#ifdef SANDCLOCK_CORE
    glGenVertexArrays(1, &vao_);
#endif

    // The trail map: half floats where the device can render and blend them (smoother faint
    // trails), otherwise RGBA8.
    int ti = std::max(0, std::min(TRAIL_COUNT - 1, s_.trail));
    while (ti > 0 && TRAIL_SIZES[ti].w > max_tex) --ti;
    tw_ = TRAIL_SIZES[ti].w;
    th_ = TRAIL_SIZES[ti].h;
    bool half_ok = gles() ? has_extension("GL_OES_texture_half_float") && has_extension("GL_EXT_color_buffer_half_float")
                          : true;
    bool half_linear = !gles() || has_extension("GL_OES_texture_half_float_linear");
    half_ = false;
    if (half_ok && half_linear && !force_rgba8) {
        half_ = make_target(&trail_[0], tw_, th_, true, true) && make_target(&trail_[1], tw_, th_, true, true);
        if (!half_) {
            for (Target& t : trail_) { free_target(&t.tex, &t.fbo); t = Target(); }
            while (glGetError() != GL_NO_ERROR) {}
        }
    }
    if (!half_ && (!make_target(&trail_[0], tw_, th_, true, false) || !make_target(&trail_[1], tw_, th_, true, false))) {
        *error = "cannot make a " + std::to_string(tw_) + "x" + std::to_string(th_) + " trail map to render to";
        return false;
    }

    // The agents: as many as asked, or the most the device will give.
    for (int ai = std::max(0, std::min(AGENT_COUNT - 1, s_.agents)); ai >= 0; --ai) {
        if (AGENT_SIZES[ai].w > max_tex || AGENT_SIZES[ai].h > max_tex) continue;
        aw_ = AGENT_SIZES[ai].w;
        ah_ = AGENT_SIZES[ai].h;
        bool ok = true;
        for (Target* t : {&pos_[0], &pos_[1], &head_[0], &head_[1]}) ok = ok && make_target(t, aw_, ah_, false, false);
        if (ok) break;
        for (Target* t : {&pos_[0], &pos_[1], &head_[0], &head_[1]}) { free_target(&t->tex, &t->fbo); *t = Target(); }
        while (glGetError() != GL_NO_ERROR) {}
        aw_ = ah_ = 0;
    }
    if (!aw_) { *error = "cannot make the agent textures"; return false; }

    // The deposit pass draws the agents a block of rows at a time from one small vertex buffer.
    block_rows_ = std::max(1, std::min(ah_, 262144 / aw_));
    std::vector<float> pts((size_t)aw_ * block_rows_ * 2);
    for (int y = 0; y < block_rows_; ++y)
        for (int x = 0; x < aw_; ++x) {
            pts[((size_t)y * aw_ + x) * 2] = (float)x;
            pts[((size_t)y * aw_ + x) * 2 + 1] = (float)y;
        }
    glGenBuffers(1, &points_vbo_);
    glBindBuffer(GL_ARRAY_BUFFER, points_vbo_);
    glBufferData(GL_ARRAY_BUFFER, (long)(pts.size() * sizeof(float)), pts.data(), GL_STATIC_DRAW);

    px_scale_ = tw_ / 960.0f * std::max(40, std::min(300, s_.scale)) / 100.0f;
    params_ = params_for(s_, px_scale_);

    glGenTextures(1, &pal_tex_);
    set_palette();

    glGenTextures(1, &food_tex_);
    glBindTexture(GL_TEXTURE_2D, food_tex_);
    unsigned char blank[4] = {0, 0, 0, 0};
    glTexImage2D(GL_TEXTURE_2D, 0, GL_RGBA, 1, 1, 0, GL_RGBA, GL_UNSIGNED_BYTE, blank);
    glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_MIN_FILTER, GL_LINEAR);
    glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_MAG_FILTER, GL_LINEAR);
    glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_WRAP_S, GL_CLAMP_TO_EDGE);
    glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_WRAP_T, GL_CLAMP_TO_EDGE);
    nodes_.clear();
    build_food();

    pace_ = std::max(1, std::min(4, s_.pace));
    frames_since_step_ = 0;
    ready_ = true;
    restart();
    return true;
}

void App::release() {
    for (Target* t : {&pos_[0], &pos_[1], &head_[0], &head_[1], &trail_[0], &trail_[1], &draw_}) {
        free_target(&t->tex, &t->fbo);
        *t = Target();
    }
    for (unsigned* t : {&pal_tex_, &food_tex_})
        if (*t) glDeleteTextures(1, t);
    for (unsigned* b : {&vbo_, &points_vbo_})
        if (*b) glDeleteBuffers(1, b);
#ifdef SANDCLOCK_CORE
    if (vao_) glDeleteVertexArrays(1, &vao_);
#endif
    for (unsigned* p : {&prog_sense_, &prog_move_, &prog_deposit_, &prog_diffuse_, &prog_init_, &prog_draw_,
                        &prog_upscale_}) {
        if (*p) glDeleteProgram(*p);
        *p = 0;
    }
    vbo_ = points_vbo_ = vao_ = pal_tex_ = food_tex_ = 0;
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

static void bind(unsigned unit, unsigned tex) {
    glActiveTexture(GL_TEXTURE0 + unit);
    glBindTexture(GL_TEXTURE_2D, tex);
}

// The food map (FOOD_W x FOOD_H over the whole screen): G is the food sources.
void App::build_food() {
    std::vector<uint8_t> px((size_t)FOOD_W * FOOD_H * 4, 0);
    const double R = 5.0;                                      // food source radius, food px
    for (size_t i = 0; i + 1 < nodes_.size(); i += 2) {
        double cx = nodes_[i] * FOOD_W, cy = nodes_[i + 1] * FOOD_H;
        for (int y = (int)(cy - R - 1); y <= (int)(cy + R + 1); ++y)
            for (int x = (int)(cx - R - 1); x <= (int)(cx + R + 1); ++x) {
                if (x < 0 || y < 0 || x >= FOOD_W || y >= FOOD_H) continue;
                double d = std::hypot(x + 0.5 - cx, y + 0.5 - cy);
                double v = std::min(1.0, std::max(0.0, R - d + 0.5));
                uint8_t& g = px[((size_t)y * FOOD_W + x) * 4 + 1];
                g = std::max(g, (uint8_t)(v * 255));
            }
    }
    glActiveTexture(GL_TEXTURE3);
    glBindTexture(GL_TEXTURE_2D, food_tex_);
    glPixelStorei(GL_UNPACK_ALIGNMENT, 1);
    glTexImage2D(GL_TEXTURE_2D, 0, GL_RGBA, FOOD_W, FOOD_H, 0, GL_RGBA, GL_UNSIGNED_BYTE, px.data());
    glActiveTexture(GL_TEXTURE0);
}

void App::restart() {
    SavedState saved;
    // Food sources.
    nodes_.clear();
    std::uniform_real_distribution<double> U(0, 1);
    if (s_.food == 1) {
        int n = std::max(3, std::min(40, s_.food_nodes));
        for (int tries = 0; tries < 4000 && (int)nodes_.size() < 2 * n; ++tries) {
            double x = 0.06 + 0.88 * U(rng_), y = 0.08 + 0.84 * U(rng_);
            bool clear = true;
            for (size_t i = 0; i < nodes_.size(); i += 2)
                clear = clear && std::hypot((x - nodes_[i]) * 16 / 9.0, y - nodes_[i + 1]) > 0.09;
            if (clear) { nodes_.push_back((float)x); nodes_.push_back((float)y); }
        }
    } else if (s_.food == 2) {
        for (int i = 0; i < 14; ++i) {
            double a = i * 6.2831853 / 14;
            nodes_.push_back((float)(0.5 + std::cos(a) * 0.4 * 9 / 16.0));
            nodes_.push_back((float)(0.5 + std::sin(a) * 0.4));
        }
    } else if (s_.food == 3) {
        for (int y = 0; y < 4; ++y)
            for (int x = 0; x < 6; ++x) {
                nodes_.push_back((float)((x + 0.5) / 6));
                nodes_.push_back((float)((y + 0.5) / 4));
            }
    }
    build_food();

    // Agents.
    int mode = std::max(0, std::min(LITE_START_COUNT - 1, s_.start));
    glUseProgram(prog_init_);
    glUniform4f(u(prog_init_, "u_i"), (float)aw_, (float)ah_, (float)mode, (float)(rng_() % 1000));
    glViewport(0, 0, aw_, ah_);
    for (int what = 0; what < 2; ++what) {
        glUniform4f(u(prog_init_, "u_j"), (float)what, (float)species_, (float)tw_ / th_, 0.f);
        glBindFramebuffer(GL_FRAMEBUFFER, what == 0 ? pos_[cp_].fbo : head_[ch_].fbo);
        draw_quad();
    }
    for (Target& t : trail_) {
        glBindFramebuffer(GL_FRAMEBUFFER, t.fbo);
        glViewport(0, 0, tw_, th_);
        glClearColor(0, 0, 0, 0);
        glClear(GL_COLOR_BUFFER_BIT);
    }
}

int App::deposit_stride() const {
    long agents = (long)aw_ * ah_;
    int blocks = (ah_ + block_rows_ - 1) / block_rows_;
    return (int)std::max(1L, std::min((long)blocks, (agents + DEPOSIT_BUDGET - 1) / DEPOSIT_BUDGET));
}

float App::deposit_amount(const Params& p) const {
    double per_px = (double)aw_ * ah_ / ((double)tw_ * th_);           // agents per trail pixel
    double d = p.deposit * (1.0 - p.decay) * 0.5 / std::max(0.01, per_px);
    double lo = half_ ? 0.0005 : 1.6 / 255.0;                         // below this an 8-bit add rounds away
    return (float)std::min(1.0, std::max(lo, d));
}

void App::step(int n, const Params& p) {
    SavedState saved;
    step_saved(n, p);
}

// Expects a glu::SavedState to be in force (it has turned blending, depth, cull and scissor off).
void App::step_saved(int n, const Params& base) {
    if (n <= 0) return;
    Params sp[3];
    for (int i = 0; i < 3; ++i) sp[i] = for_species(base, i, s_.species_differ);
    float node_food = nodes_.empty() ? 0.0f : 0.06f;
    float amount = deposit_amount(base);

    glUseProgram(prog_sense_);
    glUniform1i(u(prog_sense_, "u_pos"), 0);
    glUniform1i(u(prog_sense_, "u_head"), 1);
    glUniform1i(u(prog_sense_, "u_trail"), 2);
    glUniform4f(u(prog_sense_, "u_a"), (float)aw_, (float)ah_, (float)tw_, (float)th_);
    glUniform4f(u(prog_sense_, "u_sa"), sp[0].sa, sp[1].sa, sp[2].sa, 0);
    glUniform4f(u(prog_sense_, "u_ra"), sp[0].ra, sp[1].ra, sp[2].ra, 0);
    glUniform4f(u(prog_sense_, "u_so"), sp[0].so, sp[1].so, sp[2].so, 0);
    glUniform4f(u(prog_sense_, "u_ss"), sp[0].ss, sp[1].ss, sp[2].ss, 0);
    int sense_b = u(prog_sense_, "u_b");

    glUseProgram(prog_move_);
    glUniform1i(u(prog_move_, "u_pos"), 0);
    glUniform1i(u(prog_move_, "u_head"), 1);
    glUniform4f(u(prog_move_, "u_a"), (float)aw_, (float)ah_, (float)tw_, (float)th_);
    glUniform4f(u(prog_move_, "u_ss"), sp[0].ss, sp[1].ss, sp[2].ss, 0);
    glUniform4f(u(prog_move_, "u_m"), (float)species_, 0, 0, 0);

    glUseProgram(prog_deposit_);
    glUniform1i(u(prog_deposit_, "u_pos"), 0);
    int dep_d = u(prog_deposit_, "u_d"), dep_amt = u(prog_deposit_, "u_amt");

    glUseProgram(prog_diffuse_);
    glUniform1i(u(prog_diffuse_, "u_trail"), 2);
    glUniform1i(u(prog_diffuse_, "u_food"), 3);
    glUniform4f(u(prog_diffuse_, "u_t"), (float)tw_, (float)th_, base.decay, base.diffuse);
    glUniform1f(u(prog_diffuse_, "u_node_food"), node_food);
    glUniform4f(u(prog_diffuse_, "u_q"), half_ ? 0.0f : 0.5f / 255.0f, 0.97f, 0, 0);

    bind(3, food_tex_);
    for (int i = 0; i < n; ++i) {
        // 1. Sense and turn.
        glUseProgram(prog_sense_);
        glUniform4f(sense_b, (float)species_, base.repel, base.jitter, (float)(rng_() % 1000) + 0.5f);
        glBindFramebuffer(GL_FRAMEBUFFER, head_[1 - ch_].fbo);
        glViewport(0, 0, aw_, ah_);
        bind(0, pos_[cp_].tex);
        bind(1, head_[ch_].tex);
        bind(2, trail_[ct_].tex);
        draw_quad();
        ch_ = 1 - ch_;

        // 2. Move.
        glUseProgram(prog_move_);
        glBindFramebuffer(GL_FRAMEBUFFER, pos_[1 - cp_].fbo);
        bind(1, head_[ch_].tex);
        draw_quad();
        cp_ = 1 - cp_;

        // 3. Deposit.
        // Points blended into the same pixels are the slow part on tile-based GPUs, so above
        // DEPOSIT_BUDGET agents each step deposits a rotating 1/k of them, k times as much.
        int k = deposit_stride();
        glUseProgram(prog_deposit_);
        glUniform1f(dep_amt, amount * k);
        glBindFramebuffer(GL_FRAMEBUFFER, trail_[ct_].fbo);
        glViewport(0, 0, tw_, th_);
        bind(2, 0);
        bind(0, pos_[cp_].tex);
        glEnable(GL_BLEND);
        glBlendFunc(GL_ONE, GL_ONE);
#ifdef SANDCLOCK_CORE
        glBindVertexArray(vao_);
#endif
        glBindBuffer(GL_ARRAY_BUFFER, points_vbo_);
        glEnableVertexAttribArray(0);
        glVertexAttribPointer(0, 2, GL_FLOAT, GL_FALSE, 0, (const void*)0);
        int phase = (int)(steps_ % k), block = 0;
        for (int row = 0; row < ah_; row += block_rows_, ++block) {
            if (block % k != phase) continue;
            glUniform4f(dep_d, (float)aw_, (float)ah_, (float)row, (float)species_);
            glDrawArrays(GL_POINTS, 0, aw_ * std::min(block_rows_, ah_ - row));
        }
        glDisableVertexAttribArray(0);
#ifdef SANDCLOCK_CORE
        glBindVertexArray(0);
#endif
        glDisable(GL_BLEND);

        // 4. Diffuse, decay, feed.
        glUseProgram(prog_diffuse_);
        glBindFramebuffer(GL_FRAMEBUFFER, trail_[1 - ct_].fbo);
        bind(2, trail_[ct_].tex);
        draw_quad();
        ct_ = 1 - ct_;
        ++steps_;
    }
    glActiveTexture(GL_TEXTURE0);
}

void App::set_agents(const std::vector<float>& x, const std::vector<float>& y, const std::vector<float>& heading) {
    SavedState saved;
    size_t n = (size_t)aw_ * ah_;
    std::vector<uint8_t> p(n * 4, 0), h(n * 4, 0);
    for (size_t i = 0; i < n && i < x.size(); ++i) {
        encode16(x[i], &p[i * 4], &p[i * 4 + 1]);
        encode16(y[i], &p[i * 4 + 2], &p[i * 4 + 3]);
        encode16(heading[i], &h[i * 4], &h[i * 4 + 1]);
        h[i * 4 + 3] = 255;
    }
    glPixelStorei(GL_UNPACK_ALIGNMENT, 1);
    glBindTexture(GL_TEXTURE_2D, pos_[cp_].tex);
    glTexSubImage2D(GL_TEXTURE_2D, 0, 0, 0, aw_, ah_, GL_RGBA, GL_UNSIGNED_BYTE, p.data());
    glBindTexture(GL_TEXTURE_2D, head_[ch_].tex);
    glTexSubImage2D(GL_TEXTURE_2D, 0, 0, 0, aw_, ah_, GL_RGBA, GL_UNSIGNED_BYTE, h.data());
}

void App::read_agents(std::vector<float>* x, std::vector<float>* y, std::vector<float>* heading) {
    SavedState saved;
    size_t n = (size_t)aw_ * ah_;
    std::vector<uint8_t> p(n * 4), h(n * 4);
    glPixelStorei(GL_PACK_ALIGNMENT, 1);
    glBindFramebuffer(GL_FRAMEBUFFER, pos_[cp_].fbo);
    glReadPixels(0, 0, aw_, ah_, GL_RGBA, GL_UNSIGNED_BYTE, p.data());
    glBindFramebuffer(GL_FRAMEBUFFER, head_[ch_].fbo);
    glReadPixels(0, 0, aw_, ah_, GL_RGBA, GL_UNSIGNED_BYTE, h.data());
    x->resize(n); y->resize(n); heading->resize(n);
    for (size_t i = 0; i < n; ++i) {
        (*x)[i] = (float)decode16(p[i * 4], p[i * 4 + 1]);
        (*y)[i] = (float)decode16(p[i * 4 + 2], p[i * 4 + 3]);
        (*heading)[i] = (float)decode16(h[i * 4], h[i * 4 + 1]);
    }
}

void App::set_trail(const std::vector<uint8_t>& rgba) {
    SavedState saved;
    glPixelStorei(GL_UNPACK_ALIGNMENT, 1);
    glBindTexture(GL_TEXTURE_2D, trail_[ct_].tex);
    glTexSubImage2D(GL_TEXTURE_2D, 0, 0, 0, tw_, th_, GL_RGBA, GL_UNSIGNED_BYTE, rgba.data());
}

void App::read_trail(std::vector<uint8_t>* rgba) {
    SavedState saved;
    rgba->resize((size_t)tw_ * th_ * 4);
    glPixelStorei(GL_PACK_ALIGNMENT, 1);
    glBindFramebuffer(GL_FRAMEBUFFER, trail_[ct_].fbo);
    glReadPixels(0, 0, tw_, th_, GL_RGBA, GL_UNSIGNED_BYTE, rgba->data());
}

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
            cam_x_ = wrap01(cam_x_ - std::sin(heading) * v * dt * (9.0 / 16.0));
            cam_y_ = wrap01(cam_y_ + std::cos(heading) * v * dt);
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
    double dt = last_now_ < 0 ? 0.016 : std::min(0.25, std::max(0.0, now - last_now_));
    last_now_ = now;
    update_camera(dt);

    SavedState saved;

    // One step on every pace-th frame, and never more than one. At pace 1 every frame asks the GPU
    // for exactly the same work, so the compositor either keeps its refresh rate or settles evenly
    // on a lower one. A time-based accumulator instead hands it frames of different weights (0, 1
    // or 2 steps depending on where the frame landed), and that unevenness is what reads as
    // judder. Higher paces are still evenly spaced; if one step plus the draw does not fit in a
    // frame, prefer lowering the agent count over spacing the steps out.
    if (++frames_since_step_ >= pace_) {
        frames_since_step_ = 0;
        step_saved(1, params_);
    }

    // Draw. The draw pass is the most per-pixel work in the add-on, and the trail map underneath it
    // is far smaller than the screen, so it renders into a target of at most draw_cap_w x
    // draw_cap_h and that is scaled up with one bilinear sample a pixel. A 4K output then costs
    // about what a 1080p one does.
    int vw = fb_w, vh = fb_w * 9 / 16;
    if (vh > fb_h) { vh = fb_h; vw = fb_h * 16 / 9; }
    int dw = vw, dh = vh;
    bool scaled = vw > draw_cap_w || vh > draw_cap_h;
    if (scaled) {
        if (dw > draw_cap_w) { dh = std::max(1, dh * draw_cap_w / dw); dw = draw_cap_w; }
        if (dh > draw_cap_h) { dw = std::max(1, dw * draw_cap_h / dh); dh = draw_cap_h; }
    }
    if (scaled && (!draw_.tex || draw_.w != dw || draw_.h != dh) && !make_target(&draw_, dw, dh, true, false)) {
        free_target(&draw_.tex, &draw_.fbo);   // no render targets: draw straight to the framebuffer
        draw_ = Target();
        scaled = false;
    } else if (!scaled && draw_.tex) {
        free_target(&draw_.tex, &draw_.fbo);
        draw_ = Target();
    }

    const uint32_t* pal = PALETTE[std::max(0, std::min(PALETTE_COUNT - 1, s_.palette))];
    double phase = std::fmod(now * s_.cycle / 100.0 * 0.05, 1.0);
    float c[3][3];
    for (int i = 0; i < 3; ++i) palette_at(pal, phase + i * 2.0 / 7.0, c[i]);
    float colour[3], bg[3];
    colour3(s_.colour, colour);
    colour3(s_.background, bg);
    bool food_visible = !nodes_.empty();

    if (draw_.tex) {
        glBindFramebuffer(GL_FRAMEBUFFER, draw_.fbo);
        glViewport(0, 0, dw, dh);
    } else {
        // The screen is small enough to draw into directly: clear the black bars around it.
        glBindFramebuffer(GL_FRAMEBUFFER, (unsigned)saved.fbo);
        glViewport(saved.viewport[0], saved.viewport[1], fb_w, fb_h);
        glClearColor(0, 0, 0, 1);
        glClear(GL_COLOR_BUFFER_BIT);
        glViewport(saved.viewport[0] + (fb_w - vw) / 2, saved.viewport[1] + (fb_h - vh) / 2, vw, vh);
    }

    glUseProgram(prog_draw_);
    bind(1, pal_tex_);
    bind(0, trail_[ct_].tex);
    glUniform1i(u(prog_draw_, "u_trail"), 0);
    glUniform1i(u(prog_draw_, "u_pal"), 1);
    glUniform4f(u(prog_draw_, "u_p0"), (float)s_.colour_mode, (float)phase, s_.brightness / 100.0f,
                (float)std::fmod(now, 3600.0));
    glUniform4f(u(prog_draw_, "u_p1"), (float)s_.view, (float)zoom_, (float)rot_, s_.glow / 100.0f);
    glUniform4f(u(prog_draw_, "u_p2"), (float)cam_x_, (float)cam_y_, (float)tw_, (float)th_);
    glUniform4f(u(prog_draw_, "u_p3"), (float)species_, 1.0f - s_.dim / 100.0f, (float)s_.screen_fx,
                food_visible ? 0.18f : 0.0f);
    glUniform3f(u(prog_draw_, "u_c0"), c[0][0], c[0][1], c[0][2]);
    glUniform3f(u(prog_draw_, "u_c1"), c[1][0], c[1][1], c[1][2]);
    glUniform3f(u(prog_draw_, "u_c2"), c[2][0], c[2][1], c[2][2]);
    glUniform3f(u(prog_draw_, "u_colour"), colour[0], colour[1], colour[2]);
    glUniform3f(u(prog_draw_, "u_bg"), bg[0], bg[1], bg[2]);
    draw_quad();

    if (!draw_.tex) return;

    // Scale the scene up into the letterboxed part of the framebuffer; the black bars are cleared
    // behind it.
    glBindFramebuffer(GL_FRAMEBUFFER, (unsigned)saved.fbo);
    glViewport(saved.viewport[0], saved.viewport[1], fb_w, fb_h);
    glClearColor(0, 0, 0, 1);
    glClear(GL_COLOR_BUFFER_BIT);
    glViewport(saved.viewport[0] + (fb_w - vw) / 2, saved.viewport[1] + (fb_h - vh) / 2, vw, vh);
    glUseProgram(prog_upscale_);
    bind(0, draw_.tex);
    glUniform1i(u(prog_upscale_, "u_tex"), 0);
    draw_quad();
}

}  // namespace lite
}  // namespace physarum
}  // namespace sandclock
