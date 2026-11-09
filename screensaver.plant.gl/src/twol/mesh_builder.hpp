#pragma once

#include "twol/plant.hpp"

namespace twol {

void append_cylinder(Mesh& mesh, Vec3 a, Vec3 b, float radius_a, float radius_b, int radial_segments, Color4 color);
void append_node_marker(Mesh& mesh, Vec3 center, float radius, Color4 color);
void append_fan_leaf(Mesh& mesh, const PlantParameters& params, const LeafCluster& leaf, float grow01);
void append_broad_leaf(Mesh& mesh, const PlantParameters& params, const LeafCluster& leaf, float grow01);
void append_fernlet_leaf(Mesh& mesh, const PlantParameters& params, const LeafCluster& leaf, float grow01);

} // namespace twol
