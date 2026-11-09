#include "twol/mesh_builder.hpp"

#include <algorithm>
#include <cmath>
#include <cstdint>

namespace twol {

namespace {

constexpr Vec3 world_up{0.0f, 1.0f, 0.0f};
constexpr Vec3 world_right{1.0f, 0.0f, 0.0f};

Color4 stem_color_for(const PlantParameters& params, const int depth)
{
    switch (params.preset) {
    case PlantPreset::Cannabis:
        return depth == 0 ? Color4{0.58f, 0.42f, 0.24f, 1.0f} : Color4{0.66f, 0.48f, 0.26f, 1.0f};
    case PlantPreset::Tree:
        return depth == 0 ? Color4{0.42f, 0.30f, 0.18f, 1.0f} : Color4{0.36f, 0.25f, 0.14f, 1.0f};
    case PlantPreset::Bush:
        return Color4{0.30f, 0.55f, 0.22f, 1.0f};
    case PlantPreset::Fern:
        return Color4{0.25f, 0.52f, 0.22f, 1.0f};
    case PlantPreset::Pattern2D:
        return Color4{0.58f, 0.92f, 0.33f, 1.0f};
    }
    return Color4{0.5f, 0.5f, 0.5f, 1.0f};
}

Color4 leaf_color_for(const LeafCluster& leaf, const float t)
{
    const float jitter = hash01(static_cast<std::uint32_t>(leaf.variant * 9781 + 33)) * 0.16f - 0.08f;
    const Color4 dark{0.06f, 0.24f + jitter, 0.06f, 1.0f};
    const Color4 light{0.32f + jitter, 0.82f, 0.16f, 1.0f};
    return mix(dark, light, clamp01(0.26f + t * 0.62f));
}

void append_triangle(Mesh& mesh, const Vertex& a, const Vertex& b, const Vertex& c)
{
    const std::uint32_t base = static_cast<std::uint32_t>(mesh.vertices.size());
    mesh.vertices.push_back(a);
    mesh.vertices.push_back(b);
    mesh.vertices.push_back(c);
    mesh.indices.push_back(base + 0U);
    mesh.indices.push_back(base + 1U);
    mesh.indices.push_back(base + 2U);
}

void append_quad_double_sided(Mesh& mesh, Vec3 a, Vec3 b, Vec3 c, Vec3 d, const Color4 color, const Vec2 uv0, const Vec2 uv1)
{
    Vec3 normal = safe_normalize(cross(b - a, c - a), world_up);
    if (length(normal) < 0.0001f) {
        normal = world_up;
    }

    const Vertex va{a, normal, color, {uv0.x, uv0.y}};
    const Vertex vb{b, normal, color, {uv1.x, uv0.y}};
    const Vertex vc{c, normal, color, {uv1.x, uv1.y}};
    const Vertex vd{d, normal, color, {uv0.x, uv1.y}};
    append_triangle(mesh, va, vb, vc);
    append_triangle(mesh, va, vc, vd);

    const Vec3 n2 = -normal;
    const Vertex vda{d, n2, color, {uv0.x, uv1.y}};
    const Vertex vdc{c, n2, color, {uv1.x, uv1.y}};
    const Vertex vdb{b, n2, color, {uv1.x, uv0.y}};
    const Vertex vdaa{a, n2, color, {uv0.x, uv0.y}};
    append_triangle(mesh, vda, vdc, vdb);
    append_triangle(mesh, vda, vdb, vdaa);
}

void make_basis_from_axis(const Vec3 axis, Vec3& right, Vec3& forward)
{
    const Vec3 n = safe_normalize(axis, world_up);
    const Vec3 helper = std::abs(dot(n, world_up)) > 0.92f ? world_right : world_up;
    right = safe_normalize(cross(helper, n), {1.0f, 0.0f, 0.0f});
    forward = safe_normalize(cross(n, right), {0.0f, 0.0f, 1.0f});
}

void append_leaflet_strip(
    Mesh& mesh,
    const Vec3 base,
    const Vec3 direction,
    const Vec3 lateral,
    const float length_value,
    const float width_value,
    const float droop_value,
    const int segments,
    const Color4 color)
{
    const int segs = std::max(2, segments);
    Vec3 upish = safe_normalize(cross(lateral, direction), world_up);
    if (dot(upish, world_up) < 0.0f) {
        upish = -upish;
    }

    for (int i = 0; i < segs; ++i) {
        const float t0 = static_cast<float>(i) / static_cast<float>(segs);
        const float t1 = static_cast<float>(i + 1) / static_cast<float>(segs);

        const float profile0 = std::sin(t0 * pi);
        const float profile1 = std::sin(t1 * pi);
        const float w0 = width_value * profile0 * (0.82f + 0.18f * (1.0f - t0));
        const float w1 = width_value * profile1 * (0.82f + 0.18f * (1.0f - t1));
        const float ridge0 = width_value * 0.16f * (1.0f - t0) * profile0;
        const float ridge1 = width_value * 0.16f * (1.0f - t1) * profile1;

        const Vec3 p0 = base + direction * (length_value * t0) + Vec3{0.0f, -droop_value * t0 * t0, 0.0f};
        const Vec3 p1 = base + direction * (length_value * t1) + Vec3{0.0f, -droop_value * t1 * t1, 0.0f};

        const Vec3 a = p0 - lateral * w0 + upish * (ridge0 * 0.35f);
        const Vec3 b = p0 + lateral * w0 + upish * ridge0;
        const Vec3 c = p1 + lateral * w1 + upish * ridge1;
        const Vec3 d = p1 - lateral * w1 + upish * (ridge1 * 0.35f);
        append_quad_double_sided(mesh, a, b, c, d, color, {0.0f, t0}, {1.0f, t1});
    }
}

void append_leaf_vein_strip(
    Mesh& mesh,
    const Vec3 a,
    const Vec3 b,
    const Vec3 view_lateral,
    const float width_value,
    const Color4 color)
{
    const Vec3 axis = b - a;
    if (length(axis) <= 0.0001f || width_value <= 0.00001f) {
        return;
    }

    Vec3 lateral = safe_normalize(cross(axis, world_up), view_lateral);
    if (length(lateral) <= 0.0001f) {
        lateral = safe_normalize(view_lateral, {1.0f, 0.0f, 0.0f});
    }

    const Vec3 lift{0.0f, 0.0020f, 0.0f};
    append_quad_double_sided(
        mesh,
        a - lateral * width_value + lift,
        a + lateral * width_value + lift,
        b + lateral * (width_value * 0.45f) + lift,
        b - lateral * (width_value * 0.45f) + lift,
        color,
        {0.0f, 0.0f},
        {1.0f, 1.0f});
}

} // namespace

void append_disc(Mesh& mesh, const Vec3 center, const Vec3 axis, const float radius, const int radial_segments, const Color4 color, const bool flip_normal)
{
    if (radius <= 0.00001f) {
        return;
    }
    const int segs = std::max(4, radial_segments);
    Vec3 right;
    Vec3 forward;
    make_basis_from_axis(axis, right, forward);
    Vec3 normal = safe_normalize(axis, world_up);
    if (flip_normal) {
        normal = -normal;
    }

    const std::uint32_t center_index = static_cast<std::uint32_t>(mesh.vertices.size());
    mesh.vertices.push_back({center, normal, color, {0.5f, 0.5f}});
    for (int i = 0; i < segs; ++i) {
        const float angle = (static_cast<float>(i) / static_cast<float>(segs)) * 2.0f * pi;
        const Vec3 ring_dir = right * std::cos(angle) + forward * std::sin(angle);
        mesh.vertices.push_back({center + ring_dir * radius, normal, color, {0.5f + ring_dir.x * 0.5f, 0.5f + ring_dir.z * 0.5f}});
    }
    for (int i = 0; i < segs; ++i) {
        const std::uint32_t i0 = center_index + 1U + static_cast<std::uint32_t>(i);
        const std::uint32_t i1 = center_index + 1U + static_cast<std::uint32_t>((i + 1) % segs);
        if (flip_normal) {
            mesh.indices.push_back(center_index);
            mesh.indices.push_back(i1);
            mesh.indices.push_back(i0);
        } else {
            mesh.indices.push_back(center_index);
            mesh.indices.push_back(i0);
            mesh.indices.push_back(i1);
        }
    }
}

void append_tip_cone(Mesh& mesh, const Vec3 base_center, const Vec3 axis, const float base_radius, const float length_scale, const int radial_segments, const Color4 color)
{
    if (base_radius <= 0.00001f || length_scale <= 0.00001f) {
        return;
    }
    const int segs = std::max(4, radial_segments);
    Vec3 right;
    Vec3 forward;
    make_basis_from_axis(axis, right, forward);
    const Vec3 n = safe_normalize(axis, world_up);
    const Vec3 tip = base_center + n * length_scale;

    const std::uint32_t tip_index = static_cast<std::uint32_t>(mesh.vertices.size());
    mesh.vertices.push_back({tip, n, color, {0.5f, 1.0f}});
    for (int i = 0; i < segs; ++i) {
        const float angle = (static_cast<float>(i) / static_cast<float>(segs)) * 2.0f * pi;
        const Vec3 ring_dir = right * std::cos(angle) + forward * std::sin(angle);
        const Vec3 pos = base_center + ring_dir * base_radius;
        const Vec3 normal = safe_normalize(ring_dir * 0.78f + n * 0.62f, ring_dir);
        mesh.vertices.push_back({pos, normal, color, {static_cast<float>(i) / static_cast<float>(segs), 0.0f}});
    }
    for (int i = 0; i < segs; ++i) {
        const std::uint32_t i0 = tip_index + 1U + static_cast<std::uint32_t>(i);
        const std::uint32_t i1 = tip_index + 1U + static_cast<std::uint32_t>((i + 1) % segs);
        mesh.indices.push_back(tip_index);
        mesh.indices.push_back(i0);
        mesh.indices.push_back(i1);
    }
}

void append_cylinder(Mesh& mesh, const Vec3 a, const Vec3 b, const float radius_a, const float radius_b, const int radial_segments, const Color4 color)
{
    const Vec3 axis = b - a;
    if (length(axis) <= 0.0001f) {
        return;
    }

    const int segs = std::max(4, radial_segments);
    Vec3 right;
    Vec3 forward;
    make_basis_from_axis(axis, right, forward);
    const Vec3 normal_axis = safe_normalize(axis);

    const std::uint32_t base = static_cast<std::uint32_t>(mesh.vertices.size());
    mesh.vertices.reserve(mesh.vertices.size() + static_cast<std::size_t>(segs * 2));

    for (int i = 0; i < segs; ++i) {
        const float angle = (static_cast<float>(i) / static_cast<float>(segs)) * 2.0f * pi;
        const Vec3 ring_dir = right * std::cos(angle) + forward * std::sin(angle);
        const Vec3 normal = safe_normalize(ring_dir * 0.92f + normal_axis * 0.08f, ring_dir);
        mesh.vertices.push_back({a + ring_dir * radius_a, normal, color, {static_cast<float>(i) / static_cast<float>(segs), 0.0f}});
        mesh.vertices.push_back({b + ring_dir * radius_b, normal, color, {static_cast<float>(i) / static_cast<float>(segs), 1.0f}});
    }

    for (int i = 0; i < segs; ++i) {
        const std::uint32_t i0 = base + static_cast<std::uint32_t>(i * 2);
        const std::uint32_t i1 = base + static_cast<std::uint32_t>(((i + 1) % segs) * 2);
        const std::uint32_t i2 = i0 + 1U;
        const std::uint32_t i3 = i1 + 1U;

        mesh.indices.push_back(i0);
        mesh.indices.push_back(i1);
        mesh.indices.push_back(i3);
        mesh.indices.push_back(i0);
        mesh.indices.push_back(i3);
        mesh.indices.push_back(i2);
    }
}

void append_node_marker(Mesh& mesh, const Vec3 center, const float radius, const Color4 color)
{
    append_cylinder(mesh, center + Vec3{-radius, 0.0f, 0.0f}, center + Vec3{radius, 0.0f, 0.0f}, radius * 0.30f, radius * 0.30f, 6, color);
    append_cylinder(mesh, center + Vec3{0.0f, -radius, 0.0f}, center + Vec3{0.0f, radius, 0.0f}, radius * 0.30f, radius * 0.30f, 6, color);
    append_cylinder(mesh, center + Vec3{0.0f, 0.0f, -radius}, center + Vec3{0.0f, 0.0f, radius}, radius * 0.30f, radius * 0.30f, 6, color);
}

void append_soft_terminal_taper(Mesh& mesh, const Vec3 base_center, const Vec3 axis, const float base_radius, const int radial_segments, const Color4 color)
{
    const float r0 = std::max(0.0010f, base_radius);
    const float r1 = std::max(0.0008f, r0 * 0.46f);
    const float r2 = std::max(0.0006f, r0 * 0.12f);
    const Vec3 n = safe_normalize(axis, world_up);
    const Vec3 mid = base_center + n * (r0 * 0.95f);
    const Vec3 tip = mid + n * (r0 * 0.38f);
    append_cylinder(mesh, base_center, mid, r0, r1, radial_segments, color);
    append_cylinder(mesh, mid, tip, r1, r2, radial_segments, color);
    append_disc(mesh, tip, n, r2, radial_segments, color, false);
}

void append_fan_leaf(Mesh& mesh, const PlantParameters& params, const LeafCluster& leaf, const float grow01)
{
    const float grow = smoothstep(0.0f, 1.0f, grow01);
    if (grow <= 0.0001f) {
        return;
    }

    const Vec3 outward = safe_normalize(leaf.outward, {1.0f, 0.0f, 0.0f});
    Vec3 side = safe_normalize(cross(world_up, outward), {0.0f, 0.0f, 1.0f});
    if (length(side) <= 0.0001f) {
        side = {1.0f, 0.0f, 0.0f};
    }

    const float pitch = params.leaf_pitch_down_deg * deg_to_rad;
    Vec3 dir = safe_normalize(outward * std::cos(pitch) + Vec3{0.0f, -std::sin(pitch), 0.0f}, outward);

    const float variant = hash01(static_cast<std::uint32_t>(leaf.variant * 2654435761U + 91U));
    const float roll = (variant - 0.5f) * 0.44f;
    side = safe_normalize(rotate_around_axis(side, dir, roll), side);

    Vec3 normal = safe_normalize(cross(side, dir), world_up);
    if (dot(normal, world_up) < -0.25f) {
        normal = -normal;
    }
    dir = safe_normalize(cross(normal, side), dir);

    const float base_scale = leaf.scale * grow;
    const float aspect = params.preset == PlantPreset::Cannabis ? 0.88f : 0.66f;
    const float card_h = base_scale * (params.preset == PlantPreset::Cannabis ? 0.62f : 0.48f);
    const float card_w = card_h * aspect;
    const float droop = card_h * params.leaf_droop * (0.18f + 0.22f * variant) * grow;
    const Vec3 petiole_base = leaf.origin;
    const Vec3 center = petiole_base + dir * (params.petiole_length * base_scale + card_h * 0.42f) + Vec3{0.0f, -droop * 0.35f, 0.0f};

    const Color4 petiole_color = params.preset == PlantPreset::Cannabis
        ? Color4{0.46f, 0.31f, 0.16f, 1.0f}
        : Color4{0.20f, 0.42f, 0.14f, 1.0f};
    append_leaf_vein_strip(mesh, petiole_base, center - dir * (card_h * 0.38f), side, 0.0055f * base_scale, petiole_color);

    const Vec3 root = center - dir * (card_h * 0.50f);
    const Vec3 tip = center + dir * (card_h * 0.50f) + Vec3{0.0f, -droop, 0.0f};
    const Vec3 mid_l = center - side * (card_w * 0.50f) + Vec3{0.0f, -droop * 0.18f, 0.0f};
    const Vec3 mid_r = center + side * (card_w * 0.50f) + Vec3{0.0f, -droop * 0.18f, 0.0f};

    const Color4 color = leaf_color_for(leaf, 0.78f);
    append_quad_double_sided(mesh, root - side * (card_w * 0.10f), root + side * (card_w * 0.10f), mid_r, mid_l, color, {0.0f, 0.0f}, {1.0f, 0.52f});
    append_quad_double_sided(mesh, mid_l, mid_r, tip + side * (card_w * 0.08f), tip - side * (card_w * 0.08f), color, {0.0f, 0.48f}, {1.0f, 1.0f});
}

void append_broad_leaf(Mesh& mesh, const PlantParameters& params, const LeafCluster& leaf, const float grow01)
{
    const float grow = smoothstep(0.0f, 1.0f, grow01);
    if (grow <= 0.0001f) {
        return;
    }

    const Vec3 outward = safe_normalize(leaf.outward, {1.0f, 0.0f, 0.0f});
    const Vec3 side = safe_normalize(cross(world_up, outward), {0.0f, 0.0f, 1.0f});
    const float pitch = params.leaf_pitch_down_deg * deg_to_rad;
    const Vec3 dir = safe_normalize(outward * std::cos(pitch) + Vec3{0.0f, -std::sin(pitch), 0.0f}, outward);
    const float length_value = params.leaf_scale * leaf.scale * 0.30f * grow;
    const float width_value = length_value * params.leaf_width_ratio;
    const float droop = length_value * params.leaf_droop;
    append_leaflet_strip(mesh, leaf.origin + dir * (params.petiole_length * grow), dir, side, length_value, width_value, droop, std::max(3, params.leaflet_segments), leaf_color_for(leaf, 0.72f));
}

void append_fernlet_leaf(Mesh& mesh, const PlantParameters& params, const LeafCluster& leaf, const float grow01)
{
    const float grow = smoothstep(0.0f, 1.0f, grow01);
    if (grow <= 0.0001f) {
        return;
    }

    const Vec3 outward = safe_normalize(leaf.outward, {1.0f, 0.0f, 0.0f});
    const Vec3 side = safe_normalize(cross(world_up, outward), {0.0f, 0.0f, 1.0f});
    const int count = std::max(5, params.leaflet_count);
    const float stem_len = leaf.scale * params.leaf_scale * 0.42f * grow;
    const Vec3 stem_base = leaf.origin;
    const Vec3 stem_tip = stem_base + outward * stem_len;
    append_cylinder(mesh, stem_base, stem_tip, 0.006f * grow, 0.002f * grow, 5, {0.20f, 0.50f, 0.16f, 1.0f});

    for (int i = 1; i <= count; ++i) {
        const float t = static_cast<float>(i) / static_cast<float>(count + 1);
        const Vec3 base = stem_base + outward * (stem_len * t);
        const float s = (i % 2 == 0) ? 1.0f : -1.0f;
        const Vec3 dir = safe_normalize(side * s + outward * 0.24f, side * s);
        const float l = stem_len * 0.28f * (1.0f - 0.35f * t);
        append_leaflet_strip(mesh, base, dir, outward, l, l * 0.12f, l * 0.05f, 3, leaf_color_for(leaf, t));
    }
}

Mesh build_mesh(const NodeGraph& graph, const float time01)
{
    Mesh mesh;
    const PlantParameters& params = graph.parameters;
    const float t = clamp01(time01);

    mesh.vertices.reserve(graph.branches.size() * static_cast<std::size_t>(params.radial_segments) * 6U + graph.leaves.size() * 256U);
    mesh.indices.reserve(graph.branches.size() * static_cast<std::size_t>(params.radial_segments) * 18U + graph.leaves.size() * 1024U);

    std::vector<std::uint32_t> outgoing(graph.nodes.size(), 0U);
    for (const BranchSegment& branch : graph.branches) {
        if (branch.parent_node < outgoing.size()) {
            ++outgoing[branch.parent_node];
        }
    }

    for (const BranchSegment& branch : graph.branches) {
        const float grow = smoothstep(branch.birth, branch.end, t);
        if (grow <= 0.0001f) {
            continue;
        }

        const Vec3 end = lerp(branch.a, branch.b, grow);
        const float radius_b = lerp(branch.radius_a, branch.radius_b, grow);
        const Color4 stem_color = stem_color_for(params, branch.depth);
        append_cylinder(
            mesh,
            branch.a,
            end,
            branch.radius_a,
            radius_b,
            params.radial_segments,
            stem_color);

        const bool still_growing = grow < 0.999f;
        const bool child_terminal = branch.child_node >= outgoing.size() || outgoing[branch.child_node] == 0U;
        const Vec3 axis = safe_normalize(branch.b - branch.a, world_up);
        if (still_growing) {
            append_disc(mesh, end, axis, std::max(0.001f, radius_b), params.radial_segments, stem_color, false);
        } else if (child_terminal) {
            append_soft_terminal_taper(mesh, end, axis, std::max(0.0010f, radius_b), params.radial_segments, stem_color);
        }
    }

    for (const LeafCluster& leaf : graph.leaves) {
        const float grow = clamp01((t - leaf.birth) / std::max(0.0001f, params.leaf_grow_seconds / std::max(0.01f, params.full_growth_seconds)));
        if (grow <= 0.0001f) {
            continue;
        }

        switch (leaf.style) {
        case LeafStyle::Fan:
            append_fan_leaf(mesh, params, leaf, grow);
            break;
        case LeafStyle::Broad:
            append_broad_leaf(mesh, params, leaf, grow);
            break;
        case LeafStyle::Needle:
            append_broad_leaf(mesh, params, leaf, grow * 0.75f);
            break;
        case LeafStyle::Fernlet:
            append_fernlet_leaf(mesh, params, leaf, grow);
            break;
        case LeafStyle::None:
            break;
        }
    }

    if (params.show_node_markers) {
        for (const Node& node : graph.nodes) {
            if (t >= node.birth) {
                append_node_marker(mesh, node.position, std::max(0.012f, node.radius * 0.55f), {0.96f, 0.74f, 0.25f, 1.0f});
            }
        }
    }

    return mesh;
}

} // namespace twol
