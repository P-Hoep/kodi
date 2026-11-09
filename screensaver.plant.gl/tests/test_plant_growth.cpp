// Growth-mesh tests: index ranges, batching limits, growth windows and determinism.
#include <cmath>
#include <cstddef>
#include <cstdint>
#include <cstdio>
#include <string>
#include <vector>

#include "plant_growth.hpp"
#include "twol/plant.hpp"

namespace {

int failures = 0;

void expect(const bool ok, const std::string& what) {
  if (!ok) {
    std::fprintf(stderr, "FAIL: %s\n", what.c_str());
    ++failures;
  }
}

void check_mesh(const twol::PlantPreset preset, const char* name) {
  twol::PlantParameters p = twol::make_preset(preset);
  p.seed = 4242U;
  p.full_growth_seconds = 20.0f;
  twol::NodeGraph graph = twol::generate_node_graph(p);
  const plantgl::GrowthMesh mesh = plantgl::build_growth_mesh(graph);

  expect(!mesh.empty(), std::string(name) + ": mesh is not empty");
  expect(mesh.vertex_count > 0, std::string(name) + ": has vertices");
  expect(mesh.triangle_count > 0, std::string(name) + ": has triangles");
  expect(mesh.batches.size() > 0, std::string(name) + ": has batches");
  expect(mesh.height >= 0.5f, std::string(name) + ": height >= 0.5");
  expect(mesh.radius >= 0.25f, std::string(name) + ": radius >= 0.25");
  if (preset == twol::PlantPreset::Pattern2D) {
    expect(mesh.leaf_clusters == 0, std::string(name) + ": L-system has no leaves");
  } else {
    expect(mesh.leaf_clusters > 0, std::string(name) + ": has leaves");
  }

  std::size_t vertex_sum = 0;
  std::size_t triangle_sum = 0;
  for (const plantgl::GrowthBatch& b : mesh.batches) {
    expect(b.vertices.size() <= 60000U, std::string(name) + ": batch size <= 60000");
    expect(!b.vertices.empty(), std::string(name) + ": batch not empty");
    expect(b.indices.size() % 3U == 0U, std::string(name) + ": whole triangles");
    expect(!b.indices.empty(), std::string(name) + ": batch has indices");
    for (const std::uint16_t index : b.indices) {
      expect(index < b.vertices.size(), std::string(name) + ": index in range");
      if (index >= b.vertices.size()) break;
    }
    for (const plantgl::GrowthVertex& v : b.vertices) {
      // Sapling vertices have negative birth and may already be finished at time01 = 0; what
      // matters is that no window runs past the end of the growth phase.
      expect(v.span > 0.0f, std::string(name) + ": positive growth span");
      expect(v.birth + v.span <= 1.00001f, std::string(name) + ": growth ends by time01 1");
      expect(v.sway >= 0.0f && v.sway <= 1.0001f, std::string(name) + ": sway in 0..1");
      expect(std::abs(v.position[1]) < 1000.0f, std::string(name) + ": sane position");
    }
    vertex_sum += b.vertices.size();
    triangle_sum += b.indices.size() / 3U;
  }
  expect(vertex_sum == mesh.vertex_count, std::string(name) + ": vertex count is the sum");
  expect(triangle_sum == mesh.triangle_count, std::string(name) + ": triangle count is the sum");

  // A second build of the same graph must be identical.
  const plantgl::GrowthMesh again = plantgl::build_growth_mesh(graph);
  expect(again.vertex_count == mesh.vertex_count, std::string(name) + ": deterministic count");
  expect(again.triangle_count == mesh.triangle_count, std::string(name) + ": deterministic tris");
  expect(again.batches.size() == mesh.batches.size(), std::string(name) + ": deterministic batches");
  if (!mesh.batches.empty() && !again.batches.empty()) {
    const plantgl::GrowthVertex& a = mesh.batches.front().vertices.front();
    const plantgl::GrowthVertex& b = again.batches.front().vertices.front();
    bool same = true;
    for (int i = 0; i < 3; ++i) same = same && a.position[i] == b.position[i];
    same = same && a.birth == b.birth && a.span == b.span && a.sway == b.sway;
    expect(same, std::string(name) + ": deterministic first vertex");
  }
}

}  // namespace

int main() {
  static_assert(sizeof(plantgl::GrowthVertex) == 16U * sizeof(float),
                "GrowthVertex stays 16 tightly packed floats");
  static_assert(offsetof(plantgl::GrowthVertex, position) == 0, "position offset");
  static_assert(offsetof(plantgl::GrowthVertex, normal) == 12, "normal offset");
  static_assert(offsetof(plantgl::GrowthVertex, color) == 24, "color offset");
  static_assert(offsetof(plantgl::GrowthVertex, anchor) == 36, "anchor offset");
  static_assert(offsetof(plantgl::GrowthVertex, birth) == 48, "growth offset");
  static_assert(offsetof(plantgl::GrowthVertex, sway) == 56, "sway offset");

  check_mesh(twol::PlantPreset::Cannabis, "cannabis");
  check_mesh(twol::PlantPreset::Tree, "tree");
  check_mesh(twol::PlantPreset::Bush, "bush");
  check_mesh(twol::PlantPreset::Fern, "fern");
  check_mesh(twol::PlantPreset::Pattern2D, "lsystem");

  // A pattern with each of the three L-system seeds.
  for (std::uint32_t n = 0; n < 3; ++n) {
    twol::PlantParameters p = twol::make_preset(twol::PlantPreset::Pattern2D);
    p.seed = 100U + n;
    p.generations = 4;
    const twol::NodeGraph g = twol::generate_node_graph(p);
    const plantgl::GrowthMesh m = plantgl::build_growth_mesh(g);
    expect(!m.empty(), "pattern seed " + std::to_string(n) + ": mesh is not empty");
    expect(m.branch_segments > 0, "pattern seed " + std::to_string(n) + ": has segments");
  }

  if (failures == 0) {
    std::printf("plant_growth: all tests passed\n");
    return 0;
  }
  std::fprintf(stderr, "plant_growth: %d failure(s)\n", failures);
  return 1;
}
