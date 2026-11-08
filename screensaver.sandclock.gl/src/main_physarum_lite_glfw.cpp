// Test window for the Physarum Lite screensaver, no Kodi involved.
//   physarum_lite_glfw [--preset N] [--species N] [--agents N] [--trail N] [--speed N] [--start N]
//                      [--food N] [--mode N] [--palette N] [--glow N] [--bright N] [--scale N] [--fx N]
//                      [--view N] [--camera N] [--cam-speed N] [--zoom N] [--no-differ]
//                      [--fullscreen] [--shot out.ppm --shot-after SECONDS] [--selftest]
// N is the index in the settings lists (tools/make_settings_physarum_lite.py). --selftest checks
// the sense / move / deposit passes against the model computed on the CPU.
#define GLFW_INCLUDE_NONE
#include <GLFW/glfw3.h>

#include <cmath>
#include <cstdio>
#include <cstdlib>
#include <cstring>
#include <ctime>
#include <random>
#include <string>
#include <vector>

#include "gl_include.hpp"
#include "physarum_lite_app.hpp"

using namespace sandclock::physarum::lite;

static bool save_ppm(const std::string& path, int w, int h) {
    std::vector<unsigned char> px((size_t)w * h * 3);
    glPixelStorei(GL_PACK_ALIGNMENT, 1);
    glReadPixels(0, 0, w, h, GL_RGB, GL_UNSIGNED_BYTE, px.data());
    FILE* f = std::fopen(path.c_str(), "wb");
    if (!f) return false;
    std::fprintf(f, "P6\n%d %d\n255\n", w, h);
    for (int y = h - 1; y >= 0; --y) std::fwrite(&px[(size_t)y * w * 3], 1, (size_t)w * 3, f);
    std::fclose(f);
    return true;
}

static double wrapd(double d) { return d - std::round(d); }   // shortest signed difference on a circle of 1

static int selftest() {
    int failures = 0;
    Settings s;
    s.agents = 0;                    // 128 x 128
    s.trail = 0;                     // 480 x 270
    s.species = 0;
    App app;
    std::string err;
    if (!app.init(s, 1, &err)) { std::printf("init: %s\n", err.c_str()); return 1; }
    std::printf("trail %dx%d (%s), %d agents\n", app.trail_w(), app.trail_h(), app.half_float() ? "half float" : "8 bit",
                app.agents_w() * app.agents_h());
    const int W = app.trail_w(), H = app.trail_h();
    const size_t N = (size_t)app.agents_w() * app.agents_h();
    std::mt19937 rng(5);
    std::uniform_real_distribution<float> U(0, 1);
    Params p;
    p.sa = 0.4f; p.ra = 0.5f; p.so = 20; p.ss = 1.5f; p.decay = 0.9f; p.diffuse = 0; p.deposit = 0.3f;
    p.jitter = 0; p.repel = 0;

    // 1. Empty trail: no turning, a straight step, and a deposit where each agent lands.
    std::vector<float> x(N), y(N), h(N);
    for (size_t i = 0; i < N; ++i) { x[i] = 0.05f + 0.9f * U(rng); y[i] = 0.05f + 0.9f * U(rng); h[i] = U(rng); }
    app.set_agents(x, y, h);
    app.set_trail(std::vector<uint8_t>((size_t)W * H * 4, 0));
    app.step(1, p);
    std::vector<float> x2, y2, h2;
    app.read_agents(&x2, &y2, &h2);
    size_t bad_move = 0, bad_head = 0;
    std::vector<int> count((size_t)W * H, 0);
    for (size_t i = 0; i < N; ++i) {
        double hx = (double)(uint32_t)(h[i] * 65535.0 + 0.5) / 65535.0 * 6.283185307;   // as stored
        double qx = std::round(x[i] * 65535.0) / 65535.0, qy = std::round(y[i] * 65535.0) / 65535.0;
        double ex = qx + std::cos(hx) * p.ss / W, ey = qy + std::sin(hx) * p.ss / H;
        if (std::fabs(wrapd(x2[i] - ex)) > 3e-5 || std::fabs(wrapd(y2[i] - ey)) > 3e-5) ++bad_move;
        if (std::fabs(wrapd(h2[i] - h[i])) > 3e-5) ++bad_head;
        int px = (int)(x2[i] * W), py = (int)(y2[i] * H);
        if (px >= 0 && py >= 0 && px < W && py < H) ++count[(size_t)py * W + px];
    }
    std::printf("move:    %zu of %zu agents off, %zu headings changed  %s\n", bad_move, N, bad_head,
                bad_move || bad_head ? "FAIL" : "ok");
    failures += bad_move || bad_head;

    std::vector<uint8_t> trail;
    app.read_trail(&trail);
    float amt = app.deposit_amount(p);
    size_t bad_dep = 0, checked = 0;
    for (size_t i = 0; i < count.size(); ++i) {
        double expect = count[i] * amt * p.decay - (app.half_float() ? 0 : 0.5 / 255);
        expect = std::max(0.0, std::min(1.0, expect)) * 255;
        double got = trail[i * 4];
        // An agent right on a pixel edge can land either side; allow it, but most must match.
        if (std::fabs(got - expect) > 1.5) ++bad_dep;
        ++checked;
    }
    bool dep_ok = bad_dep < checked / 200;
    std::printf("deposit: %zu of %zu pixels off (amount %.4f)  %s\n", bad_dep, checked, amt, dep_ok ? "ok" : "FAIL");
    failures += !dep_ok;

    // 2. A trail that rises to the right: agents facing up turn right, facing down turn left,
    //    facing right keep going; facing left the front is weakest, so they turn either way.
    std::vector<uint8_t> ramp((size_t)W * H * 4, 0);
    for (int yy = 0; yy < H; ++yy)
        for (int xx = 0; xx < W; ++xx) ramp[((size_t)yy * W + xx) * 4] = (uint8_t)(xx * 255 / (W - 1));
    const float heads[4] = {0.25f, 0.75f, 0.0f, 0.5f};
    for (size_t i = 0; i < N; ++i) { x[i] = 0.2f + 0.6f * U(rng); y[i] = 0.2f + 0.6f * U(rng); h[i] = heads[i % 4]; }
    app.set_agents(x, y, h);
    app.set_trail(ramp);
    app.step(1, p);
    app.read_agents(&x2, &y2, &h2);
    size_t bad_turn = 0;
    const double r = p.ra / 6.283185307;
    for (size_t i = 0; i < N; ++i) {
        double d = wrapd(h2[i] - h[i]);
        bool ok;
        switch (i % 4) {
            case 0: ok = std::fabs(d + r) < 3e-5; break;                       // up: turn right
            case 1: ok = std::fabs(d - r) < 3e-5; break;                       // down: turn left
            case 2: ok = std::fabs(d) < 3e-5; break;                           // right: straight on
            default: ok = std::fabs(std::fabs(d) - r) < 3e-5; break;           // left: either way
        }
        bad_turn += !ok;
    }
    std::printf("turning: %zu of %zu agents turned wrongly  %s\n", bad_turn, N, bad_turn ? "FAIL" : "ok");
    failures += bad_turn != 0;

    std::printf(failures ? "%d FAILED\n" : "selftest passed\n", failures);
    return failures ? 1 : 0;
}

int main(int argc, char** argv) {
    Settings s;
    std::string shot;
    double shot_after = 8;
    bool fullscreen = false, test = false;
    for (int i = 1; i < argc; ++i) {
        auto is = [&](const char* a) { return !std::strcmp(argv[i], a); };
        auto next = [&] { return i + 1 < argc ? argv[++i] : (char*)"0"; };
        if (is("--preset")) s.preset = std::atoi(next());
        else if (is("--species")) s.species = std::atoi(next());
        else if (is("--agents")) s.agents = std::atoi(next());
        else if (is("--trail")) s.trail = std::atoi(next());
        else if (is("--speed")) s.speed = std::atoi(next());
        else if (is("--start")) s.start = std::atoi(next());
        else if (is("--food")) s.food = std::atoi(next());
        else if (is("--mode")) s.colour_mode = std::atoi(next());
        else if (is("--palette")) s.palette = std::atoi(next());
        else if (is("--glow")) s.glow = std::atoi(next());
        else if (is("--bright")) s.brightness = std::atoi(next());
        else if (is("--scale")) s.scale = std::atoi(next());
        else if (is("--fx")) s.screen_fx = std::atoi(next());
        else if (is("--view")) s.view = std::atoi(next());
        else if (is("--camera")) s.camera = std::atoi(next());
        else if (is("--cam-speed")) s.camera_speed = std::atoi(next());
        else if (is("--zoom")) s.zoom = std::atoi(next());
        else if (is("--no-differ")) s.species_differ = false;
        else if (is("--fullscreen")) fullscreen = true;
        else if (is("--shot")) shot = next();
        else if (is("--shot-after")) shot_after = std::atof(next());
        else if (is("--selftest")) test = true;
        else if (is("--rgba8")) App::force_rgba8 = true;
        else if (is("--custom")) {      // sa,ra,so,ss,decay,diffuse,deposit,jitter in the slider units
            s.preset = PRESET_COUNT;
            std::sscanf(next(), "%f,%f,%f,%f,%f,%f,%f,%f", &s.sa, &s.ra, &s.so, &s.ss, &s.decay, &s.diffuse, &s.deposit,
                        &s.jitter);
        }
    }

    if (!glfwInit()) return 1;
#ifdef SANDCLOCK_CORE  // the profile Kodi gets on macOS
    glfwWindowHint(GLFW_CONTEXT_VERSION_MAJOR, 3);
    glfwWindowHint(GLFW_CONTEXT_VERSION_MINOR, 2);
    glfwWindowHint(GLFW_OPENGL_PROFILE, GLFW_OPENGL_CORE_PROFILE);
    glfwWindowHint(GLFW_OPENGL_FORWARD_COMPAT, GLFW_TRUE);
#endif
    GLFWmonitor* mon = fullscreen ? glfwGetPrimaryMonitor() : nullptr;
    GLFWwindow* win = glfwCreateWindow(1280, 720, "Physarum Lite (OpenGL)", mon, nullptr);
    if (!win) { glfwTerminate(); return 1; }
    glfwMakeContextCurrent(win);
    glfwSwapInterval(1);
    std::printf("GL %s | %s\n", glGetString(GL_VERSION), glGetString(GL_RENDERER));
    if (test) {
        int rc = selftest();
        App::force_rgba8 = true;
        rc |= selftest();
        glfwTerminate();
        return rc;
    }
    if (fullscreen) glfwSetInputMode(win, GLFW_CURSOR, GLFW_CURSOR_HIDDEN);

    App app;
    std::string err;
    if (!app.init(s, (unsigned)std::time(nullptr), &err)) {
        std::fprintf(stderr, "init: %s\n", err.c_str());
        return 1;
    }
    if (!err.empty()) std::fprintf(stderr, "note: %s\n", err.c_str());
    std::printf("%d agents, trail %d x %d (%s)\n", app.agents_w() * app.agents_h(), app.trail_w(), app.trail_h(),
                app.half_float() ? "half float" : "8 bit");

    double next_status = 5, last_status = 0;
    long frames = 0, frames_at = 0, steps_at = 0;
    while (!glfwWindowShouldClose(win)) {
        glfwPollEvents();
        if (glfwGetKey(win, GLFW_KEY_ESCAPE) == GLFW_PRESS) break;
        double now = glfwGetTime();
        int fw, fh;
        glfwGetFramebufferSize(win, &fw, &fh);
        glViewport(0, 0, fw, fh);
        app.render(now, fw, fh);
        if (!shot.empty() && now >= shot_after) {
            std::printf("shot %s %s\n", shot.c_str(), save_ppm(shot, fw, fh) ? "ok" : "FAILED");
            break;
        }
        glfwSwapBuffers(win);
        ++frames;
        if (now >= next_status) {
            double dt = now - last_status;
            std::printf("t=%.0fs %.0f fps, %.0f steps/s, up to %d per frame, behaviour %d\n", now,
                        (frames - frames_at) / dt, (app.steps() - steps_at) / dt, app.steps_per_frame_limit(),
                        app.preset());
            frames_at = frames;
            steps_at = app.steps();
            last_status = now;
            next_status += 10;
        }
    }
    app.release();
    glfwTerminate();
    return 0;
}
