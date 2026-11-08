// Test window for the Physarum music visualisation, no Kodi involved.
//   physarum_audio_glfw [--preset N] [--species N] [--agents N] [--trail N] [--pace N] [--start N]
//                       [--food N] [--mode N] [--palette N] [--glow N] [--bright N] [--scale N] [--fx N]
//                       [--view N] [--camera N] [--cam-speed N] [--zoom N] [--no-differ]
//                       [--reactivity N] [--sensitivity N] [--spectrum N] [--beat-zoom N] [--beat-wave N]
//                       [--no-react-speed] [--no-react-trails] [--no-react-beat] [--no-react-colour]
//                       [--bpm N] [--silent]
//                       [--fullscreen] [--draw-cap N] [--shot out.ppm --shot-after SECONDS] [--selftest]
// The harness plays a synthetic track (kick, bass, hats, pad at --bpm, 120 by default) into the
// analyser, so the reactions can be seen without Kodi or a music file. --silent sends nothing.
// --selftest checks the analyser against known tones and that the app renders a non-empty trail.
#define GLFW_INCLUDE_NONE
#include <GLFW/glfw3.h>

#include <algorithm>
#include <cmath>
#include <cstdio>
#include <cstdlib>
#include <cstring>
#include <ctime>
#include <random>
#include <string>
#include <vector>

#include "audio_react.hpp"
#include "gl_include.hpp"
#include "physarum_audio.hpp"

using namespace sandclock::physarum::audio;

namespace {

constexpr int SR = 44100;
constexpr double PI2 = 6.283185307179586;

bool save_ppm(const std::string& path, int w, int h) {
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

float noise(unsigned& state) {
    state = state * 1664525u + 1013904223u;
    return (float)((state >> 8) & 0xFFFF) / 32768.0f - 1.0f;
}

// A simple four-to-the-floor track: 55 Hz kick on every beat, a gated bass saw, noise hats on the
// offbeats and a quiet three-note pad. Loud enough for the analyser but well below clipping.
void synth(float* out, int frames, int channels, double t0, double bpm, unsigned& rng) {
    const double beat = 60.0 / bpm;
    for (int i = 0; i < frames; ++i) {
        const double t = t0 + (double)i / SR;
        const double bt = std::fmod(t, beat);                 // time into the beat
        const double ht = std::fmod(t + beat * 0.5, beat / 2);  // time into the offbeat

        const double kick_env = std::exp(-bt * 16.0);
        double v = 0.55 * kick_env * std::sin(PI2 * 55.0 * bt * (1.0 + 0.8 * std::exp(-bt * 30.0)));

        const double bass_env = std::exp(-bt * 3.0) * 0.5 + 0.15;
        const double bass_ph = std::fmod(t * 55.0, 1.0);
        v += 0.22 * bass_env * (2.0 * bass_ph - 1.0);

        const double hat_env = std::exp(-ht * 50.0);
        v += 0.10 * hat_env * noise(rng);

        const double pad = std::sin(PI2 * 220.0 * t) + 0.6 * std::sin(PI2 * 330.0 * t) +
                           0.4 * std::sin(PI2 * 440.0 * t);
        v += 0.05 * pad * (0.6 + 0.4 * std::sin(PI2 * t / (beat * 8.0)));

        const float sf = (float)std::max(-0.98, std::min(0.98, v));
        for (int c = 0; c < channels; ++c) out[(size_t)i * channels + c] = sf;
    }
}

int selftest() {
    int failures = 0;

    // 1. A loud 55 Hz tone must read as bass, with a level and a spectrum, and no NaN.
    {
        AudioAnalyzer a;
        a.configure(SR, 2);
        std::vector<float> buf(1024 * 2);
        for (int i = 0; i < 1024; ++i) {
            float v = 0.6f * std::sin((float)(PI2 * 55.0 * i / SR));
            buf[i * 2] = buf[i * 2 + 1] = v;
        }
        for (int n = 0; n < 40; ++n) {
            a.push(buf.data(), buf.size());
            a.update(1.0 / 60.0);
        }
        const AudioState& s = a.state();
        bool finite = std::isfinite(s.level) && std::isfinite(s.bass) && std::isfinite(s.bands[0]);
        bool heard = s.level > 0.2f && s.bass > 0.3f && s.bass > s.air;
        std::printf("tone:    level %.2f bass %.2f air %.2f  %s\n", s.level, s.bass, s.air,
                    finite && heard ? "ok" : "FAIL");
        failures += !(finite && heard);
    }

    // 2. A beat pattern must produce beat impulses, but not on every single frame.
    {
        AudioAnalyzer a;
        a.configure(SR, 2);
        unsigned rng = 7;
        std::vector<float> buf(735 * 2);
        int beats = 0, frames = 0;
        double t = 0;
        for (int n = 0; n < 600; ++n) {          // 10 seconds at 60 fps
            synth(buf.data(), 735, 2, t, 120, rng);
            t += 735.0 / SR;
            a.push(buf.data(), buf.size());
            a.update(1.0 / 60.0);
            if (a.state().beat > 0.9f) ++beats;
            ++frames;
        }
        bool ok = beats >= 4 && beats <= frames / 4;
        std::printf("beat:    %d beat frames in %d  %s\n", beats, frames, ok ? "ok" : "FAIL");
        failures += !ok;
    }

    // 3. Silence must fade rather than stick at the last values.
    {
        AudioAnalyzer a;
        a.configure(SR, 2);
        std::vector<float> buf(1024 * 2);
        for (int i = 0; i < 1024; ++i) buf[i * 2] = buf[i * 2 + 1] = 0.6f * std::sin((float)(PI2 * 55.0 * i / SR));
        for (int n = 0; n < 40; ++n) { a.push(buf.data(), buf.size()); a.update(1.0 / 60.0); }
        float loud = a.state().level;
        for (int n = 0; n < 120; ++n) { std::fill(buf.begin(), buf.end(), 0.0f); a.push(buf.data(), buf.size()); a.update(1.0 / 60.0); }
        bool ok = loud > 0.2f && a.state().level < loud * 0.2f;
        std::printf("silence: %.2f -> %.2f  %s\n", loud, a.state().level, ok ? "ok" : "FAIL");
        failures += !ok;
    }

    // 4. Reactivity scales the simulation's response and zero leaves it alone.
    {
        Settings s;
        Params base;
        base.ss = 2.0f; base.deposit = 0.3f; base.decay = 0.9f; base.jitter = 0; base.ra = 0.5f;
        AudioState a;
        a.level = 1.0f; a.bass = 1.0f; a.treble = 0.5f; a.beat = 1.0f;
        s.reactivity = 0;
        Params off = reactive_params(base, s, a);
        s.reactivity = 100;
        Params on = reactive_params(base, s, a);
        bool ok = off.ss == base.ss && off.deposit == base.deposit && off.decay == base.decay &&
                  off.jitter == base.jitter && on.ss > base.ss && on.deposit > base.deposit &&
                  on.decay > base.decay && on.jitter > base.jitter;
        std::printf("react:   ss %.2f -> %.2f, deposit %.2f -> %.2f, decay %.2f -> %.2f, jitter %.2f -> %.2f  %s\n",
                    base.ss, on.ss, base.deposit, on.deposit, base.decay, on.decay, base.jitter, on.jitter,
                    ok ? "ok" : "FAIL");
        failures += !ok;
    }
    return failures;
}

}  // namespace

int main(int argc, char** argv) {
    Settings s;
    std::string shot;
    double shot_after = 8, bpm = 120;
    bool fullscreen = false, test = false, silent = false;
    for (int i = 1; i < argc; ++i) {
        auto is = [&](const char* a) { return !std::strcmp(argv[i], a); };
        auto next = [&] { return i + 1 < argc ? argv[++i] : (char*)"0"; };
        if (is("--preset")) s.preset = std::atoi(next());
        else if (is("--species")) s.species = std::atoi(next());
        else if (is("--agents")) s.agents = std::atoi(next());
        else if (is("--trail")) s.trail = std::atoi(next());
        else if (is("--pace")) s.pace = std::atoi(next());
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
        else if (is("--reactivity")) s.reactivity = std::atoi(next());
        else if (is("--sensitivity")) s.sensitivity = std::atoi(next());
        else if (is("--spectrum")) s.spectrum = std::atoi(next());
        else if (is("--beat-zoom")) s.beat_zoom = std::atoi(next());
        else if (is("--beat-wave")) s.beat_wave = std::atoi(next());
        else if (is("--no-react-speed")) s.react_speed = false;
        else if (is("--no-react-trails")) s.react_trails = false;
        else if (is("--no-react-beat")) s.react_beat = false;
        else if (is("--no-react-colour")) s.react_colour = false;
        else if (is("--bpm")) bpm = std::atof(next());
        else if (is("--silent")) silent = true;
        else if (is("--fullscreen")) fullscreen = true;
        else if (is("--shot")) shot = next();
        else if (is("--shot-after")) shot_after = std::atof(next());
        else if (is("--selftest")) test = true;
        else if (is("--rgba8")) App::force_rgba8 = true;
        else if (is("--draw-cap")) {
            App::draw_cap_w = std::max(16, std::atoi(next()));
            App::draw_cap_h = App::draw_cap_w * 9 / 16;
        }
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
    GLFWwindow* win = glfwCreateWindow(1280, 720, "Physarum Visualisation (OpenGL)", mon, nullptr);
    if (!win) { glfwTerminate(); return 1; }
    glfwMakeContextCurrent(win);
    glfwSwapInterval(1);
    std::printf("GL %s | %s\n", glGetString(GL_VERSION), glGetString(GL_RENDERER));

    if (test) {
        int rc = selftest();
        App::force_rgba8 = true;
        rc |= selftest();
        App::force_rgba8 = false;

        // The app must compile its shaders, take audio and draw a non-empty trail.
        App app;
        std::string err;
        if (!app.init(s, 3, &err)) {
            std::printf("init: %s\n", err.c_str());
            rc |= 1;
        } else {
            unsigned rng = 11;
            std::vector<float> buf(735 * 2);
            double t = 0;
            for (int n = 0; n < 240; ++n) {
                synth(buf.data(), 735, 2, t, bpm, rng);
                t += 735.0 / SR;
                app.push_audio(buf.data(), buf.size());
                app.render(n / 60.0, 640, 360);
            }
            std::vector<uint8_t> trail;
            app.read_trail(&trail);
            size_t lit = 0;
            for (size_t i = 0; i < trail.size(); i += 4) lit += trail[i] > 8;
            bool ok = app.steps() == 240 && app.audio().level > 0.1f && lit > (size_t)app.trail_w() * app.trail_h() / 200;
            std::printf("render:  %ld steps, level %.2f, %zu lit trail pixels  %s\n", app.steps(), app.audio().level, lit,
                        ok ? "ok" : "FAIL");
            rc |= !ok;
            app.release();
        }
        std::printf(rc ? "%d FAILED\n" : "selftest passed\n", rc);
        glfwTerminate();
        return rc ? 1 : 0;
    }
    if (fullscreen) glfwSetInputMode(win, GLFW_CURSOR, GLFW_CURSOR_HIDDEN);

    App app;
    std::string err;
    if (!app.init(s, (unsigned)std::time(nullptr), &err)) {
        std::fprintf(stderr, "init: %s\n", err.c_str());
        return 1;
    }
    if (!err.empty()) std::fprintf(stderr, "note: %s\n", err.c_str());
    app.start_audio(SR, 2);
    std::printf("%d agents, trail %d x %d (%s), %s\n", app.agents_w() * app.agents_h(), app.trail_w(), app.trail_h(),
                app.half_float() ? "half float" : "8 bit", silent ? "silent" : "synthetic track at 120 bpm");

    unsigned rng = 1;
    std::vector<float> buf(735 * 2);
    double audio_t = 0;
    double next_status = 5, last_status = 0;
    long frames = 0, frames_at = 0, steps_at = 0;
    while (!glfwWindowShouldClose(win)) {
        glfwPollEvents();
        if (glfwGetKey(win, GLFW_KEY_ESCAPE) == GLFW_PRESS) break;
        double now = glfwGetTime();
        int fw, fh;
        glfwGetFramebufferSize(win, &fw, &fh);
        glViewport(0, 0, fw, fh);

        // Feed the analyser the part of the synthetic track that belongs to this frame, in blocks
        // no larger than the real Kodi callbacks.
        if (!silent) {
            while (audio_t < now) {
                int n = std::min(735, (int)((now - audio_t) * SR) + 1);
                n = std::max(1, n);
                synth(buf.data(), n, 2, audio_t, bpm, rng);
                app.push_audio(buf.data(), (size_t)n * 2);
                audio_t += (double)n / SR;
            }
        }

        app.render(now, fw, fh);
        if (!shot.empty() && now >= shot_after) {
            std::printf("shot %s %s\n", shot.c_str(), save_ppm(shot, fw, fh) ? "ok" : "FAILED");
            break;
        }
        glfwSwapBuffers(win);
        ++frames;
        if (now >= next_status) {
            double dt = now - last_status;
            const AudioState& a = app.audio();
            std::printf("t=%.0fs %.0f fps, %.0f steps/s, level %.2f bass %.2f treble %.2f beat %.2f, behaviour %d\n", now,
                        (frames - frames_at) / dt, (app.steps() - steps_at) / dt, a.level, a.bass, a.treble, a.beat,
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
