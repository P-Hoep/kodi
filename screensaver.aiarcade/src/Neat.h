// NEAT (spec 4.4): feed-forward genomes over a fixed interface, speciation
// with an adaptive threshold, fitness sharing, stagnation, elitism, and a
// global innovation table reused within a generation.
#pragma once

#include "Common.h"
#include "Store.h"

#include <map>
#include <memory>
#include <string>
#include <vector>

namespace arcade
{

// Interface: 240 screen cells, 16 objective bytes, the 8 previous outputs, bias.
constexpr int kInObj = kNetGrid;            // 240
constexpr int kInPrev = kInObj + 16;        // 256
constexpr int kInBias = kInPrev + 8;        // 264
constexpr int kInputs = kInBias + 1;        // 265
constexpr int kOutputs = 8;                 // A B Select Start Up Down Left Right
constexpr int kFirstHidden = kInputs + kOutputs;

struct ConnGene
{
  int in, out;
  float w;
  bool enabled;
  int innov;
};

struct Genome
{
  std::vector<ConnGene> conns; // sorted by innovation
  std::vector<int> hidden;     // hidden node ids
  double fitness = 0;
  bool evaluated = false;

  int maxInnov() const { return conns.empty() ? -1 : conns.back().innov; }
};

void WriteGenome(BinWriter& w, const Genome& g);
bool ReadGenome(BinReader& r, Genome& g);

// A genome compiled for evaluation: nodes in topological order.
class Network
{
public:
  void Build(const Genome& g);
  // inputs: kInputs values; returns the 8 buttons as a pad byte, and the raw
  // outputs (0..1) for the next step's "previous action" inputs
  uint8_t Activate(const float* inputs, float* outs);
  int nodes() const { return static_cast<int>(m_order.size()); }

private:
  struct Link
  {
    int src; // index into m_value
    float w;
  };
  std::vector<int> m_order;          // node slots to compute, in order (hidden then outputs)
  std::vector<int> m_firstLink;      // per computed node: range into m_links
  std::vector<Link> m_links;
  std::vector<float> m_value;        // inputs, outputs, hidden
  std::map<int, int> m_slot;         // node id -> value index (hidden)
};

struct Species
{
  int id = 0;
  Genome rep;
  std::vector<int> members; // indices into the population
  double best = 0;          // best raw fitness ever
  int lastImproved = 0;     // generation
  int created = 0;
};

class Neat
{
public:
  void Init(int population, Rng& rng);
  bool initialised() const { return !m_pop.empty(); }

  std::vector<Genome>& population() { return m_pop; }
  const std::vector<Genome>& population() const { return m_pop; }
  int generation() const { return m_generation; }
  int speciesCount() const { return static_cast<int>(m_species.size()); }
  double threshold() const { return m_threshold; }

  // After every genome has a fitness: speciate, then breed the next generation.
  void Epoch(Rng& rng);
  // Speciate only (for the HUD's species count on a fresh population).
  void Speciate();

  void Save(BinWriter& w) const;
  bool Load(BinReader& r);

  void SetPopulationSize(int n) { m_size = n; }
  int populationSize() const { return m_size; }

  // compatibility distance (c1 = c2 = 1.0, c3 = 0.4)
  static double Distance(const Genome& a, const Genome& b);

private:
  Genome NewGenome(Rng& rng);
  Genome Crossover(const Genome& fit, const Genome& other, Rng& rng);
  void Mutate(Genome& g, Rng& rng);
  void MutateAddConn(Genome& g, Rng& rng);
  void MutateAddNode(Genome& g, Rng& rng);
  int Innovation(int in, int out);
  static bool Reaches(const Genome& g, int from, int to); // a path from -> to over enabled+disabled links

  std::vector<Genome> m_pop;
  std::vector<Species> m_species;
  int m_size = 100;
  int m_generation = 0;
  int m_nextInnov = 0;
  int m_nextNode = kFirstHidden;
  int m_nextSpecies = 1;
  double m_threshold = 3.0;
  // per-generation reuse of innovations: (in, out) -> innov; split conn innov -> new node id
  std::map<std::pair<int, int>, int> m_genInnov;
  std::map<int, int> m_genSplit;
};

} // namespace arcade
