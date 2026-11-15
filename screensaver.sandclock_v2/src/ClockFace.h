// The clock text, laid out and rasterised onto a simulation grid. No Kodi / GL.
//
// The glyph masks come from Glyphs.h (the Sand Clock fonts). A glyph is
// stretched over its advance box as in the other Sand Clock add-ons, and a
// grid cell belongs to the glyph when most of its footprint is ink (2 x 2
// samples), so thin strokes stay connected at coarse grids.
#pragma once

#include "Glyphs.h"

#include <algorithm>
#include <cmath>
#include <cstdint>
#include <cstdio>
#include <string>
#include <vector>

namespace sandclock2
{

constexpr int kMaxSlots = 8; // "HH:MM:SS"

struct ClockStyle
{
  int font = 0;          // index into kFaces / FONTS in the settings generator
  int weight = 1;        // 0 regular, 1 bold
  bool seconds = true;
  bool twelveHour = false;
  float size = 0.8f;     // widest text as a fraction of the grid width
  float maxHeight = 0.34f; // ... and at most this fraction of the grid height
  float centreY = 0.30f; // centre of the text, fraction of the height from the top
};

inline std::string TimeText(const ClockStyle& s, int hour, int minute, int second)
{
  const int h = s.twelveHour ? (hour % 12 == 0 ? 12 : hour % 12) : hour;
  char buf[16];
  if (s.seconds)
    std::snprintf(buf, sizeof buf, s.twelveHour ? "%d:%02d:%02d" : "%02d:%02d:%02d", h, minute, second);
  else
    std::snprintf(buf, sizeof buf, s.twelveHour ? "%d:%02d" : "%02d:%02d", h, minute);
  return buf;
}

inline int CharIndex(char c) { return c == ':' ? 10 : c - '0'; }

inline const Face& FaceOf(const ClockStyle& s)
{
  const int f = std::min(std::max(s.font, 0), kNumFonts - 1);
  const int w = std::min(std::max(s.weight, 0), kNumWeights - 1);
  return kFaces[f * kNumWeights + w];
}

inline const Glyph& GlyphOf(const ClockStyle& s, char c)
{
  const int f = std::min(std::max(s.font, 0), kNumFonts - 1);
  const int w = std::min(std::max(s.weight, 0), kNumWeights - 1);
  return kGlyphs[(f * kNumWeights + w) * kNumChars + CharIndex(c)];
}

// One glyph decoded to a bitmap.
struct Bitmap
{
  int w = 0, h = 0;
  std::vector<uint8_t> px;
  bool at(int u, int v) const { return u >= 0 && v >= 0 && u < w && v < h && px[v * w + u]; }
};

inline Bitmap Decode(const Glyph& g)
{
  Bitmap b;
  b.w = g.w;
  b.h = g.h;
  b.px.assign(static_cast<size_t>(b.w) * b.h, 0);
  const uint16_t* p = kRuns + g.offset;
  for (int r = 0; r < b.h; r++)
  {
    const int n = *p++;
    for (int k = 0; k < n; k++)
    {
      const int start = *p++, len = *p++;
      for (int u = start; u < std::min<int>(start + len, b.w); u++)
        b.px[static_cast<size_t>(r) * b.w + u] = 1;
    }
  }
  return b;
}

// Where each character of the text goes, in grid cells (floating point).
struct Box
{
  float x, y, w, h;
};

inline std::vector<Box> Layout(const ClockStyle& s, const std::string& text, int gridW, int gridH,
                               float offsetX = 0, float offsetY = 0)
{
  const Face& face = FaceOf(s);
  auto advance = [&](char c) { return static_cast<float>(c == ':' ? face.colonW : face.digitW); };
  const std::string widest = s.seconds ? "88:88:88" : "88:88";
  float widestW = 0, textW = 0;
  for (char c : widest)
    widestW += advance(c);
  for (char c : text)
    textW += advance(c);
  const float scale = std::min(gridW * s.size / widestW, gridH * s.maxHeight / face.h);
  const float h = face.h * scale;
  float x = (gridW - textW * scale) * 0.5f + offsetX;
  const float y = gridH * s.centreY - h * 0.5f + offsetY;
  std::vector<Box> boxes;
  for (char c : text)
  {
    const float w = advance(c) * scale;
    boxes.push_back({x, y, w, h});
    x += w;
  }
  return boxes;
}

// The cells of one glyph in its box: (x, y) grid cells, row 0 at the top.
struct Cell
{
  int x, y;
};

inline std::vector<Cell> Rasterise(const Bitmap& bm, const Box& b, int gridW, int gridH)
{
  std::vector<Cell> out;
  if (bm.w == 0 || bm.h == 0 || b.w <= 0 || b.h <= 0)
    return out;
  const int x0 = std::max(0, static_cast<int>(std::floor(b.x)));
  const int x1 = std::min(gridW, static_cast<int>(std::ceil(b.x + b.w)));
  const int y0 = std::max(0, static_cast<int>(std::floor(b.y)));
  const int y1 = std::min(gridH, static_cast<int>(std::ceil(b.y + b.h)));
  for (int y = y0; y < y1; y++)
    for (int x = x0; x < x1; x++)
    {
      int ink = 0;
      for (int sy = 0; sy < 2; sy++)
        for (int sx = 0; sx < 2; sx++)
        {
          const float fx = (x + 0.25f + 0.5f * sx - b.x) / b.w;
          const float fy = (y + 0.25f + 0.5f * sy - b.y) / b.h;
          ink += bm.at(static_cast<int>(fx * bm.w), static_cast<int>(fy * bm.h));
        }
      if (ink >= 2)
        out.push_back({x, y});
    }
  return out;
}

// Decoded glyphs for one style, cached.
class GlyphCache
{
public:
  void Set(const ClockStyle& s)
  {
    m_style = s;
    for (int i = 0; i < kNumChars; i++)
      m_bm[i] = Decode(GlyphOf(s, i == 10 ? ':' : static_cast<char>('0' + i)));
  }
  const Bitmap& Get(char c) const { return m_bm[CharIndex(c)]; }
  const ClockStyle& style() const { return m_style; }

private:
  ClockStyle m_style;
  Bitmap m_bm[kNumChars];
};

} // namespace sandclock2
