// The baked crab: mesh, and a skinning palette sampled at evenly spaced times over one loop of
// the walk cycle. Written by tools/make_crab_model.py (format described there). No GL here.
#pragma once

#include <algorithm>
#include <cmath>
#include <cstdint>
#include <cstring>
#include <fstream>
#include <string>
#include <vector>

namespace crab
{

#pragma pack(push, 1)
struct Vertex
{
  float pos[3];
  int8_t nrm[4];
  int8_t tan[4];
  uint16_t uv[2];
  uint8_t joint[4];
  uint8_t weight[4];
};
#pragma pack(pop)
static_assert(sizeof(Vertex) == 32, "crab.bin vertex layout");

// Feet on the ground move +x relative to the body, so one loop of the cycle carries the crab
// this far towards -x (model units, bounding radius 1). Measured by the converter's data.
constexpr float kWalkPerLoop = 0.27f;

class Model
{
public:
  bool Load(const std::string& path, std::string* error)
  {
    std::ifstream f(path, std::ios::binary);
    if (!f)
    {
      *error = "cannot open " + path;
      return false;
    }
    std::vector<char> d((std::istreambuf_iterator<char>(f)), std::istreambuf_iterator<char>());
    if (d.size() < 32 || std::memcmp(d.data(), "CRB1", 4) != 0)
    {
      *error = "not a crab model: " + path;
      return false;
    }
    uint32_t h[4];
    float hf[3];
    std::memcpy(h, d.data() + 4, 16);
    std::memcpy(hf, d.data() + 20, 12);
    const size_t nv = h[0], ni = h[1], np = h[2], nf = h[3];
    const size_t need = 32 + nv * sizeof(Vertex) + ni * 2 + nf * np * 12 * 4;
    if (nv == 0 || ni == 0 || np == 0 || nf == 0 || d.size() < need)
    {
      *error = "truncated crab model: " + path;
      return false;
    }
    m_vertices.resize(nv);
    m_indices.resize(ni);
    m_palette.resize(nf * np * 12);
    size_t o = 32;
    std::memcpy(m_vertices.data(), d.data() + o, nv * sizeof(Vertex));
    o += nv * sizeof(Vertex);
    std::memcpy(m_indices.data(), d.data() + o, ni * 2);
    o += ni * 2;
    std::memcpy(m_palette.data(), d.data() + o, m_palette.size() * 4);
    m_joints = static_cast<int>(np);
    m_frames = static_cast<int>(nf);
    m_duration = hf[0] > 0 ? hf[0] : 1.0f;
    for (const Vertex& v : m_vertices)
      for (int k = 0; k < 4; k++)
        if (v.joint[k] >= np)
        {
          *error = "bad joint index in " + path;
          return false;
        }
    return true;
  }

  // Palette (joints x 3 rows of vec4) at time t seconds into the loop (any t; it wraps).
  void Pose(float t, std::vector<float>& out) const
  {
    const float frame = std::fmod(t / m_duration, 1.0f) * m_frames;
    float f = frame < 0 ? frame + m_frames : frame;
    int a = static_cast<int>(f);
    if (a >= m_frames)
      a = 0;
    const int b = (a + 1) % m_frames;
    const float k = f - static_cast<float>(a);
    const size_t n = static_cast<size_t>(m_joints) * 12;
    out.resize(n);
    const float* pa = &m_palette[a * n];
    const float* pb = &m_palette[b * n];
    for (size_t i = 0; i < n; i++)
      out[i] = pa[i] + (pb[i] - pa[i]) * k;
  }

  // CPU skinning, for GPUs with too few vertex uniforms. Writes position, normal, tangent
  // (3 + 3 + 4 floats per vertex).
  void Skin(const std::vector<float>& pal, std::vector<float>& out) const
  {
    out.resize(m_vertices.size() * 10);
    float* o = out.data();
    for (const Vertex& v : m_vertices)
    {
      float m[12] = {0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0};
      for (int k = 0; k < 4; k++)
      {
        if (!v.weight[k])
          continue;
        const float w = v.weight[k] * (1.0f / 255.0f);
        const float* p = &pal[v.joint[k] * 12];
        for (int i = 0; i < 12; i++)
          m[i] += w * p[i];
      }
      const float x = v.pos[0], y = v.pos[1], z = v.pos[2];
      const float nx = v.nrm[0], ny = v.nrm[1], nz = v.nrm[2];
      const float tx = v.tan[0], ty = v.tan[1], tz = v.tan[2];
      for (int r = 0; r < 3; r++)
      {
        o[r] = m[r * 4] * x + m[r * 4 + 1] * y + m[r * 4 + 2] * z + m[r * 4 + 3];
        o[3 + r] = (m[r * 4] * nx + m[r * 4 + 1] * ny + m[r * 4 + 2] * nz) * (1.0f / 127.0f);
        o[6 + r] = (m[r * 4] * tx + m[r * 4 + 1] * ty + m[r * 4 + 2] * tz) * (1.0f / 127.0f);
      }
      o[9] = v.tan[3] < 0 ? -1.0f : 1.0f;
      o += 10;
    }
  }

  const std::vector<Vertex>& Vertices() const { return m_vertices; }
  const std::vector<uint16_t>& Indices() const { return m_indices; }
  int Joints() const { return m_joints; }
  float Duration() const { return m_duration; }

private:
  std::vector<Vertex> m_vertices;
  std::vector<uint16_t> m_indices;
  std::vector<float> m_palette; // frames x joints x 12
  int m_joints = 0, m_frames = 0;
  float m_duration = 1;
};

} // namespace crab
