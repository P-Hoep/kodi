// The neural controller (Section 6 of EvolveLife.md): a small NEAT
// implementation (Stanley and Miikkulainen 2002). Genomes are lists of node
// and connection genes tagged with innovation numbers so they can be lined up
// for crossover and compared for speciation; new nodes split connections,
// recurrent links are allowed. The brain interface is fixed-size with masking
// (J_MAX joint slots, C_MAX contact slots), so brains stay inheritable when
// bodies change.
//
// The spec names MultiNEAT; it would bring Boost and an LGPL licence into a
// Kodi add-on that has to run on 32-bit TV sticks, so this is an in-house
// NEAT behind the same ideas (the risk table in Section 19 allows for it).
#pragma once

#include "Body.h"
#include "Common.h"

#include <unordered_map>
#include <vector>

namespace evo
{

// inputs
enum
{
  IN_ANGLE = 0,                // J_MAX joint angles (relative to the rest angle, / range)
  IN_CONTACT = IN_ANGLE + J_MAX, // C_MAX foot contacts (+1 / -1)
  IN_SIN = IN_CONTACT + C_MAX, // torso orientation
  IN_COS,
  IN_SPIN,                     // torso angular velocity
  IN_VX,                       // centre of mass velocity
  IN_VY,
  IN_TX,                       // unit vector to the target (or the direction of travel)
  IN_TY,
  IN_TDIST,                    // distance to the target, squashed
  IN_CLK1S,                    // two fixed clocks (0.9 Hz and 1.9 Hz)
  IN_CLK1C,
  IN_CLK2S,
  IN_CLK2C,
  IN_ENERGY,
  IN_BIAS,
  N_IN
};
constexpr int N_OUT = J_MAX;      // one target angle per joint slot
constexpr int OUT0 = N_IN;        // first output node id
constexpr int HID0 = N_IN + N_OUT;// first hidden node id
constexpr int MAX_HIDDEN = 24;
constexpr int MAX_CONNS = 160;

struct NodeGene
{
  int id;
  float depth;
  float bias;
};

struct ConnGene
{
  int innov;
  int16_t in, out;
  float w;
  uint8_t on;
};

struct BrainGenome
{
  std::vector<NodeGene> hidden;   // sorted by id
  std::vector<ConnGene> conns;    // sorted by innovation
  float outBias[N_OUT] = {};

  int Enabled() const
  {
    int n = 0;
    for (const ConnGene& c : conns)
      n += c.on;
    return n;
  }
};

// The session's innovation record: the same structural change gets the same
// number in every genome. Bounded: cleared (losing only alignment between
// very old and new genes) if it ever grows large.
class Innovations
{
public:
  void Reset()
  {
    m_conn.clear();
    m_split.clear();
    m_depth.clear();
    m_nextInnov = 0;
    m_nextNode = HID0;
  }

  int Conn(int in, int out)
  {
    const uint32_t key = (static_cast<uint32_t>(in) << 16) | static_cast<uint32_t>(out);
    auto it = m_conn.find(key);
    if (it != m_conn.end())
      return it->second;
    if (m_conn.size() > 40000)
      m_conn.clear();
    m_conn[key] = m_nextInnov;
    return m_nextInnov++;
  }

  // the node that splitting connection `innov` makes
  int Split(int innov, float depth)
  {
    auto it = m_split.find(innov);
    if (it != m_split.end())
      return it->second;
    if (m_split.size() > 20000)
      m_split.clear();
    const int id = m_nextNode++;
    if (m_nextNode > 30000) // node ids are int16 in the genes
      m_nextNode = HID0 + 1000;
    m_split[innov] = id;
    m_depth[id] = depth;
    return id;
  }

  int nextInnov() const { return m_nextInnov; }

private:
  std::unordered_map<uint32_t, int> m_conn;
  std::unordered_map<int, int> m_split;
  std::unordered_map<int, float> m_depth;
  int m_nextInnov = 0;
  int m_nextNode = HID0;
};

inline float NodeDepth(const BrainGenome& g, int id)
{
  if (id < OUT0)
    return 0.0f;
  if (id < HID0)
    return 1.0f;
  for (const NodeGene& n : g.hidden)
    if (n.id == id)
      return n.depth;
  return 0.5f;
}

inline bool HasNode(const BrainGenome& g, int id)
{
  if (id < HID0)
    return true;
  for (const NodeGene& n : g.hidden)
    if (n.id == id)
      return true;
  return false;
}

inline void SortGenes(BrainGenome& g)
{
  std::sort(g.conns.begin(), g.conns.end(), [](const ConnGene& a, const ConnGene& b) { return a.innov < b.innov; });
  std::sort(g.hidden.begin(), g.hidden.end(), [](const NodeGene& a, const NodeGene& b) { return a.id < b.id; });
}

inline void AddConn(BrainGenome& g, Innovations& inn, int in, int out, float w)
{
  for (ConnGene& c : g.conns)
    if (c.in == in && c.out == out)
    {
      c.on = 1;
      return;
    }
  ConnGene c;
  c.innov = inn.Conn(in, out);
  c.in = static_cast<int16_t>(in);
  c.out = static_cast<int16_t>(out);
  c.w = w;
  c.on = 1;
  g.conns.push_back(c);
}

// Minimal start (Section 6.3): every output gets one or two links, mostly
// from the clocks, its own joint angle or the bias, so generation 0 already
// moves rhythmically without any gait being written.
inline BrainGenome RandomBrain(Rng& r, Innovations& inn)
{
  BrainGenome g;
  for (int o = 0; o < N_OUT; o++)
  {
    g.outBias[o] = 0.3f * r.Gauss();
    const int links = 1 + r.Int(2);
    for (int k = 0; k < links; k++)
    {
      int in;
      const float p = r.Uni();
      if (p < 0.6f)
        in = IN_CLK1S + r.Int(4);
      else if (p < 0.75f)
        in = IN_ANGLE + o;
      else if (p < 0.85f)
        in = IN_CONTACT + r.Int(C_MAX);
      else
        in = IN_SIN + r.Int(IN_BIAS - IN_SIN + 1);
      AddConn(g, inn, in, OUT0 + o, 1.5f * r.Gauss());
    }
  }
  SortGenes(g);
  return g;
}

inline uint32_t MutateBrain(BrainGenome& g, Innovations& inn, Rng& r, float rate)
{
  uint32_t flags = 0;
  // weights and biases
  if (r.Chance(0.8f))
  {
    const float p = std::min(0.25f * rate, 0.9f);
    for (ConnGene& c : g.conns)
      if (r.Chance(p))
        c.w = r.Chance(0.1f) ? 1.5f * r.Gauss() : Clamp(c.w + 0.35f * r.Gauss(), -4.0f, 4.0f);
    for (float& b : g.outBias)
      if (r.Chance(p * 0.5f))
        b = Clamp(b + 0.2f * r.Gauss(), -2.0f, 2.0f);
    for (NodeGene& n : g.hidden)
      if (r.Chance(p * 0.5f))
        n.bias = Clamp(n.bias + 0.2f * r.Gauss(), -2.0f, 2.0f);
  }
  // a new connection
  if (r.Chance(0.12f * rate) && static_cast<int>(g.conns.size()) < MAX_CONNS)
  {
    for (int tries = 0; tries < 8; tries++)
    {
      const int nh = static_cast<int>(g.hidden.size());
      // source: any input or hidden node (outputs only as rare recurrent links)
      int src;
      const int pick = r.Int(N_IN + nh + 2);
      if (pick < N_IN)
        src = pick;
      else if (pick < N_IN + nh)
        src = g.hidden[static_cast<size_t>(pick - N_IN)].id;
      else
        src = OUT0 + r.Int(N_OUT);
      int dst;
      if (nh > 0 && r.Chance(0.3f))
        dst = g.hidden[static_cast<size_t>(r.Int(nh))].id;
      else
        dst = OUT0 + r.Int(N_OUT);
      if (src == dst && r.Chance(0.7f))
        continue;
      const bool recurrent = NodeDepth(g, src) >= NodeDepth(g, dst);
      if (recurrent && r.Chance(0.6f))
        continue;
      AddConn(g, inn, src, dst, 1.0f * r.Gauss());
      flags |= MF_SYNAPSE;
      break;
    }
  }
  // a new node, splitting an enabled connection
  if (r.Chance(0.04f * rate) && static_cast<int>(g.hidden.size()) < MAX_HIDDEN &&
      static_cast<int>(g.conns.size()) + 2 <= MAX_CONNS && !g.conns.empty())
  {
    for (int tries = 0; tries < 6; tries++)
    {
      ConnGene& c = g.conns[static_cast<size_t>(r.Int(static_cast<int>(g.conns.size())))];
      if (!c.on)
        continue;
      const float d0 = NodeDepth(g, c.in), d1 = NodeDepth(g, c.out);
      if (d0 >= d1) // do not split recurrent links
        continue;
      const int id = inn.Split(c.innov, 0.5f * (d0 + d1));
      if (HasNode(g, id))
        continue;
      c.on = 0;
      const int in = c.in, out = c.out;
      const float w = c.w;
      g.hidden.push_back({id, 0.5f * (d0 + d1), 0.0f});
      AddConn(g, inn, in, id, 1.0f);
      AddConn(g, inn, id, out, w);
      flags |= MF_NEURON;
      break;
    }
  }
  // toggle
  if (r.Chance(0.02f * rate) && !g.conns.empty())
  {
    ConnGene& c = g.conns[static_cast<size_t>(r.Int(static_cast<int>(g.conns.size())))];
    c.on ^= 1;
  }
  SortGenes(g);
  return flags;
}

// NEAT crossover: matching genes from either parent, disjoint and excess genes
// from the fitter one (so its node set is complete).
inline BrainGenome CrossBrain(const BrainGenome& fit, const BrainGenome& other, Rng& r)
{
  BrainGenome g;
  g.hidden = fit.hidden;
  for (int o = 0; o < N_OUT; o++)
    g.outBias[o] = r.Chance(0.5f) ? fit.outBias[o] : other.outBias[o];
  g.conns.reserve(fit.conns.size());
  size_t j = 0;
  for (const ConnGene& a : fit.conns)
  {
    while (j < other.conns.size() && other.conns[j].innov < a.innov)
      j++;
    ConnGene c = a;
    if (j < other.conns.size() && other.conns[j].innov == a.innov)
    {
      const ConnGene& b = other.conns[j];
      if (r.Chance(0.5f))
        c.w = b.w;
      if ((!a.on || !b.on) && r.Chance(0.75f))
        c.on = 0;
    }
    g.conns.push_back(c);
  }
  return g;
}

// NEAT compatibility distance (excess + disjoint, mean weight difference).
inline float BrainDistance(const BrainGenome& a, const BrainGenome& b)
{
  size_t i = 0, j = 0;
  int unmatched = 0, matched = 0;
  float wdiff = 0.0f;
  while (i < a.conns.size() && j < b.conns.size())
  {
    if (a.conns[i].innov == b.conns[j].innov)
    {
      wdiff += std::fabs(a.conns[i].w - b.conns[j].w);
      matched++;
      i++;
      j++;
    }
    else if (a.conns[i].innov < b.conns[j].innov)
    {
      unmatched++;
      i++;
    }
    else
    {
      unmatched++;
      j++;
    }
  }
  unmatched += static_cast<int>(a.conns.size() - i + b.conns.size() - j);
  const float n = static_cast<float>(std::max<size_t>(std::max(a.conns.size(), b.conns.size()), 20));
  return static_cast<float>(unmatched) / n * 2.0f + (matched ? 0.4f * wdiff / static_cast<float>(matched) : 0.0f);
}

// The phenotype: nodes in evaluation order (by depth), each with its incoming
// links. One value array, updated in order, so a link from a shallower node
// carries this tick's value and a recurrent link last tick's.
struct Net
{
  struct Link
  {
    int16_t src;
    float w;
  };
  int numNodes = 0;
  std::vector<float> val;        // by local index: inputs, outputs, hidden
  std::vector<float> bias;
  std::vector<int16_t> order;    // non-input local indices, by depth
  std::vector<int> first;        // order position -> first link (size order+1)
  std::vector<Link> links;
  std::vector<int> ids;          // local index -> genome node id (for the neural view)
  std::vector<float> depth;      // local index -> depth

  void Build(const BrainGenome& g)
  {
    const int nh = static_cast<int>(g.hidden.size());
    numNodes = HID0 + nh;
    val.assign(static_cast<size_t>(numNodes), 0.0f);
    bias.assign(static_cast<size_t>(numNodes), 0.0f);
    ids.resize(static_cast<size_t>(numNodes));
    depth.resize(static_cast<size_t>(numNodes));
    for (int i = 0; i < HID0; i++)
    {
      ids[static_cast<size_t>(i)] = i;
      depth[static_cast<size_t>(i)] = i < OUT0 ? 0.0f : 1.0f;
    }
    for (int o = 0; o < N_OUT; o++)
      bias[static_cast<size_t>(OUT0 + o)] = g.outBias[o];
    for (int k = 0; k < nh; k++)
    {
      ids[static_cast<size_t>(HID0 + k)] = g.hidden[static_cast<size_t>(k)].id;
      depth[static_cast<size_t>(HID0 + k)] = g.hidden[static_cast<size_t>(k)].depth;
      bias[static_cast<size_t>(HID0 + k)] = g.hidden[static_cast<size_t>(k)].bias;
    }
    auto local = [&](int id) -> int {
      if (id < HID0)
        return id;
      // hidden is sorted by id
      int lo = 0, hi = nh - 1;
      while (lo <= hi)
      {
        const int mid = (lo + hi) / 2;
        const int v = g.hidden[static_cast<size_t>(mid)].id;
        if (v == id)
          return HID0 + mid;
        if (v < id)
          lo = mid + 1;
        else
          hi = mid - 1;
      }
      return -1;
    };
    order.clear();
    for (int i = OUT0; i < numNodes; i++)
      order.push_back(static_cast<int16_t>(i));
    std::stable_sort(order.begin(), order.end(),
                     [&](int16_t a, int16_t b) { return depth[static_cast<size_t>(a)] < depth[static_cast<size_t>(b)]; });
    std::vector<int> pos(static_cast<size_t>(numNodes), -1);
    for (size_t k = 0; k < order.size(); k++)
      pos[static_cast<size_t>(order[k])] = static_cast<int>(k);
    // counting sort of the enabled links by their target's position
    first.assign(order.size() + 1, 0);
    for (const ConnGene& c : g.conns)
    {
      if (!c.on)
        continue;
      const int s = local(c.in), t = local(c.out);
      if (s < 0 || t < OUT0)
        continue;
      first[static_cast<size_t>(pos[static_cast<size_t>(t)]) + 1]++;
    }
    for (size_t k = 1; k < first.size(); k++)
      first[k] += first[k - 1];
    links.resize(static_cast<size_t>(first.back()));
    std::vector<int> fill(first.begin(), first.end() - 1);
    for (const ConnGene& c : g.conns)
    {
      if (!c.on)
        continue;
      const int s = local(c.in), t = local(c.out);
      if (s < 0 || t < OUT0)
        continue;
      links[static_cast<size_t>(fill[static_cast<size_t>(pos[static_cast<size_t>(t)])]++)] = {static_cast<int16_t>(s), c.w};
    }
  }

  void Reset() { std::fill(val.begin(), val.end(), 0.0f); }

  // inputs must be in val[0 .. N_IN) already
  void Activate()
  {
    float* v = val.data();
    const Link* L = links.data();
    const int n = static_cast<int>(order.size());
    for (int k = 0; k < n; k++)
    {
      const int node = order[static_cast<size_t>(k)];
      float sum = bias[static_cast<size_t>(node)];
      for (int l = first[static_cast<size_t>(k)]; l < first[static_cast<size_t>(k) + 1]; l++)
        sum += L[l].w * v[L[l].src];
      v[node] = FastTanh(sum);
    }
  }
};

} // namespace evo
