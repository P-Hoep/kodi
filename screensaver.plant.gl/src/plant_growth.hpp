// GPU growth mesh: the plant graph baked into vertices that carry their own growth window, so
// the whole plant can grow, sway and thicken in the vertex shader from one static upload.
#pragma once

#include <cstddef>
#include <cstdint>
#include <vector>

#include "twol/plant.hpp"

namespace plantgl {

// 16 floats, 64 bytes. The shader grows a vertex from its anchor toward its final position:
//   p = mix(anchor, position, smoothstep(birth, birth + span, time01))
// For a stem segment that extends and thickens the tube; for a leaf it scales it up from its
// petiole. sway is 0 at a leaf's base and 1 at its tip, so wind never detaches a leaf.
struct GrowthVertex {
  float position[3];
  float normal[3];
  float color[3];
  float anchor[3];
  float birth;
  float span;
  float sway;
  float phase;
};

// GLES 2.0 only has 16-bit indices, so a large plant is split into batches of at most 65000
// vertices. Each batch is one VBO/IBO/draw call.
struct GrowthBatch {
  std::vector<GrowthVertex> vertices;
  std::vector<std::uint16_t> indices;
};

struct GrowthMesh {
  std::vector<GrowthBatch> batches;
  twol::Vec3 bounds_min;
  twol::Vec3 bounds_max;
  std::size_t vertex_count = 0;
  std::size_t triangle_count = 0;
  int leaf_clusters = 0;
  int branch_segments = 0;
  float height = 1.0f;
  float radius = 1.0f;

  bool empty() const { return batches.empty(); }
};

// Builds the growth mesh for a generated plant graph. Deterministic for a deterministic graph.
GrowthMesh build_growth_mesh(const twol::NodeGraph& graph);

}  // namespace plantgl
