// Test window for the Cellular Automata 3D screensaver, no Kodi involved.
//   voxel_glfw [--preset N | --rotate-time N] [--rule N] [--custom B4/S45] [--grid N] [--speed N]
//              [--start N] [--density N] [--infinite]
//              [--mode N] [--palette N] [--sparks N] [--no-wrap] [--draw N] [--camera N]
//              [--cam-speed N] [--zoom N] [--bg N] [--glow N] [--fx N] [--dim N]
//              [--fullscreen] [--shot out.ppm --shot-after SECONDS]
//              [--selftest] [--dump-shaders DIR] [--bench N]
// N for --preset, --rotate-time, --rule, --grid, --speed, --start, --draw is the index in the
// settings lists (see tools/make_settings_voxel.py); --preset 10 rotates through them.
// --selftest checks the update shader against the CPU reference.
#define GLFW_INCLUDE_NONE
#include <GLFW/glfw3.h>

#include <cstdio>
#include <cstdlib>
#include <cstring>
#include <ctime>
#include <string>
#include <utility>
#include <vector>

#include "gl_include.hpp"
#include "voxel_app.hpp"

using namespace sandclock::voxel;
using sandclock::voxel::App;

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

// The shader against the reference: random volumes for every rule, with and without wrapping.
// The update shader is the part that must agree with the CPU; the draw pass is not compared.
static int selftest() {
    int failures = 0;
    {   // Sparks compile a different update shader; it cannot be compared with the CPU reference,
        // but it must build and run.
        Settings sp;
        sp.grid = 0;
        sp.sparks = 100;
        App app;
        std::string err;
        if (!app.init(sp, 3, &err)) {
            std::printf("sparks: %s\n", err.c_str());
            ++failures;
        } else {
            app.step(3);
            std::printf("sparks shader ok\n");
        }
    }
    for (int r = 0; r < VOXEL_RULE_COUNT; ++r) {
        for (int wrap = 1; wrap >= 0; --wrap) {
            Settings s;
            s.grid = 0;                       // the smallest cube, 24 x 24 x 24
            s.rule = r;
            s.wrap = wrap != 0;
            s.sparks = 0;
            s.auto_restart = false;
            App app;
            std::string err;
            if (!app.init(s, 1, &err)) {
                std::printf("init: %s\n", err.c_str());
                return 1;
            }
            Rule3D rule = rule_for(s);
            const int n = app.n();
            std::mt19937 rng(11);
            std::vector<uint8_t> cpu((size_t)n * n * n);
            for (auto& v : cpu) v = (rng() % 100) < 30;
            app.upload_state(cpu);
            std::vector<uint8_t> next;
            const int gens = 20;
            for (int g = 0; g < gens; ++g) {
                step_cpu(cpu, next, n, rule, s.wrap);
                cpu = next;
            }
            app.step(gens);
            std::vector<uint8_t> gpu;
            app.read_state(&gpu);
            size_t bad = 0;
            for (size_t i = 0; i < cpu.size(); ++i) bad += cpu[i] != gpu[i];
            std::printf("%-18s wrap=%d  %d cells, %zu differ after %d generations  %s\n",
                        VOXEL_RULES[r].rule, s.wrap, n * n * n, bad, gens, bad ? "FAIL" : "ok");
            failures += bad != 0;

            // measure(): a live volume reads as alive, an emptied one does not.
            bool alive = app.measure().any_alive;
            app.upload_state(std::vector<uint8_t>(cpu.size(), 0));
            bool dead = !app.measure().any_alive;
            if (!alive || !dead) {
                std::printf("  measure(): alive=%d dead=%d  FAIL\n", alive, dead);
                ++failures;
            }
        }
    }
    // Every preset builds and draws (this is what compiles the "inside" and "endless" variants of
    // the draw shader); the colours are not compared.
    for (int p = 1; p <= VOXEL_PRESET_COUNT; ++p) {
        Settings ps;
        ps.preset = p;
        App app;
        std::string err;
        if (!app.init(ps, 5, &err)) {
            std::printf("preset %d: %s\n", p, err.c_str());
            ++failures;
            continue;
        }
        app.render(0.1, 320, 180);
        std::printf("preset %-2d %-18s %d cells  ok\n", p, VOXEL_PRESETS[p - 1].name, app.cells());
    }
    std::printf(failures ? "%d FAILED\n" : "selftest passed\n", failures);
    return failures ? 1 : 0;
}

int main(int argc, char** argv) {
    Settings s;
    std::string shot;
    double shot_after = 8;
    bool fullscreen = false, test = false;
    std::string dump_shaders;
    int bench = 0;
    for (int i = 1; i < argc; ++i) {
        auto is = [&](const char* a) { return !std::strcmp(argv[i], a); };
        auto next = [&] { return i + 1 < argc ? argv[++i] : (char*)"0"; };
        if (is("--preset")) s.preset = std::atoi(next());
        else if (is("--rotate-time")) s.rotate_time = std::atoi(next());
        else if (is("--infinite")) s.infinite = true;
        else if (is("--rule")) s.rule = std::atoi(next());
        else if (is("--custom")) { s.rule = VOXEL_RULE_COUNT; s.custom_rule = next(); }
        else if (is("--grid")) s.grid = std::atoi(next());
        else if (is("--speed")) s.speed = std::atoi(next());
        else if (is("--start")) s.start = std::atoi(next());
        else if (is("--density")) s.density = std::atoi(next());
        else if (is("--mode")) s.colour_mode = std::atoi(next());
        else if (is("--palette")) s.palette = std::atoi(next());
        else if (is("--sparks")) s.sparks = std::atoi(next());
        else if (is("--no-wrap")) s.wrap = false;
        else if (is("--draw")) s.draw = std::atoi(next());
        else if (is("--fullscreen")) fullscreen = true;
        else if (is("--shot")) shot = next();
        else if (is("--shot-after")) shot_after = std::atof(next());
        else if (is("--selftest")) test = true;
        else if (is("--camera")) s.camera = std::atoi(next());
        else if (is("--cam-speed")) s.camera_speed = std::atoi(next());
        else if (is("--zoom")) s.zoom = std::atoi(next());
        else if (is("--bg")) s.background_style = std::atoi(next());
        else if (is("--glow")) s.glow = std::atoi(next());
        else if (is("--fx")) s.screen_fx = std::atoi(next());
        else if (is("--dim")) s.dim = std::atoi(next());
        else if (is("--cycle")) s.cycle = std::atoi(next());
        else if (is("--agespan")) s.age_span = std::atoi(next());
        else if (is("--dump-shaders")) dump_shaders = next();
        else if (is("--bench")) bench = std::atoi(next());
    }

    if (!dump_shaders.empty()) {
        // No GL needed: the sources are built from the settings alone.
        std::string update, draw, present;
        App::shader_sources(s, &update, &draw, &present);
        std::vector<std::pair<const char*, const std::string*>> files = {
            {"update.frag", &update}, {"draw.frag", &draw}, {"present.frag", &present}};
        for (const auto& f : files) {
            std::string path = dump_shaders + "/" + f.first;
            std::FILE* out = std::fopen(path.c_str(), "wb");
            if (!out) { std::fprintf(stderr, "cannot write %s\n", path.c_str()); return 1; }
            std::fwrite(f.second->data(), 1, f.second->size(), out);
            std::fclose(out);
            std::printf("%s ", f.first);
        }
        std::printf("written to %s\n", dump_shaders.c_str());
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
    GLFWwindow* win = glfwCreateWindow(1280, 720, "Cellular Automata 3D (OpenGL)", mon, nullptr);
    if (!win) { glfwTerminate(); return 1; }
    glfwMakeContextCurrent(win);
    glfwSwapInterval(1);
    std::printf("GL %s | %s\n", glGetString(GL_VERSION), glGetString(GL_RENDERER));
    if (test) { int rc = selftest(); glfwTerminate(); return rc; }
    if (fullscreen) glfwSetInputMode(win, GLFW_CURSOR, GLFW_CURSOR_HIDDEN);

    App app;
    std::string err;
    if (!app.init(s, (unsigned)std::time(nullptr), &err)) {
        std::fprintf(stderr, "init: %s\n", err.c_str());
        return 1;
    }
    std::printf("%d x %d x %d cells (%d thousand)\n", app.n(), app.n(), app.n(), app.cells() / 1000);
    if (s.preset >= 1 && s.preset <= VOXEL_PRESET_COUNT)
        std::printf("preset: %s\n", VOXEL_PRESETS[s.preset - 1].name);
    else if (s.preset == VOXEL_PRESET_ROTATE)
        std::printf("preset: rotate every %d s\n",
                    VOXEL_ROTATE_SECONDS[s.rotate_time >= 0 && s.rotate_time < VOXEL_ROTATE_COUNT
                                             ? s.rotate_time : 0]);

    if (bench > 0) {                         // --bench N: average whole-frame cost, no vsync
        int fw, fh;
        glfwGetFramebufferSize(win, &fw, &fh);
        for (int i = 0; i < 5; ++i) app.render(glfwGetTime(), fw, fh);
        glFinish();
        double t0 = glfwGetTime();
        for (int i = 0; i < bench; ++i) app.render(glfwGetTime(), fw, fh);
        glFinish();
        double ms = (glfwGetTime() - t0) * 1000.0 / bench;
        std::printf("bench: %.2f ms a frame at %d x %d (%.0f fps), %ld generations\n", ms, fw, fh,
                    1000.0 / ms, app.generation());
        app.release();
        glfwTerminate();
        return 0;
    }

    double next_status = 5, last_status = 0;
    long frames = 0, frames_at = 0, gens_at = 0;
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
            std::printf("t=%.0fs %.0f fps, %.0f generations/s, up to %d per frame\n", now,
                        (frames - frames_at) / dt, (app.generation() - gens_at) / dt,
                        app.steps_per_frame_limit());
            frames_at = frames;
            gens_at = app.generation();
            last_status = now;
            next_status += 10;
        }
    }
    app.release();
    glfwTerminate();
    return 0;
}
