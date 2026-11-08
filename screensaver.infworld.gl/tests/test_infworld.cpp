// Tests for the Endless World's CPU world model: seeded noise, chunk tiling, decorations
// and the tree meshes. No OpenGL needed.
#include <cmath>
#include <cstdio>
#include <string>
#include <vector>

#include "infworld.hpp"

namespace infworld = sandclock::infworld;

static int failures = 0;

#define CHECK(cond)                                                     \
  do {                                                                  \
    if (!(cond)) {                                                      \
      std::printf("FAIL %s:%d: %s\n", __FILE__, __LINE__, #cond);        \
      ++failures;                                                       \
    }                                                                   \
  } while (0)

static void test_heightfield() {
  const infworld::WorldSeed a = infworld::make_seed(7);
  const infworld::WorldSeed b = infworld::make_seed(7);
  const infworld::WorldSeed c = infworld::make_seed(8);
  bool same = true, different = false;
  for (int i = 0; i < 64; ++i) {
    const float x = i * 37.0f - 1000.0f, z = i * -53.0f + 700.0f;
    const float ha = infworld::height(x, z, a);
    const float hb = infworld::height(x, z, b);
    const float hc = infworld::height(x, z, c);
    if (ha != hb) same = false;
    if (ha != hc) different = true;
    CHECK(ha >= -1.001f && ha <= 1.001f);
  }
  CHECK(same);
  CHECK(different);
  CHECK(std::fabs(infworld::world_height(123.0f, -456.0f, a) -
                  infworld::height(123.0f / infworld::SCALE, -456.0f / infworld::SCALE, a) *
                      infworld::HEIGHT * infworld::SCALE) < 1e-3f);
}

static void test_chunks_tile() {
  infworld::WorldSeed seed = infworld::make_seed(3);
  const int precision = 4;
  infworld::ChunkTable table;
  table.init(1, infworld::CHUNK_SZ, precision, &seed);
  table.follow(0.0f, 0.0f);
  std::vector<int> built;
  CHECK(table.build(1 << 20, &built) == 9);

  const int n = precision + 1;
  int left = -1, right = -1, center = -1;
  for (int slot = 0; slot < static_cast<int>(built.size()); ++slot) {
    const infworld::Vec2i p = table.position(slot);
    if (p.x == 0 && p.z == 0) center = slot;
    if (p.x == 0 && p.z == 1) left = slot;
    if (p.x == 1 && p.z == 0) right = slot;
  }
  CHECK(center >= 0 && left >= 0 && right >= 0);
  const infworld::TerrainChunk& c = table.chunk(center);
  const infworld::TerrainChunk& l = table.chunk(left);
  const infworld::TerrainChunk& r = table.chunk(right);
  CHECK(static_cast<int>(c.verts.size()) == n * n * 3);

  // The +z edge vertex of the centre chunk is the -z edge vertex of the chunk at z+1.
  bool z_seam = true;
  for (int i = 0; i < n; ++i) {
    const float a = c.verts[(static_cast<size_t>(i) * n + n - 1) * 3 + 0];
    const float b = l.verts[(static_cast<size_t>(i) * n + 0) * 3 + 0];
    if (std::fabs(a - b) > 1e-5f) z_seam = false;
  }
  CHECK(z_seam);

  // The +x edge vertex of the centre chunk is the -x edge vertex of the chunk at x+1.
  bool x_seam = true;
  for (int j = 0; j < n; ++j) {
    const float a = c.verts[(static_cast<size_t>(n - 1) * n + j) * 3 + 0];
    const float b = r.verts[(static_cast<size_t>(0) * n + j) * 3 + 0];
    if (std::fabs(a - b) > 1e-5f) x_seam = false;
  }
  CHECK(x_seam);
}

static void test_decorations() {
  infworld::WorldSeed seed = infworld::make_seed(11);
  const float cs = infworld::CHUNK_SZ;
  infworld::DecorationTable a, b;
  a.init(2, cs, 2, &seed);
  b.init(2, cs, 2, &seed);
  a.follow(100.0f, -250.0f);
  b.follow(100.0f, -250.0f);

  int trees = 0;
  for (int slot = 0; slot < a.size() * a.size(); ++slot) {
    const infworld::DecorationChunk& ca = a.chunk(slot);
    const infworld::DecorationChunk& cb = b.chunk(slot);
    CHECK(ca.trees.size() == cb.trees.size());
    for (size_t i = 0; i < ca.trees.size(); ++i) {
      CHECK(ca.trees[i].x == cb.trees[i].x);
      CHECK(ca.trees[i].y == cb.trees[i].y);
      CHECK(ca.trees[i].z == cb.trees[i].z);
      CHECK(ca.trees[i].type == cb.trees[i].type);
      ++trees;
      // A tree stands on the heightfield at its world position.
      const float wx = ca.center.x + ca.trees[i].x;
      const float wz = ca.center.z + ca.trees[i].z;
      CHECK(std::fabs(ca.trees[i].y - infworld::world_height(wx, wz, seed)) < 1e-3f);
    }
  }
  CHECK(trees > 0);
}

static void test_tree_meshes() {
  const infworld::TreeMesh pine = infworld::make_pine_tree(5);
  const infworld::TreeMesh leafy = infworld::make_leafy_tree(3);
  CHECK(!pine.verts.empty());
  CHECK(!leafy.verts.empty());
  CHECK(pine.indices.size() % 3 == 0);
  CHECK(pine.pine_indices() == pine.indices.size());

  infworld::TreeInstance tree;
  tree.type = infworld::TREE_PINE;
  tree.rotation = 0.5f;
  tree.scale = 1.2f;
  const infworld::TreeMesh baked = infworld::bake_trees(pine, leafy, {tree});
  CHECK(baked.verts.size() == pine.verts.size());
  CHECK(baked.indices.size() == pine.indices.size());
  CHECK(baked.pine_indices() == pine.indices.size());
  CHECK(baked.leafy_indices() == 0);
  for (size_t i = 0; i < baked.verts.size(); ++i)
    CHECK(baked.verts[i].sway >= 0.0f);
}

static void test_topology_and_frustum() {
  const std::vector<float> grid = infworld::make_grid(4, 32.0f);
  CHECK(grid.size() == 25 * 2);
  CHECK(grid[0] == -32.0f && grid[1] == -32.0f);
  CHECK(grid[24 * 2] == 32.0f && grid[24 * 2 + 1] == 32.0f);
  CHECK(infworld::make_indices(4).size() == 4 * 4 * 6);

  const infworld::Vec3 forward{0, 0, -1};
  const infworld::Vec3 right = infworld::normalize(infworld::cross({0, 1, 0}, forward));
  const infworld::Vec3 up = infworld::normalize(infworld::cross(forward, right));
  const infworld::Frustum f = infworld::make_frustum({0, 0, 0}, forward, right, up, 1.0f,
                                                     1000.0f, 16.0f / 9.0f, 1.2f);
  CHECK(infworld::intersects(f, {0, 0, -100}, {1, 1, 1}));
  CHECK(!infworld::intersects(f, {0, 0, 100}, {1, 1, 1}));
  CHECK(!infworld::intersects(f, {500, 0, -100}, {1, 1, 1}));
  CHECK(infworld::intersects(f, {40, 0, -100}, {5, 5, 5}));
}

int main() {
  test_heightfield();
  test_chunks_tile();
  test_decorations();
  test_tree_meshes();
  test_topology_and_frustum();
  if (failures) {
    std::printf("%d failure(s)\n", failures);
    return 1;
  }
  std::printf("infworld: all tests passed\n");
  return 0;
}
