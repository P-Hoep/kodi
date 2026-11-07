// Helpers shared by the two Kodi add-ons (Sand Clock and Liquid Clock): reading the settings and
// the time of day. Include after <kodi/addon-instance/Screensaver.h>.
#pragma once
#include <chrono>
#include <cstdio>
#include <cstdlib>
#include <ctime>
#include <string>

#include "sand.hpp"

using sandclock::Settings;

inline uint32_t parse_colour(const std::string& text, uint32_t fallback) {
    std::string v = text;
    if (!v.empty() && v[0] == '#') v.erase(0, 1);
    if (v.size() != 6 && v.size() != 8) return fallback;
    char* end = nullptr;
    unsigned long n = std::strtoul(v.c_str(), &end, 16);
    return (end && *end == 0) ? (uint32_t)(n & 0xFFFFFF) : fallback;  // AARRGGBB or RRGGBB
}

inline int parse_minutes(const std::string& text, int fallback) {
    int h = 0, m = 0;
    if (std::sscanf(text.c_str(), "%d:%d", &h, &m) != 2 || h < 0 || h > 23 || m < 0 || m > 59) return fallback;
    return h * 60 + m;
}

template <typename T>
inline T clamp(T v, T lo, T hi) { return v < lo ? lo : (v > hi ? hi : v); }

// Same setting ids and defaults as the Python add-on (resources/settings.xml is generated from
// the same table).
inline Settings read_settings() {
    Settings s;
    s.seconds = kodi::addon::GetSettingBoolean("seconds", s.seconds);
    s.hours = clamp(kodi::addon::GetSettingInt("hours", s.hours), 0, 1);
    s.crumble = clamp(kodi::addon::GetSettingInt("crumble", s.crumble), 0, 1);
    s.speed = clamp(kodi::addon::GetSettingInt("speed", s.speed), 0, 2);
    s.font = clamp(kodi::addon::GetSettingInt("font", s.font), 0, 8);
    s.weight = clamp(kodi::addon::GetSettingInt("weight", s.weight), 0, 2);
    s.size = clamp(kodi::addon::GetSettingInt("size", s.size), 40, 95);
    s.position = clamp(kodi::addon::GetSettingInt("position", s.position), 0, 1);
    s.grain = clamp(kodi::addon::GetSettingInt("grain", s.grain), 0, 2);
    s.grain_look = clamp(kodi::addon::GetSettingInt("grain_look", s.grain_look), 0, 2);
    s.gravity = clamp(kodi::addon::GetSettingInt("gravity", s.gravity), 0, 2);
    s.pile = clamp(kodi::addon::GetSettingInt("pile", s.pile), 10, 50);
    s.colour_mode = clamp(kodi::addon::GetSettingInt("colour_mode", s.colour_mode), 0, 3);
    s.palette = clamp(kodi::addon::GetSettingInt("palette", s.palette), 0, (int)sandclock::PALETTES.size() - 1);
    s.colour = parse_colour(kodi::addon::GetSettingString("colour", ""), s.colour);
    s.background = parse_colour(kodi::addon::GetSettingString("background", ""), s.background);
    s.night_palette = clamp(kodi::addon::GetSettingInt("night_palette", s.night_palette), 0, (int)sandclock::PALETTES.size());
    s.night_dim = clamp(kodi::addon::GetSettingInt("night_dim", s.night_dim), 0, 80);
    s.day_start = parse_minutes(kodi::addon::GetSettingString("day_start", ""), s.day_start);
    s.night_start = parse_minutes(kodi::addon::GetSettingString("night_start", ""), s.night_start);
    s.dim = clamp(kodi::addon::GetSettingInt("dim", s.dim), 0, 80);
    s.drift = kodi::addon::GetSettingBoolean("drift", s.drift);
    s.slosh = clamp(kodi::addon::GetSettingInt("slosh", s.slosh), 0, 2);
    return s;
}

inline double seconds_since_midnight() {
    using namespace std::chrono;
    auto now = system_clock::now();
    std::time_t t = system_clock::to_time_t(now);
    std::tm lt;
#ifdef _WIN32
    localtime_s(&lt, &t);
#else
    localtime_r(&t, &lt);
#endif
    long ms = (long)(duration_cast<milliseconds>(now.time_since_epoch()).count() % 1000);
    return lt.tm_hour * 3600.0 + lt.tm_min * 60.0 + lt.tm_sec + ms / 1000.0;
}
