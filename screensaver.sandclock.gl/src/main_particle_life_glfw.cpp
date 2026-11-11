// Test window for the Particle Life screensaver, no Kodi involved.
//   particle_life_glfw [--preset N | --custom "a,b,c,d,..." | --random]
//                      [--species N] [--particles N] [--radius N] [--force N] [--friction N]
//                      [--speed N] [--no-wrap] [--start N] [--palette N] [--mode N] [--size N]
//                      [--glow N] [--trail N] [--bg RRGGBB] [--dim N] [--draw N] [--vary N]
//                      [--restart N] [--evolve N] [--seed N]
//                      [--fullscreen] [--shot out.ppm --shot-after SECONDS]
//                      [--selftest] [--bench FRAMES]
// N for --particles, --speed, --start and --draw is the index in the settings lists (see
// tools/make_settings_particle_life.py).
#define GLFW_INCLUDE_NONE
#include <GLFW/glfw3.h>

#include <chrono>
#include <cstdio>
#include <cstdlib>
#include <cstring>
#include <ctime>
#include <string>
#include <vector>

#include "gl_include.hpp"
#include "particle_life_app.hpp"

using namespace sandclock::particlelife;

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

// Render a few configurations at a small draw cap and count the lit pixels. This checks that the
// whole path runs (world, colours, point shaders, accumulation target, present pass) and that
// particles actually reach the screen, for presets, a custom matrix and random rules.
static int selftest() {
    struct Case { const char* name; int matrix_mode; int preset; int start; int particles; };
    const Case cases[] = {
        {"DNA scattered", 0, 0, 0, 0},       {"Worm disk", 0, 1, 1, 1},
        {"Waves ring", 0, 2, 2, 0},          {"Soap clusters", 0, 3, 3, 1},
        {"Photon grid", 0, 4, 4, 0},         {"custom 2 species", 1, 0, 0, 0},
        {"random 8 species", 2, 0, 5, 1},
    };
    const int old_w = App::draw_cap_w, old_h = App::draw_cap_h;
    App::draw_cap_w = 640;
    App::draw_cap_h = 360;
    int failures = 0;
    for (const Case& c : cases) {
        Settings s;
        s.matrix_mode = c.matrix_mode;
        s.preset = c.preset;
        s.start = c.start;
        s.particles = c.particles;
        s.speed = 4;
        s.species = 8;
        if (c.matrix_mode == 1) s.custom_matrix = "0.6,-0.4,-0.9,0.3,-0.2,0.8,0.5,-0.7,-0.1,0.2,-0.6,0.9";
        App app;
        std::string err;
        if (!app.init(s, 1234u, &err)) {
            std::printf("%-20s init FAILED: %s\n", c.name, err.c_str());
            ++failures;
            continue;
        }
        int lit = app.rendered_pixels(1280, 720);
        bool sized = app.draw_width() <= 640 && app.draw_height() <= 360;
        int expected = (int)((double)app.particles() * 4);
        bool ok = lit > expected && sized;
        std::printf("%-20s %5d particles, %d x %d target, %7d lit px  %s\n", c.name, app.particles(),
                    app.draw_width(), app.draw_height(), lit, ok ? "ok" : "FAIL");
        if (!ok) {
            if (!sized) std::printf("  target is larger than the 640 x 360 cap\n");
            if (lit <= expected) std::printf("  %d lit pixels is not more than %d\n", lit, expected);
            ++failures;
        }
        app.release();
    }
    App::draw_cap_w = old_w;
    App::draw_cap_h = old_h;
    std::printf(failures ? "%d FAILED\n" : "selftest passed\n", failures);
    return failures ? 1 : 0;
}

// The realistic frame cost: simulation steps plus both point passes and the present, at the
// configured settings, driven by a steady 60 Hz clock. Reports the average frame time and the
// number of simulation steps per second the CPU is managing.
static int bench(const Settings& s, int frames) {
    App app;
    std::string err;
    if (!app.init(s, 99u, &err)) {
        std::fprintf(stderr, "init: %s\n", err.c_str());
        return 1;
    }
    std::printf("%d particles, %d species, %d steps/s, draw index %d\n", app.particles(), app.species(),
                kSpeeds[s.speed], s.draw);
    int fw = 1920, fh = 1080;
    auto begin = std::chrono::steady_clock::now();
    for (int i = 0; i < frames; ++i) {
        glViewport(0, 0, fw, fh);
        app.render((double)i / 60.0, fw, fh);
        glFinish();
    }
    double ms = std::chrono::duration<double>(std::chrono::steady_clock::now() - begin).count() * 1000.0 / frames;
    std::printf("%d frames: %.2f ms/frame at %d x %d (%.0f fps headroom)\n", frames, ms, app.draw_width(),
                app.draw_height(), 1000.0 / ms);
    app.release();
    return 0;
}

int main(int argc, char** argv) {
    Settings s;
    std::string shot;
    double shot_after = 6;
    bool fullscreen = false, test = false;
    int bench_frames = 0, simulate = 0;
    unsigned seed = (unsigned)std::time(nullptr);
    for (int i = 1; i < argc; ++i) {
        auto is = [&](const char* a) { return !std::strcmp(argv[i], a); };
        auto next = [&] { return i + 1 < argc ? argv[++i] : (char*)"0"; };
        if (is("--preset")) s.preset = std::atoi(next());
        else if (is("--custom")) { s.matrix_mode = 1; s.custom_matrix = next(); }
        else if (is("--random")) s.matrix_mode = 2;
        else if (is("--species")) s.species = std::atoi(next());
        else if (is("--particles")) s.particles = std::atoi(next());
        else if (is("--radius")) s.radius = std::atoi(next());
        else if (is("--force")) s.force = std::atoi(next());
        else if (is("--friction")) s.friction = std::atoi(next());
        else if (is("--speed")) s.speed = std::atoi(next());
        else if (is("--no-wrap")) s.wrap = false;
        else if (is("--start")) s.start = std::atoi(next());
        else if (is("--palette")) s.palette = std::atoi(next());
        else if (is("--mode")) s.colour_mode = std::atoi(next());
        else if (is("--size")) s.size = std::atoi(next());
        else if (is("--glow")) s.glow = std::atoi(next());
        else if (is("--trail")) s.trail = std::atoi(next());
        else if (is("--bg")) s.background = (uint32_t)std::strtoul(next(), nullptr, 16);
        else if (is("--dim")) s.dim = std::atoi(next());
        else if (is("--draw")) s.draw = std::atoi(next());
        else if (is("--vary")) s.vary = std::atoi(next());
        else if (is("--restart")) s.restart = std::atoi(next());
        else if (is("--evolve")) s.evolve = std::atoi(next());
        else if (is("--seed")) seed = (unsigned)std::strtoul(next(), nullptr, 10);
        else if (is("--fullscreen")) fullscreen = true;
        else if (is("--shot")) shot = next();
        else if (is("--shot-after")) shot_after = std::atof(next());
        else if (is("--selftest")) test = true;
        else if (is("--bench")) bench_frames = std::atoi(next());
        else if (is("--simulate")) simulate = std::atoi(next());
    }
    s = sanitise(s);

    if (simulate > 0) {
        // Headless model check: how quickly do these settings gather particles, and how fast do
        // they end up moving? Printed every simulated second at 60 steps.
        World w;
        w.init(s, 16.0f / 9.0f, seed);
        for (int i = 0; i < simulate; ++i) {
            for (int k = 0; k < 60; ++k) w.step();
            World::Stats st = w.stats();
            std::printf("t=%3ds mean speed %.4f (max %.4f), density variation %.2f, finite %d\n",
                        i + 1, (double)st.mean_speed, (double)st.max_speed,
                        (double)st.density_variation, (int)st.finite);
        }
        return 0;
    }

    if (!glfwInit()) return 1;
#ifdef SANDCLOCK_CORE  // the profile Kodi gets on macOS
    glfwWindowHint(GLFW_CONTEXT_VERSION_MAJOR, 3);
    glfwWindowHint(GLFW_CONTEXT_VERSION_MINOR, 2);
    glfwWindowHint(GLFW_OPENGL_PROFILE, GLFW_OPENGL_CORE_PROFILE);
    glfwWindowHint(GLFW_OPENGL_FORWARD_COMPAT, GLFW_TRUE);
#endif
    GLFWmonitor* mon = fullscreen ? glfwGetPrimaryMonitor() : nullptr;
    GLFWwindow* win = glfwCreateWindow(1280, 720, "Particle Life (OpenGL)", mon, nullptr);
    if (!win) { glfwTerminate(); return 1; }
    glfwMakeContextCurrent(win);
    glfwSwapInterval(1);
    std::printf("GL %s | %s\n", glGetString(GL_VERSION), glGetString(GL_RENDERER));
    if (test) { int rc = selftest(); glfwTerminate(); return rc; }
    if (bench_frames > 0) { int rc = bench(s, bench_frames); glfwTerminate(); return rc; }
    if (fullscreen) glfwSetInputMode(win, GLFW_CURSOR, GLFW_CURSOR_HIDDEN);

    App app;
    std::string err;
    if (!app.init(s, seed, &err)) {
        std::fprintf(stderr, "init: %s\n", err.c_str());
        return 1;
    }
    if (!err.empty()) std::fprintf(stderr, "note: %s\n", err.c_str());
    std::printf("%d particles, %d species, %d start, preset %d\n", app.particles(), app.species(), s.start, s.preset);
    std::printf("matrix: %s\n", app.rules_text().c_str());

    double next_status = 5, last_status = 0;
    long frames = 0, frames_at = 0;
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
            const World& w = app.world();
            const std::vector<float>& pos = w.positions();
            int inside = 0;
            for (size_t i = 0; i + 1 < pos.size(); i += 2)
                inside += pos[i] >= 0 && pos[i] <= w.aspect() && pos[i + 1] >= 0 && pos[i + 1] <= 1.0f;
            World::Stats st = w.stats();
            std::printf("t=%.0fs %.0f fps, %d/%d inside, speed %.3f, density %.2f, finite %d, target %d x %d\n",
                        now, (frames - frames_at) / dt, inside, w.count(), (double)st.mean_speed,
                        (double)st.density_variation, (int)st.finite, app.draw_width(), app.draw_height());
            frames_at = frames;
            last_status = now;
            next_status += 10;
        }
    }
    app.release();
    glfwTerminate();
    return 0;
}
