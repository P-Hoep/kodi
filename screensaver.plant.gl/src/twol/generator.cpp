#include "twol/plant.hpp"

#include <algorithm>
#include <cmath>
#include <limits>

#include "twol/lsystem.hpp"
#include "twol/random.hpp"

namespace twol {

namespace {

constexpr Vec3 world_up{0.0f, 1.0f, 0.0f};
constexpr std::uint32_t no_parent = std::numeric_limits<std::uint32_t>::max();

struct BuildContext {
    NodeGraph graph;
    Rng rng;
};

std::uint32_t add_node(
    BuildContext& ctx,
    const std::uint32_t parent,
    const int depth,
    const Vec3 position,
    const Vec3 tangent,
    const float radius,
    const float birth,
    const float end)
{
    const std::uint32_t id = static_cast<std::uint32_t>(ctx.graph.nodes.size());
    ctx.graph.nodes.push_back({id, parent, depth, position, safe_normalize(tangent), radius, birth, end});
    return id;
}

void add_branch_segment(
    BuildContext& ctx,
    const std::uint32_t parent_node,
    const std::uint32_t child_node,
    const Vec3 a,
    const Vec3 b,
    const Vec3 tangent_a,
    const Vec3 tangent_b,
    const float radius_a,
    const float radius_b,
    const float birth,
    const float end,
    const int depth)
{
    ctx.graph.branches.push_back({
        parent_node,
        child_node,
        a,
        b,
        safe_normalize(tangent_a),
        safe_normalize(tangent_b),
        radius_a,
        radius_b,
        birth,
        end,
        depth,
    });
}

void add_leaf_cluster(
    BuildContext& ctx,
    const std::uint32_t node,
    const Vec3 origin,
    const Vec3 outward,
    const float scale,
    const float birth,
    const int depth,
    const int variant)
{
    const PlantParameters& p = ctx.graph.parameters;
    if (p.leaf_style == LeafStyle::None) {
        return;
    }

    if (ctx.rng.next01() > p.leaf_node_density) {
        return;
    }

    LeafCluster leaf;
    leaf.node = node;
    leaf.origin = origin;
    leaf.outward = safe_normalize(outward, {1.0f, 0.0f, 0.0f});
    leaf.up = world_up;
    leaf.scale = scale;
    leaf.birth = birth + p.leaf_delay;
    leaf.depth = depth;
    leaf.variant = variant;
    leaf.style = p.leaf_style;
    ctx.graph.leaves.push_back(leaf);
}

Vec3 direction_from_yaw_angle(const float yaw_radians, const float angle_from_up_degrees)
{
    const float angle = angle_from_up_degrees * deg_to_rad;
    const float s = std::sin(angle);
    const float c = std::cos(angle);
    return safe_normalize({std::cos(yaw_radians) * s, c, std::sin(yaw_radians) * s});
}

Vec3 reoriented_direction(
    const Vec3 initial_dir,
    const float t,
    const float upward_strength,
    const float bend_curve,
    const float outward_keep)
{
    const Vec3 initial = safe_normalize(initial_dir);
    const Vec3 outward = safe_normalize(project_on_plane(initial, world_up), {1.0f, 0.0f, 0.0f});
    const Vec3 target = safe_normalize(outward * outward_keep + world_up * (1.0f - outward_keep * 0.25f));
    const float shaped = std::pow(clamp01(t), std::max(0.05f, bend_curve));
    const float k = clamp01(shaped * upward_strength);
    return safe_normalize(lerp(initial, target, k), world_up);
}

void make_basis(const Vec3 axis, Vec3& right, Vec3& forward)
{
    const Vec3 n = safe_normalize(axis, world_up);
    const Vec3 helper = std::abs(dot(n, world_up)) > 0.92f ? Vec3{1.0f, 0.0f, 0.0f} : world_up;
    right = safe_normalize(cross(helper, n), {1.0f, 0.0f, 0.0f});
    forward = safe_normalize(cross(n, right), {0.0f, 0.0f, 1.0f});
}

Vec3 make_leaf_direction(
    const Vec3 branch_dir,
    const Vec3 preferred_outward,
    const float azimuth,
    const float side_amount,
    const float forward_amount)
{
    Vec3 right;
    Vec3 forward;
    make_basis(branch_dir, right, forward);
    Vec3 outward = safe_normalize(project_on_plane(preferred_outward, world_up), forward);
    if (length(outward) <= 0.0001f) {
        outward = forward;
    }

    Vec3 around = safe_normalize(rotate_around_axis(outward, branch_dir, azimuth), outward);
    Vec3 spun_right = safe_normalize(cross(branch_dir, around), right);
    const Vec3 dir = safe_normalize(around * (1.0f - std::abs(side_amount) * 0.18f) + spun_right * side_amount + branch_dir * forward_amount + world_up * 0.06f, around);
    return dir;
}

int desired_branch_count_at_node(const PlantParameters& p, const float height01, Rng& rng)
{
    const int requested = std::max(1, p.branch_count);
    switch (p.preset) {
    case PlantPreset::Cannabis:
        if (height01 < 0.22f) {
            return 1;
        }
        if (requested >= 4 && height01 > 0.35f && rng.chance(0.34f)) {
            return 3;
        }
        return 2;
    case PlantPreset::Tree:
        return std::clamp(requested / 2 + 1 + (rng.chance(0.35f) ? 1 : 0), 1, 4);
    case PlantPreset::Bush:
        return std::clamp(requested / 2 + 1, 2, 4);
    case PlantPreset::Fern:
        return std::clamp(requested / 3 + 1, 1, 3);
    case PlantPreset::Pattern2D:
        return 0;
    }
    return 2;
}

void build_side_branch(
    BuildContext& ctx,
    const std::uint32_t parent_node,
    const Vec3 start,
    const Vec3 initial_dir,
    const float length_value,
    const float radius,
    const int depth,
    const int branch_index,
    const float birth_start,
    const float birth_span)
{
    const PlantParameters& p = ctx.graph.parameters;
    const int segments = std::max(2, p.curve_segments);
    const Vec3 initial = safe_normalize(initial_dir, world_up);
    const Vec3 flat_outward = safe_normalize(project_on_plane(initial, world_up), {1.0f, 0.0f, 0.0f});
    const Vec3 local_side = safe_normalize(cross(world_up, flat_outward), {0.0f, 0.0f, 1.0f});

    std::uint32_t prev_node = parent_node;
    Vec3 prev_pos = start;
    Vec3 prev_dir = initial;
    float prev_radius = radius;

    const int recursive_limit = std::clamp(p.recursive_branch_depth, 0, 4);
    const int shoot_count_base = std::clamp(p.shoots_per_branch, 0, 4);
    const bool can_recurse = depth < recursive_limit && shoot_count_base > 0 && length_value > p.stem_length * 0.10f;

    for (int i = 1; i <= segments; ++i) {
        const float t0 = static_cast<float>(i - 1) / static_cast<float>(segments);
        const float t1 = static_cast<float>(i) / static_cast<float>(segments);
        Vec3 dir = reoriented_direction(
            initial,
            t1,
            p.side_branch_upward_bend,
            p.side_branch_bend_curve,
            p.side_branch_outward_keep);

        const float sweep = std::sin((static_cast<float>(branch_index) * 0.41f + t1 * 1.73f) * pi) * (0.042f / static_cast<float>(depth + 1));
        dir = safe_normalize(dir + local_side * sweep, dir);

        const float taper_curve = std::pow(t1, 1.18f + static_cast<float>(depth) * 0.22f);
        const float step_len = length_value / static_cast<float>(segments);
        Vec3 pos = prev_pos + dir * step_len;
        pos.y -= p.branch_sag * t1 * t1 * length_value;

        const float radius_b = std::max(0.0030f, radius * std::pow(p.radius_decay, 0.40f + taper_curve * 1.12f));
        const float birth = birth_start + birth_span * t0;
        const float end = birth_start + birth_span * t1;
        const std::uint32_t node = add_node(ctx, prev_node, depth, pos, dir, radius_b, birth, end);
        add_branch_segment(ctx, prev_node, node, prev_pos, pos, prev_dir, dir, prev_radius, radius_b, birth, end, depth);

        const bool leaf_here = i >= std::max(1, segments / 3) && (i == segments || ((i + branch_index + depth) % 2 == 0));
        if (leaf_here) {
            const float height01 = clamp01(pos.y / std::max(0.001f, p.stem_length));
            const float height_scale = p.preset == PlantPreset::Cannabis
                ? lerp(1.35f, 0.66f, height01)
                : lerp(1.05f, 0.68f, height01);
            const int fan_count = p.preset == PlantPreset::Cannabis ? std::max(1, std::min(3, p.fan_leaves_per_node)) : std::max(1, p.fan_leaves_per_node);
            for (int fan = 0; fan < fan_count; ++fan) {
                const float fan_bias = fan_count > 1 ? static_cast<float>(fan) / static_cast<float>(fan_count - 1) : 0.5f;
                const float side_bias = lerp(-0.72f, 0.72f, fan_bias);
                const float azimuth = (static_cast<float>(branch_index) * 0.49f + static_cast<float>(i) * 0.82f + static_cast<float>(fan) * 1.11f) * 0.65f;
                const Vec3 leaf_out = make_leaf_direction(dir, flat_outward, azimuth, side_bias, 0.18f + 0.08f * (1.0f - t1));
                add_leaf_cluster(
                    ctx,
                    node,
                    pos + dir * std::max(radius_b * 0.55f, 0.004f),
                    leaf_out,
                    p.leaf_scale * height_scale * ctx.rng.range(0.90f, 1.16f),
                    end,
                    depth,
                    branch_index * 31 + i * 7 + fan);
            }
        }

        if (can_recurse && i > segments / 2 && i < segments) {
            const bool spawn_slot = (i == (segments * 2) / 3) || (i == segments - 1 && ctx.rng.chance(0.55f));
            if (spawn_slot) {
                const int child_count = std::max(1, std::min(2, shoot_count_base - depth + (p.preset == PlantPreset::Tree ? 1 : 0)));
                for (int c = 0; c < child_count; ++c) {
                    const float side_sign = child_count == 1 ? (ctx.rng.chance(0.5f) ? 1.0f : -1.0f) : (c == 0 ? -1.0f : 1.0f);
                    Vec3 child_dir = safe_normalize(
                        flat_outward * (0.22f + 0.08f * static_cast<float>(c)) +
                        local_side * side_sign * (0.52f + 0.06f * ctx.rng.next01()) +
                        dir * 0.52f +
                        world_up * (p.preset == PlantPreset::Cannabis ? 0.74f : 0.30f),
                        dir);
                    if (p.dimension_mode == DimensionMode::Plant2D) {
                        child_dir.z = 0.0f;
                        child_dir = safe_normalize(child_dir, dir);
                    }
                    const float child_len = length_value * ctx.rng.range(0.34f, 0.56f) * std::pow(0.72f, static_cast<float>(depth));
                    const float child_radius = std::max(0.0023f, radius_b * 0.52f);
                    const float child_birth = end - 0.018f + 0.026f * static_cast<float>(depth);
                    const float child_span = birth_span * ctx.rng.range(0.42f, 0.64f);
                    build_side_branch(
                        ctx,
                        node,
                        pos + dir * std::max(radius_b * 0.72f, 0.006f),
                        child_dir,
                        child_len,
                        child_radius,
                        depth + 1,
                        branch_index * 101 + i * 13 + c,
                        child_birth,
                        child_span);
                }
            }
        }

        prev_node = node;
        prev_pos = pos;
        prev_dir = dir;
        prev_radius = radius_b;
    }

    if (length(prev_dir) > 0.0001f) {
        const float tip_scale = p.preset == PlantPreset::Cannabis ? 0.78f : 0.62f;
        add_leaf_cluster(
            ctx,
            prev_node,
            prev_pos + prev_dir * std::max(prev_radius * 0.50f, 0.004f),
            make_leaf_direction(prev_dir, flat_outward, 0.45f, 0.0f, 0.20f),
            p.leaf_scale * tip_scale * ctx.rng.range(0.92f, 1.10f),
            birth_start + birth_span,
            depth,
            branch_index * 271 + 17);
    }
}

void generate_procedural_plant(BuildContext& ctx)
{
    PlantParameters& p = ctx.graph.parameters;
    p.generations = std::clamp(p.generations, 1, 14);
    p.branch_count = std::clamp(p.branch_count, 1, 12);
    p.recursive_branch_depth = std::clamp(p.recursive_branch_depth, 0, 4);
    p.shoots_per_branch = std::clamp(p.shoots_per_branch, 0, 4);
    p.initial_sapling_nodes = std::clamp(p.initial_sapling_nodes, 0, 12);
    p.sapling_pre_age = std::clamp(p.sapling_pre_age, 0.0f, 0.75f);
    p.branch_activation_delay = std::clamp(p.branch_activation_delay, 0.0f, 0.30f);
    p.branch_growth_window = std::clamp(p.branch_growth_window, 0.08f, 0.90f);
    p.curve_segments = std::clamp(p.curve_segments, 2, 16);
    p.radial_segments = std::clamp(p.radial_segments, 4, 16);
    p.leaflet_count = std::clamp(p.leaflet_count, 1, 15);

    const int main_nodes = std::max(4, p.generations + 2);
    const float stem_step = p.stem_length / static_cast<float>(main_nodes);
    const int initial_nodes = std::clamp(p.initial_sapling_nodes, 1, std::max(1, main_nodes - 1));
    const float sapling_age = std::max(0.0f, p.sapling_pre_age);
    const float trunk_start_time = 0.018f;
    const float trunk_end_time = 0.94f;

    std::uint32_t prev_node = add_node(ctx, no_parent, 0, {0.0f, 0.0f, 0.0f}, world_up, p.base_radius, -sapling_age, -sapling_age * 0.55f);
    Vec3 prev_pos{0.0f, 0.0f, 0.0f};
    float prev_radius = p.base_radius;

    for (int i = 1; i <= main_nodes; ++i) {
        const float h1 = static_cast<float>(i) / static_cast<float>(main_nodes);
        const float bend = (ctx.rng.range(-0.028f, 0.028f) * h1);
        Vec3 pos{bend, stem_step * static_cast<float>(i), ctx.rng.range(-0.020f, 0.020f) * h1};

        if (p.dimension_mode == DimensionMode::Plant2D) {
            pos.z = 0.0f;
        }

        const float radius = std::max(0.006f, p.base_radius * std::pow(p.radius_decay, h1 * 2.35f));
        float birth = 0.0f;
        float end = 0.0f;
        if (i <= initial_nodes) {
            const float local = initial_nodes > 0 ? static_cast<float>(i) / static_cast<float>(initial_nodes) : 1.0f;
            birth = -sapling_age * (1.0f - 0.18f * local);
            end = -sapling_age * (0.56f - 0.18f * local);
        } else {
            const float live_span = static_cast<float>(std::max(1, main_nodes - initial_nodes));
            const float u = static_cast<float>(i - initial_nodes) / live_span;
            const float shaped = std::pow(clamp01(u), 1.08f);
            birth = lerp(trunk_start_time, trunk_end_time, shaped);
            end = std::min(1.0f, birth + lerp(0.18f, 0.090f, shaped));
        }
        const Vec3 tangent = safe_normalize(pos - prev_pos, world_up);
        const std::uint32_t node = add_node(ctx, prev_node, 0, pos, tangent, radius, birth, end);
        add_branch_segment(ctx, prev_node, node, prev_pos, pos, world_up, tangent, prev_radius, radius, birth, end, 0);

        const bool can_branch = i >= 2 && i < main_nodes;
        if (can_branch) {
            const float height01 = h1;
            const int local_branch_count = desired_branch_count_at_node(p, height01, ctx.rng);
            float node_yaw_deg = 0.0f;
            if (p.preset == PlantPreset::Cannabis) {
                node_yaw_deg = ((i % 2 == 0) ? 0.0f : 180.0f) + ctx.rng.range(-18.0f, 18.0f);
            } else {
                node_yaw_deg = static_cast<float>(i) * 71.0f + ctx.rng.range(-26.0f, 26.0f);
            }

            for (int b = 0; b < local_branch_count; ++b) {
                float yaw_deg = node_yaw_deg;
                if (p.preset == PlantPreset::Cannabis) {
                    if (local_branch_count == 1) {
                        yaw_deg += ctx.rng.chance(0.5f) ? -90.0f : 90.0f;
                    } else if (local_branch_count == 2) {
                        yaw_deg += (b == 0 ? -90.0f : 90.0f);
                    } else {
                        yaw_deg += (b == 0 ? -90.0f : (b == 1 ? 90.0f : 180.0f));
                    }
                    yaw_deg += ctx.rng.range(-10.0f, 10.0f);
                } else {
                    const float span = local_branch_count > 1 ? 180.0f / static_cast<float>(local_branch_count) : 0.0f;
                    yaw_deg += -90.0f + span * static_cast<float>(b) + ctx.rng.range(-12.0f, 12.0f);
                }

                float angle = p.branch_angle_from_up_deg;
                if (p.preset == PlantPreset::Cannabis) {
                    angle = lerp(p.branch_angle_from_up_deg + 4.0f, p.branch_angle_from_up_deg - 8.0f, height01);
                } else if (p.preset == PlantPreset::Tree) {
                    angle = lerp(p.branch_angle_from_up_deg + 18.0f, p.branch_angle_from_up_deg - 10.0f, height01);
                }

                Vec3 dir = direction_from_yaw_angle(yaw_deg * deg_to_rad, angle);
                if (p.dimension_mode == DimensionMode::Plant2D) {
                    dir.z = 0.0f;
                    dir = safe_normalize(dir, world_up);
                }

                const float base_length = p.stem_length * p.branch_length_scale;
                const float profile = p.preset == PlantPreset::Cannabis
                    ? (0.72f + 0.34f * std::sin(height01 * pi))
                    : (0.58f + 0.48f * std::pow(1.0f - height01, 0.72f));
                const float length_value = base_length * profile * std::pow(p.internode_scale, static_cast<float>(i) * 0.18f) * ctx.rng.range(0.86f, 1.10f);
                const float branch_radius = std::max(0.0045f, radius * (p.preset == PlantPreset::Cannabis ? 0.46f : 0.55f));
                const bool sapling_node = i <= initial_nodes;
                const float branch_birth = sapling_node
                    ? (-sapling_age * (0.72f - 0.12f * height01) + 0.010f * static_cast<float>(b))
                    : (birth + p.branch_activation_delay + height01 * 0.012f + 0.004f * static_cast<float>(b));
                const float branch_span = p.branch_growth_window * (p.preset == PlantPreset::Cannabis ? 0.78f : 1.00f) * (sapling_node ? 0.72f : 1.0f);
                const Vec3 branch_start = pos + tangent * std::max(radius * 0.72f, 0.012f);
                build_side_branch(ctx, node, branch_start, dir, length_value, branch_radius, 1, i * 11 + b, branch_birth, branch_span);
            }
        }

        if (p.preset == PlantPreset::Cannabis && i >= 2 && ctx.rng.chance(0.55f)) {
            const float yaw = (static_cast<float>(i) * 87.0f + ctx.rng.range(-35.0f, 35.0f)) * deg_to_rad;
            const Vec3 out = direction_from_yaw_angle(yaw, 80.0f);
            const float height_scale = lerp(1.15f, 0.52f, h1);
            add_leaf_cluster(ctx, node, pos + tangent * std::max(radius * 0.42f, 0.010f), out, p.leaf_scale * height_scale, end + 0.04f, 0, i * 29);
        }

        prev_node = node;
        prev_pos = pos;
        prev_radius = radius;
    }

    if (!ctx.graph.nodes.empty()) {
        const Node& top = ctx.graph.nodes.back();
        const int crown_count = p.preset == PlantPreset::Cannabis ? 3 : std::max(2, p.branch_count / 2 + 1);
        for (int i = 0; i < crown_count; ++i) {
            const float yaw = (static_cast<float>(i) * 360.0f / static_cast<float>(std::max(1, crown_count)) + 25.0f) * deg_to_rad;
            add_leaf_cluster(
                ctx,
                top.id,
                top.position,
                direction_from_yaw_angle(yaw, p.preset == PlantPreset::Cannabis ? 56.0f : 68.0f),
                p.leaf_scale * (p.preset == PlantPreset::Cannabis ? 0.46f : 0.50f),
                top.end + 0.05f,
                0,
                900 + i);
        }
    }
}

void generate_pattern_graph(BuildContext& ctx)
{
    PlantParameters& p = ctx.graph.parameters;
    LSystemDefinition def = plant_pattern_definition();
    def.iterations = std::clamp(p.generations, 1, 7);
    if (p.seed % 3U == 1U) {
        def = koch_pattern_definition();
        def.iterations = std::clamp(p.generations, 1, 5);
    } else if (p.seed % 3U == 2U) {
        def = cannabis_leaf_pattern_definition();
        def.iterations = std::clamp(p.generations, 1, 5);
    }

    const LSystemResult traced = trace_lsystem_2d(def);
    std::uint32_t parent = no_parent;
    std::uint32_t id = 0U;
    const float total = static_cast<float>(std::max<std::size_t>(1U, traced.lines.size()));

    for (std::size_t i = 0; i < traced.lines.size(); ++i) {
        const LSystemLine& line = traced.lines[i];
        const float birth = static_cast<float>(i) / total;
        const float end = static_cast<float>(i + 1U) / total;
        const std::uint32_t a = add_node(ctx, parent, 0, line.a, safe_normalize(line.b - line.a), line.radius, birth, birth);
        const std::uint32_t b = add_node(ctx, a, 0, line.b, safe_normalize(line.b - line.a), line.radius, birth, end);
        add_branch_segment(ctx, a, b, line.a, line.b, safe_normalize(line.b - line.a), safe_normalize(line.b - line.a), line.radius, line.radius, birth, end, 0);
        parent = b;
        id = b;
        (void)id;
    }
}

} // namespace

NodeGraph generate_node_graph(const PlantParameters& params)
{
    BuildContext ctx{NodeGraph{}, Rng(params.seed)};
    ctx.graph.parameters = params;
    ctx.graph.parameters.generations = std::clamp(ctx.graph.parameters.generations, 1, 10);

    if (ctx.graph.parameters.dimension_mode == DimensionMode::Pattern2D || ctx.graph.parameters.preset == PlantPreset::Pattern2D) {
        ctx.graph.parameters.dimension_mode = DimensionMode::Pattern2D;
        generate_pattern_graph(ctx);
    } else {
        generate_procedural_plant(ctx);
        apply_dimension_mode(ctx.graph);
    }

    return ctx.graph;
}

void apply_dimension_mode(NodeGraph& graph)
{
    const DimensionMode mode = graph.parameters.dimension_mode;
    if (mode == DimensionMode::Plant3D) {
        return;
    }

    auto transform = [mode](const Vec3 v) -> Vec3 {
        if (mode == DimensionMode::Plant2D || mode == DimensionMode::Pattern2D) {
            return flatten_for_2d(v);
        }
        if (mode == DimensionMode::Plant25D) {
            return flatten_for_25d(v);
        }
        return v;
    };

    for (Node& node : graph.nodes) {
        node.position = transform(node.position);
        node.tangent = safe_normalize(transform(node.tangent), world_up);
    }
    for (BranchSegment& branch : graph.branches) {
        branch.a = transform(branch.a);
        branch.b = transform(branch.b);
        branch.tangent_a = safe_normalize(transform(branch.tangent_a), world_up);
        branch.tangent_b = safe_normalize(transform(branch.tangent_b), world_up);
    }
    for (LeafCluster& leaf : graph.leaves) {
        leaf.origin = transform(leaf.origin);
        leaf.outward = safe_normalize(transform(leaf.outward), {1.0f, 0.0f, 0.0f});
    }
}

} // namespace twol
