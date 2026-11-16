// The Go-Explore archive (spec 4.2): one entry per screen cell reached from
// start.state, each with a compressed savestate, the RAM at that moment, its
// depth in motifs and its visit count.
#pragma once

#include "Common.h"

#include <array>
#include <memory>
#include <string>
#include <unordered_map>
#include <unordered_set>
#include <vector>

namespace arcade
{

struct Cell
{
  uint64_t key = 0, parent = 0; // parent 0: the root
  std::shared_ptr<const std::string> zstate; // zlib savestate, shared with the display
  std::array<uint8_t, kRamSize> ram{};
  int depth = 0;
  uint32_t visits = 0;
  uint64_t added = 0; // archive iteration when it was added
};

class Archive
{
public:
  static constexpr int kCap = 1500;

  void Clear()
  {
    m_cells.clear();
    m_index.clear();
    m_iter = 0;
    m_deepest = -1;
  }
  int size() const { return static_cast<int>(m_cells.size()); }
  bool empty() const { return m_cells.empty(); }
  bool Has(uint64_t key) const { return m_index.count(key) != 0; }
  const Cell& at(int i) const { return m_cells[static_cast<size_t>(i)]; }
  Cell& at(int i) { return m_cells[static_cast<size_t>(i)]; }
  const std::vector<Cell>& cells() const { return m_cells; }
  uint64_t iteration() const { return m_iter; }
  void SetIteration(uint64_t it) { m_iter = it; }
  void NextIteration() { m_iter++; }

  int deepest() const { return m_deepest; }
  int maxDepth() const { return m_deepest >= 0 ? m_cells[static_cast<size_t>(m_deepest)].depth : 0; }

  // Add a new cell (ignored if the key exists). Evicts first when full.
  bool Add(Cell&& c)
  {
    if (c.key == 0 || Has(c.key))
      return false;
    if (size() >= kCap)
      Evict();
    c.added = m_iter;
    m_index[c.key] = size();
    m_cells.push_back(std::move(c));
    const int i = size() - 1;
    if (m_deepest < 0 || m_cells[static_cast<size_t>(i)].depth > m_cells[static_cast<size_t>(m_deepest)].depth)
      m_deepest = i;
    return true;
  }

  // weight 1 / sqrt(visits + 1), +1 when added in the last 100 iterations
  int Pick(Rng& rng) const
  {
    if (m_cells.empty())
      return -1;
    double total = 0;
    m_weights.resize(m_cells.size());
    for (size_t i = 0; i < m_cells.size(); i++)
    {
      const Cell& c = m_cells[i];
      double w = 1.0 / std::sqrt(static_cast<double>(c.visits) + 1.0);
      if (m_iter - c.added < 100)
        w += 1.0;
      m_weights[i] = w;
      total += w;
    }
    double r = rng.Uniform() * total;
    for (size_t i = 0; i < m_cells.size(); i++)
    {
      r -= m_weights[i];
      if (r <= 0)
        return static_cast<int>(i);
    }
    return size() - 1;
  }

  // Keys of every cell, for novelty checks off the archive's thread.
  std::shared_ptr<const std::unordered_set<uint64_t>> KeySet() const
  {
    auto s = std::make_shared<std::unordered_set<uint64_t>>();
    s->reserve(m_cells.size() * 2);
    for (const Cell& c : m_cells)
      s->insert(c.key);
    return s;
  }

  void Rebuild() // after loading: index and deepest
  {
    m_index.clear();
    m_deepest = -1;
    for (size_t i = 0; i < m_cells.size(); i++)
    {
      m_index[m_cells[i].key] = static_cast<int>(i);
      if (m_deepest < 0 || m_cells[i].depth > m_cells[static_cast<size_t>(m_deepest)].depth)
        m_deepest = static_cast<int>(i);
    }
  }
  std::vector<Cell>& mutableCells() { return m_cells; }

private:
  // the most visited entry that is not an ancestor of the deepest cell (nor the root)
  void Evict()
  {
    std::unordered_set<uint64_t> keep;
    if (m_deepest >= 0)
    {
      uint64_t k = m_cells[static_cast<size_t>(m_deepest)].key;
      for (int guard = 0; k && guard < kCap + 1; guard++)
      {
        keep.insert(k);
        auto it = m_index.find(k);
        if (it == m_index.end())
          break;
        k = m_cells[static_cast<size_t>(it->second)].parent;
      }
    }
    int victim = -1;
    for (size_t i = 0; i < m_cells.size(); i++)
    {
      const Cell& c = m_cells[i];
      if (c.parent == 0 || keep.count(c.key))
        continue;
      if (victim < 0 || c.visits > m_cells[static_cast<size_t>(victim)].visits)
        victim = static_cast<int>(i);
    }
    if (victim < 0)
      return;
    // swap-remove, then fix the index of the moved cell
    m_index.erase(m_cells[static_cast<size_t>(victim)].key);
    const int last = size() - 1;
    if (victim != last)
    {
      m_cells[static_cast<size_t>(victim)] = std::move(m_cells[static_cast<size_t>(last)]);
      m_index[m_cells[static_cast<size_t>(victim)].key] = victim;
    }
    m_cells.pop_back();
    if (m_deepest == last)
      m_deepest = victim;
    else if (m_deepest == victim)
      Rebuild();
  }

  std::vector<Cell> m_cells;
  std::unordered_map<uint64_t, int> m_index;
  uint64_t m_iter = 0;
  int m_deepest = -1;
  mutable std::vector<double> m_weights;
};

} // namespace arcade
