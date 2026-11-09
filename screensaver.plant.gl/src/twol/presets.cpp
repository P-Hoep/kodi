#include "twol/plant.hpp"

#include <algorithm>

namespace twol {

const char* to_string(const PlantPreset preset) noexcept
{
    switch (preset) {
    case PlantPreset::Cannabis: return "Cannabis visual preset";
    case PlantPreset::Tree: return "Tree";
    case PlantPreset::Bush: return "Bush";
    case PlantPreset::Fern: return "Fern/Vine";
    case PlantPreset::Pattern2D: return "2D Pattern";
    }
    return "Unknown";
}

const char* to_string(const DimensionMode mode) noexcept
{
    switch (mode) {
    case DimensionMode::Plant3D: return "3D";
    case DimensionMode::Plant25D: return "2.5D";
    case DimensionMode::Plant2D: return "2D Plant";
    case DimensionMode::Pattern2D: return "2D Pattern";
    }
    return "Unknown";
}

const char* to_string(const LeafStyle style) noexcept
{
    switch (style) {
    case LeafStyle::None: return "None";
    case LeafStyle::Broad: return "Broad";
    case LeafStyle::Fan: return "Fan";
    case LeafStyle::Needle: return "Needle";
    case LeafStyle::Fernlet: return "Fernlet";
    }
    return "Unknown";
}

PlantParameters make_preset(const PlantPreset preset)
{
    PlantParameters p;
    p.preset = preset;

    switch (preset) {
    case PlantPreset::Cannabis:
        p.dimension_mode = DimensionMode::Plant3D;
        p.seed = 1337U;
        p.generations = 7;
        p.branch_count = 2;
        p.recursive_branch_depth = 2;
        p.shoots_per_branch = 2;
        p.initial_sapling_nodes = 5;
        p.curve_segments = 7;
        p.radial_segments = 8;
        p.stem_length = 4.8f;
        p.internode_scale = 0.68f;
        p.base_radius = 0.075f;
        p.radius_decay = 0.72f;
        p.branch_length_scale = 0.46f;
        p.branch_angle_from_up_deg = 32.0f;
        p.phyllotaxis_deg = 137.5f;
        p.twist_jitter_deg = 8.0f;
        p.side_branch_upward_bend = 0.89f;
        p.side_branch_bend_curve = 0.33f;
        p.side_branch_outward_keep = 0.12f;
        p.branch_sag = 0.00f;
        p.sapling_pre_age = 0.28f;
        p.branch_activation_delay = 0.018f;
        p.branch_growth_window = 0.50f;
        p.leaf_style = LeafStyle::Fan;
        p.fan_leaves_per_node = 1;
        p.leaflet_count = 7;
        p.leaflet_segments = 7;
        p.leaf_scale = 2.75f;
        p.leaf_width_ratio = 0.125f;
        p.leaf_pitch_down_deg = 38.0f;
        p.leaf_outer_extra_drop_deg = 17.0f;
        p.leaf_droop = 0.42f;
        p.fan_spread_deg = 146.0f;
        p.petiole_length = 0.20f;
        p.leaf_node_density = 1.0f;
        p.leaf_veins = false;
        p.full_growth_seconds = 12.0f;
        break;

    case PlantPreset::Tree:
        p.dimension_mode = DimensionMode::Plant3D;
        p.seed = 2401U;
        p.generations = 6;
        p.branch_count = 4;
        p.recursive_branch_depth = 3;
        p.shoots_per_branch = 2;
        p.initial_sapling_nodes = 5;
        p.curve_segments = 8;
        p.radial_segments = 9;
        p.stem_length = 6.0f;
        p.internode_scale = 0.82f;
        p.base_radius = 0.13f;
        p.radius_decay = 0.68f;
        p.branch_length_scale = 0.70f;
        p.branch_angle_from_up_deg = 52.0f;
        p.phyllotaxis_deg = 109.0f;
        p.twist_jitter_deg = 16.0f;
        p.side_branch_upward_bend = 0.38f;
        p.side_branch_bend_curve = 0.74f;
        p.side_branch_outward_keep = 0.55f;
        p.branch_sag = 0.08f;
        p.sapling_pre_age = 0.24f;
        p.branch_activation_delay = 0.045f;
        p.branch_growth_window = 0.55f;
        p.leaf_style = LeafStyle::Broad;
        p.fan_leaves_per_node = 1;
        p.leaflet_count = 1;
        p.leaflet_segments = 3;
        p.leaf_scale = 0.82f;
        p.leaf_width_ratio = 0.38f;
        p.leaf_pitch_down_deg = 12.0f;
        p.leaf_outer_extra_drop_deg = 0.0f;
        p.leaf_droop = 0.08f;
        p.fan_spread_deg = 50.0f;
        p.petiole_length = 0.05f;
        p.leaf_node_density = 0.65f;
        p.full_growth_seconds = 14.0f;
        break;

    case PlantPreset::Bush:
        p.dimension_mode = DimensionMode::Plant3D;
        p.seed = 99U;
        p.generations = 5;
        p.branch_count = 5;
        p.recursive_branch_depth = 2;
        p.shoots_per_branch = 2;
        p.initial_sapling_nodes = 4;
        p.curve_segments = 6;
        p.radial_segments = 7;
        p.stem_length = 3.2f;
        p.internode_scale = 0.72f;
        p.base_radius = 0.07f;
        p.radius_decay = 0.66f;
        p.branch_length_scale = 0.78f;
        p.branch_angle_from_up_deg = 60.0f;
        p.phyllotaxis_deg = 137.5f;
        p.twist_jitter_deg = 20.0f;
        p.side_branch_upward_bend = 0.48f;
        p.side_branch_bend_curve = 0.62f;
        p.side_branch_outward_keep = 0.62f;
        p.branch_sag = 0.04f;
        p.sapling_pre_age = 0.26f;
        p.branch_activation_delay = 0.020f;
        p.branch_growth_window = 0.44f;
        p.leaf_style = LeafStyle::Broad;
        p.fan_leaves_per_node = 2;
        p.leaflet_count = 1;
        p.leaflet_segments = 4;
        p.leaf_scale = 0.95f;
        p.leaf_width_ratio = 0.44f;
        p.leaf_pitch_down_deg = 18.0f;
        p.leaf_droop = 0.10f;
        p.fan_spread_deg = 80.0f;
        p.petiole_length = 0.04f;
        p.leaf_node_density = 1.0f;
        p.full_growth_seconds = 10.0f;
        break;

    case PlantPreset::Fern:
        p.dimension_mode = DimensionMode::Plant25D;
        p.seed = 404U;
        p.generations = 8;
        p.branch_count = 2;
        p.recursive_branch_depth = 1;
        p.shoots_per_branch = 1;
        p.initial_sapling_nodes = 3;
        p.curve_segments = 6;
        p.radial_segments = 6;
        p.stem_length = 3.8f;
        p.internode_scale = 0.62f;
        p.base_radius = 0.035f;
        p.radius_decay = 0.70f;
        p.branch_length_scale = 0.72f;
        p.branch_angle_from_up_deg = 68.0f;
        p.phyllotaxis_deg = 180.0f;
        p.twist_jitter_deg = 3.0f;
        p.side_branch_upward_bend = 0.30f;
        p.side_branch_bend_curve = 0.80f;
        p.side_branch_outward_keep = 0.68f;
        p.branch_sag = 0.02f;
        p.sapling_pre_age = 0.18f;
        p.branch_activation_delay = 0.030f;
        p.branch_growth_window = 0.36f;
        p.leaf_style = LeafStyle::Fernlet;
        p.fan_leaves_per_node = 1;
        p.leaflet_count = 11;
        p.leaflet_segments = 4;
        p.leaf_scale = 0.95f;
        p.leaf_width_ratio = 0.18f;
        p.leaf_pitch_down_deg = 5.0f;
        p.leaf_droop = 0.05f;
        p.fan_spread_deg = 110.0f;
        p.petiole_length = 0.02f;
        p.leaf_node_density = 1.0f;
        p.full_growth_seconds = 9.0f;
        break;

    case PlantPreset::Pattern2D:
        p.dimension_mode = DimensionMode::Pattern2D;
        p.seed = 2026U;
        p.generations = 5;
        p.branch_count = 2;
        p.recursive_branch_depth = 0;
        p.shoots_per_branch = 0;
        p.initial_sapling_nodes = 0;
        p.leaf_style = LeafStyle::None;
        p.full_growth_seconds = 8.0f;
        break;
    }

    p.generations = std::clamp(p.generations, 1, 14);
    p.branch_count = std::clamp(p.branch_count, 1, 12);
    p.recursive_branch_depth = std::clamp(p.recursive_branch_depth, 0, 4);
    p.shoots_per_branch = std::clamp(p.shoots_per_branch, 0, 4);
    p.leaflet_count = std::clamp(p.leaflet_count, 1, 13);
    if (p.preset == PlantPreset::Cannabis && (p.leaflet_count % 2) == 0) {
        ++p.leaflet_count;
    }
    return p;
}

float timeline01(const PlantParameters& params) noexcept
{
    if (params.full_growth_seconds <= 0.0001f) {
        return 1.0f;
    }
    return clamp01(params.time_seconds / params.full_growth_seconds);
}

} // namespace twol
