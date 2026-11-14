// The behaviours and palettes of the Physarum screensavers (the same table as
// screensaver.sandclock.gl/src/physarum_tables.hpp, so a preset looks the same
// in every Physarum add-on). tools/make_settings_physarum_v2.py lists the
// names in the same order.
#pragma once
#include <cstdint>

namespace physarum
{

// sa, ra: degrees; so: px of a 960 px wide trail; ss: tenths of a px; decay: %
// kept per step; diffuse: %; deposit; jitter: degrees; repel: %.
struct PresetDef
{
  const char* name;
  float sa, ra, so, ss, decay, diffuse, deposit, jitter, repel;
};

constexpr PresetDef kPresets[] = {
    {"Transport network", 22.5f, 45.0f, 9.0f, 10.0f, 90.0f, 100.0f, 30.0f, 0.0f, 50.0f},
    {"Fine web", 20.0f, 10.0f, 15.0f, 10.0f, 70.0f, 0.0f, 30.0f, 0.0f, 50.0f},
    {"Double-veined cells", 45.0f, 9.0f, 30.0f, 15.0f, 90.0f, 30.0f, 30.0f, 0.0f, 50.0f},
    {"Coarse veins", 22.5f, 45.0f, 24.0f, 12.0f, 92.0f, 100.0f, 30.0f, 2.0f, 50.0f},
    {"Honeycomb", 60.0f, 30.0f, 14.0f, 10.0f, 94.0f, 60.0f, 30.0f, 0.0f, 50.0f},
    {"Labyrinth", 45.0f, 22.5f, 7.0f, 8.0f, 88.0f, 100.0f, 30.0f, 0.0f, 50.0f},
    {"Worms", 45.0f, 45.0f, 3.0f, 10.0f, 90.0f, 100.0f, 30.0f, 0.0f, 50.0f},
    {"Spots and comets", 90.0f, 10.0f, 15.0f, 10.0f, 90.0f, 50.0f, 30.0f, 0.0f, 50.0f},
    {"Foam", 15.0f, 120.0f, 10.0f, 20.0f, 93.0f, 60.0f, 30.0f, 0.0f, 50.0f},
    {"Long threads", 30.0f, 30.0f, 8.0f, 40.0f, 90.0f, 50.0f, 30.0f, 0.0f, 50.0f},
    {"Restless", 35.0f, 35.0f, 18.0f, 18.0f, 93.0f, 70.0f, 30.0f, 25.0f, 40.0f},
};
constexpr int kNumPresets = sizeof(kPresets) / sizeof(kPresets[0]);

constexpr uint32_t kPalettes[][7] = {
    {0xFF5FA2, 0xD45CFF, 0x5C9DFF, 0x3FE0E8, 0x45E07A, 0xFFB38A, 0xFF5C6C}, // neon
    {0xE8C27A, 0xD9A25F, 0xC98A4B, 0xF2D7A0, 0xB5734A, 0xE3B58C, 0xA86A3D}, // desert sand
    {0x3FA9F5, 0x1F6FD1, 0x45D6C9, 0x8FE3FF, 0x2A9D8F, 0x6C8CFF, 0xB8F2E6}, // ocean
    {0xFF7A45, 0xFFB347, 0xFF4F70, 0xC2448F, 0x8A4FD1, 0xFFD166, 0xF25C54}, // sunset
    {0xFF9CEE, 0xB28DFF, 0x85E3FF, 0xBFFCC6, 0xFFF5BA, 0xFFABAB, 0xACE7FF}, // candy
    {0x6BBF59, 0x2E8B57, 0xA3D977, 0xD4C36A, 0x8C6A43, 0x4FA36C, 0xC9E4A6}, // forest
    {0xFFFFFF, 0xD6F1FF, 0xA9DEFF, 0x7CC8F2, 0xC9D6FF, 0xE8F7FF, 0x9FB8D9}, // ice
    {0xFFFFFF, 0xD9D9D9, 0xB3B3B3, 0x8C8C8C, 0xEDEDED, 0xA6A6A6, 0xC7C7C7}, // greyscale
};
constexpr int kNumPalettes = sizeof(kPalettes) / sizeof(kPalettes[0]);

} // namespace physarum
