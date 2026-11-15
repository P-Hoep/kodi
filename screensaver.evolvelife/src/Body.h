// Morphology (Section 5 of EvolveLife.md): a directed graph of body-part
// nodes and attachment edges, with repeat counts, mirror flags and bounded
// recursion, expanded into a tree of segments joined by revolute joints.
//
// A segment is a rod between two point masses with a thickness (drawn as a
// capsule). The root node is the torso; an edge hangs a child segment off
// one end of its parent at a rest angle, and the joint there is a motor the
// brain drives within limits. The expanded body is a tree by construction,
// so it is always connected, and Validate() repairs every genome into range
// before a creature is built.
#pragma once

#include "Common.h"

#include <cstring>
#include <vector>

namespace evo
{

constexpr int MAX_NODES = 8;
constexpr int MAX_EDGES = 10;
constexpr int MAX_SEGS = 16;
constexpr int MAX_PARTS = MAX_SEGS + 1; // point masses
constexpr int J_MAX = 16;               // joint slots in the brain interface
constexpr int C_MAX = 8;                // contact slots
constexpr int MAX_DEPTH = 4;            // recursion limit of the expansion

struct BodyNode
{
  float len = 0.6f;     // m
  float thick = 0.12f;  // radius, m
  float density = 1.0f;
  float fin = 0.0f;     // 0 = no fin; else the fin's width in m (aerodynamic surface)
};

struct BodyEdge
{
  uint8_t from = 0, to = 0;
  uint8_t atStart = 0;  // hang off the parent's first end instead of its last
  uint8_t repeat = 0;   // 0..3 extra copies in a chain
  uint8_t mirror = 0;   // also a mirrored twin (rest angle reflected front to back)
  float angle = 0.0f;   // rest angle relative to the parent's direction, rad
  float curl = 0.0f;    // rest angle between chained copies
  float range = 0.6f;   // +- joint range around the rest angle, rad
  float strength = 0.3f;// motor stiffness, 0..1 of the error closed per iteration
  float speed = 6.0f;   // motor speed cap, rad/s
  float taper = 0.85f;  // size scale per chained copy
};

struct BodyGenome
{
  uint8_t numNodes = 1, numEdges = 0;
  BodyNode node[MAX_NODES];
  BodyEdge edge[MAX_EDGES];
};

// The expanded body. Joint j's child segment is segment j + 1 (segment 0 is
// the torso), so joint slots follow the creation order: depth first, a
// mirrored twin right after its original.
struct Segment
{
  uint8_t a, b;      // point masses
  uint8_t node;      // genome node
  uint8_t back;      // a mirrored twin, drawn behind
  float len, thick, mass, fin;
};

struct Joint
{
  uint8_t p, q, c;   // parent's far end, pivot, child end
  float rest, lo, hi, strength, speed;
};

struct Phenotype
{
  int numParts = 0, numSegs = 0, numJoints = 0, numFeet = 0;
  float px[MAX_PARTS], py[MAX_PARTS]; // rest pose, centred, lowest point at y = 0
  float mass[MAX_PARTS], radius[MAX_PARTS];
  Segment seg[MAX_SEGS];
  Joint joint[MAX_SEGS];
  uint8_t foot[C_MAX];                // point masses with a contact sensor
  float totalMass = 0.0f, finArea = 0.0f, width = 0.0f, height = 0.0f;
  int limbs = 0;                      // chains hanging off the torso
};

inline void Repair(BodyGenome& g)
{
  g.numNodes = static_cast<uint8_t>(std::min<int>(std::max<int>(g.numNodes, 1), MAX_NODES));
  g.numEdges = static_cast<uint8_t>(std::min<int>(g.numEdges, MAX_EDGES));
  for (int i = 0; i < g.numNodes; i++)
  {
    BodyNode& n = g.node[i];
    n.len = Clamp(std::isfinite(n.len) ? n.len : 0.6f, 0.2f, 1.3f);
    n.thick = Clamp(std::isfinite(n.thick) ? n.thick : 0.1f, 0.05f, 0.22f);
    n.thick = std::min(n.thick, n.len * 0.45f);
    n.density = Clamp(std::isfinite(n.density) ? n.density : 1.0f, 0.4f, 2.5f);
    n.fin = std::isfinite(n.fin) ? n.fin : 0.0f;
    n.fin = n.fin < 0.15f ? 0.0f : Clamp(n.fin, 0.15f, 0.9f);
  }
  int k = 0;
  for (int i = 0; i < g.numEdges; i++)
  {
    BodyEdge e = g.edge[i];
    if (e.from >= g.numNodes || e.to >= g.numNodes || e.to == 0)
      continue; // nothing hangs the torso off anything
    e.atStart = e.atStart ? 1 : 0;
    e.mirror = e.mirror ? 1 : 0;
    e.repeat = static_cast<uint8_t>(std::min<int>(e.repeat, 3));
    e.angle = std::isfinite(e.angle) ? WrapAngle(e.angle) : 0.0f;
    e.curl = Clamp(std::isfinite(e.curl) ? e.curl : 0.0f, -1.2f, 1.2f);
    e.range = Clamp(std::isfinite(e.range) ? e.range : 0.6f, 0.15f, 1.4f);
    e.strength = Clamp(std::isfinite(e.strength) ? e.strength : 0.3f, 0.05f, 0.6f);
    e.speed = Clamp(std::isfinite(e.speed) ? e.speed : 6.0f, 2.0f, 14.0f);
    e.taper = Clamp(std::isfinite(e.taper) ? e.taper : 0.85f, 0.6f, 1.05f);
    g.edge[k++] = e;
  }
  g.numEdges = static_cast<uint8_t>(k);

  // drop nodes the torso cannot reach, renumbering the rest
  bool reach[MAX_NODES] = {true};
  for (int pass = 0; pass < MAX_NODES; pass++)
    for (int i = 0; i < g.numEdges; i++)
      if (reach[g.edge[i].from])
        reach[g.edge[i].to] = true;
  int map[MAX_NODES];
  int m = 0;
  for (int i = 0; i < g.numNodes; i++)
  {
    map[i] = reach[i] ? m : -1;
    if (reach[i])
      g.node[m++] = g.node[i];
  }
  k = 0;
  for (int i = 0; i < g.numEdges; i++)
  {
    BodyEdge e = g.edge[i];
    if (map[e.from] < 0 || map[e.to] < 0)
      continue;
    e.from = static_cast<uint8_t>(map[e.from]);
    e.to = static_cast<uint8_t>(map[e.to]);
    g.edge[k++] = e;
  }
  g.numNodes = static_cast<uint8_t>(m);
  g.numEdges = static_cast<uint8_t>(k);
}

// Expand a (repaired) genome into at most maxSegs segments. Returns false if
// the body is degenerate (fewer than two segments), which the caller repairs.
inline bool Expand(const BodyGenome& g, int maxSegs, Phenotype& ph)
{
  maxSegs = std::min(std::max(maxSegs, 2), MAX_SEGS);
  ph.numParts = ph.numSegs = ph.numJoints = ph.numFeet = 0;
  ph.limbs = 0;
  const BodyNode& root = g.node[0];
  auto addPart = [&](float x, float y) {
    ph.px[ph.numParts] = x;
    ph.py[ph.numParts] = y;
    ph.mass[ph.numParts] = 0.0f;
    ph.radius[ph.numParts] = 0.0f;
    return ph.numParts++;
  };
  auto addSeg = [&](int a, int b, int node, bool back, float scale) {
    const BodyNode& n = g.node[node];
    Segment& s = ph.seg[ph.numSegs];
    s.a = static_cast<uint8_t>(a);
    s.b = static_cast<uint8_t>(b);
    s.node = static_cast<uint8_t>(node);
    s.back = back ? 1 : 0;
    s.len = n.len * scale;
    s.thick = std::max(n.thick * scale, 0.05f);
    s.fin = n.fin * scale;
    s.mass = s.len * s.thick * 2.0f * n.density + s.fin * s.len * 0.05f;
    ph.mass[a] += 0.5f * s.mass;
    ph.mass[b] += 0.5f * s.mass;
    ph.radius[a] = std::max(ph.radius[a], s.thick);
    ph.radius[b] = std::max(ph.radius[b], s.thick);
    return ph.numSegs++;
  };

  const int p0 = addPart(-0.5f * root.len, 0.0f);
  const int p1 = addPart(0.5f * root.len, 0.0f);
  addSeg(p0, p1, 0, false, 1.0f);

  // depth-first expansion with an explicit stack (node, segment, depth, back, scale)
  struct Item
  {
    int node, seg, depth;
    bool back;
    float scale;
  };
  Item stack[64];
  int sp = 0;
  stack[sp++] = {0, 0, 0, false, 1.0f};
  while (sp > 0)
  {
    const Item it = stack[--sp];
    // children are pushed in reverse so the first edge is expanded first
    Item later[32];
    int nl = 0;
    for (int ei = 0; ei < g.numEdges; ei++)
    {
      const BodyEdge& e = g.edge[ei];
      if (e.from != it.node)
        continue;
      if (it.depth >= MAX_DEPTH)
        continue;
      for (int twin = 0; twin <= (e.mirror ? 1 : 0); twin++)
      {
        int parentSeg = it.seg;
        float angle = twin ? WrapAngle(-kPi - e.angle) : e.angle;
        const float curl = twin ? -e.curl : e.curl;
        bool atStart = e.atStart != 0;
        float scale = it.scale;
        int last = -1;
        for (int k = 0; k <= e.repeat; k++)
        {
          if (ph.numSegs >= maxSegs)
            break;
          const Segment& ps = ph.seg[parentSeg];
          const int pivot = atStart ? ps.a : ps.b;
          const int far = atStart ? ps.b : ps.a;
          float dx = ph.px[pivot] - ph.px[far], dy = ph.py[pivot] - ph.py[far];
          const float dl = std::sqrt(dx * dx + dy * dy);
          dx /= dl;
          dy /= dl;
          const float ca = std::cos(angle), sa = std::sin(angle);
          const float ux = dx * ca - dy * sa, uy = dx * sa + dy * ca;
          const float len = g.node[e.to].len * scale;
          const int child = addPart(ph.px[pivot] + ux * len, ph.py[pivot] + uy * len);
          const int s = addSeg(pivot, child, e.to, it.back || twin, scale);
          Joint& j = ph.joint[ph.numJoints++];
          j.p = static_cast<uint8_t>(far);
          j.q = static_cast<uint8_t>(pivot);
          j.c = static_cast<uint8_t>(child);
          j.rest = angle;
          j.lo = angle - e.range;
          j.hi = angle + e.range;
          j.strength = e.strength;
          j.speed = e.speed;
          if (it.node == 0 && k == 0)
            ph.limbs++;
          parentSeg = s;
          last = s;
          atStart = false; // a chain continues from the far end
          angle = curl;
          scale = std::max(scale * e.taper, 0.35f);
        }
        if (last >= 0 && nl < 32)
          later[nl++] = {e.to, last, it.depth + 1, it.back || twin != 0, scale};
      }
    }
    for (int i = nl - 1; i >= 0 && sp < 64; i--)
      stack[sp++] = later[i];
  }
  if (ph.numSegs < 2)
    return false;

  // feet: the free ends of leaf segments (or the torso's ends when no leaf)
  int degree[MAX_PARTS] = {};
  for (int s = 0; s < ph.numSegs; s++)
  {
    degree[ph.seg[s].a]++;
    degree[ph.seg[s].b]++;
  }
  for (int i = 0; i < ph.numParts && ph.numFeet < C_MAX; i++)
    if (degree[i] == 1)
      ph.foot[ph.numFeet++] = static_cast<uint8_t>(i);

  // centre on the centre of mass, lowest point at y = 0
  float mx = 0, my = 0, mt = 0;
  float lo = 1e9f, xl = 1e9f, xh = -1e9f, yh = -1e9f;
  for (int i = 0; i < ph.numParts; i++)
  {
    mx += ph.px[i] * ph.mass[i];
    my += ph.py[i] * ph.mass[i];
    mt += ph.mass[i];
  }
  mx /= mt;
  for (int i = 0; i < ph.numParts; i++)
  {
    ph.px[i] -= mx;
    lo = std::min(lo, ph.py[i] - ph.radius[i]);
  }
  for (int i = 0; i < ph.numParts; i++)
  {
    ph.py[i] -= lo;
    xl = std::min(xl, ph.px[i] - ph.radius[i]);
    xh = std::max(xh, ph.px[i] + ph.radius[i]);
    yh = std::max(yh, ph.py[i] + ph.radius[i]);
  }
  (void)my;
  ph.totalMass = mt;
  ph.width = xh - xl;
  ph.height = yh;
  ph.finArea = 0.0f;
  for (int s = 0; s < ph.numSegs; s++)
    ph.finArea += ph.seg[s].fin * ph.seg[s].len;
  return true;
}

// A random body plan from broad ranges (Section 9.4): no hand-picked designs.
inline BodyGenome RandomBody(Rng& r, int maxSegs)
{
  BodyGenome g;
  g.numNodes = static_cast<uint8_t>(r.IntRange(2, 5));
  for (int i = 0; i < g.numNodes; i++)
  {
    BodyNode& n = g.node[i];
    n.len = i == 0 ? r.Range(0.5f, 1.2f) : r.Range(0.25f, 0.9f);
    n.thick = i == 0 ? r.Range(0.1f, 0.2f) : r.Range(0.05f, 0.14f);
    n.density = r.Range(0.6f, 1.6f);
    n.fin = r.Chance(0.15f) ? r.Range(0.2f, 0.7f) : 0.0f;
  }
  g.numEdges = 0;
  // a spanning tree first so every node is used, then extra edges
  for (int i = 1; i < g.numNodes; i++)
  {
    BodyEdge& e = g.edge[g.numEdges++];
    e.from = static_cast<uint8_t>(r.Int(i));
    e.to = static_cast<uint8_t>(i);
  }
  const int extra = r.IntRange(0, 3);
  for (int k = 0; k < extra && g.numEdges < MAX_EDGES; k++)
  {
    BodyEdge& e = g.edge[g.numEdges++];
    e.from = static_cast<uint8_t>(r.Int(g.numNodes));
    e.to = static_cast<uint8_t>(1 + r.Int(g.numNodes - 1));
  }
  for (int i = 0; i < g.numEdges; i++)
  {
    BodyEdge& e = g.edge[i];
    e.atStart = r.Chance(0.35f);
    e.repeat = static_cast<uint8_t>(r.Chance(0.3f) ? r.IntRange(1, 3) : 0);
    e.mirror = r.Chance(0.4f);
    e.angle = r.Range(-kPi, kPi);
    e.curl = r.Range(-0.8f, 0.8f);
    e.range = r.Range(0.3f, 1.2f);
    e.strength = r.Range(0.1f, 0.5f);
    e.speed = r.Range(3.0f, 12.0f);
    e.taper = r.Range(0.7f, 1.0f);
  }
  Repair(g);
  (void)maxSegs;
  return g;
}

// Mutation flags recorded on a newborn for the family tree and the ticker.
enum MutationFlag : uint32_t
{
  MF_LIMB = 1,      // a limb was added
  MF_LOSE = 2,      // a part was removed
  MF_FIN = 4,       // a fin appeared
  MF_MIRROR = 8,    // symmetry changed
  MF_REPEAT = 16,   // a segment chain grew or shrank
  MF_NEURON = 32,   // a new hidden neuron
  MF_SYNAPSE = 64,  // a new connection
  MF_RESHAPE = 128, // body proportions changed
  MF_CROSS = 256,   // born of two parents
  MF_IMMIGRANT = 512,
};

inline uint32_t MutateBody(BodyGenome& g, Rng& r, float rate)
{
  uint32_t flags = 0;
  // parameter drift
  if (r.Chance(0.6f * std::min(rate, 1.5f)))
  {
    const int count = 1 + r.Int(3);
    for (int k = 0; k < count; k++)
    {
      if (r.Chance(0.4f))
      {
        BodyNode& n = g.node[r.Int(g.numNodes)];
        switch (r.Int(4))
        {
          case 0: n.len *= 1.0f + 0.15f * r.Gauss(); break;
          case 1: n.thick *= 1.0f + 0.15f * r.Gauss(); break;
          case 2: n.density *= 1.0f + 0.2f * r.Gauss(); break;
          default: if (n.fin > 0) n.fin *= 1.0f + 0.2f * r.Gauss(); break;
        }
        flags |= MF_RESHAPE;
      }
      else if (g.numEdges > 0)
      {
        BodyEdge& e = g.edge[r.Int(g.numEdges)];
        switch (r.Int(6))
        {
          case 0: e.angle += 0.3f * r.Gauss(); break;
          case 1: e.curl += 0.2f * r.Gauss(); break;
          case 2: e.range *= 1.0f + 0.2f * r.Gauss(); break;
          case 3: e.strength *= 1.0f + 0.2f * r.Gauss(); break;
          case 4: e.speed *= 1.0f + 0.2f * r.Gauss(); break;
          default: e.taper += 0.05f * r.Gauss(); break;
        }
        flags |= MF_RESHAPE;
      }
    }
  }
  // structure
  if (r.Chance(0.12f * rate))
  {
    switch (r.Int(8))
    {
      case 0: // add a node and an edge to it
      case 1:
        if (g.numNodes < MAX_NODES && g.numEdges < MAX_EDGES)
        {
          BodyNode& n = g.node[g.numNodes];
          n.len = r.Range(0.25f, 0.8f);
          n.thick = r.Range(0.05f, 0.12f);
          n.density = r.Range(0.6f, 1.4f);
          n.fin = r.Chance(0.2f) ? r.Range(0.2f, 0.6f) : 0.0f;
          BodyEdge& e = g.edge[g.numEdges++];
          e = BodyEdge();
          e.from = static_cast<uint8_t>(r.Int(g.numNodes));
          e.to = g.numNodes++;
          e.atStart = r.Chance(0.35f);
          e.mirror = r.Chance(0.4f);
          e.angle = r.Range(-kPi, kPi);
          e.range = r.Range(0.3f, 1.1f);
          e.strength = r.Range(0.1f, 0.5f);
          e.speed = r.Range(3.0f, 12.0f);
          flags |= MF_LIMB | (n.fin > 0 ? MF_FIN : 0u);
        }
        break;
      case 2: // remove an edge
        if (g.numEdges > 1)
        {
          const int i = r.Int(g.numEdges);
          g.edge[i] = g.edge[--g.numEdges];
          flags |= MF_LOSE;
        }
        break;
      case 3: // duplicate an edge (same child, another parent: a copied subtree)
        if (g.numEdges > 0 && g.numEdges < MAX_EDGES)
        {
          BodyEdge e = g.edge[r.Int(g.numEdges)];
          e.from = static_cast<uint8_t>(r.Int(g.numNodes));
          e.angle += 0.5f * r.Gauss();
          g.edge[g.numEdges++] = e;
          flags |= MF_LIMB;
        }
        break;
      case 4: // repeat count
        if (g.numEdges > 0)
        {
          BodyEdge& e = g.edge[r.Int(g.numEdges)];
          e.repeat = static_cast<uint8_t>(std::max(0, std::min(3, e.repeat + (r.Chance(0.5f) ? 1 : -1))));
          flags |= MF_REPEAT;
        }
        break;
      case 5: // mirror
        if (g.numEdges > 0)
        {
          BodyEdge& e = g.edge[r.Int(g.numEdges)];
          e.mirror ^= 1;
          flags |= MF_MIRROR;
        }
        break;
      case 6: // fin on/off
      {
        BodyNode& n = g.node[r.Int(g.numNodes)];
        n.fin = n.fin > 0 ? 0.0f : r.Range(0.2f, 0.6f);
        if (n.fin > 0)
          flags |= MF_FIN;
        else
          flags |= MF_RESHAPE;
        break;
      }
      default: // reattach, or swap which end an edge hangs off
        if (g.numEdges > 0)
        {
          BodyEdge& e = g.edge[r.Int(g.numEdges)];
          if (r.Chance(0.5f))
            e.atStart ^= 1;
          else
            e.from = static_cast<uint8_t>(r.Int(g.numNodes));
          flags |= MF_RESHAPE;
        }
        break;
    }
  }
  Repair(g);
  return flags;
}

// Crossover: the fitter parent's structure, parameters blended where the two
// line up (same node / edge index and topology).
inline BodyGenome CrossBody(const BodyGenome& fit, const BodyGenome& other, Rng& r)
{
  BodyGenome g = fit;
  for (int i = 0; i < std::min(g.numNodes, other.numNodes); i++)
    if (r.Chance(0.5f))
    {
      const float t = r.Uni();
      BodyNode& a = g.node[i];
      const BodyNode& b = other.node[i];
      a.len += (b.len - a.len) * t;
      a.thick += (b.thick - a.thick) * t;
      a.density += (b.density - a.density) * t;
      if ((a.fin > 0) == (b.fin > 0))
        a.fin += (b.fin - a.fin) * t;
    }
  for (int i = 0; i < std::min(g.numEdges, other.numEdges); i++)
  {
    BodyEdge& a = g.edge[i];
    const BodyEdge& b = other.edge[i];
    if (a.from != b.from || a.to != b.to || !r.Chance(0.5f))
      continue;
    const float t = r.Uni();
    a.angle += WrapAngle(b.angle - a.angle) * t;
    a.curl += (b.curl - a.curl) * t;
    a.range += (b.range - a.range) * t;
    a.strength += (b.strength - a.strength) * t;
    a.speed += (b.speed - a.speed) * t;
  }
  Repair(g);
  return g;
}

// Descriptors for niching, the archive and the species map (Section 5.5).
struct BodyTraits
{
  int segs = 0, limbs = 0, fins = 0;
  float mass = 0, aspect = 1, finArea = 0, chain = 0;
};

inline BodyTraits Traits(const Phenotype& ph)
{
  BodyTraits t;
  t.segs = ph.numSegs;
  t.limbs = ph.limbs;
  for (int s = 0; s < ph.numSegs; s++)
    if (ph.seg[s].fin > 0)
      t.fins++;
  t.mass = ph.totalMass;
  t.aspect = ph.width / std::max(ph.height, 0.05f);
  t.finArea = ph.finArea;
  // the longest chain from the torso, in segments
  int depth[MAX_SEGS] = {};
  int best = 0;
  for (int s = 1; s < ph.numSegs; s++)
  {
    // every point mass but the torso's first end was made as some segment's b
    int parent = 0;
    for (int k = 0; k < s; k++)
      if (ph.seg[k].b == ph.seg[s].a)
        parent = k;
    depth[s] = depth[parent] + 1;
    best = std::max(best, depth[s]);
  }
  t.chain = static_cast<float>(best);
  return t;
}

inline float BodyDistance(const BodyTraits& a, const BodyTraits& b)
{
  return std::fabs(static_cast<float>(a.segs - b.segs)) * 0.25f + std::fabs(static_cast<float>(a.limbs - b.limbs)) * 0.3f +
         std::fabs(static_cast<float>(a.fins - b.fins)) * 0.3f + std::fabs(std::log(a.aspect / b.aspect)) * 0.4f;
}

} // namespace evo
