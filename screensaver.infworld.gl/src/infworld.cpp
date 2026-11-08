#include "infworld.hpp"

#include <algorithm>
#include <cmath>
#include <random>

namespace sandclock {
namespace infworld {

namespace {

constexpr float PI = 3.14159265358979323846f;
constexpr float TREE_MODEL_SCALE = SCALE * 2.5f;  // the original's tree transform

float interpolate(float x, float lower, float upper, float a, float b) {
  return (x - lower) / (upper - lower) * (b - a) + a;
}

// The original's "please do not be periodic" integer hash, used for chunk seeds.
int chunk_seed(int x, int z, const WorldSeed& seed) {
  const Perm& p = seed[0];
  unsigned a = static_cast<unsigned>(x), b = static_cast<unsigned>(z);
  const unsigned w = 8 * sizeof(unsigned);
  const unsigned s = w / 2;
  a *= 3284157443u;
  b ^= (a << s) | (a >> (w - s));
  b *= 1911520717u;
  a ^= (b << s) | (b >> (w - s));
  a *= 2048419325u;
  return p.p[p.p[(static_cast<unsigned>(p.p[a & 255]) + b) & 255] & 255];
}

float random01(std::minstd_rand0& rng) {
  return static_cast<float>(rng()) / 2147483647.0f;
}

float random_tree_count(int density, int type) {
  if (density <= 0) return 0;
  if (density == 1) return type == TREE_PINE ? 20 : 6;
  if (density == 2) return type == TREE_PINE ? 48 : 16;
  return type == TREE_PINE ? 96 : 32;
}

// ---- Plant models ---------------------------------------------------------------
// A direct port of infworld's gfx.cpp / plants.cpp geometry, in model units.

struct Model {
  std::vector<Vec3> pos;
  std::vector<Vec3> nrm;
  std::vector<Vec2> uv;
  std::vector<unsigned> idx;
};

Model cone1(int prec) {
  Model m;
  const Vec3 top{0, 1, 0};
  m.pos.push_back(top);
  m.nrm.push_back({0, 1, 0});
  m.uv.push_back({0.5f, 1.0f});
  for (int i = 0; i < prec; ++i) {
    const float angle = 2.0f * PI / prec * i;
    const Vec3 vert{std::cos(angle), 0, std::sin(angle)};
    m.pos.push_back(vert);
    float fract = static_cast<float>(i % std::max(prec / 2, 1)) / static_cast<float>(prec - 1);
    float tcx = i < prec / 2 ? std::min(fract * 2.0f, 1.0f) : std::max(1.0f - fract * 2.0f, 0.0f);
    m.uv.push_back({tcx, 0.0f});
    const float next_angle = 2.0f * PI / prec * (i + 1);
    const Vec3 next{std::cos(next_angle), 0, std::sin(next_angle)};
    m.nrm.push_back(normalize(cross(top - vert, next - vert)));
    unsigned index1 = static_cast<unsigned>(i + 1);
    unsigned index2 = index1 + 1;
    if (index2 >= static_cast<unsigned>(prec) + 1) index2 = 1;
    m.idx.push_back(index2);
    m.idx.push_back(index1);
    m.idx.push_back(0);
  }
  return m;
}

Model cone2(int prec) {
  Model m;
  const Vec3 top{0, 1, 0};
  m.pos.push_back(top);
  m.nrm.push_back({0, 1, 0});
  m.uv.push_back({0.5f, 0.5f});
  for (int i = 0; i < prec; ++i) {
    const float angle = 2.0f * PI / prec * i;
    const Vec3 vert{std::cos(angle), 0, std::sin(angle)};
    m.pos.push_back(vert);
    const float next_angle = 2.0f * PI / prec * (i + 1);
    const Vec3 next{std::cos(next_angle), 0, std::sin(next_angle)};
    m.nrm.push_back(normalize(cross(top - vert, next - vert)));
    m.uv.push_back({std::cos(angle) * 0.5f + 0.5f, std::sin(angle) * 0.5f + 0.5f});
    unsigned index1 = static_cast<unsigned>(i + 1);
    unsigned index2 = index1 + 1;
    if (index2 >= static_cast<unsigned>(prec) + 1) index2 = 1;
    m.idx.push_back(index2);
    m.idx.push_back(index1);
    m.idx.push_back(0);
  }
  return m;
}

Model frustum(int prec, float radius1, float radius2) {
  Model m;
  for (int i = 0; i < prec; ++i) {
    const float angle = static_cast<float>(i) / prec * 2.0f * PI;
    const Vec3 vert = Vec3{std::cos(angle), 0, std::sin(angle)} * radius1;
    float fract = static_cast<float>(i % std::max(prec / 2, 1)) / static_cast<float>(prec - 1);
    float tcx = i < prec / 2 ? std::min(fract * 2.0f, 1.0f) : std::max(1.0f - fract * 2.0f, 0.0f);
    const Vec3 top = Vec3{std::cos(angle), 0, std::sin(angle)} * radius2 + Vec3{0, 1, 0};
    const float next_angle = static_cast<float>(i + 1) / prec * 2.0f * PI;
    const Vec3 next = Vec3{std::cos(next_angle), 0, std::sin(next_angle)} * radius1;
    m.pos.push_back(vert);
    m.uv.push_back({tcx, 0.0f});
    m.nrm.push_back(normalize(cross(top - vert, next - vert)));
  }
  for (int i = 0; i < prec; ++i) {
    const float angle = static_cast<float>(i) / prec * 2.0f * PI;
    const Vec3 vert = Vec3{std::cos(angle), 0, std::sin(angle)} * radius2 + Vec3{0, 1, 0};
    float fract = static_cast<float>(i % std::max(prec / 2, 1)) / static_cast<float>(prec - 1);
    float tcx = i < prec / 2 ? std::min(fract * 2.0f, 1.0f) : std::max(1.0f - fract * 2.0f, 0.0f);
    const Vec3 bot = Vec3{std::cos(angle), 0, std::sin(angle)} * radius1;
    const float next_angle = static_cast<float>(i + 1) / prec * 2.0f * PI;
    const Vec3 next = Vec3{std::cos(next_angle), 0, std::sin(next_angle)} * radius2 + Vec3{0, 1, 0};
    m.pos.push_back(vert);
    m.uv.push_back({tcx, 1.0f});
    m.nrm.push_back(normalize(cross(vert - bot, next - vert)));
  }
  for (int i = 0; i < prec; ++i) {
    m.idx.push_back(static_cast<unsigned>(i));
    m.idx.push_back(static_cast<unsigned>((i + 1) % prec));
    m.idx.push_back(static_cast<unsigned>(i + prec));
    m.idx.push_back(static_cast<unsigned>(i + prec));
    m.idx.push_back(static_cast<unsigned>((i + 1) % prec + prec));
    m.idx.push_back(static_cast<unsigned>((i + 1) % prec));
  }
  return m;
}

Model plane(int subdivision) {
  Model m;
  const int n = subdivision + 3;
  for (int i = 0; i <= n - 1; ++i) {
    for (int j = 0; j <= n - 1; ++j) {
      const float x = static_cast<float>(j) / (n - 1) * 2.0f - 1.0f;
      const float y = static_cast<float>(i) / (n - 1) * 2.0f - 1.0f;
      m.pos.push_back({x, y, 0});
      m.nrm.push_back({0, 0, 1});
      m.uv.push_back({static_cast<float>(j) / (n - 1), static_cast<float>(i) / (n - 1)});
    }
  }
  for (int i = 0; i < n - 1; ++i) {
    for (int j = 0; j < n - 1; ++j) {
      m.idx.push_back(static_cast<unsigned>(i * n + j));
      m.idx.push_back(static_cast<unsigned>(i * n + j + 1));
      m.idx.push_back(static_cast<unsigned>((i + 1) * n + j));
      m.idx.push_back(static_cast<unsigned>((i + 1) * n + j));
      m.idx.push_back(static_cast<unsigned>((i + 1) * n + j + 1));
      m.idx.push_back(static_cast<unsigned>(i * n + j + 1));
    }
  }
  return m;
}

void transform_model(Model& m, const Mat4& t) {
  for (Vec3& p : m.pos) p = transform_point(t, p);
  for (Vec3& n : m.nrm) n = transform_direction(t, n);
}

void transform_uv(Model& m, const Mat4& t) {
  for (Vec2& uv : m.uv) {
    const Vec3 p = transform_point(t, {uv.x, uv.y, 0});
    uv = {p.x, p.y};
  }
}

void merge(Model& into, const Model& other) {
  const unsigned base = static_cast<unsigned>(into.pos.size());
  into.pos.insert(into.pos.end(), other.pos.begin(), other.pos.end());
  into.nrm.insert(into.nrm.end(), other.nrm.begin(), other.nrm.end());
  into.uv.insert(into.uv.end(), other.uv.begin(), other.uv.end());
  for (unsigned i : other.idx) into.idx.push_back(base + i);
}

Model branch_segment(const Mat4& transform, const Vec3& position, unsigned depth, float thickness,
                     float decrease, float length, int detail) {
  const float radius1 = std::max(thickness - decrease * depth, 0.01f);
  const float radius2 = std::max(thickness - decrease * (depth + 1), 0.01f);
  Model m = frustum(detail, radius1, radius2);
  transform_uv(m, Mat4::translate({0.01f, 0, 0}) * Mat4::scale({0.48f, 2.0f, 1.0f}));
  const Mat4 place =
      Mat4::translate(position) * transform * Mat4::scale({1.0f, length, 1.0f});
  transform_model(m, place);
  return m;
}

Model branch_end(const Mat4& transform, const Vec3& position, unsigned depth, float thickness,
                 float decrease, float length, int detail) {
  Model m = cone1(detail);
  transform_uv(m, Mat4::translate({0.01f, 0, 0}) * Mat4::scale({0.48f, 2.0f, 1.0f}));
  const float radius = std::max(thickness - decrease * depth, 0.01f);
  transform_model(m, Mat4::scale({radius, length, radius}));
  transform_model(m, Mat4::translate(position) * transform);

  const float leaf_scale = depth <= 2 ? 0.5f : 1.0f;
  const Mat4 leaf_tc = Mat4::translate({0.51f, 0, 0}) * Mat4::scale({0.48f, 1.0f, 1.0f});
  const int leaf_count = std::max(2 * detail / 3 - 1, 1);
  const int leaf_detail = std::max(detail / 2 - 2, 0);
  const Vec3 tip = transform_point(transform, {0.0f, length, 0.0f});
  for (int i = 0; i < leaf_count; ++i) {
    Model leaves = plane(leaf_detail);
    transform_uv(leaves, leaf_tc);
    const Vec3 offset = (1.0f - leaf_scale) * tip;
    const Mat4 place = Mat4::translate(position + offset) * transform *
                       Mat4::rotate_y(120.0f * PI / 180.0f * i) *
                       Mat4::scale({leaf_scale, leaf_scale, leaf_scale}) *
                       Mat4::translate({0, 1, 0});
    transform_model(leaves, place);
    merge(m, leaves);
  }
  return m;
}

std::string lsystem(unsigned iterations, const std::string& axiom, const std::string& rule) {
  std::string result = axiom;
  for (unsigned i = 0; i < iterations; ++i) {
    std::string next;
    for (char c : result) {
      if (c == 'F')
        next += rule;
      else
        next += c;
    }
    result.swap(next);
  }
  return result;
}

Model plant_from_str(const std::string& str, float angle, float length, float thickness,
                     float decrease, int detail) {
  struct Branch {
    Mat4 transform;
    Vec3 position;
    unsigned depth = 0;
  };
  Model plant;
  std::vector<Branch> stack;
  Branch branch;
  const float a = angle;
  for (size_t i = 0; i < str.size(); ++i) {
    const char c = str[i];
    switch (c) {
      case '<': branch.transform = branch.transform * Mat4::rotate_x(a); continue;
      case '>': branch.transform = branch.transform * Mat4::rotate_x(-a); continue;
      case '&': branch.transform = branch.transform * Mat4::rotate_y(a); continue;
      case '+': branch.transform = branch.transform * Mat4::rotate_z(a); continue;
      case '-': branch.transform = branch.transform * Mat4::rotate_z(-a); continue;
      case '[': stack.push_back(branch); continue;
      case ']':
        if (!stack.empty()) {
          branch = stack.back();
          stack.pop_back();
        }
        continue;
      case 'F': {
        const bool end = i + 1 >= str.size() || str[i + 1] == ']';
        merge(plant, end ? branch_end(branch.transform, branch.position, branch.depth, thickness,
                                      decrease, length, detail)
                         : branch_segment(branch.transform, branch.position, branch.depth,
                                          thickness, decrease, length, detail));
        branch.position += transform_point(branch.transform, {0, length, 0});
        ++branch.depth;
        continue;
      }
      default: continue;
    }
  }
  return plant;
}

Model pine_model(int detail) {
  Model tree = cone1(detail);
  transform_model(tree, Mat4::scale({0.3f, 5.0f, 0.3f}));
  transform_uv(tree, Mat4::scale({0.5f, 8.0f, 1.0f}));

  if (detail > 4) {
    Model bottom = frustum(detail, 0.3f, 0.3f);
    transform_model(bottom, Mat4::translate({0, -1, 0}));
    transform_uv(bottom, Mat4::translate({0.01f, 0, 0}) * Mat4::scale({0.48f, 8.0f / 5.0f, 1}));
    merge(tree, bottom);
  }

  Vec3 top{0, 5, 0};
  const Mat4 tc = Mat4::translate({0.51f, 0.02f, 0}) * Mat4::scale({0.48f, 0.96f, 1});
  for (int i = 0; i < 4; ++i) {
    Model part = cone2(detail);
    const float s = 0.75f + 0.25f * std::pow(1.5f, static_cast<float>(i));
    const float h = 1.6f + 0.2f * i;
    const Mat4 place = Mat4::translate(top - Vec3{0, h, 0}) * Mat4::scale({s, h, s}) *
                       Mat4::rotate_y(PI / 16.0f * i);
    transform_model(part, place);
    transform_uv(part, tc);
    merge(tree, part);
    top.y -= s * 0.6f;
  }
  return tree;
}

Model leafy_model(int detail) {
  constexpr float ANGLE = 30.0f * PI / 180.0f;
  constexpr float LENGTH = 0.8f;
  constexpr float THICKNESS = 0.15f;
  constexpr float DECREASE = 0.025f;
  constexpr unsigned ITERATIONS = 2;
  const std::string RULE = "F[&&>F]F[--F][&&&&-F][&&&&&&&&-F]";
  Model tree = plant_from_str(lsystem(ITERATIONS, "F", RULE), ANGLE, LENGTH, THICKNESS, DECREASE,
                              detail);
  if (detail > 4) {
    Model bottom = frustum(detail, THICKNESS, THICKNESS);
    transform_model(bottom, Mat4::translate({0, -1, 0}));
    transform_uv(bottom, Mat4::translate({0.01f, 0, 0}) * Mat4::scale({0.48f, 8.0f / 5.0f, 1}));
    merge(tree, bottom);
  }
  return tree;
}

void append_model(TreeMesh& mesh, const Model& model, const Mat4& transform, float tree_scale,
                  unsigned* first, unsigned* count) {
  const unsigned base = static_cast<unsigned>(mesh.verts.size());
  *first = static_cast<unsigned>(mesh.indices.size());
  for (size_t i = 0; i < model.pos.size(); ++i) {
    const Vec3 p = transform_point(transform, model.pos[i]);
    const Vec3 n = transform_direction(transform, model.nrm[i]);
    TreeVertex v;
    v.x = p.x;
    v.y = p.y;
    v.z = p.z;
    v.u = model.uv[i].x;
    v.v = model.uv[i].y;
    v.nx = n.x;
    v.ny = n.y;
    v.nz = n.z;
    const Vec3 local = model.pos[i];
    v.sway = std::sqrt(local.x * local.x + local.z * local.z) * tree_scale;
    mesh.verts.push_back(v);
  }
  for (unsigned index : model.idx) mesh.indices.push_back(static_cast<unsigned short>(base + index));
  *count = static_cast<unsigned>(mesh.indices.size()) - *first;
  if (mesh.indices.size() > 65535) {
    // Terrain chunks guarantee this; decorations would need splitting if they ever did.
    mesh.indices.resize(65535);
  }
}

}  // namespace

// ---- Settings -------------------------------------------------------------------

void Settings::sanitise() {
  range = std::max(3, std::min(9, range));
  detail = std::max(0, std::min(2, detail));
  trees = std::max(0, std::min(3, trees));
  mode = std::max(0, std::min(2, mode));
  speed = std::max(10, std::min(200, speed));
  height = std::max(20, std::min(400, height));
  dim = std::max(0, std::min(80, dim));
  draw_res = std::max(0, std::min(4, draw_res));
}

// ---- Noise and heights ----------------------------------------------------------

WorldSeed make_seed(int seed) {
  WorldSeed permutations(6);
  std::minstd_rand outer(static_cast<unsigned>(seed));
  for (Perm& perm : permutations) {
    const unsigned inner_seed = outer();
    std::minstd_rand lcg(inner_seed);
    int values[256];
    for (int i = 0; i < 256; ++i) values[i] = i;
    int count = 256, index = 0;
    while (count > 0) {
      const int pick = static_cast<int>(lcg() % static_cast<unsigned>(count));
      perm.p[index++] = values[pick];
      values[pick] = values[count - 1];
      --count;
    }
  }
  return permutations;
}

namespace {
Vec2 gradient(int x, int y, const Perm& p) {
  const unsigned w = 8 * sizeof(unsigned);
  const unsigned s = w / 2;
  unsigned a = static_cast<unsigned>(x), b = static_cast<unsigned>(y);
  a *= 3284157443u;
  b ^= (a << s) | (a >> (w - s));
  b *= 1911520717u;
  a ^= (b << s) | (b >> (w - s));
  a *= 2048419325u;
  static const Vec2 gradients[4] = {{1, 0}, {-1, 0}, {0, 1}, {0, -1}};
  const int index =
      p.p[static_cast<unsigned>(p.p[static_cast<unsigned>(p.p[a & 255] + b) & 255]) & 255];
  return gradients[index & 3];
}

float dot_gradient(int gx, int gy, float x, float y, const Perm& p) {
  const Vec2 v = gradient(gx, gy, p);
  return v.x * (x - gx) + v.y * (y - gy);
}

float noise_interp(float a, float b, float x) {
  return (b - a) * (3.0f - x * 2.0f) * x * x + a;
}
}  // namespace

float noise(float x, float y, const Perm& p) {
  const int leftx = static_cast<int>(std::floor(x));
  const int lowery = static_cast<int>(std::floor(y));
  const float fx = x - leftx, fy = y - lowery;
  const float lowerleft = dot_gradient(leftx, lowery, x, y, p);
  const float lowerright = dot_gradient(leftx + 1, lowery, x, y, p);
  const float upperleft = dot_gradient(leftx, lowery + 1, x, y, p);
  const float upperright = dot_gradient(leftx + 1, lowery + 1, x, y, p);
  return noise_interp(noise_interp(lowerleft, lowerright, fx),
                      noise_interp(upperleft, upperright, fx), fy);
}

float height(float x, float z, const WorldSeed& seed) {
  float h = 0;
  float freq = FREQUENCY;
  float amplitude = 1.0f;
  for (const Perm& p : seed) {
    h += noise(x / freq, z / freq, p) * amplitude;
    freq *= 0.5f;
    amplitude *= 0.5f;
  }
  if (h < -0.1f)
    h = interpolate(h, -1.0f, -0.1f, -1.0f, 0.003f);
  else if (h < 0.0f)
    h = interpolate(h, -0.1f, 0.0f, 0.003f, 0.03f);
  else if (h < 0.15f)
    h = interpolate(h, 0.0f, 0.15f, 0.03f, 0.12f);
  else
    h = interpolate(h, 0.15f, 1.0f, 0.12f, 1.0f);
  return std::max(-1.0f, std::min(1.0f, h));
}

float world_height(float wx, float wz, const WorldSeed& seed) {
  return height(wx / SCALE, wz / SCALE, seed) * HEIGHT * SCALE;
}

namespace {
float normal_angle(float x, float y) {
  if (x == 0.0f) return y >= 0.0f ? PI / 2.0f : PI * 1.5f;
  float angle = std::atan(y / x);
  if (x > 0.0f && y < 0.0f)
    angle += PI * 2.0f;
  else if (x < 0.0f)
    angle += PI;
  return angle;
}
}  // namespace

Vec2 compress_normal(const Vec3& n) {
  return {normal_angle(n.x, n.z), std::asin(std::max(-1.0f, std::min(1.0f, n.y)))};
}

// ---- ChunkTable -----------------------------------------------------------------

void ChunkTable::init(int range, float chunk_scale, int precision, const WorldSeed* seed) {
  range_ = range;
  size_ = 2 * range + 1;
  chunk_scale_ = chunk_scale;
  precision_ = precision;
  seed_ = seed;
  positions_.clear();
  positions_.reserve(static_cast<size_t>(size_) * size_);
  for (int x = -range; x <= range; ++x)
    for (int z = -range; z <= range; ++z) positions_.push_back({x, z});
  chunks_.assign(positions_.size(), TerrainChunk{});
  pending_.clear();
  pending_.reserve(positions_.size());
  queued_.assign(positions_.size(), 1);
  for (int i = 0; i < static_cast<int>(positions_.size()); ++i) pending_.push_back(i);
  centerx_ = centerz_ = 0;
  started_ = false;
}

int ChunkTable::center_of(float camera) const {
  return static_cast<int>(std::floor(camera / world_size() + 0.5f));
}

bool ChunkTable::follow(float camx, float camz) {
  const int cx = center_of(camx), cz = center_of(camz);
  if (started_ && cx == centerx_ && cz == centerz_) return false;

  const int n = size_, r = range_;
  std::vector<int> slot_at(static_cast<size_t>(n) * n, -1);
  std::vector<char> used(static_cast<size_t>(n) * n, 0);
  for (int s = 0; s < static_cast<int>(positions_.size()); ++s) {
    const int dx = positions_[s].x - cx, dz = positions_[s].z - cz;
    if (std::abs(dx) <= r && std::abs(dz) <= r) {
      slot_at[(dx + r) * n + (dz + r)] = s;
      used[s] = 1;
    }
  }
  std::vector<Vec2i> needed;
  for (int dx = -r; dx <= r; ++dx)
    for (int dz = -r; dz <= r; ++dz)
      if (slot_at[(dx + r) * n + (dz + r)] < 0) needed.push_back({cx + dx, cz + dz});
  std::sort(needed.begin(), needed.end(), [](const Vec2i& a, const Vec2i& b) {
    return a.x * a.x + a.z * a.z < b.x * b.x + b.z * b.z;
  });

  size_t next = 0;
  for (int s = 0; s < static_cast<int>(positions_.size()); ++s) {
    if (used[s]) continue;
    positions_[s] = needed[next++];
    chunks_[s].verts.clear();
    chunks_[s].ready = false;
    ++chunks_[s].serial;
    if (!queued_[s]) {
      queued_[s] = 1;
      pending_.push_back(s);
    }
  }
  centerx_ = cx;
  centerz_ = cz;
  started_ = true;

  std::sort(pending_.begin(), pending_.end(), [this, cx, cz](int a, int b) {
    const Vec2i pa = positions_[a], pb = positions_[b];
    const int da = (pa.x - cx) * (pa.x - cx) + (pa.z - cz) * (pa.z - cz);
    const int db = (pb.x - cx) * (pb.x - cx) + (pb.z - cz) * (pb.z - cz);
    return da < db;
  });
  return true;
}

int ChunkTable::build(int max_chunks, std::vector<int>* built) {
  int made = 0;
  while (made < max_chunks && !pending_.empty()) {
    const int slot = pending_.front();
    pending_.erase(pending_.begin());
    queued_[slot] = 0;
    build_chunk(slot);
    if (built) built->push_back(slot);
    ++made;
  }
  return made;
}

void ChunkTable::build_chunk(int slot) {
  const int p = precision_;
  const int n = p + 1;
  const float cs = chunk_scale_;
  const float step = 2.0f * cs / p;
  const Vec2i pos = positions_[slot];
  const float bx = pos.x * 2.0f * cs - cs;
  const float bz = pos.z * 2.0f * cs - cs;

  std::vector<float> hs(static_cast<size_t>(n) * n);
  for (int i = 0; i < n; ++i)
    for (int j = 0; j < n; ++j) hs[i * n + j] = height(bx + i * step, bz + j * step, *seed_);

  TerrainChunk& c = chunks_[slot];
  c.verts.assign(static_cast<size_t>(n) * n * 3, 0.0f);
  for (int i = 0; i < n; ++i) {
    for (int j = 0; j < n; ++j) {
      const int index = i * n + j;
      const int il = i > 0 ? i - 1 : i, ir = i < p ? i + 1 : i;
      const int jl = j > 0 ? j - 1 : j, jr = j < p ? j + 1 : j;
      const float dhx = (hs[ir * n + j] - hs[il * n + j]) * HEIGHT / ((ir - il) * step);
      const float dhz = (hs[i * n + jr] - hs[i * n + jl]) * HEIGHT / ((jr - jl) * step);
      const Vec3 normal = normalize({-dhx, 1.0f, -dhz});
      const Vec2 compressed = compress_normal(normal);

      float hw = hs[index] * HEIGHT;
      hw = hw <= 0.0f ? std::min(-0.007f, hw) : std::max(0.007f, hw);
      c.verts[index * 3 + 0] = hw / HEIGHT;
      c.verts[index * 3 + 1] = compressed.x;
      c.verts[index * 3 + 2] = compressed.y;
    }
  }
  c.ready = true;
  ++c.serial;
}

Vec3 ChunkTable::center_world(int slot) const {
  const Vec2i p = positions_[slot];
  return {p.x * world_size(), 0.0f, p.z * world_size()};
}

// ---- DecorationTable ------------------------------------------------------------

void DecorationTable::init(int range, float chunk_scale, int density, const WorldSeed* seed) {
  range_ = range;
  size_ = 2 * range + 1;
  chunk_scale_ = chunk_scale;
  density_ = density;
  seed_ = seed;
  positions_.clear();
  positions_.reserve(static_cast<size_t>(size_) * size_);
  for (int x = -range; x <= range; ++x)
    for (int z = -range; z <= range; ++z) positions_.push_back({x, z});
  chunks_.assign(positions_.size(), DecorationChunk{});
  centerx_ = centerz_ = 0;
  started_ = false;
}

int DecorationTable::center_of(float camera) const {
  return static_cast<int>(std::floor(camera / (2.0f * chunk_scale_ * SCALE) + 0.5f));
}

bool DecorationTable::follow(float camx, float camz) {
  const int cx = center_of(camx), cz = center_of(camz);
  if (started_ && cx == centerx_ && cz == centerz_) return false;

  const int n = size_, r = range_;
  std::vector<int> slot_at(static_cast<size_t>(n) * n, -1);
  std::vector<char> used(static_cast<size_t>(n) * n, 0);
  for (int s = 0; s < static_cast<int>(positions_.size()); ++s) {
    const int dx = positions_[s].x - cx, dz = positions_[s].z - cz;
    if (std::abs(dx) <= r && std::abs(dz) <= r) {
      slot_at[(dx + r) * n + (dz + r)] = s;
      used[s] = 1;
    }
  }
  std::vector<Vec2i> needed;
  for (int dx = -r; dx <= r; ++dx)
    for (int dz = -r; dz <= r; ++dz)
      if (slot_at[(dx + r) * n + (dz + r)] < 0) needed.push_back({cx + dx, cz + dz});
  std::sort(needed.begin(), needed.end(), [](const Vec2i& a, const Vec2i& b) {
    return a.x * a.x + a.z * a.z < b.x * b.x + b.z * b.z;
  });

  size_t next = 0;
  for (int s = 0; s < static_cast<int>(positions_.size()); ++s) {
    if (used[s]) continue;
    positions_[s] = needed[next++];
    generate(s);
  }
  centerx_ = cx;
  centerz_ = cz;
  started_ = true;
  return true;
}

void DecorationTable::generate(int slot) {
  DecorationChunk& c = chunks_[slot];
  const Vec2i pos = positions_[slot];
  const float span = 2.0f * chunk_scale_;
  c.trees.clear();
  c.center = {pos.x * span * SCALE, 0.0f, pos.z * span * SCALE};
  ++c.serial;
  c.ready = true;
  if (density_ <= 0) return;

  std::minstd_rand0 lcg(static_cast<unsigned>(chunk_seed(pos.x, pos.z, *seed_)));

  auto add = [&](int type, float amount) {
    const int count = static_cast<int>(lcg() % static_cast<unsigned>(std::max(1.0f, amount)));
    for (int i = 0; i < count; ++i) {
      const float lx = random01(lcg) * span - chunk_scale_;
      const float lz = random01(lcg) * span - chunk_scale_;
      const float px = pos.x * span + lx;
      const float pz = pos.z * span + lz;
      const float h = height(px, pz, *seed_);
      if (noise(pz / 128.0f, px / 128.0f, (*seed_)[0]) < 0.0f) continue;
      if (type == TREE_PINE && (h < 0.04f || h > 0.30f)) continue;
      if (type == TREE_LEAFY && (h < 0.02f || h > 0.20f)) continue;
      TreeInstance tree;
      tree.x = px * SCALE - c.center.x;
      tree.y = h * HEIGHT * SCALE;
      tree.z = pz * SCALE - c.center.z;
      tree.rotation = random01(lcg) * 2.0f * PI;
      tree.scale = 0.75f + random01(lcg) * 0.5f;
      tree.type = type;
      c.trees.push_back(tree);
    }
  };
  add(TREE_PINE, random_tree_count(density_, TREE_PINE));
  add(TREE_LEAFY, random_tree_count(density_, TREE_LEAFY));
}

// ---- Tree meshes ----------------------------------------------------------------

TreeMesh make_pine_tree(int detail) {
  const Model m = pine_model(detail);
  TreeMesh mesh;
  unsigned first = 0, count = 0;
  append_model(mesh, m, Mat4::scale({TREE_MODEL_SCALE, TREE_MODEL_SCALE, TREE_MODEL_SCALE}),
               TREE_MODEL_SCALE, &first, &count);
  mesh.pine_count_ = count;
  mesh.leafy_count_ = 0;
  return mesh;
}

TreeMesh make_leafy_tree(int detail) {
  const Model m = leafy_model(detail);
  TreeMesh mesh;
  unsigned first = 0, count = 0;
  append_model(mesh, m, Mat4::scale({TREE_MODEL_SCALE, TREE_MODEL_SCALE, TREE_MODEL_SCALE}),
               TREE_MODEL_SCALE, &first, &count);
  mesh.pine_count_ = 0;
  mesh.leafy_count_ = count;
  return mesh;
}

TreeMesh bake_trees(const TreeMesh& pine, const TreeMesh& leafy,
                    const std::vector<TreeInstance>& trees) {
  TreeMesh mesh;
  const TreeMesh* templates[2] = {&pine, &leafy};
  for (int type = 0; type < 2; ++type) {
    const TreeMesh& source = *templates[type];
    unsigned index_count = 0;
    for (const TreeInstance& tree : trees) {
      if (tree.type != type) continue;
      const unsigned base = static_cast<unsigned>(mesh.verts.size());
      const Mat4 rotation = Mat4::rotate_y(tree.rotation);
      for (const TreeVertex& v : source.verts) {
        const Vec3 p = transform_point(rotation, {v.x, v.y, v.z}) * tree.scale;
        const Vec3 n = transform_point(rotation, {v.nx, v.ny, v.nz});
        TreeVertex out;
        out.x = p.x + tree.x;
        out.y = p.y + tree.y;
        out.z = p.z + tree.z;
        out.u = v.u;
        out.v = v.v;
        out.nx = n.x;
        out.ny = n.y;
        out.nz = n.z;
        out.sway = v.sway * tree.scale;
        mesh.verts.push_back(out);
      }
      for (unsigned short index : source.indices)
        mesh.indices.push_back(static_cast<unsigned short>(base + index));
      index_count += static_cast<unsigned>(source.indices.size());
    }
    if (type == TREE_PINE)
      mesh.pine_count_ = index_count;
    else
      mesh.leafy_count_ = index_count;
  }
  return mesh;
}

// ---- Shared terrain topology ----------------------------------------------------

std::vector<float> make_grid(int precision, float chunk_scale) {
  const int n = precision + 1;
  std::vector<float> grid(static_cast<size_t>(n) * n * 2);
  for (int i = 0; i < n; ++i) {
    for (int j = 0; j < n; ++j) {
      const size_t k = (static_cast<size_t>(i) * n + j) * 2;
      grid[k] = -chunk_scale + static_cast<float>(i) / precision * 2.0f * chunk_scale;
      grid[k + 1] = -chunk_scale + static_cast<float>(j) / precision * 2.0f * chunk_scale;
    }
  }
  return grid;
}

std::vector<unsigned short> make_indices(int precision) {
  std::vector<unsigned short> indices;
  indices.reserve(static_cast<size_t>(precision) * precision * 6);
  for (int i = 0; i < precision; ++i) {
    for (int j = 0; j < precision; ++j) {
      const unsigned index = static_cast<unsigned>(i * (precision + 1) + j);
      // Counter-clockwise seen from above, so the ground is front-facing for glCullFace(GL_BACK).
      // (infworld's original shader swapped x and z in gl_VertexID, which mirrored each chunk.)
      indices.push_back(static_cast<unsigned short>(index + 1));
      indices.push_back(static_cast<unsigned short>(index + precision + 1));
      indices.push_back(static_cast<unsigned short>(index));
      indices.push_back(static_cast<unsigned short>(index + precision + 1));
      indices.push_back(static_cast<unsigned short>(index + 1));
      indices.push_back(static_cast<unsigned short>(index + precision + 2));
    }
  }
  return indices;
}

// ---- Frustum --------------------------------------------------------------------

namespace {
Frustum::Plane plane_at(const Vec3& position, const Vec3& normal) {
  Frustum::Plane p;
  p.n = normalize(normal);
  p.d = dot(position, p.n);
  return p;
}
}  // namespace

Frustum make_frustum(const Vec3& pos, const Vec3& forward, const Vec3& right, const Vec3& up,
                     float znear, float zfar, float aspect, float fovy) {
  const Vec3 f = normalize(forward);
  const Vec3 r = normalize(right);
  const Vec3 u = normalize(up);
  const float half_height = zfar * std::tan(fovy / 2.0f);
  const float half_width = half_height * aspect;
  Frustum frustum;
  frustum.planes[0] = plane_at(pos + f * znear, f);
  frustum.planes[1] = plane_at(pos + f * zfar, -f);
  frustum.planes[2] = plane_at(pos, cross(r, f * zfar + u * half_height));
  frustum.planes[3] = plane_at(pos, cross(f * zfar - u * half_height, r));
  frustum.planes[4] = plane_at(pos, cross(u, f * zfar - r * half_width));
  frustum.planes[5] = plane_at(pos, cross(f * zfar + r * half_width, u));
  return frustum;
}

bool intersects(const Frustum& frustum, const Vec3& center, const Vec3& half) {
  for (const Frustum::Plane& p : frustum.planes) {
    const float radius =
        std::abs(p.n.x) * half.x + std::abs(p.n.y) * half.y + std::abs(p.n.z) * half.z;
    if (dot(center, p.n) - p.d < -radius) return false;
  }
  return true;
}

}  // namespace infworld
}  // namespace sandclock
