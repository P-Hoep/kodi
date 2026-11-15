// Drawing helpers shared by the stage and the HUD: quads into vertex
// batches (one shader, its look picked per vertex), colours, palettes and
// text from the baked font. No GL here; the Kodi shell uploads the batches.
//
// Every batch is a list of quads (4 vertices each, drawn with one shared
// index buffer). Colours are premultiplied, and a glow is written with zero
// alpha, so additive light and ordinary blending share one draw call with
// glBlendFunc(GL_ONE, GL_ONE_MINUS_SRC_ALPHA).
#pragma once

#include "Common.h"
#include "Font.h"

#include <cstring>
#include <vector>

namespace evo
{

struct RGB
{
  float r, g, b;
};

inline RGB Mix(const RGB& a, const RGB& b, float t) { return {a.r + (b.r - a.r) * t, a.g + (b.g - a.g) * t, a.b + (b.b - a.b) * t}; }
inline RGB Scale(const RGB& a, float k) { return {a.r * k, a.g * k, a.b * k}; }

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

// premultiplied: rgb * a, then a (0 = additive light)
inline uint32_t PackPre(const RGB& c, float a, float add = 0.0f)
{
  auto q = [](float v) { return static_cast<uint32_t>(Clamp(v, 0.0f, 1.0f) * 255.0f + 0.5f); };
  const float k = a + add;
  return q(c.r * k) | (q(c.g * k) << 8) | (q(c.b * k) << 16) | (q(add > 0.0f ? 0.0f : a) << 24);
}

inline uint32_t PackPar(float mode, float a, float b, float c)
{
  auto q = [](float v) { return static_cast<uint32_t>(Clamp(v, 0.0f, 255.0f) + 0.5f); };
  return q(mode) | (q(a) << 8) | (q(b) << 16) | (q(c) << 24);
}

// shader looks (keep in step with the fragment shader in ScreensaverEvolveLife.cpp)
enum Look
{
  LK_FLAT = 0,    // vertex colour (dithered)
  LK_CAPSULE = 1, // a lit, rim-glowing capsule: a body segment
  LK_GLOW = 2,    // soft radial light (additive)
  LK_PANEL = 3,   // rounded glass rectangle
  LK_DISC = 4,    // a bright disc with a halo
  LK_LINE = 5,    // an anti-aliased line (v across)
};

struct Vertex
{
  float x, y, u, v;
  uint32_t col, par;
};

struct Batch
{
  std::vector<Vertex> v;
  float W = 1920.0f, H = 1080.0f; // screen size, for text placed in pixels
  void Clear() { v.clear(); }
  size_t quads() const { return v.size() / 4; }
  // corners in order: (0) top-left, (1) top-right, (2) bottom-left, (3) bottom-right
  void Quad(const float* xy, const float* uv, uint32_t col, uint32_t par)
  {
    for (int i = 0; i < 4; i++)
      v.push_back({xy[2 * i], xy[2 * i + 1], uv[2 * i], uv[2 * i + 1], col, par});
  }
  void Quad4(const float* xy, const float* uv, const uint32_t* col, uint32_t par)
  {
    for (int i = 0; i < 4; i++)
      v.push_back({xy[2 * i], xy[2 * i + 1], uv[2 * i], uv[2 * i + 1], col[i], par});
  }
};

struct Palette
{
  RGB skyTop, skyBottom, fog, groundTop, groundBottom, edge, beacon, mote;
  float sat, val;
  bool mono;
};

enum PaletteId
{
  PAL_AUTO,
  PAL_WARM,
  PAL_COOL,
  PAL_NEON,
  PAL_MONO,
  PAL_COUNT
};

inline Palette GetPalette(int id)
{
  switch (id)
  {
    case PAL_COOL:
      return {{0.01f, 0.025f, 0.07f}, {0.04f, 0.17f, 0.24f}, {0.05f, 0.18f, 0.24f}, {0.07f, 0.17f, 0.23f},
              {0.01f, 0.03f, 0.05f}, {0.35f, 0.95f, 1.0f}, {0.6f, 1.0f, 0.95f}, {0.6f, 0.9f, 1.0f}, 0.62f, 1.0f, false};
    case PAL_NEON:
      return {{0.015f, 0.0f, 0.04f}, {0.20f, 0.02f, 0.24f}, {0.22f, 0.03f, 0.26f}, {0.12f, 0.03f, 0.16f},
              {0.01f, 0.0f, 0.02f}, {0.95f, 0.25f, 0.95f}, {0.4f, 1.0f, 0.6f}, {1.0f, 0.5f, 1.0f}, 0.85f, 1.0f, false};
    case PAL_MONO:
      return {{0.02f, 0.025f, 0.03f}, {0.14f, 0.15f, 0.17f}, {0.15f, 0.16f, 0.18f}, {0.08f, 0.085f, 0.095f},
              {0.02f, 0.02f, 0.025f}, {0.85f, 0.88f, 0.95f}, {1.0f, 1.0f, 1.0f}, {0.8f, 0.85f, 0.9f}, 0.0f, 1.0f, true};
    default: // warm dusk
      return {{0.035f, 0.03f, 0.10f}, {0.36f, 0.15f, 0.19f}, {0.33f, 0.15f, 0.19f}, {0.22f, 0.10f, 0.17f},
              {0.03f, 0.015f, 0.04f}, {1.0f, 0.62f, 0.38f}, {1.0f, 0.85f, 0.5f}, {1.0f, 0.75f, 0.55f}, 0.68f, 1.0f, false};
  }
}

// ---- text ------------------------------------------------------------------

inline const font::Glyph& GlyphOf(char ch)
{
  const int c = static_cast<unsigned char>(ch);
  return font::kGlyphs[(c < 32 || c > 126) ? 0 : c - 32];
}

inline float TextWidth(const char* s, float size)
{
  const float k = size / static_cast<float>(font::kSize);
  float w = 0;
  for (; *s; s++)
    w += GlyphOf(*s).adv * k;
  return w;
}

// Draw a string with its top at y (pixels, y down). align: 0 left, 1 centre,
// 2 right. Returns the width. The text shader draws a soft shadow from the
// same glyph, so each glyph is one quad padded by two atlas pixels.
inline float DrawText(Batch& b, float x, float y, float size, const RGB& c, float alpha, const char* s, int align = 0)
{
  if (alpha <= 0.003f)
    return 0.0f;
  const float k = size / static_cast<float>(font::kSize);
  const float w = TextWidth(s, size);
  if (align == 1)
    x -= 0.5f * w;
  else if (align == 2)
    x -= w;
  const float base = y + static_cast<float>(font::kAscent) * k;
  const uint32_t col = PackPre(c, alpha);
  const float iw = 1.0f / static_cast<float>(font::kAtlasW), ih = 1.0f / static_cast<float>(font::kAtlasH);
  for (; *s; s++)
  {
    const font::Glyph& g = GlyphOf(*s);
    if (g.w > 0)
    {
      const float pad = 2.0f;
      const float x0 = x + (static_cast<float>(g.xoff) - pad) * k, y0 = base + (static_cast<float>(g.yoff) - pad) * k;
      const float x1 = x0 + (static_cast<float>(g.w) + 2 * pad) * k, y1 = y0 + (static_cast<float>(g.h) + 2 * pad) * k;
      const float u0 = (static_cast<float>(g.x) - pad) * iw, v0 = (static_cast<float>(g.y) - pad) * ih;
      const float u1 = (static_cast<float>(g.x + g.w) + pad) * iw, v1 = (static_cast<float>(g.y + g.h) + pad) * ih;
      const float cx0 = x0 * 2.0f / b.W - 1.0f, cx1 = x1 * 2.0f / b.W - 1.0f;
      const float cy0 = 1.0f - y0 * 2.0f / b.H, cy1 = 1.0f - y1 * 2.0f / b.H;
      const float xy[8] = {cx0, cy0, cx1, cy0, cx0, cy1, cx1, cy1};
      const float uv[8] = {u0, v0, u1, v0, u0, v1, u1, v1};
      b.Quad(xy, uv, col, 0);
    }
    x += g.adv * k;
  }
  return w;
}

// Greedy word wrap into at most maxLines lines of up to 127 characters.
inline int WrapText(const char* s, float size, float maxW, char lines[][128], int maxLines)
{
  int n = 0;
  while (*s && n < maxLines)
  {
    while (*s == ' ')
      s++;
    int len = 0, lastSpace = -1;
    float w = 0;
    while (s[len] && len < 127)
    {
      w += GlyphOf(s[len]).adv * size / static_cast<float>(font::kSize);
      if (s[len] == ' ')
        lastSpace = len;
      if (w > maxW && lastSpace > 0)
      {
        len = lastSpace;
        break;
      }
      len++;
    }
    std::memcpy(lines[n], s, static_cast<size_t>(len));
    lines[n][len] = 0;
    n++;
    s += len;
  }
  return n;
}

} // namespace evo
