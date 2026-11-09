#include "plant_growth.hpp"

#include <algorithm>
#include <cmath>
#include <cstdint>
#include <limits>

namespace plantgl {

namespace {

using twol::Color4;
using twol::Vec3;

constexpr Vec3 kWorldUp{0.0f, 1.0f, 0.0f};
constexpr Vec3 kWorldRight{1.0f, 0.0f, 0.0f};
constexpr std::size_t kMaxBatchVertices = 60000;

float clampf(float v, float lo, float hi) { return v < lo ? lo : (v > hi ? hi : v); }

Vec3 mix_rgb(const Vec3 a, const Vec3 b, float t) {
  return {twol::lerp(a.x, b.x, t), twol::lerp(a.y, b.y, t), twol::lerp(a.z, b.z, t)};
}

Vec3 scale_rgb(const Vec3 c, float s) { return {c.x * s, c.y * s, c.z * s}; }

Vec3 stem_color(const twol::PlantParameters& p, int depth) {
  switch (p.preset) {
    case twol::PlantPreset::Cannabis:
      return depth == 0 ? Vec3{0.42f, 0.28f, 0.14f} : Vec3{0.52f, 0.35f, 0.17f};
    case twol::PlantPreset::Tree:
      return depth == 0 ? Vec3{0.29f, 0.19f, 0.11f} : Vec3{0.36f, 0.24f, 0.13f};
    case twol::PlantPreset::Bush:
      return Vec3{0.22f, 0.34f, 0.13f};
    case twol::PlantPreset::Fern:
      return Vec3{0.16f, 0.38f, 0.14f};
    case twol::PlantPreset::Pattern2D:
      return Vec3{0.45f, 0.92f, 0.34f};
  }
  return Vec3{0.4f, 0.4f, 0.4f};
}

Vec3 leaf_color(const twol::PlantParameters& p, const twol::LeafCluster& leaf) {
  const std::uint32_t h =
      static_cast<std::uint32_t>(leaf.variant) * 2654435761U + p.seed * 40503U + 91U;
  const float v = twol::hash01(h);
  const float w = twol::hash01(h ^ 0x9e3779b9U);
  Vec3 dark;
  Vec3 light;
  switch (p.preset) {
    case twol::PlantPreset::Tree:
      dark = {0.045f, 0.16f, 0.055f};
      light = {0.16f, 0.48f, 0.12f};
      if (v > 0.93f) {  // a few autumn leaves in an otherwise green crown
        dark = {0.38f, 0.20f, 0.04f};
        light = {0.82f, 0.52f, 0.10f};
      }
      break;
    case twol::PlantPreset::Bush:
      dark = {0.08f, 0.26f, 0.06f};
      light = {0.28f, 0.62f, 0.15f};
      break;
    case twol::PlantPreset::Fern:
      dark = {0.14f, 0.32f, 0.08f};
      light = {0.46f, 0.78f, 0.24f};
      break;
    case twol::PlantPreset::Cannabis:
      dark = {0.055f, 0.22f, 0.055f};
      light = {0.26f, 0.68f, 0.16f};
      break;
    case twol::PlantPreset::Pattern2D:
      dark = {0.35f, 0.80f, 0.25f};
      light = {0.72f, 1.00f, 0.45f};
      break;
  }
  Vec3 c = mix_rgb(dark, light, 0.30f + 0.55f * twol::hash01(h ^ 0x85ebca6bU));
  return scale_rgb(c, 0.90f + 0.20f * w);
}

void make_basis(const Vec3 axis, Vec3& right, Vec3& forward) {
  const Vec3 n = twol::safe_normalize(axis, kWorldUp);
  const Vec3 helper = std::abs(twol::dot(n, kWorldUp)) > 0.92f ? kWorldRight : kWorldUp;
  right = twol::safe_normalize(twol::cross(helper, n), kWorldRight);
  forward = twol::safe_normalize(twol::cross(n, right), Vec3{0.0f, 0.0f, 1.0f});
}

GrowthVertex make_vertex(const Vec3 p, const Vec3 n, const Vec3 c, const Vec3 anchor,
                         float birth, float span, float sway, float phase) {
  GrowthVertex v{};
  v.position[0] = p.x;
  v.position[1] = p.y;
  v.position[2] = p.z;
  v.normal[0] = n.x;
  v.normal[1] = n.y;
  v.normal[2] = n.z;
  v.color[0] = c.x;
  v.color[1] = c.y;
  v.color[2] = c.z;
  v.anchor[0] = anchor.x;
  v.anchor[1] = anchor.y;
  v.anchor[2] = anchor.z;
  v.birth = birth;
  v.span = span;
  v.sway = sway;
  v.phase = phase;
  return v;
}

class Builder {
 public:
  explicit Builder(GrowthMesh& mesh) : mesh_(mesh) {}

  void tri(const GrowthVertex& a, const GrowthVertex& b, const GrowthVertex& c) {
    ensure(3);
    const std::uint16_t i0 = push(a);
    const std::uint16_t i1 = push(b);
    const std::uint16_t i2 = push(c);
    auto& batch = mesh_.batches.back();
    batch.indices.push_back(i0);
    batch.indices.push_back(i1);
    batch.indices.push_back(i2);
    mesh_.triangle_count += 1;
  }

  void quad(const GrowthVertex& a, const GrowthVertex& b, const GrowthVertex& c,
            const GrowthVertex& d) {
    ensure(4);
    const std::uint16_t i0 = push(a);
    const std::uint16_t i1 = push(b);
    const std::uint16_t i2 = push(c);
    const std::uint16_t i3 = push(d);
    auto& batch = mesh_.batches.back();
    batch.indices.push_back(i0);
    batch.indices.push_back(i1);
    batch.indices.push_back(i2);
    batch.indices.push_back(i0);
    batch.indices.push_back(i2);
    batch.indices.push_back(i3);
    mesh_.triangle_count += 2;
  }

  // A tapered tube from a to b, grown from its a end. Used for stems and petioles.
  void tube(const Vec3 a, const Vec3 b, float radius_a, float radius_b, int radial_segments,
            const Vec3 color, const Vec3 anchor, float birth, float span, float phase) {
    const Vec3 axis = b - a;
    if (twol::length(axis) <= 0.00001f) return;
    const int segs = std::max(3, radial_segments);
    Vec3 right;
    Vec3 forward;
    make_basis(axis, right, forward);
    const Vec3 axis_n = twol::safe_normalize(axis, kWorldUp);
    const float r0 = std::max(0.0005f, radius_a);
    const float r1 = std::max(0.0005f, radius_b);

    ensure(static_cast<std::size_t>(segs) * 2U);
    auto& batch = mesh_.batches.back();
    const std::uint16_t start = static_cast<std::uint16_t>(batch.vertices.size());
    for (int i = 0; i < segs; ++i) {
      const float angle = (static_cast<float>(i) / static_cast<float>(segs)) * 2.0f * twol::pi;
      const Vec3 ring = right * std::cos(angle) + forward * std::sin(angle);
      const Vec3 n = twol::safe_normalize(ring * 0.92f + axis_n * 0.08f, ring);
      push(make_vertex(a + ring * r0, n, color, anchor, birth, span, 0.0f, phase));
      push(make_vertex(b + ring * r1, n, color, anchor, birth, span, 0.0f, phase));
    }
    for (int i = 0; i < segs; ++i) {
      const std::uint16_t i0 = static_cast<std::uint16_t>(start + i * 2);
      const std::uint16_t i1 = static_cast<std::uint16_t>(start + ((i + 1) % segs) * 2);
      batch.indices.push_back(i0);
      batch.indices.push_back(i1);
      batch.indices.push_back(static_cast<std::uint16_t>(i1 + 1));
      batch.indices.push_back(i0);
      batch.indices.push_back(static_cast<std::uint16_t>(i1 + 1));
      batch.indices.push_back(static_cast<std::uint16_t>(i0 + 1));
      mesh_.triangle_count += 2;
    }
  }

 private:
  void ensure(std::size_t n) {
    if (mesh_.batches.empty() ||
        mesh_.batches.back().vertices.size() + n > kMaxBatchVertices) {
      mesh_.batches.emplace_back();
      mesh_.batches.back().vertices.reserve(std::min(n * 2U, kMaxBatchVertices));
      mesh_.batches.back().indices.reserve(std::min(n * 3U, kMaxBatchVertices));
    }
  }
  std::uint16_t push(const GrowthVertex& v) {
    auto& b = mesh_.batches.back();
    const std::uint16_t index = static_cast<std::uint16_t>(b.vertices.size());
    b.vertices.push_back(v);
    return index;
  }

  GrowthMesh& mesh_;
};

struct LeafBasis {
  Vec3 outward;
  Vec3 side;
  Vec3 dir;
  Vec3 normal;
};

LeafBasis leaf_basis(const twol::PlantParameters& p, const twol::LeafCluster& leaf) {
  LeafBasis b;
  b.outward = twol::safe_normalize(leaf.outward, Vec3{1.0f, 0.0f, 0.0f});
  b.side = twol::safe_normalize(twol::cross(kWorldUp, b.outward), Vec3{0.0f, 0.0f, 1.0f});
  if (twol::length(b.side) <= 0.0001f) b.side = Vec3{1.0f, 0.0f, 0.0f};
  const float pitch = clampf(p.leaf_pitch_down_deg, 0.0f, 85.0f) * twol::deg_to_rad;
  b.dir = twol::safe_normalize(
      b.outward * std::cos(pitch) + Vec3{0.0f, -std::sin(pitch), 0.0f}, b.outward);
  const float variant =
      twol::hash01(static_cast<std::uint32_t>(leaf.variant) * 2654435761U + 91U);
  const float roll = (variant - 0.5f) * 0.44f;
  b.side = twol::safe_normalize(twol::rotate_around_axis(b.side, b.dir, roll), b.side);
  b.normal = twol::safe_normalize(twol::cross(b.side, b.dir), kWorldUp);
  if (twol::dot(b.normal, kWorldUp) < -0.25f) b.normal = -b.normal;
  b.dir = twol::safe_normalize(twol::cross(b.normal, b.side), b.dir);
  return b;
}

// One leaflet / leaf blade: a curved ribbon with a raised, darker midrib and a pointed tip.
// Three vertices per cross-section (left, midrib, right).
void ribbon(Builder& builder, const Vec3 base, const Vec3 dir, const Vec3 side,
            const Vec3 normal, float length, float half_width, float droop, int segments,
            const Vec3 color_base, const Vec3 color_tip, const Vec3 anchor, float birth,
            float span, float phase, float sway_scale) {
  const int segs = std::max(3, segments);
  const Vec3 up = twol::safe_normalize(normal, kWorldUp);
  GrowthVertex prev_left{};
  GrowthVertex prev_mid{};
  GrowthVertex prev_right{};
  for (int i = 0; i <= segs; ++i) {
    const float t = static_cast<float>(i) / static_cast<float>(segs);
    const float profile = std::pow(std::max(0.0f, std::sin(t * twol::pi)), 0.68f);
    const float w = half_width * profile * (1.0f - 0.22f * t);
    const Vec3 p = base + dir * (length * t) + Vec3{0.0f, -droop * t * t, 0.0f};
    const Vec3 ridge = up * (half_width * 0.16f * profile);
    const Vec3 c = mix_rgb(color_base, color_tip, t * 0.75f);
    const Vec3 c_mid = scale_rgb(c, 0.78f);
    const float sway = t * sway_scale;
    const GrowthVertex left = make_vertex(p - side * w, normal, c, anchor, birth, span, sway, phase);
    const GrowthVertex mid = make_vertex(p + ridge, normal, c_mid, anchor, birth, span, sway, phase);
    const GrowthVertex right = make_vertex(p + side * w, normal, c, anchor, birth, span, sway, phase);
    if (i > 0) {
      builder.quad(prev_left, prev_mid, mid, left);
      builder.quad(prev_mid, prev_right, right, mid);
    }
    prev_left = left;
    prev_mid = mid;
    prev_right = right;
  }
}

}  // namespace

GrowthMesh build_growth_mesh(const twol::NodeGraph& graph) {
  GrowthMesh mesh;
  Builder builder(mesh);

  const twol::PlantParameters& p = graph.parameters;
  const bool pattern = p.preset == twol::PlantPreset::Pattern2D ||
                       p.dimension_mode == twol::DimensionMode::Pattern2D;
  const int radial = std::clamp(p.radial_segments, 4, 12);
  const float leaf_span =
      std::max(0.012f, p.leaf_grow_seconds / std::max(0.1f, p.full_growth_seconds));

  std::vector<std::uint32_t> outgoing(graph.nodes.size(), 0U);
  for (const twol::BranchSegment& b : graph.branches) {
    if (b.parent_node < outgoing.size()) ++outgoing[b.parent_node];
  }

  for (std::size_t bi = 0; bi < graph.branches.size(); ++bi) {
    const twol::BranchSegment& b = graph.branches[bi];
    const float span = std::max(0.0008f, b.end - b.birth);
    Vec3 color = stem_color(p, b.depth);
    float radius_scale = 1.0f;
    if (pattern) {
      // L-system lines are very thin; widen them so they read as glowing stems.
      radius_scale = 2.8f;
      const float t = twol::clamp01(b.birth);
      color = mix_rgb(Vec3{0.18f, 0.55f, 0.22f}, Vec3{0.62f, 1.0f, 0.40f}, t);
    }
    const bool terminal = b.child_node >= outgoing.size() || outgoing[b.child_node] == 0U;
    const float phase = twol::hash01(static_cast<std::uint32_t>(bi) * 747796405U);
    builder.tube(b.a, b.b, b.radius_a * radius_scale, b.radius_b * radius_scale, radial, color,
                 b.a, b.birth, span, phase);
    if (!pattern && terminal) {
      const Vec3 axis = twol::safe_normalize(b.b - b.a, kWorldUp);
      const float r = std::max(0.0012f, b.radius_b);
      builder.tube(b.b, b.b + axis * (r * 2.2f), r, 0.0010f, radial, color, b.a, b.birth, span,
                   phase);
    }
    mesh.branch_segments += 1;
  }

  if (!pattern) {
    for (const twol::LeafCluster& leaf : graph.leaves) {
      const LeafBasis basis = leaf_basis(p, leaf);
      const Vec3 color = leaf_color(p, leaf);
      const std::uint32_t h =
          static_cast<std::uint32_t>(leaf.variant) * 2654435761U + p.seed * 40503U;
      const float phase = twol::hash01(h ^ 0x27d4eb2fU);
      const float birth = leaf.birth;
      const float span = leaf_span * (0.85f + 0.30f * twol::hash01(h ^ 0x165667b1U));
      const float petiole = std::min(0.40f, std::max(0.015f, p.petiole_length * 1.15f));
      const Vec3 root = leaf.origin + basis.dir * petiole;
      const Vec3 petiole_color = stem_color(p, 1);
      const float petiole_scale = std::max(0.5f, leaf.scale * 0.4f);

      if (p.leaf_style == twol::LeafStyle::Fan) {
        if (petiole > 0.02f) {
          builder.tube(leaf.origin, root, 0.010f * petiole_scale, 0.006f * petiole_scale, 5,
                       petiole_color, leaf.origin, birth, span, phase);
        }
        const int count = std::clamp(p.leaflet_count, 3, 15);
        const float spread = clampf(p.fan_spread_deg, 40.0f, 180.0f) * twol::deg_to_rad;
        const float base_len =
            leaf.scale * (p.preset == twol::PlantPreset::Cannabis ? 0.46f : 0.40f);
        for (int i = 0; i < count; ++i) {
          const float u = count > 1 ? static_cast<float>(i) / static_cast<float>(count - 1) : 0.5f;
          const float angle = (u - 0.5f) * spread;
          const Vec3 dir = twol::safe_normalize(
              twol::rotate_around_axis(basis.dir, basis.normal, angle), basis.dir);
          const float len =
              base_len * (0.58f + 0.42f * std::cos(angle)) *
              (0.90f + 0.20f * twol::hash01(h + static_cast<std::uint32_t>(i) * 6151U));
          const float half_width = len * 0.115f;
          const float droop = len * p.leaf_droop * 0.55f;
          const Vec3 tip_color = mix_rgb(color, Vec3{0.72f, 0.90f, 0.30f},
                                         0.18f + 0.22f * std::abs(u - 0.5f) * 2.0f);
          ribbon(builder, root, dir, basis.side, basis.normal, len, half_width, droop,
                 std::max(4, p.leaflet_segments), color, tip_color, leaf.origin, birth, span,
                 phase + static_cast<float>(i) * 0.061f,
                 0.55f + 0.45f * std::abs(u - 0.5f) * 2.0f);
        }
      } else if (p.leaf_style == twol::LeafStyle::Fernlet) {
        const float stem_len = leaf.scale * 0.72f;
        const Vec3 tip = leaf.origin + basis.outward * stem_len;
        builder.tube(leaf.origin, tip, 0.010f * std::max(0.5f, leaf.scale), 0.0025f, 5,
                     petiole_color, leaf.origin, birth, span, phase);
        const int count = std::clamp(p.leaflet_count, 5, 15);
        for (int i = 1; i <= count; ++i) {
          const float t = static_cast<float>(i) / static_cast<float>(count + 1);
          const Vec3 b = leaf.origin + basis.outward * (stem_len * t);
          const float s = (i % 2 == 0) ? 1.0f : -1.0f;
          const Vec3 dir = twol::safe_normalize(basis.side * s + basis.outward * 0.26f,
                                                basis.side * s);
          const float len = stem_len * 0.30f * (1.0f - 0.35f * t);
          ribbon(builder, b, dir, basis.outward, basis.normal, len, len * 0.14f, len * 0.05f, 3,
                 color, mix_rgb(color, Vec3{0.60f, 0.88f, 0.30f}, 0.35f), leaf.origin, birth,
                 span, phase + static_cast<float>(i) * 0.033f, 0.50f + 0.50f * t);
        }
        (void)tip;
      } else {
        // Broad leaves (Tree, Bush) and needles are one blade.
        const bool needle = p.leaf_style == twol::LeafStyle::Needle;
        const float len = leaf.scale * (needle ? 0.70f : 0.92f);
        const float half_width = len * (needle ? 0.035f : p.leaf_width_ratio * 0.55f);
        const float droop = len * p.leaf_droop * (needle ? 0.35f : 0.85f);
        if (petiole > 0.02f) {
          builder.tube(leaf.origin, root, 0.008f * petiole_scale, 0.005f * petiole_scale, 5,
                       petiole_color, leaf.origin, birth, span, phase);
        }
        ribbon(builder, root, basis.dir, basis.side, basis.normal, len, half_width, droop,
               std::max(4, p.leaflet_segments), color,
               mix_rgb(color, Vec3{0.62f, 0.88f, 0.26f}, 0.25f), leaf.origin, birth, span,
               phase, 1.0f);
      }
      mesh.leaf_clusters += 1;
    }
  }

  // Leaf births can land just past 1.0 in the plant graph (a leaf on the last node is born after
  // the trunk finishes). Stretch every growth window by the same factor so the whole plant has
  // finished growing at time01 == 1 and the final leaves are not left invisible forever.
  float growth_end = 0.0f;
  for (const GrowthBatch& b : mesh.batches) {
    for (const GrowthVertex& v : b.vertices) {
      growth_end = std::max(growth_end, v.birth + v.span);
    }
  }
  if (growth_end > 0.0001f) {
    const float inv = 1.0f / growth_end;
    for (GrowthBatch& b : mesh.batches) {
      for (GrowthVertex& v : b.vertices) {
        v.birth *= inv;
        v.span *= inv;
      }
    }
  }

  // Bounds over the fully grown plant (all vertices, all batches).
  Vec3 lo{std::numeric_limits<float>::max(), std::numeric_limits<float>::max(),
          std::numeric_limits<float>::max()};
  Vec3 hi{-std::numeric_limits<float>::max(), -std::numeric_limits<float>::max(),
          -std::numeric_limits<float>::max()};
  mesh.vertex_count = 0;
  for (const GrowthBatch& b : mesh.batches) {
    mesh.vertex_count += b.vertices.size();
    for (const GrowthVertex& v : b.vertices) {
      const Vec3 q{v.position[0], v.position[1], v.position[2]};
      lo.x = std::min(lo.x, q.x);
      lo.y = std::min(lo.y, q.y);
      lo.z = std::min(lo.z, q.z);
      hi.x = std::max(hi.x, q.x);
      hi.y = std::max(hi.y, q.y);
      hi.z = std::max(hi.z, q.z);
    }
  }
  if (mesh.vertex_count == 0) {
    lo = {-0.5f, 0.0f, -0.5f};
    hi = {0.5f, 1.0f, 0.5f};
  }
  mesh.bounds_min = lo;
  mesh.bounds_max = hi;
  const float y0 = std::min(0.0f, lo.y);
  mesh.height = std::max(0.5f, hi.y - y0);
  mesh.radius = std::max(0.25f, std::max(std::abs(lo.x), std::abs(hi.x)));
  mesh.radius = std::max(mesh.radius, std::max(std::abs(lo.z), std::abs(hi.z)));
  return mesh;
}

}  // namespace plantgl
