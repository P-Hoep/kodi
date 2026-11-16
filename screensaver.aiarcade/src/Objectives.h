// "Progress" discovered from RAM with no supervision (spec 4.3): RAM bytes and
// 16-bit pairs that react to input and rise with archive depth, combined into
// a normalised Value in 0..1.
#pragma once

#include "Archive.h"

#include <memory>
#include <string>
#include <vector>

namespace arcade
{

struct Objective
{
  int lo = 0, hi = -1; // address of the value's low byte; hi >= 0 for a 16-bit pair
  double rho = 0, weight = 0;
  std::vector<uint16_t> sorted; // the archive's values, sorted, for percentile ranks

  uint32_t Raw(const uint8_t* ram) const
  {
    return hi < 0 ? ram[lo] : static_cast<uint32_t>(ram[lo]) | (static_cast<uint32_t>(ram[hi]) << 8);
  }
  // fraction of archive values below this state's value
  double Percentile(const uint8_t* ram) const
  {
    if (sorted.empty())
      return 0;
    const uint32_t v = Raw(ram);
    const size_t below = static_cast<size_t>(std::lower_bound(sorted.begin(), sorted.end(), v) - sorted.begin());
    return static_cast<double>(below) / static_cast<double>(sorted.size());
  }
  std::string Name() const; // "$0086" or "$0086+$006D<<8"
};

struct Objectives
{
  std::vector<Objective> list; // at most 8, by rho
  int version = 0;             // bumps on every change; the champion belongs to one version

  bool empty() const { return list.empty(); }
  double Value(const uint8_t* ram) const
  {
    double v = 0;
    for (const Objective& o : list)
      v += o.weight * o.Percentile(ram);
    return v;
  }
  double topRho() const { return list.empty() ? 0.0 : list[0].rho; }
  // the RAM addresses the networks read (up to 16)
  std::vector<int> InputBytes() const;
  std::string Describe() const;
};

// Fraction of the 2048 RAM bytes equal to start_ram (death detection, spec 4.3).
inline double RamSimilarity(const uint8_t* ram, const uint8_t* startRam)
{
  int same = 0;
  for (int i = 0; i < kRamSize; i++)
    same += ram[i] == startRam[i];
  return static_cast<double>(same) / kRamSize;
}

struct LearnStats
{
  int constantDropped = 0, clockDropped = 0, candidates = 0, passed = 0;
};

// Steps 1 to 5 of spec 4.3. Uses `emu` (already loaded with the ROM) for the
// counterfactual test. Returns an empty set when no candidate passes.
Objectives LearnObjectives(Emu& emu, const Archive& archive, Rng& rng, LearnStats* stats = nullptr,
                           const std::atomic<bool>* stop = nullptr);

// Re-fit an existing set to the current archive: fresh percentile tables and
// rho, same addresses. Used to compare the old set with a new one (spec 4.5).
void RefitObjectives(Objectives& obj, const Archive& archive);

} // namespace arcade
