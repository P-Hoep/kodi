// Kodi binary add-on: a screensaver instance around Engine + Renderer. Built against the
// kodi-addon-dev-kit (Kodi 21 "Omega", screensaver API 2.2.0). Kodi creates the GL context and
// calls Render() once per frame on its render thread.
#include <kodi/addon-instance/Screensaver.h>

#include <chrono>
#include <cstdlib>
#include <ctime>
#include <memory>
#include <string>

#include "engine.hpp"
#include "gl_include.hpp"
#include "kodi_common.hpp"
#include "renderer.hpp"

class ATTR_DLL_LOCAL CSandClock : public kodi::addon::CInstanceScreensaver {
public:
    explicit CSandClock(const kodi::addon::IInstanceInfo& instance) : CInstanceScreensaver(instance) {}

    bool Start() override {
        try {
            Settings s = read_settings();
            sandclock::Font font = sandclock::Font::load(kodi::addon::GetAddonPath("resources/fonts.json"),
                                                         sandclock::FONT_FOLDERS[s.font], s.weight);
            std::string error;
            renderer_ = std::make_unique<sandclock::Renderer>();
            if (!renderer_->init(&error)) {
                kodi::Log(ADDON_LOG_ERROR, "Sand Clock: shader error: %s", error.c_str());
                renderer_.reset();
                return false;
            }
            engine_ = std::make_unique<sandclock::Engine>(
                s, font, (unsigned)std::chrono::steady_clock::now().time_since_epoch().count());
            started_ = std::chrono::steady_clock::now();
            kodi::Log(ADDON_LOG_INFO, "Sand Clock: started, grain %d px, GL %s", engine_->grain(),
                      (const char*)glGetString(GL_VERSION));
            return true;
        } catch (const std::exception& e) {
            kodi::Log(ADDON_LOG_ERROR, "Sand Clock: cannot start: %s", e.what());
            return false;
        }
    }

    void Stop() override {
        if (renderer_) renderer_->release();  // the GL context is still current here
        renderer_.reset();
        engine_.reset();
    }

    void Render() override {
        if (!engine_ || !renderer_) return;
        double now = std::chrono::duration<double>(std::chrono::steady_clock::now() - started_).count();
        engine_->update(now, seconds_since_midnight());
        renderer_->draw(*engine_, now, Width(), Height());
    }

private:
    std::unique_ptr<sandclock::Engine> engine_;
    std::unique_ptr<sandclock::Renderer> renderer_;
    std::chrono::steady_clock::time_point started_;
};

class ATTR_DLL_LOCAL CSandClockAddon : public kodi::addon::CAddonBase {
public:
    CSandClockAddon() = default;
    ADDON_STATUS CreateInstance(const kodi::addon::IInstanceInfo& instance,
                                KODI_ADDON_INSTANCE_HDL& hdl) override {
        if (instance.IsType(ADDON_INSTANCE_SCREENSAVER)) {
            hdl = new CSandClock(instance);
            return ADDON_STATUS_OK;
        }
        return ADDON_STATUS_UNKNOWN;
    }
};

ADDONCREATOR(CSandClockAddon)
