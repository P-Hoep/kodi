// Endless World: the world model behind the screensaver, ported from infworld
// (Copyright 2024 Jeremy Li "Nullptr Error", MIT) into the sandclock framework.
//
// Everything in this file is CPU-only and knows nothing about OpenGL: multi-octave
// gradient-noise heightfields in five sliding LOD rings, chunk decorations (pine and
// broadleaf trees) and the tree meshes themselves. infworld_app.cpp turns it into draws.
#pragma once

#include <cstdint>
#include <string>
#include <vector>

#include "infworld_math.hpp"

namespace sandclock {
namespace infworld {

// Geometry constants. Heights are sampled in "pre-scale" units; the renderer and the
// decoration table multiply by SCALE to get world units, exactly like the original.
constexpr float CHUNK_SZ = 32.0f;
constexpr float HEIGHT = 270.0f;
constexpr float SCALE = 2.5f;
constexpr float FREQUENCY = 720.0f;
constexpr int LOD_LEVELS = 5;
constexpr float LOD_SCALE = 2.0f;
constexpr int TREE_PINE = 0;
constexpr int TREE_LEAFY = 1;

struct Vec2i {
  int x = 0, z = 0;
};

struct Settings {
  int seed = 0;       // 0 = pick one each start
  int range = 6;      // chunks each side, per LOD ring (3..9)
  int detail = 1;     // 0 low, 1 medium, 2 high
  int trees = 2;      // 0 none, 1 sparse, 2 normal, 3 lush
  int mode = 0;       // 0 glide, 1 circle, 2 drift
  int speed = 45;     // world units per second (10..200)
  int height = 90;    // metres above the ground (20..400)
  bool wander = true;
  bool water = true;
  int dim = 0;        // 0..80 percent
  int draw_res = 0;   // 0 auto, 1 full, 2 1080p, 3 720p, 4 540p
  bool adaptive = true;

  void sanitise();
  int precision() const { return detail == 0 ? 10 : (detail == 1 ? 16 : 24); }
  int pine_detail() const { return detail == 0 ? 4 : (detail == 1 ? 6 : 8); }
  int tree_detail() const { return detail == 0 ? 2 : (detail == 1 ? 3 : 4); }
};

// A 256-entry permutation table; the gradient noise below reads it.
struct Perm {
  int p[256] = {};
};
using WorldSeed = std::vector<Perm>;

WorldSeed make_seed(int seed);
float noise(float x, float y, const Perm& p);
// Height in pre-scale units, normalised to about -1..1 (the original's remap).
float height(float x, float z, const WorldSeed& seed);
// The same height in world units.
float world_height(float wx, float wz, const WorldSeed& seed);
Vec2 compress_normal(const Vec3& n);

// The CPU side of one terrain chunk: three floats per vertex,
// (height / HEIGHT, normal angle, asin(normal.y)).
struct TerrainChunk {
  std::vector<float> verts;
  bool ready = false;
  unsigned serial = 0;
};

// One LOD ring. Chunks are re-used as the camera moves: only the slots that leave the
// window and the positions that enter it are rebuilt, one camera chunk at a time.
class ChunkTable {
 public:
  void init(int range, float chunk_scale, int precision, const WorldSeed* seed);
  // Re-centre on the camera's chunk if needed; returns true if the window moved.
  bool follow(float camx, float camz);
  // Build up to max_chunks pending chunks, nearest first. Appends their slots.
  int build(int max_chunks, std::vector<int>* built);
  int pending() const { return static_cast<int>(pending_.size()); }

  int size() const { return size_; }
  int range() const { return range_; }
  int precision() const { return precision_; }
  float chunk_scale() const { return chunk_scale_; }
  const TerrainChunk& chunk(int slot) const { return chunks_[slot]; }
  Vec2i position(int slot) const { return positions_[slot]; }
  int center_x() const { return centerx_; }
  int center_z() const { return centerz_; }
  float world_size() const { return 2.0f * chunk_scale_ * SCALE; }
  Vec3 center_world(int slot) const;

 private:
  void build_chunk(int slot);
  int center_of(float camera) const;

  int size_ = 0, range_ = 0, precision_ = 0;
  float chunk_scale_ = CHUNK_SZ;
  const WorldSeed* seed_ = nullptr;
  std::vector<Vec2i> positions_;
  std::vector<TerrainChunk> chunks_;
  std::vector<int> pending_;
  std::vector<char> queued_;
  int centerx_ = 0, centerz_ = 0;
  bool started_ = false;
};

struct TreeInstance {
  float x = 0, y = 0, z = 0;  // world position, relative to the decoration chunk centre
  float rotation = 0;
  float scale = 1;
  int type = TREE_PINE;
};

struct DecorationChunk {
  std::vector<TreeInstance> trees;
  Vec3 center;  // world XZ of the chunk centre, kept for the draw transform
  bool ready = false;
  unsigned serial = 0;
};

class DecorationTable {
 public:
  void init(int range, float chunk_scale, int density, const WorldSeed* seed);
  bool follow(float camx, float camz);
  int size() const { return size_; }
  int range() const { return range_; }
  const DecorationChunk& chunk(int slot) const { return chunks_[slot]; }
  Vec2i position(int slot) const { return positions_[slot]; }

 private:
  void generate(int slot);
  int center_of(float camera) const;

  int size_ = 0, range_ = 0, density_ = 2;
  float chunk_scale_ = CHUNK_SZ;
  const WorldSeed* seed_ = nullptr;
  std::vector<Vec2i> positions_;
  std::vector<DecorationChunk> chunks_;
  int centerx_ = 0, centerz_ = 0;
  bool started_ = false;
};

// A CPU tree mesh: position, texture coordinate, normal and a wind lever (how far the
// vertex is from the trunk, in world units).
struct TreeVertex {
  float x, y, z;
  float u, v;
  float nx, ny, nz;
  float sway;
};
struct TreeMesh {
  std::vector<TreeVertex> verts;
  std::vector<unsigned short> indices;
  unsigned pine_indices() const { return pine_count_; }
  unsigned leafy_indices() const { return leafy_count_; }
  unsigned pine_count_ = 0;
  unsigned leafy_count_ = 0;
};

TreeMesh make_pine_tree(int detail);
TreeMesh make_leafy_tree(int detail);
// Bake every instance of a decoration chunk into one mesh, relative to its centre.
// The mesh's indices are ordered pines first, then leafy trees. The two templates are
// the meshes make_pine_tree() and make_leafy_tree() return at the chosen detail.
TreeMesh bake_trees(const TreeMesh& pine, const TreeMesh& leafy,
                    const std::vector<TreeInstance>& trees);

// Shared terrain topology. The grid is in pre-scale world units (-chunk_scale..+).
std::vector<float> make_grid(int precision, float chunk_scale);
std::vector<unsigned short> make_indices(int precision);

struct Frustum {
  struct Plane {
    Vec3 n;
    float d = 0;
  };
  Plane planes[6];
};
Frustum make_frustum(const Vec3& pos, const Vec3& forward, const Vec3& right, const Vec3& up,
                     float znear, float zfar, float aspect, float fovy);
bool intersects(const Frustum& f, const Vec3& center, const Vec3& half);

}  // namespace infworld
}  // namespace sandclock
