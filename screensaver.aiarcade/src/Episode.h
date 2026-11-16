// One controller playing from a start state (spec 4.4 "Episode"). Used both
// to score genomes on the training threads and to show the champion on the
// display thread, so what is shown is exactly the run that was scored.
#pragma once

#include "Neat.h"
#include "Objectives.h"

#include <unordered_set>

namespace arcade
{

constexpr int kEpisodeFrames = 4000;
constexpr int kStallFrames = 600;
constexpr int kDecideEvery = 4;
constexpr int kMaxNovelty = 50;

struct EpisodeResult
{
  double maxValue = 0, finalValue = 0;
  int frames = 0, newCells = 0;
  bool died = false;
  std::vector<Cell> found; // new cells with their states, when collecting

  double Fitness() const
  {
    return 100.0 * maxValue + 20.0 * finalValue + 0.25 * std::min(newCells, kMaxNovelty) / double(kMaxNovelty) * 100.0;
  }
};

class Episode
{
public:
  struct Setup
  {
    const std::string* startState = nullptr; // raw savestate
    uint64_t startKey = 0;
    int startDepth = 0;
    const Objectives* obj = nullptr;
    const uint8_t* startRam = nullptr;
    const std::unordered_set<uint64_t>* known = nullptr; // archive keys, for novelty
    bool collect = false;                                // keep states of new cells
  };

  bool Begin(Emu& emu, const Genome& genome, const Setup& setup)
  {
    m_emu = &emu;
    m_setup = setup;
    m_net.Build(genome);
    m_res = EpisodeResult();
    m_f = 0;
    m_buttons = 0;
    m_done = false;
    m_lastImprove = 0;
    m_lastNovel = 0;
    m_haveValue = false;
    m_lastKnown = setup.startKey;
    m_value = 0;
    m_hist.clear();
    m_seen.clear();
    std::fill(std::begin(m_prev), std::end(m_prev), 0.0f);
    m_inputBytes = setup.obj ? setup.obj->InputBytes() : std::vector<int>();
    if (!setup.startState || !emu.Restore(*setup.startState))
    {
      m_done = true;
      return false;
    }
    return true;
  }

  // One frame. `show` (optional) receives the frame. Returns false when over.
  bool Step(uint32_t* show = nullptr)
  {
    if (m_done)
      return false;
    const bool observe = (m_f % kDecideEvery) == kDecideEvery - 1;
    uint32_t* buf = show ? show : m_buf.data();
    m_emu->Frame(m_buttons, (show || observe) ? buf : nullptr);
    m_f++;
    if (observe)
      Observe(buf);
    const bool stalled = (m_setup.obj && !m_setup.obj->empty()) ? m_f - m_lastImprove >= kStallFrames
                         : m_setup.known                       ? m_f - m_lastNovel >= kStallFrames
                                                               : false;
    if (m_res.died || m_f >= kEpisodeFrames || stalled)
    {
      m_done = true;
      m_res.frames = m_f;
    }
    return !m_done;
  }

  bool done() const { return m_done; }
  int frame() const { return m_f; }
  double value() const { return m_value; }
  uint8_t buttons() const { return m_buttons; }
  const EpisodeResult& result() const { return m_res; }
  EpisodeResult& result() { return m_res; }

  // Run to the end (training). `stop` aborts; returns false if aborted.
  template <class Tick> bool Run(const std::atomic<bool>& stop, Tick&& tick)
  {
    while (Step())
    {
      if ((m_f & 63) == 0)
      {
        if (stop.load(std::memory_order_relaxed))
          return false;
        tick();
      }
    }
    return true;
  }

private:
  void Observe(const uint32_t* frame)
  {
    const uint8_t* ram = m_emu->Ram();
    // Value, max Value, and death (sim rises >= 0.20 within 30 frames while
    // Value drops by >= 20% of the episode's max)
    if (m_setup.obj && !m_setup.obj->empty())
    {
      m_value = m_setup.obj->Value(ram);
      if (!m_haveValue || m_value > m_res.maxValue)
      {
        m_res.maxValue = m_value;
        m_lastImprove = m_f;
        m_haveValue = true;
      }
      m_res.finalValue = m_value;
      if (m_setup.startRam)
      {
        const double sim = RamSimilarity(ram, m_setup.startRam);
        double minSim = sim, maxVal = m_value;
        for (const Sample& s : m_hist)
          if (m_f - s.f <= 30)
          {
            minSim = std::min(minSim, s.sim);
            maxVal = std::max(maxVal, s.value);
          }
        if (m_res.maxValue > 0 && sim - minSim >= 0.20 && maxVal - m_value >= 0.20 * m_res.maxValue)
          m_res.died = true;
        m_hist.push_back({m_f, sim, m_value});
        if (m_hist.size() > 10)
          m_hist.erase(m_hist.begin());
      }
    }

    // novelty: archive cells this run reached that the archive does not have
    const uint64_t key = CellKey(frame);
    if (m_setup.known)
    {
      if (m_setup.known->count(key))
        m_lastKnown = key;
      else if (m_seen.insert(key).second)
      {
        m_res.newCells++;
        m_lastNovel = m_f;
        if (m_setup.collect && static_cast<int>(m_res.found.size()) < kMaxNovelty)
        {
          Cell c;
          c.key = key;
          c.parent = m_lastKnown ? m_lastKnown : 1;
          c.depth = m_setup.startDepth + m_f / 17; // a motif is 17 frames on average
          std::string raw;
          if (m_emu->Save(raw))
          {
            c.zstate = std::make_shared<const std::string>(Compress(raw, 1));
            std::copy(ram, ram + kRamSize, c.ram.begin());
            m_res.found.push_back(std::move(c));
          }
        }
      }
    }

    // the network: 16 x 15 grey screen, objective bytes, previous action, bias
    float in[kInputs];
    float grid[kNetGrid];
    GreyGrid(frame, kNetGridW, kNetGridH, grid);
    for (int i = 0; i < kNetGrid; i++)
      in[i] = grid[i] * (1.0f / 255.0f);
    for (int i = 0; i < 16; i++)
      in[kInObj + i] = i < static_cast<int>(m_inputBytes.size()) ? ram[m_inputBytes[static_cast<size_t>(i)]] * (1.0f / 255.0f) : 0.0f;
    for (int i = 0; i < 8; i++)
      in[kInPrev + i] = m_prev[i];
    in[kInBias] = 1.0f;
    m_buttons = m_net.Activate(in, m_prev);
  }

  struct Sample
  {
    int f;
    double sim, value;
  };

  Emu* m_emu = nullptr;
  Setup m_setup;
  Network m_net;
  EpisodeResult m_res;
  std::vector<int> m_inputBytes;
  std::vector<Sample> m_hist;
  std::unordered_set<uint64_t> m_seen;
  std::vector<uint32_t> m_buf = std::vector<uint32_t>(kScreenW * kScreenH);
  float m_prev[8] = {0};
  uint64_t m_lastKnown = 0;
  double m_value = 0;
  int m_f = 0, m_lastImprove = 0, m_lastNovel = 0;
  uint8_t m_buttons = 0;
  bool m_done = true, m_haveValue = false;
};

} // namespace arcade
