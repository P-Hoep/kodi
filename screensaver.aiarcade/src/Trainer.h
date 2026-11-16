// The whole pipeline (spec 3 to 5) behind a small interface for the Kodi
// shell: Start() launches the threads, the render thread copies the latest
// frame and stats, Stop() signals, joins and saves.
//
// Threads:
//   training thread  - scans the library, picks a ROM, runs FIND_GAMEPLAY,
//                      EXPLORE, LEARN_OBJECTIVES and EVOLVE on its own emulator
//   helper threads   - (threads > 1) evaluate genomes in parallel, one emulator each
//   display thread   - emulator #1: plays the champion (or explores) in real time
#pragma once

#include <atomic>
#include <cstdint>
#include <functional>
#include <memory>
#include <string>
#include <thread>
#include <vector>

namespace arcade
{

enum class Phase
{
  Idle,
  FindGameplay,
  Explore,
  Learn,
  Evolve,
};
const char* PhaseName(Phase p); // "finding gameplay", "exploring", ...

struct Config
{
  std::string bundledDir; // the add-on's own roms/ folder, always scanned
  std::string romDir;     // an extra folder from the settings (may be empty)
  bool recursive = true;
  int threads = 1;      // training threads
  double cpuCap = 0.6;  // of one core, per training thread
  int population = 100; // 25 to 300
  int switchMinutes = 0;
  bool resetAll = false;
  bool display = true;  // run the display thread
  std::string dataDir;  // .../addon_data/screensaver.aiarcade
  std::string onlyRom;  // tools: always this ROM file
  uint64_t seed = 0;    // 0: random
  // 0 debug, 1 info, 2 warning, 3 error
  std::function<void(int, const std::string&)> log;
  // optional file-system hooks (Kodi VFS); local files when empty
  std::function<std::vector<std::string>(const std::string&, bool)> listRoms;
  std::function<bool(const std::string&, std::vector<uint8_t>&)> readFile;
};

struct Stats
{
  std::string title;
  std::string status; // shown when there is no game (no ROM folder, scanning, ...)
  std::string mode;   // what the display shows: "champion", "exploring", ...
  Phase phase = Phase::Idle;
  bool noveltyOnly = false;
  int generation = 0, species = 0, archive = 0, objectives = 0, roms = 0;
  int evaluated = 0, populationSize = 0; // progress through the current generation
  double bestFitness = 0, hours = 0;
  double value = 0, runBest = 0; // the displayed run
  int runFrame = 0;
  std::vector<float> histBest, histAvg; // last 100 generations
  std::string objectivesText;
};

class Arcade
{
public:
  Arcade();
  ~Arcade();
  void Start(const Config& cfg);
  void Stop();
  bool running() const { return m_running; }

  // The latest display frame (256 x 240 RGBX) if newer than `serial`.
  bool CopyFrame(uint64_t& serial, std::vector<uint32_t>& out);
  Stats GetStats();

private:
  struct Impl;
  std::unique_ptr<Impl> m;
  bool m_running = false;
};

} // namespace arcade
