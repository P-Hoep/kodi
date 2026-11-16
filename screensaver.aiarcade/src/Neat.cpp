#include "Neat.h"

#include <set>
#include <unordered_map>

namespace arcade
{

namespace
{
constexpr double kC1 = 1.0, kC2 = 1.0, kC3 = 0.4;
constexpr double kWeightMutate = 0.80, kPerturb = 0.90, kPerturbSigma = 0.2;
constexpr double kAddConn = 0.05, kAddNode = 0.03, kToggle = 0.01;
constexpr double kCrossover = 0.75, kInterspecies = 0.001, kKeepDisabled = 0.75;
constexpr double kSurvival = 0.20;
constexpr int kEliteMin = 5, kStagnation = 15, kKeepTopSpecies = 2;
constexpr int kTargetMin = 8, kTargetMax = 12;
constexpr float kWeightClamp = 8.0f;

inline float Sigmoid(float x) { return 1.0f / (1.0f + std::exp(-4.9f * x)); }
inline bool IsInput(int id) { return id < kInputs; }
inline bool IsOutput(int id) { return id >= kInputs && id < kFirstHidden; }
} // namespace

// ---- serialisation -------------------------------------------------------------

void WriteGenome(BinWriter& w, const Genome& g)
{
  w.U32(static_cast<uint32_t>(g.hidden.size()));
  for (int h : g.hidden)
    w.I32(h);
  w.U32(static_cast<uint32_t>(g.conns.size()));
  for (const ConnGene& c : g.conns)
  {
    w.I32(c.in);
    w.I32(c.out);
    w.F32(c.w);
    w.U8(c.enabled ? 1 : 0);
    w.I32(c.innov);
  }
  w.F64(g.fitness);
  w.U8(g.evaluated ? 1 : 0);
}

bool ReadGenome(BinReader& r, Genome& g)
{
  const uint32_t nh = r.U32();
  if (!r.ok || nh > 100000)
    return false;
  g.hidden.resize(nh);
  std::set<int> nodes;
  for (uint32_t i = 0; i < nh; i++)
  {
    g.hidden[i] = r.I32();
    if (g.hidden[i] < kFirstHidden)
      return false;
    nodes.insert(g.hidden[i]);
  }
  const uint32_t nc = r.U32();
  if (!r.ok || nc > 1000000)
    return false;
  g.conns.resize(nc);
  for (uint32_t i = 0; i < nc; i++)
  {
    ConnGene& c = g.conns[i];
    c.in = r.I32();
    c.out = r.I32();
    c.w = r.F32();
    c.enabled = r.U8() != 0;
    c.innov = r.I32();
    const bool inOk = c.in >= 0 && (c.in < kInputs || nodes.count(c.in));
    const bool outOk = IsOutput(c.out) || nodes.count(c.out);
    if (!inOk || !outOk || !std::isfinite(c.w))
      return false;
  }
  g.fitness = r.F64();
  g.evaluated = r.U8() != 0;
  return r.ok;
}

// ---- network --------------------------------------------------------------------

void Network::Build(const Genome& g)
{
  m_slot.clear();
  m_order.clear();
  m_links.clear();
  m_firstLink.clear();
  // value slots: inputs, outputs, then hidden
  int next = kFirstHidden;
  for (int h : g.hidden)
    m_slot[h] = next++;
  m_value.assign(static_cast<size_t>(next), 0.0f);
  auto slot = [&](int id) -> int {
    if (id < kFirstHidden)
      return id;
    auto it = m_slot.find(id);
    return it == m_slot.end() ? -1 : it->second;
  };

  // Kahn's algorithm over enabled links between computed nodes (hidden and
  // outputs). Links that close a cycle (crossover can create one) are dropped.
  const int n = next;
  std::vector<std::vector<std::pair<int, float>>> incoming(static_cast<size_t>(n));
  std::vector<std::vector<int>> outgoing(static_cast<size_t>(n));
  std::vector<int> indeg(static_cast<size_t>(n), 0);
  for (const ConnGene& c : g.conns)
  {
    if (!c.enabled)
      continue;
    const int s = slot(c.in), d = slot(c.out);
    if (s < 0 || d < 0 || d < kInputs)
      continue;
    incoming[static_cast<size_t>(d)].push_back({s, c.w});
    if (s >= kInputs)
    {
      outgoing[static_cast<size_t>(s)].push_back(d);
      indeg[static_cast<size_t>(d)]++;
    }
  }
  std::vector<int> queue;
  for (int v = kInputs; v < n; v++)
    if (indeg[static_cast<size_t>(v)] == 0)
      queue.push_back(v);
  std::vector<bool> done(static_cast<size_t>(n), false);
  for (int v = 0; v < kInputs; v++)
    done[static_cast<size_t>(v)] = true;
  for (size_t qi = 0; qi < queue.size(); qi++)
  {
    const int v = queue[qi];
    done[static_cast<size_t>(v)] = true;
    m_order.push_back(v);
    for (int d : outgoing[static_cast<size_t>(v)])
      if (--indeg[static_cast<size_t>(d)] == 0)
        queue.push_back(d);
  }
  // nodes stuck in a cycle: compute them last from what is ready
  for (int v = kInputs; v < n; v++)
    if (!done[static_cast<size_t>(v)])
      m_order.push_back(v);
  std::vector<bool> ready(static_cast<size_t>(n), false);
  for (int v = 0; v < kInputs; v++)
    ready[static_cast<size_t>(v)] = true;
  for (int v : m_order)
  {
    m_firstLink.push_back(static_cast<int>(m_links.size()));
    for (const auto& in : incoming[static_cast<size_t>(v)])
      if (ready[static_cast<size_t>(in.first)])
        m_links.push_back({in.first, in.second});
    ready[static_cast<size_t>(v)] = true;
  }
  m_firstLink.push_back(static_cast<int>(m_links.size()));
}

uint8_t Network::Activate(const float* inputs, float* outs)
{
  std::copy(inputs, inputs + kInputs, m_value.begin());
  for (size_t i = 0; i < m_order.size(); i++)
  {
    float sum = 0;
    for (int k = m_firstLink[i]; k < m_firstLink[i + 1]; k++)
      sum += m_links[static_cast<size_t>(k)].w * m_value[static_cast<size_t>(m_links[static_cast<size_t>(k)].src)];
    m_value[static_cast<size_t>(m_order[i])] = Sigmoid(sum);
  }
  uint8_t pad = 0;
  for (int o = 0; o < kOutputs; o++)
  {
    // an output with no links stays at sigmoid(0) = 0.5, which is "not pressed"
    const float v = m_value[static_cast<size_t>(kInputs + o)];
    outs[o] = v;
    if (v > 0.5f)
      pad |= static_cast<uint8_t>(1u << o);
  }
  return pad;
}

// ---- NEAT -------------------------------------------------------------------------

int Neat::Innovation(int in, int out)
{
  const auto key = std::make_pair(in, out);
  auto it = m_genInnov.find(key);
  if (it != m_genInnov.end())
    return it->second;
  const int innov = m_nextInnov++;
  m_genInnov[key] = innov;
  return innov;
}

Genome Neat::NewGenome(Rng& rng)
{
  // no hidden nodes; each output linked to a random 10% of the inputs, plus bias
  Genome g;
  for (int o = 0; o < kOutputs; o++)
  {
    const int out = kInputs + o;
    for (int i = 0; i < kInBias; i++)
      if (rng.Chance(0.10))
        g.conns.push_back({i, out, static_cast<float>(rng.Uniform(-1, 1)), true, Innovation(i, out)});
    g.conns.push_back({kInBias, out, static_cast<float>(rng.Uniform(-1, 1)), true, Innovation(kInBias, out)});
  }
  std::sort(g.conns.begin(), g.conns.end(), [](const ConnGene& a, const ConnGene& b) { return a.innov < b.innov; });
  return g;
}

void Neat::Init(int population, Rng& rng)
{
  m_size = population;
  m_pop.clear();
  m_species.clear();
  m_generation = 0;
  m_nextInnov = 0;
  m_nextNode = kFirstHidden;
  m_nextSpecies = 1;
  m_threshold = 3.0;
  m_genInnov.clear();
  m_genSplit.clear();
  for (int i = 0; i < population; i++)
    m_pop.push_back(NewGenome(rng));
  Speciate();
}

double Neat::Distance(const Genome& a, const Genome& b)
{
  size_t i = 0, j = 0;
  int disjoint = 0, matching = 0;
  double wdiff = 0;
  while (i < a.conns.size() && j < b.conns.size())
  {
    const int ia = a.conns[i].innov, ib = b.conns[j].innov;
    if (ia == ib)
    {
      wdiff += std::fabs(a.conns[i].w - b.conns[j].w);
      matching++;
      i++;
      j++;
    }
    else if (ia < ib)
    {
      disjoint++;
      i++;
    }
    else
    {
      disjoint++;
      j++;
    }
  }
  const int excess = static_cast<int>((a.conns.size() - i) + (b.conns.size() - j));
  size_t big = std::max(a.conns.size(), b.conns.size());
  const double n = big < 20 ? 1.0 : static_cast<double>(big);
  return kC1 * excess / n + kC2 * disjoint / n + kC3 * (matching ? wdiff / matching : 0.0);
}

void Neat::Speciate()
{
  for (Species& s : m_species)
    s.members.clear();
  for (size_t i = 0; i < m_pop.size(); i++)
  {
    bool placed = false;
    for (Species& s : m_species)
      if (Distance(m_pop[i], s.rep) < m_threshold)
      {
        s.members.push_back(static_cast<int>(i));
        placed = true;
        break;
      }
    if (!placed)
    {
      Species s;
      s.id = m_nextSpecies++;
      s.rep = m_pop[i];
      s.members.push_back(static_cast<int>(i));
      s.lastImproved = m_generation;
      s.created = m_generation;
      m_species.push_back(std::move(s));
    }
  }
  m_species.erase(std::remove_if(m_species.begin(), m_species.end(), [](const Species& s) { return s.members.empty(); }),
                  m_species.end());
}

bool Neat::Reaches(const Genome& g, int from, int to)
{
  if (from == to)
    return true;
  std::vector<int> stack{from};
  std::set<int> seen{from};
  while (!stack.empty())
  {
    const int v = stack.back();
    stack.pop_back();
    for (const ConnGene& c : g.conns)
      if (c.in == v && !seen.count(c.out))
      {
        if (c.out == to)
          return true;
        seen.insert(c.out);
        stack.push_back(c.out);
      }
  }
  return false;
}

void Neat::MutateAddConn(Genome& g, Rng& rng)
{
  // sources: inputs and hidden; targets: hidden and outputs; no cycles
  const int nh = static_cast<int>(g.hidden.size());
  for (int attempt = 0; attempt < 20; attempt++)
  {
    const int si = rng.Int(kInputs + nh);
    const int src = si < kInputs ? si : g.hidden[static_cast<size_t>(si - kInputs)];
    const int di = rng.Int(kOutputs + nh);
    const int dst = di < kOutputs ? kInputs + di : g.hidden[static_cast<size_t>(di - kOutputs)];
    if (src == dst)
      continue;
    bool exists = false;
    for (const ConnGene& c : g.conns)
      if (c.in == src && c.out == dst)
      {
        exists = true;
        break;
      }
    if (exists)
      continue;
    if (!IsInput(src) && Reaches(g, dst, src)) // would close a loop
      continue;
    ConnGene c{src, dst, static_cast<float>(rng.Uniform(-1, 1)), true, Innovation(src, dst)};
    auto pos = std::upper_bound(g.conns.begin(), g.conns.end(), c.innov,
                                [](int innov, const ConnGene& x) { return innov < x.innov; });
    g.conns.insert(pos, c);
    return;
  }
}

void Neat::MutateAddNode(Genome& g, Rng& rng)
{
  std::vector<int> enabled;
  for (size_t i = 0; i < g.conns.size(); i++)
    if (g.conns[i].enabled)
      enabled.push_back(static_cast<int>(i));
  if (enabled.empty())
    return;
  ConnGene& old = g.conns[static_cast<size_t>(enabled[static_cast<size_t>(rng.Int(static_cast<int>(enabled.size())))])];
  old.enabled = false;
  int node;
  auto it = m_genSplit.find(old.innov);
  if (it != m_genSplit.end() && std::find(g.hidden.begin(), g.hidden.end(), it->second) == g.hidden.end())
    node = it->second;
  else
  {
    node = m_nextNode++;
    m_genSplit[old.innov] = node;
  }
  const int in = old.in, out = old.out;
  const float w = old.w;
  g.hidden.push_back(node);
  // in-link weight 1.0, out-link weight old
  ConnGene a{in, node, 1.0f, true, Innovation(in, node)};
  ConnGene b{node, out, w, true, Innovation(node, out)};
  g.conns.push_back(a);
  g.conns.push_back(b);
  std::sort(g.conns.begin(), g.conns.end(), [](const ConnGene& x, const ConnGene& y) { return x.innov < y.innov; });
}

void Neat::Mutate(Genome& g, Rng& rng)
{
  if (rng.Chance(kWeightMutate))
    for (ConnGene& c : g.conns)
    {
      if (rng.Chance(kPerturb))
        c.w += static_cast<float>(rng.Normal() * kPerturbSigma);
      else
        c.w = static_cast<float>(rng.Uniform(-1, 1));
      c.w = std::max(-kWeightClamp, std::min(kWeightClamp, c.w));
    }
  if (rng.Chance(kAddConn))
    MutateAddConn(g, rng);
  if (rng.Chance(kAddNode))
    MutateAddNode(g, rng);
  if (rng.Chance(kToggle) && !g.conns.empty())
  {
    ConnGene& c = g.conns[static_cast<size_t>(rng.Int(static_cast<int>(g.conns.size())))];
    // re-enabling must not close a loop
    if (c.enabled || IsInput(c.in) || !Reaches(g, c.out, c.in))
      c.enabled = !c.enabled;
  }
  g.evaluated = false;
}

Genome Neat::Crossover(const Genome& fit, const Genome& other, Rng& rng)
{
  // matching genes from a random parent; disjoint and excess from the fitter one
  Genome child;
  std::unordered_map<int, const ConnGene*> o;
  o.reserve(other.conns.size() * 2);
  for (const ConnGene& c : other.conns)
    o[c.innov] = &c;
  std::set<int> hidden;
  for (const ConnGene& c : fit.conns)
  {
    ConnGene g = c;
    auto it = o.find(c.innov);
    if (it != o.end())
    {
      if (rng.Chance(0.5))
        g = *it->second;
      const bool disabled = !c.enabled || !it->second->enabled;
      g.enabled = disabled ? !rng.Chance(kKeepDisabled) : true;
    }
    child.conns.push_back(g);
    if (g.in >= kFirstHidden)
      hidden.insert(g.in);
    if (g.out >= kFirstHidden)
      hidden.insert(g.out);
  }
  for (int h : fit.hidden)
    hidden.insert(h);
  child.hidden.assign(hidden.begin(), hidden.end());
  return child;
}

void Neat::Epoch(Rng& rng)
{
  m_genInnov.clear();
  m_genSplit.clear();
  Speciate();

  // species bests and stagnation
  for (Species& s : m_species)
  {
    double best = 0;
    for (int m : s.members)
      best = std::max(best, m_pop[static_cast<size_t>(m)].fitness);
    if (best > s.best)
    {
      s.best = best;
      s.lastImproved = m_generation;
    }
  }
  {
    std::vector<int> order(m_species.size());
    for (size_t i = 0; i < order.size(); i++)
      order[i] = static_cast<int>(i);
    std::sort(order.begin(), order.end(), [&](int a, int b) {
      return m_species[static_cast<size_t>(a)].best > m_species[static_cast<size_t>(b)].best;
    });
    std::vector<bool> keep(m_species.size(), true);
    for (size_t r = 0; r < order.size(); r++)
    {
      const Species& s = m_species[static_cast<size_t>(order[r])];
      if (static_cast<int>(r) >= kKeepTopSpecies && m_generation - s.lastImproved >= kStagnation)
        keep[static_cast<size_t>(order[r])] = false;
    }
    std::vector<Species> alive;
    for (size_t i = 0; i < m_species.size(); i++)
      if (keep[i])
        alive.push_back(std::move(m_species[i]));
    m_species.swap(alive);
  }

  // offspring per species in proportion to its summed adjusted fitness
  // (fitness / species size), i.e. its mean fitness
  std::vector<double> share(m_species.size());
  double total = 0;
  for (size_t i = 0; i < m_species.size(); i++)
  {
    double sum = 0;
    for (int m : m_species[i].members)
      sum += std::max(0.0, m_pop[static_cast<size_t>(m)].fitness);
    share[i] = sum / static_cast<double>(m_species[i].members.size());
    total += share[i];
  }
  std::vector<int> counts(m_species.size(), 0);
  int assigned = 0;
  for (size_t i = 0; i < m_species.size(); i++)
  {
    const double f = total > 0 ? share[i] / total : 1.0 / static_cast<double>(m_species.size());
    counts[i] = static_cast<int>(std::floor(f * m_size));
    assigned += counts[i];
  }
  // hand out the remainder to the best shares
  {
    std::vector<int> order(m_species.size());
    for (size_t i = 0; i < order.size(); i++)
      order[i] = static_cast<int>(i);
    std::sort(order.begin(), order.end(), [&](int a, int b) { return share[static_cast<size_t>(a)] > share[static_cast<size_t>(b)]; });
    for (size_t k = 0; assigned < m_size && !order.empty(); k = (k + 1) % order.size())
    {
      counts[static_cast<size_t>(order[k])]++;
      assigned++;
    }
  }

  std::vector<Genome> next;
  next.reserve(static_cast<size_t>(m_size));
  for (size_t si = 0; si < m_species.size(); si++)
  {
    Species& s = m_species[si];
    std::vector<int> ranked = s.members;
    std::sort(ranked.begin(), ranked.end(), [&](int a, int b) {
      return m_pop[static_cast<size_t>(a)].fitness > m_pop[static_cast<size_t>(b)].fitness;
    });
    int n = counts[si];
    if (n <= 0)
      continue;
    // elitism: the best of every species with 5 or more members, unchanged
    if (static_cast<int>(ranked.size()) >= kEliteMin)
    {
      Genome elite = m_pop[static_cast<size_t>(ranked[0])];
      next.push_back(std::move(elite));
      n--;
    }
    const int parents = std::max(1, static_cast<int>(std::ceil(kSurvival * static_cast<double>(ranked.size()))));
    for (int k = 0; k < n; k++)
    {
      const Genome& p1 = m_pop[static_cast<size_t>(ranked[static_cast<size_t>(rng.Int(parents))])];
      Genome child;
      if (rng.Chance(kCrossover))
      {
        const Genome* p2;
        if (rng.Chance(kInterspecies) && m_species.size() > 1)
        {
          const Species& o = m_species[static_cast<size_t>(rng.Int(static_cast<int>(m_species.size())))];
          p2 = &m_pop[static_cast<size_t>(o.members[static_cast<size_t>(rng.Int(static_cast<int>(o.members.size())))])];
        }
        else
          p2 = &m_pop[static_cast<size_t>(ranked[static_cast<size_t>(rng.Int(parents))])];
        child = p1.fitness >= p2->fitness ? Crossover(p1, *p2, rng) : Crossover(*p2, p1, rng);
      }
      else
        child = p1;
      Mutate(child, rng);
      next.push_back(std::move(child));
    }
  }
  while (static_cast<int>(next.size()) < m_size) // all species gone: start fresh ones
    next.push_back(NewGenome(rng));
  next.resize(static_cast<size_t>(m_size));

  // new representatives: a random member of each species from this generation
  for (Species& s : m_species)
    s.rep = m_pop[static_cast<size_t>(s.members[static_cast<size_t>(rng.Int(static_cast<int>(s.members.size())))])];
  m_pop.swap(next);
  m_generation++;
  Speciate();

  // steer the threshold toward 8 to 12 species
  const int ns = static_cast<int>(m_species.size());
  if (ns < kTargetMin)
    m_threshold = std::max(0.3, m_threshold - 0.3);
  else if (ns > kTargetMax)
    m_threshold += 0.3;
}

void Neat::Save(BinWriter& w) const
{
  w.U32(static_cast<uint32_t>(m_size));
  w.I32(m_generation);
  w.I32(m_nextInnov);
  w.I32(m_nextNode);
  w.I32(m_nextSpecies);
  w.F64(m_threshold);
  w.U32(static_cast<uint32_t>(m_pop.size()));
  for (const Genome& g : m_pop)
    WriteGenome(w, g);
  w.U32(static_cast<uint32_t>(m_species.size()));
  for (const Species& s : m_species)
  {
    w.I32(s.id);
    w.F64(s.best);
    w.I32(s.lastImproved);
    w.I32(s.created);
    WriteGenome(w, s.rep);
  }
}

bool Neat::Load(BinReader& r)
{
  Neat n;
  n.m_size = static_cast<int>(r.U32());
  n.m_generation = r.I32();
  n.m_nextInnov = r.I32();
  n.m_nextNode = r.I32();
  n.m_nextSpecies = r.I32();
  n.m_threshold = r.F64();
  const uint32_t np = r.U32();
  if (!r.ok || np == 0 || np > 1000 || n.m_size < 1 || n.m_size > 1000 || n.m_nextNode < kFirstHidden ||
      !std::isfinite(n.m_threshold))
    return false;
  n.m_pop.resize(np);
  for (Genome& g : n.m_pop)
    if (!ReadGenome(r, g))
      return false;
  const uint32_t ns = r.U32();
  if (!r.ok || ns > 1000)
    return false;
  n.m_species.resize(ns);
  for (Species& s : n.m_species)
  {
    s.id = r.I32();
    s.best = r.F64();
    s.lastImproved = r.I32();
    s.created = r.I32();
    if (!ReadGenome(r, s.rep))
      return false;
  }
  if (!r.ok)
    return false;
  // node and innovation ids must stay ahead of everything loaded
  for (const Genome& g : n.m_pop)
  {
    for (int h : g.hidden)
      n.m_nextNode = std::max(n.m_nextNode, h + 1);
    n.m_nextInnov = std::max(n.m_nextInnov, g.maxInnov() + 1);
  }
  *this = std::move(n);
  Speciate();
  return true;
}

} // namespace arcade
