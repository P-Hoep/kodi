// Colours for new digits, shared by the sand and the liquid. No Kodi / GL.
#pragma once

#include <cmath>
#include <cstdint>
#include <random>

namespace sandclock2
{

// The Sand Clock palettes (screensaver.sandclock/resources/lib/config.py), 0xRRGGBB.
constexpr int kNumPalettes = 8;
const uint32_t kPalettes[kNumPalettes][7] = {
    {0xFF5FA2, 0xD45CFF, 0x5C9DFF, 0x3FE0E8, 0x45E07A, 0xFFB38A, 0xFF5C6C}, // Neon
    {0xE8C27A, 0xD9A25F, 0xC98A4B, 0xF2D7A0, 0xB5734A, 0xE3B58C, 0xA86A3D}, // Desert sand
    {0x3FA9F5, 0x1F6FD1, 0x45D6C9, 0x8FE3FF, 0x2A9D8F, 0x6C8CFF, 0xB8F2E6}, // Ocean
    {0xFF7A45, 0xFFB347, 0xFF4F70, 0xC2448F, 0x8A4FD1, 0xFFD166, 0xF25C54}, // Sunset
    {0xFF9CEE, 0xB28DFF, 0x85E3FF, 0xBFFCC6, 0xFFF5BA, 0xFFABAB, 0xACE7FF}, // Candy
    {0x6BBF59, 0x2E8B57, 0xA3D977, 0xD4C36A, 0x8C6A43, 0x4FA36C, 0xC9E4A6}, // Forest
    {0xFFFFFF, 0xD6F1FF, 0xA9DEFF, 0x7CC8F2, 0xC9D6FF, 0xE8F7FF, 0x9FB8D9}, // Ice
    {0xFFFFFF, 0xD9D9D9, 0xB3B3B3, 0x8C8C8C, 0xEDEDED, 0xA6A6A6, 0xC7C7C7}, // Greyscale
};

enum ColourMode
{
  COLOUR_EVERY_CHANGE = 0, // a new colour from the palette for every change
  COLOUR_PER_DIGIT,        // each position keeps its own colour
  COLOUR_ONE,              // one colour
  COLOUR_RAINBOW,          // the hue walks around the colour wheel over two minutes
  COLOUR_COUNT
};

struct RGB
{
  float r = 0, g = 0, b = 0;
};

inline RGB Hex(uint32_t c)
{
  return {((c >> 16) & 255) / 255.0f, ((c >> 8) & 255) / 255.0f, (c & 255) / 255.0f};
}

inline RGB Hsv(float h, float s, float v)
{
  h = (h - std::floor(h)) * 6.0f;
  const int i = static_cast<int>(h) % 6;
  const float f = h - std::floor(h);
  const float p = v * (1 - s), q = v * (1 - s * f), t = v * (1 - s * (1 - f));
  switch (i)
  {
    case 0: return {v, t, p};
    case 1: return {q, v, p};
    case 2: return {p, v, t};
    case 3: return {p, q, v};
    case 4: return {t, p, v};
    default: return {v, p, q};
  }
}

// Every grain or drop gets one of a fixed set of base colours, so a colour
// index stored with a grain never has to change: the palette mode uses its
// seven colours, one colour mode one, rainbow 31 hues around the wheel.
class ColourPicker
{
public:
  int mode = COLOUR_EVERY_CHANGE;
  int palette = 1;
  RGB colour = Hex(0xE8C27A);

  static constexpr int kRainbowHues = 31;

  void Seed(uint32_t s) { m_rng.seed(s); }

  int NumBases() const
  {
    return mode == COLOUR_ONE ? 1 : mode == COLOUR_RAINBOW ? kRainbowHues : 7;
  }

  RGB Base(int i) const
  {
    if (mode == COLOUR_ONE)
      return colour;
    if (mode == COLOUR_RAINBOW)
      return Hsv(static_cast<float>(i) / kRainbowHues, 0.62f, 1.0f);
    return Hex(Pal()[((i % 7) + 7) % 7]);
  }

  // The base colour for a new glyph at position `slot`, `seconds` since the start.
  int Next(int slot, double seconds)
  {
    switch (mode)
    {
      case COLOUR_PER_DIGIT:
        return slot % 7;
      case COLOUR_ONE:
        return 0;
      case COLOUR_RAINBOW: // once around the wheel every two minutes
        return static_cast<int>(std::fmod(seconds / 120.0, 1.0) * kRainbowHues) % kRainbowHues;
      default:
      {
        int i = static_cast<int>(m_rng() % 7);
        if (i == m_last)
          i = (i + 1 + static_cast<int>(m_rng() % 6)) % 7; // never the same twice in a row
        m_last = i;
        return i;
      }
    }
  }

private:
  const uint32_t* Pal() const { return kPalettes[palette < 0 || palette >= kNumPalettes ? 0 : palette]; }

  std::mt19937 m_rng{12345};
  int m_last = -1;
};

// A cheap, stateless random number from a few integers (the same on any thread,
// so the simulations give the same result however the work is split).
inline uint32_t Hash(uint32_t a, uint32_t b = 0, uint32_t c = 0)
{
  uint32_t h = a * 0x9E3779B1u ^ (b + 0x7F4A7C15u) * 0x85EBCA77u ^ (c + 0x165667B1u) * 0xC2B2AE3Du;
  h ^= h >> 15;
  h *= 0x2C1B3C6Du;
  h ^= h >> 12;
  h *= 0x297A2D39u;
  h ^= h >> 15;
  return h;
}

} // namespace sandclock2
