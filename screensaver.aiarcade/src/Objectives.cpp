#include "Objectives.h"

#include "Store.h"

#include <cstdio>
#include <numeric>

namespace arcade
{

std::string Objective::Name() const
{
  char buf[48];
  if (hi < 0)
    std::snprintf(buf, sizeof buf, "$%04X", lo);
  else
    std::snprintf(buf, sizeof buf, "$%04X:$%04X", hi, lo); // high byte : low byte
  return buf;
}

std::vector<int> Objectives::InputBytes() const
{
  std::vector<int> out;
  auto add = [&](int a) {
    if (a >= 0 && out.size() < 16 && std::find(out.begin(), out.end(), a) == out.end())
      out.push_back(a);
  };
  for (const Objective& o : list)
  {
    add(o.lo);
    add(o.hi);
  }
  return out;
}

std::string Objectives::Describe() const
{
  if (list.empty())
    return "none (novelty only)";
  std::string s;
  char buf[96];
  for (const Objective& o : list)
  {
    std::snprintf(buf, sizeof buf, "%s%s rho %.2f w %.2f", s.empty() ? "" : ", ", o.Name().c_str(), o.rho, o.weight);
    s += buf;
  }
  return s;
}

namespace
{

// average ranks (ties share the mean rank)
void Ranks(const std::vector<double>& v, std::vector<double>& r)
{
  const size_t n = v.size();
  std::vector<int> idx(n);
  std::iota(idx.begin(), idx.end(), 0);
  std::sort(idx.begin(), idx.end(), [&](int a, int b) { return v[static_cast<size_t>(a)] < v[static_cast<size_t>(b)]; });
  r.assign(n, 0.0);
  for (size_t i = 0; i < n;)
  {
    size_t j = i;
    while (j + 1 < n && v[static_cast<size_t>(idx[j + 1])] == v[static_cast<size_t>(idx[i])])
      j++;
    const double rank = 0.5 * static_cast<double>(i + j);
    for (size_t k = i; k <= j; k++)
      r[static_cast<size_t>(idx[k])] = rank;
    i = j + 1;
  }
}

double Pearson(const std::vector<double>& a, const std::vector<double>& b)
{
  const size_t n = a.size();
  if (n < 2)
    return 0;
  double ma = 0, mb = 0;
  for (size_t i = 0; i < n; i++)
  {
    ma += a[i];
    mb += b[i];
  }
  ma /= static_cast<double>(n);
  mb /= static_cast<double>(n);
  double sab = 0, saa = 0, sbb = 0;
  for (size_t i = 0; i < n; i++)
  {
    const double da = a[i] - ma, db = b[i] - mb;
    sab += da * db;
    saa += da * da;
    sbb += db * db;
  }
  if (saa <= 0 || sbb <= 0)
    return 0;
  return sab / std::sqrt(saa * sbb);
}

struct Candidate
{
  int lo, hi;
  double rho = 0;
  std::vector<double> ranks;
};

void FillValues(Objective& o, const Archive& archive)
{
  o.sorted.resize(static_cast<size_t>(archive.size()));
  for (int i = 0; i < archive.size(); i++)
    o.sorted[static_cast<size_t>(i)] = static_cast<uint16_t>(o.Raw(archive.at(i).ram.data()));
  std::sort(o.sorted.begin(), o.sorted.end());
}

void RunRandom(Emu& emu, Rng& rng, int frames)
{
  uint8_t b = 0;
  int left = 0;
  for (int f = 0; f < frames; f++)
  {
    if (left-- <= 0)
    {
      b = RandomMotifButtons(rng);
      left = rng.Range(2, 10);
    }
    emu.Frame(b);
  }
}

} // namespace

Objectives LearnObjectives(Emu& emu, const Archive& archive, Rng& rng, LearnStats* stats, const std::atomic<bool>* stop)
{
  auto stopped = [&] { return stop && stop->load(std::memory_order_relaxed); };
  Objectives out;
  const int n = archive.size();
  if (n < 20)
    return out;

  // Step 1: drop bytes with fewer than 8 distinct values
  std::vector<bool> varied(kRamSize, false);
  for (int a = 0; a < kRamSize; a++)
  {
    bool seen[256] = {false};
    int distinct = 0;
    for (int i = 0; i < n && distinct < 8; i++)
    {
      const uint8_t v = archive.at(i).ram[static_cast<size_t>(a)];
      if (!seen[v])
      {
        seen[v] = true;
        distinct++;
      }
    }
    varied[static_cast<size_t>(a)] = distinct >= 8;
  }

  // Step 2: the counterfactual test. 50 states, 30 frames twice with different
  // random input; a byte is input-dependent if the end values differ in >= 5%.
  const int tests = 50;
  std::vector<int> differ(kRamSize, 0);
  std::string raw, ztmp;
  std::array<uint8_t, kRamSize> end1{};
  for (int t = 0; t < tests; t++)
  {
    if (stopped())
      return out;
    const Cell& c = archive.at(rng.Int(n));
    if (!c.zstate || !Decompress(*c.zstate, raw) || !emu.Restore(raw))
      continue;
    RunRandom(emu, rng, 30);
    std::copy(emu.Ram(), emu.Ram() + kRamSize, end1.begin());
    emu.Restore(raw);
    RunRandom(emu, rng, 30);
    const uint8_t* end2 = emu.Ram();
    for (int a = 0; a < kRamSize; a++)
      differ[static_cast<size_t>(a)] += end1[static_cast<size_t>(a)] != end2[a];
  }
  const int need = static_cast<int>(std::ceil(0.05 * tests));
  std::vector<bool> dependent(kRamSize, false);
  int kept = 0;
  LearnStats st;
  for (int a = 0; a < kRamSize; a++)
  {
    if (!varied[static_cast<size_t>(a)])
    {
      st.constantDropped++;
      // a byte can still join a 16-bit pair through an input-dependent partner
      dependent[static_cast<size_t>(a)] = differ[static_cast<size_t>(a)] >= need;
      continue;
    }
    dependent[static_cast<size_t>(a)] = differ[static_cast<size_t>(a)] >= need;
    if (!dependent[static_cast<size_t>(a)])
      st.clockDropped++;
    else
      kept++;
  }

  // Step 3: candidates. Kept bytes, and 16-bit pairs (a, a+1) in both byte
  // orders when at least one byte is input-dependent and the pair varies.
  std::vector<Candidate> cands;
  for (int a = 0; a < kRamSize; a++)
    if (varied[static_cast<size_t>(a)] && dependent[static_cast<size_t>(a)])
      cands.push_back({a, -1, 0, {}});
  for (int a = 0; a + 1 < kRamSize; a++)
  {
    const bool da = dependent[static_cast<size_t>(a)] && varied[static_cast<size_t>(a)];
    const bool db = dependent[static_cast<size_t>(a + 1)] && varied[static_cast<size_t>(a + 1)];
    if (!da && !db)
      continue;
    cands.push_back({a, a + 1, 0, {}}); // little-endian: a is the low byte
    cands.push_back({a + 1, a, 0, {}}); // big-endian
  }
  st.candidates = static_cast<int>(cands.size());

  // Step 4: Spearman rank correlation with depth; keep rho >= 0.30
  std::vector<double> depth(static_cast<size_t>(n)), depthRanks;
  for (int i = 0; i < n; i++)
    depth[static_cast<size_t>(i)] = archive.at(i).depth;
  Ranks(depth, depthRanks);
  std::vector<double> vals(static_cast<size_t>(n));
  std::vector<Candidate> pass;
  for (Candidate& c : cands)
  {
    if (stopped())
      return Objectives();
    Objective probe;
    probe.lo = c.lo;
    probe.hi = c.hi;
    double first = -1;
    bool constant = true;
    for (int i = 0; i < n; i++)
    {
      vals[static_cast<size_t>(i)] = probe.Raw(archive.at(i).ram.data());
      if (i == 0)
        first = vals[0];
      else if (vals[static_cast<size_t>(i)] != first)
        constant = false;
    }
    if (constant)
      continue;
    Ranks(vals, c.ranks);
    c.rho = Pearson(c.ranks, depthRanks);
    if (c.rho >= 0.30)
      pass.push_back(std::move(c));
  }
  st.passed = static_cast<int>(pass.size());

  // Step 5: by rho, dropping near-duplicates (|correlation| > 0.98) of a higher one; top 8
  std::sort(pass.begin(), pass.end(), [](const Candidate& a, const Candidate& b) {
    if (a.rho != b.rho)
      return a.rho > b.rho;
    return (a.hi < 0) > (b.hi < 0); // a single byte before an equal pair
  });
  std::vector<const Candidate*> chosen;
  for (const Candidate& c : pass)
  {
    bool dup = false;
    for (const Candidate* k : chosen)
      if (std::fabs(Pearson(c.ranks, k->ranks)) > 0.98)
      {
        dup = true;
        break;
      }
    if (!dup)
      chosen.push_back(&c);
    if (chosen.size() >= 8)
      break;
  }
  double sum = 0;
  for (const Candidate* c : chosen)
    sum += c->rho;
  for (const Candidate* c : chosen)
  {
    Objective o;
    o.lo = c->lo;
    o.hi = c->hi;
    o.rho = c->rho;
    o.weight = c->rho / sum;
    FillValues(o, archive);
    out.list.push_back(std::move(o));
  }
  (void)kept;
  if (stats)
    *stats = st;
  return out;
}

void RefitObjectives(Objectives& obj, const Archive& archive)
{
  const int n = archive.size();
  if (n < 2)
    return;
  std::vector<double> depth(static_cast<size_t>(n)), depthRanks, vals(static_cast<size_t>(n)), ranks;
  for (int i = 0; i < n; i++)
    depth[static_cast<size_t>(i)] = archive.at(i).depth;
  Ranks(depth, depthRanks);
  double sum = 0;
  for (Objective& o : obj.list)
  {
    for (int i = 0; i < n; i++)
      vals[static_cast<size_t>(i)] = o.Raw(archive.at(i).ram.data());
    Ranks(vals, ranks);
    o.rho = std::max(0.0, Pearson(ranks, depthRanks));
    sum += o.rho;
    FillValues(o, archive);
  }
  for (Objective& o : obj.list)
    o.weight = sum > 0 ? o.rho / sum : 1.0 / static_cast<double>(obj.list.size());
  std::stable_sort(obj.list.begin(), obj.list.end(), [](const Objective& a, const Objective& b) { return a.rho > b.rho; });
}

} // namespace arcade
