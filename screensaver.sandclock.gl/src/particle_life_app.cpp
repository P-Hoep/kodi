// Particle Life renderer: see particle_life_app.hpp.
//
// The simulation runs on the CPU with a uniform grid (particle_life.*), a few fixed steps per
// frame; the renderer interpolates between the last two steps and uploads (x, y, speed) once a
// frame. Particles are point sprites drawn twice (a wide faint halo and a small bright core) into
// a target that fades itself a little each frame, which makes trails. Everything is blended
// "over", never added: the target is 8-bit, and additive trails of slow particles would clip
// every channel to white. The target is
// drawn at no more than the chosen resolution and scaled up once, and a final pass tone-maps,
// vignettes and dithers the result. All of that is cheap enough for a 32-bit TV box running 30
// simulation steps a second with a few thousand particles.
#include "particle_life_app.hpp"

#include <algorithm>
#include <cmath>
#include <cstdio>

#include "gl_util.hpp"

#ifndef GL_ALIASED_POINT_SIZE_RANGE
#define GL_ALIASED_POINT_SIZE_RANGE 0x846D
#endif
#ifndef GL_PROGRAM_POINT_SIZE
#define GL_PROGRAM_POINT_SIZE 0x8642
#endif
#ifndef GL_VERTEX_PROGRAM_POINT_SIZE
#define GL_VERTEX_PROGRAM_POINT_SIZE 0x8642
#endif
#ifndef GL_POINT_SPRITE
#define GL_POINT_SPRITE 0x8861
#endif

namespace sandclock {
namespace particlelife {
namespace {

int clamp_int(int v, int lo, int hi) { return v < lo ? lo : (v > hi ? hi : v); }

// The particle pass. a_speed is 0..1 from the world's speed limit; a_colour.a is the species
// index, used by the shimmer mode as a phase so species pulse out of step.
const char* kPointsVertex = R"(
attribute vec2 a_pos;
attribute float a_speed;
attribute vec4 a_colour;
uniform vec2 u_world;
uniform float u_point;
uniform float u_alpha;
uniform float u_mode;
uniform float u_time;
varying vec4 v_col;

vec3 heat(float t) {
    t = clamp(t * 2.5, 0.0, 1.0);
    vec3 slow = vec3(0.10, 0.22, 0.80);
    vec3 mid  = vec3(0.15, 0.85, 1.00);
    vec3 fast = vec3(1.00, 0.92, 0.72);
    return t < 0.5 ? mix(slow, mid, t * 2.0) : mix(mid, fast, (t - 0.5) * 2.0);
}

void main() {
    gl_Position = vec4((a_pos / u_world) * 2.0 - 1.0, 0.0, 1.0);
    gl_PointSize = u_point;
    vec3 c = a_colour.rgb;
    if (u_mode > 0.5 && u_mode < 1.5) c = heat(a_speed);
    else if (u_mode > 1.5) c *= 0.72 + 0.28 * sin(u_time * 0.9 + a_colour.a * 1.9);
    v_col = vec4(c, u_alpha);
}
)";

const char* kPointsFragment = R"(
varying vec4 v_col;
uniform float u_soft;
void main() {
    vec2 q = gl_PointCoord * 2.0 - 1.0;
    float d2 = dot(q, q);
    if (d2 > 1.0) discard;
    float a = exp(-d2 * u_soft);
    a *= 1.0 - smoothstep(0.55, 1.0, d2);
    gl_FragColor = vec4(v_col.rgb * v_col.a * a, v_col.a * a);
}
)";

// Fade the accumulation target towards the background. u_bg.a is how much of the background is
// mixed in this frame, frame-rate corrected on the CPU.
const char* kFadeFragment = R"(
uniform vec4 u_bg;
void main() { gl_FragColor = u_bg; }
)";

// Scale-up and finish: tone map so dense clusters glow without hard clipping, a soft vignette,
// and a little ordered-free noise to stop banding in the dark background.
const char* kPresentFragment = R"(
uniform sampler2D u_tex;
uniform float u_dim;
varying vec2 v_uv;
float hash(vec2 p) { return fract(sin(dot(p, vec2(12.9898, 78.233))) * 43758.5453); }
void main() {
    vec3 c = texture2D(u_tex, v_uv).rgb;
    vec2 p = (v_uv - 0.5) * vec2(1.7777778, 1.0);
    // Tone map by brightness and keep the hue, so a glowing particle stays its species colour
    // instead of clipping every channel to white once trails pile up.
    float m = max(c.r, max(c.g, c.b));
    c *= (1.0 - exp(-m * 2.2)) / max(m, 1e-4);
    c *= (1.0 - 0.30 * dot(p, p)) * u_dim;
    c += (hash(gl_FragCoord.xy) - 0.5) / 255.0;
    gl_FragColor = vec4(c, 1.0);
}
)";

}  // namespace

int App::draw_cap_w = 1920, App::draw_cap_h = 1080;

App::~App() { release(); }

int App::loc(unsigned prog, const char* name) const { return glGetUniformLocation(prog, name); }

bool App::make_target(Target* t, int w, int h) {
    destroy_target(t);
    t->w = w;
    t->h = h;
    glGenTextures(1, &t->tex);
    glBindTexture(GL_TEXTURE_2D, t->tex);
    glTexImage2D(GL_TEXTURE_2D, 0, GL_RGBA, w, h, 0, GL_RGBA, GL_UNSIGNED_BYTE, nullptr);
    glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_MIN_FILTER, GL_LINEAR);
    glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_MAG_FILTER, GL_LINEAR);
    glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_WRAP_S, GL_CLAMP_TO_EDGE);
    glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_WRAP_T, GL_CLAMP_TO_EDGE);
    glGenFramebuffers(1, &t->fbo);
    glBindFramebuffer(GL_FRAMEBUFFER, t->fbo);
    glFramebufferTexture2D(GL_FRAMEBUFFER, GL_COLOR_ATTACHMENT0, GL_TEXTURE_2D, t->tex, 0);
    return glCheckFramebufferStatus(GL_FRAMEBUFFER) == GL_FRAMEBUFFER_COMPLETE;
}

void App::destroy_target(Target* t) {
    if (t->fbo) glDeleteFramebuffers(1, &t->fbo);
    if (t->tex) glDeleteTextures(1, &t->tex);
    *t = Target();
}

void App::draw_quad() {
#ifdef SANDCLOCK_CORE
    glBindVertexArray(vao_);
#endif
    glBindBuffer(GL_ARRAY_BUFFER, vbo_quad_);
    glEnableVertexAttribArray(0);
    glVertexAttribPointer(0, 2, GL_FLOAT, GL_FALSE, 0, (const void*)0);
    glDrawArrays(GL_TRIANGLE_STRIP, 0, 4);
    glDisableVertexAttribArray(0);
#ifdef SANDCLOCK_CORE
    glBindVertexArray(0);
#endif
}

uint32_t App::dark_tint(std::mt19937& rng) {
    unsigned c = kPalettes[rng() % kPaletteCount][rng() % 8];
    unsigned r = 3 + ((c >> 16) & 0xFF) / 34;
    unsigned g = 3 + ((c >> 8) & 0xFF) / 40;
    unsigned b = 5 + (c & 0xFF) / 30;
    return ((r & 0xFF) << 16) | ((g & 0xFF) << 8) | (b & 0xFF);
}

bool App::init(const Settings& settings, unsigned seed, std::string* error) {
    release();
    glu::SavedState saved;
    s_ = sanitise(settings);
    seed_ = seed;
    rng_.seed(seed);

    std::string note;
    rules_for(s_, seed, &note);   // only for the warning about unreadable custom text
    note_ = note;

    prog_points_ = glu::link(kPointsVertex, kPointsFragment, error);
    if (!prog_points_) return false;
    prog_fade_ = glu::link(nullptr, kFadeFragment, error);
    if (!prog_fade_) return false;
    prog_present_ = glu::link(nullptr, kPresentFragment, error);
    if (!prog_present_) return false;

    pu_ = {loc(prog_points_, "u_world"), loc(prog_points_, "u_point"), loc(prog_points_, "u_alpha"),
           loc(prog_points_, "u_soft"), loc(prog_points_, "u_mode"), loc(prog_points_, "u_time")};
    fu_ = {loc(prog_fade_, "u_bg")};
    xu_ = {loc(prog_present_, "u_tex"), loc(prog_present_, "u_dim")};
    attr_.pos = glGetAttribLocation(prog_points_, "a_pos");
    attr_.speed = glGetAttribLocation(prog_points_, "a_speed");
    attr_.colour = glGetAttribLocation(prog_points_, "a_colour");

    static const float quad[8] = {-1, -1, 1, -1, -1, 1, 1, 1};
    glGenBuffers(1, &vbo_quad_);
    glBindBuffer(GL_ARRAY_BUFFER, vbo_quad_);
    glBufferData(GL_ARRAY_BUFFER, sizeof quad, quad, GL_STATIC_DRAW);
#ifdef SANDCLOCK_CORE
    glGenVertexArrays(1, &vao_);
#endif
    glGenBuffers(1, &vbo_particles_);
    glGenBuffers(1, &vbo_colours_);

    float range[2] = {1.0f, 64.0f};
    glGetFloatv(GL_ALIASED_POINT_SIZE_RANGE, range);
    point_max_ = std::max(1.0f, range[1]);

    // The world is (re)built at the real framebuffer aspect on the first render, so a 4:3 or
    // 21:9 screen is not stretched, and normally never rebuilt again.
    world_.init(s_, 16.0f / 9.0f, seed);
    world_sized_ = false;
    colours_dirty_ = true;
    last_now_ = -1;
    acc_ = 0;
    next_restart_ = next_evolve_ = -1;
    steps_ = 0;
    ready_ = true;
    return true;
}

void App::release() {
    destroy_target(&scene_);
    if (vbo_particles_) glDeleteBuffers(1, &vbo_particles_);
    if (vbo_colours_) glDeleteBuffers(1, &vbo_colours_);
    if (vbo_quad_) glDeleteBuffers(1, &vbo_quad_);
#ifdef SANDCLOCK_CORE
    if (vao_) glDeleteVertexArrays(1, &vao_);
#endif
    for (unsigned* p : {&prog_points_, &prog_fade_, &prog_present_})
        if (*p) glDeleteProgram(*p);
    prog_points_ = prog_fade_ = prog_present_ = 0;
    vbo_particles_ = vbo_colours_ = vbo_quad_ = vao_ = 0;
    ready_ = false;
}

void App::update_world_size(int fb_w, int fb_h) {
    float aspect = (float)fb_w / (float)std::max(1, fb_h);
    world_.init(s_, aspect, seed_);
    world_sized_ = true;
    colours_dirty_ = true;
    acc_ = 0;
}

void App::build_colours() {
    const int n = world_.count();
    colour_.resize((size_t)n * 4);
    const unsigned* pal = kPalettes[clamp_int(s_.palette, 0, kPaletteCount - 1)];
    for (int i = 0; i < n; ++i) {
        unsigned c = pal[world_.species()[i] % 8];
        colour_[(size_t)i * 4 + 0] = ((c >> 16) & 0xFF) / 255.0f;
        colour_[(size_t)i * 4 + 1] = ((c >> 8) & 0xFF) / 255.0f;
        colour_[(size_t)i * 4 + 2] = (c & 0xFF) / 255.0f;
        colour_[(size_t)i * 4 + 3] = (float)world_.species()[i];
    }
    glBindBuffer(GL_ARRAY_BUFFER, vbo_colours_);
    glBufferData(GL_ARRAY_BUFFER, (GLsizeiptr)(colour_.size() * sizeof(float)), colour_.data(), GL_STATIC_DRAW);
    colours_dirty_ = false;
}

void App::upload_particles(float t) {
    frame_.resize((size_t)world_.count() * 3);
    world_.interpolate(frame_.data(), t);
    glBindBuffer(GL_ARRAY_BUFFER, vbo_particles_);
    glBufferData(GL_ARRAY_BUFFER, (GLsizeiptr)(frame_.size() * sizeof(float)), frame_.data(), GL_STREAM_DRAW);
}

void App::apply_random_look() {
    std::mt19937& r = rng_;
    auto pick = [&](int n) { return (int)(r() % (unsigned)n); };
    s_.palette = pick(kPaletteCount);
    s_.colour_mode = pick(3);
    s_.radius = 6 + pick(15);          // 6..20 %
    s_.force = 35 + pick(90);          // 35..124 %
    s_.friction = 8 + pick(55);        // 8..62 %
    s_.size = 20 + pick(50);
    s_.glow = 30 + pick(60);
    s_.trail = 25 + pick(60);
    s_.start = pick(kStartCount);
    s_.species = 3 + pick(6);          // 3..8
    s_.background = dark_tint(r);
    colours_dirty_ = true;
}

void App::restart(double now) {
    unsigned s = (unsigned)rng_();
    if (s_.vary >= 2) {
        // Everything random: a new species count, matrix, palette, physics and look.
        apply_random_look();
        Settings t = s_;
        t.matrix_mode = 2;
        world_.init(t, world_.aspect(), s);
    } else {
        if (s_.vary == 1) world_.randomize_rules(s);
        world_.reset_positions(s);
    }
    colours_dirty_ = true;
    acc_ = 0;
    int every = kRestarts[clamp_int(s_.restart, 0, kRestartCount - 1)];
    next_restart_ = every ? now + every : -1;
}

void App::evolve(double now) {
    world_.mutate_rules(0.035f, (unsigned)rng_());
    int every = kEvolves[clamp_int(s_.evolve, 0, kEvolveCount - 1)];
    next_evolve_ = every ? now + every : -1;
}

int App::rendered_pixels(int fb_w, int fb_h) {
    if (!ready_) return -1;
    render(0.0, fb_w, fb_h);
    std::vector<unsigned char> px((size_t)fb_w * fb_h * 3);
    glPixelStorei(GL_PACK_ALIGNMENT, 1);
    glReadPixels(0, 0, fb_w, fb_h, GL_RGB, GL_UNSIGNED_BYTE, px.data());
    int lit = 0;
    unsigned br = (s_.background >> 16) & 0xFF, bg_g = (s_.background >> 8) & 0xFF, bb = s_.background & 0xFF;
    int threshold = (int)(br + bg_g + bb) / 3 + 12;
    for (size_t i = 0; i < px.size(); i += 3) {
        int v = (px[i] + px[i + 1] + px[i + 2]) / 3;
        if (v > threshold) ++lit;
    }
    return lit;
}

void App::render(double now, int fb_w, int fb_h) {
    if (!ready_ || fb_w <= 0 || fb_h <= 0) return;
    glu::SavedState saved;

#ifdef SANDCLOCK_CORE
    glEnable(GL_PROGRAM_POINT_SIZE);
#elif !defined(SANDCLOCK_GLES)
    glEnable(GL_VERTEX_PROGRAM_POINT_SIZE);
    glEnable(GL_POINT_SPRITE);
#endif

    if (!world_sized_) update_world_size(fb_w, fb_h);
    if (last_now_ < 0) last_now_ = now;
    float dt = (float)(now - last_now_);
    last_now_ = now;
    if (dt < 0) dt = 0;
    if (dt > 0.25f) dt = 0.25f;             // a stall is not a physics problem
    last_dt_ = dt > 0 ? dt : (1.0f / 60.0f);

    // Fixed simulation steps, with an interpolated frame between them.
    const double interval = 1.0 / kSpeeds[clamp_int(s_.speed, 0, kSpeedCount - 1)];
    acc_ += dt;
    int stepped = 0;
    while (acc_ >= interval && stepped < 6) {
        world_.step();
        acc_ -= interval;
        ++stepped;
        ++steps_;
    }
    if (acc_ >= interval) acc_ = 0;         // could not keep up: drop the backlog
    float tover = (float)(acc_ / interval);

    if (s_.restart > 0 && kRestarts[s_.restart] > 0) {
        if (next_restart_ < 0) next_restart_ = now + kRestarts[s_.restart];
        else if (now >= next_restart_) restart(now);
    }
    if (s_.evolve > 0 && kEvolves[s_.evolve] > 0) {
        if (next_evolve_ < 0) next_evolve_ = now + kEvolves[s_.evolve];
        else if (now >= next_evolve_) evolve(now);
    }

    // Pick the scene size. The cost of a frame follows this, not the output resolution.
    int cap = kDrawCaps[clamp_int(s_.draw, 0, kDrawCount - 1)];
    int want_h = fb_h, want_w = fb_w;
    if (cap == 0) {
        want_h = std::min(fb_h, draw_cap_h);
        want_w = std::min(fb_w, draw_cap_w);
    } else if (cap > 0) {
        want_h = std::min(fb_h, std::min(cap, draw_cap_h));
        want_w = std::min(fb_w, draw_cap_w);
    }
    // Keep the target's aspect equal to the screen's, so the world is not stretched.
    float scale = std::min((float)want_w / fb_w, (float)want_h / fb_h);
    int tw = std::max(1, (int)std::lround(fb_w * scale));
    int th = std::max(1, (int)std::lround(fb_h * scale));
    if (scene_.w != tw || scene_.h != th) {
        if (!make_target(&scene_, tw, th)) { ready_ = false; return; }
        glClearColor(((s_.background >> 16) & 0xFF) / 255.0f, ((s_.background >> 8) & 0xFF) / 255.0f,
                     (s_.background & 0xFF) / 255.0f, 1.0f);
        glClear(GL_COLOR_BUFFER_BIT);
    }

    if (colours_dirty_) build_colours();
    upload_particles(tover);

    // The accumulating scene.
    glBindFramebuffer(GL_FRAMEBUFFER, scene_.fbo);
    glViewport(0, 0, scene_.w, scene_.h);
    float bg_r = ((s_.background >> 16) & 0xFF) / 255.0f;
    float bg_g = ((s_.background >> 8) & 0xFF) / 255.0f;
    float bg_b = (s_.background & 0xFF) / 255.0f;
    if (s_.trail <= 0) {
        glClearColor(bg_r, bg_g, bg_b, 1.0f);
        glClear(GL_COLOR_BUFFER_BIT);
    } else {
        // Keep the target in range: an 8-bit buffer clamps each channel at 1, so a slow fade
        // with strong additive particles would settle at pure white. This keeps the per-frame
        // contribution such that even a particle that never moves stays below clipping.
        float keep = 0.75f + (s_.trail / 100.0f) * 0.17f;     // per frame at 60 fps
        float fade = 1.0f - std::pow(keep, last_dt_ * 60.0f);
        glEnable(GL_BLEND);
        glBlendFunc(GL_SRC_ALPHA, GL_ONE_MINUS_SRC_ALPHA);
        glUseProgram(prog_fade_);
        glUniform4f(fu_.bg, bg_r, bg_g, bg_b, fade);
        draw_quad();
    }

    if (world_.count() > 0) {
        glEnable(GL_BLEND);
        // Everything is drawn "over" with premultiplied alpha, including the halo. Adding light
        // instead would look better, but the accumulation target is 8-bit: with a long fade a
        // static or slow particle would lift every channel to 1 and turn the palette white.
        glBlendFunc(GL_ONE, GL_ONE_MINUS_SRC_ALPHA);
        glUseProgram(prog_points_);
        glUniform2f(pu_.world, world_.aspect(), 1.0f);
        glUniform1f(pu_.mode, (float)s_.colour_mode);
        glUniform1f(pu_.time, (float)now);

        float base = (1.6f + (s_.size / 100.0f) * 5.4f) * scene_.h / 720.0f;
        base = std::max(1.0f, std::min(base, point_max_));
#ifdef SANDCLOCK_CORE
        glBindVertexArray(vao_);
#endif
        glBindBuffer(GL_ARRAY_BUFFER, vbo_particles_);
        glEnableVertexAttribArray((unsigned)attr_.pos);
        glVertexAttribPointer((unsigned)attr_.pos, 2, GL_FLOAT, GL_FALSE, 3 * sizeof(float), (const void*)0);
        glEnableVertexAttribArray((unsigned)attr_.speed);
        glVertexAttribPointer((unsigned)attr_.speed, 1, GL_FLOAT, GL_FALSE, 3 * sizeof(float),
                              (const void*)(2 * sizeof(float)));
        glBindBuffer(GL_ARRAY_BUFFER, vbo_colours_);
        glEnableVertexAttribArray((unsigned)attr_.colour);
        glVertexAttribPointer((unsigned)attr_.colour, 4, GL_FLOAT, GL_FALSE, 4 * sizeof(float), (const void*)0);

        if (s_.glow > 0) {
            float g = s_.glow / 100.0f;
            // A wide, faint halo: additive light in an 8-bit target must stay well below one,
            // or trails of overlapping particles clip every channel and the colours go white.
            glUniform1f(pu_.point, std::min(point_max_, base * (2.8f + g * 1.6f)));
            glUniform1f(pu_.alpha, 0.03f + g * 0.09f);
            glUniform1f(pu_.soft, 1.15f);
            glDrawArrays(GL_POINTS, 0, world_.count());
        }
        // The core is drawn over rather than added, so repeated trails cannot pile the species
        // colour up to white: the middle of a particle stays the palette colour, the glow around
        // it is what accumulates.
        glBlendFunc(GL_ONE, GL_ONE_MINUS_SRC_ALPHA);
        glUniform1f(pu_.point, base);
        glUniform1f(pu_.alpha, 0.85f);
        glUniform1f(pu_.soft, 3.6f);
        glDrawArrays(GL_POINTS, 0, world_.count());

        glDisableVertexAttribArray((unsigned)attr_.pos);
        glDisableVertexAttribArray((unsigned)attr_.speed);
        glDisableVertexAttribArray((unsigned)attr_.colour);
#ifdef SANDCLOCK_CORE
        glBindVertexArray(0);
#endif
    }

    // Present, scaled up to the screen in one pass.
    glBindFramebuffer(GL_FRAMEBUFFER, saved.fbo);
    glViewport(0, 0, fb_w, fb_h);
    glDisable(GL_BLEND);
    glUseProgram(prog_present_);
    glActiveTexture(GL_TEXTURE0);
    glBindTexture(GL_TEXTURE_2D, scene_.tex);
    glUniform1i(xu_.tex, 0);
    glUniform1f(xu_.dim, 1.0f - s_.dim / 100.0f);
    draw_quad();
}

}  // namespace particlelife
}  // namespace sandclock
