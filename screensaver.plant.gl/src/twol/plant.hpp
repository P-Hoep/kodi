#pragma once

#include <cstdint>
#include <string>
#include <vector>

#include "twol/math.hpp"

namespace twol {

enum class PlantPreset : std::uint8_t {
    Cannabis = 0,
    Tree = 1,
    Bush = 2,
    Fern = 3,
    Pattern2D = 4,
};

enum class DimensionMode : std::uint8_t {
    Plant3D = 0,
    Plant25D = 1,
    Plant2D = 2,
    Pattern2D = 3,
};

enum class LeafStyle : std::uint8_t {
    None = 0,
    Broad = 1,
    Fan = 2,
    Needle = 3,
    Fernlet = 4,
};

struct PlantParameters {
    PlantPreset preset = PlantPreset::Cannabis;
    DimensionMode dimension_mode = DimensionMode::Plant3D;

    std::uint32_t seed = 1337U;
    int generations = 7;
    int branch_count = 2;
    int recursive_branch_depth = 2;
    int shoots_per_branch = 1;
    int initial_sapling_nodes = 4;
    int curve_segments = 7;
    int radial_segments = 8;

    float stem_length = 4.8f;
    float internode_scale = 0.68f;
    float base_radius = 0.075f;
    float radius_decay = 0.72f;
    float branch_length_scale = 0.62f;
    float branch_angle_from_up_deg = 32.0f;
    float phyllotaxis_deg = 137.5f;
    float twist_jitter_deg = 7.0f;

    float side_branch_upward_bend = 0.88f;
    float side_branch_bend_curve = 0.33f;
    float side_branch_outward_keep = 0.12f;
    float branch_sag = 0.02f;

    // Temporal growth model. Negative birth times make an initial sapling visible at t=0.
    float sapling_pre_age = 0.24f;
    float branch_activation_delay = 0.035f;
    float branch_growth_window = 0.42f;

    LeafStyle leaf_style = LeafStyle::Fan;
    int fan_leaves_per_node = 2;
    int leaflet_count = 7;
    int leaflet_segments = 7;
    float leaf_scale = 3.1f;
    float leaf_width_ratio = 0.14f;
    float leaf_pitch_down_deg = 36.0f;
    float leaf_outer_extra_drop_deg = 15.0f;
    float leaf_droop = 0.38f;
    float fan_spread_deg = 142.0f;
    float petiole_length = 0.18f;
    float leaf_node_density = 1.0f;

    float time_seconds = 0.0f;
    float full_growth_seconds = 12.0f;
    float leaf_delay = 0.06f;
    float leaf_grow_seconds = 1.15f;

    bool show_node_markers = false;
    bool wireframe = false;
    bool leaf_veins = true;
};

struct Node {
    std::uint32_t id = 0U;
    std::uint32_t parent = UINT32_MAX;
    int depth = 0;
    Vec3 position;
    Vec3 tangent = {0.0f, 1.0f, 0.0f};
    float radius = 0.02f;
    float birth = 0.0f;
    float end = 1.0f;
};

struct BranchSegment {
    std::uint32_t parent_node = UINT32_MAX;
    std::uint32_t child_node = UINT32_MAX;
    Vec3 a;
    Vec3 b;
    Vec3 tangent_a = {0.0f, 1.0f, 0.0f};
    Vec3 tangent_b = {0.0f, 1.0f, 0.0f};
    float radius_a = 0.02f;
    float radius_b = 0.015f;
    float birth = 0.0f;
    float end = 1.0f;
    int depth = 0;
};

struct LeafCluster {
    std::uint32_t node = UINT32_MAX;
    Vec3 origin;
    Vec3 outward = {1.0f, 0.0f, 0.0f};
    Vec3 up = {0.0f, 1.0f, 0.0f};
    float scale = 1.0f;
    float birth = 0.0f;
    int depth = 0;
    int variant = 0;
    LeafStyle style = LeafStyle::Fan;
};

struct NodeGraph {
    std::vector<Node> nodes;
    std::vector<BranchSegment> branches;
    std::vector<LeafCluster> leaves;
    PlantParameters parameters;
};

struct Vertex {
    Vec3 position;
    Vec3 normal;
    Color4 color;
    Vec2 uv;
};

struct Mesh {
    std::vector<Vertex> vertices;
    std::vector<std::uint32_t> indices;
};

[[nodiscard]] const char* to_string(PlantPreset preset) noexcept;
[[nodiscard]] const char* to_string(DimensionMode mode) noexcept;
[[nodiscard]] const char* to_string(LeafStyle style) noexcept;
[[nodiscard]] PlantParameters make_preset(PlantPreset preset);
[[nodiscard]] NodeGraph generate_node_graph(const PlantParameters& params);
[[nodiscard]] Mesh build_mesh(const NodeGraph& graph, float time01);
[[nodiscard]] float timeline01(const PlantParameters& params) noexcept;
void apply_dimension_mode(NodeGraph& graph);

} // namespace twol
