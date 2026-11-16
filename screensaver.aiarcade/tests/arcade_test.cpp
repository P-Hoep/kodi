// Runs the whole pipeline with no Kodi: the training thread (and helpers),
// optionally the display thread, on one ROM or a folder, for a while, and
// prints the log and a status line. Stop and run it again to check that
// everything resumes from the saved files.
//
//   arcade_test <rom.nes | folder> <data dir> [seconds=60] [threads=1] [cpu=1.0] [population=100] [display=0]
#include "Trainer.h"

#include <chrono>
#include <cstdio>
#include <cstdlib>
#include <filesystem>
#include <string>
#include <thread>

using namespace arcade;

int main(int argc, char** argv)
{
  if (argc < 3)
  {
    std::printf("usage: arcade_test <rom.nes|folder> <data dir> [seconds] [threads] [cpu] [population] [display]\n");
    return 2;
  }
  Config cfg;
  const std::string target = argv[1];
  if (std::filesystem::is_directory(target))
    cfg.romDir = target;
  else
    cfg.onlyRom = target;
  cfg.dataDir = argv[2];
  const double seconds = argc > 3 ? std::atof(argv[3]) : 60.0;
  cfg.threads = argc > 4 ? std::atoi(argv[4]) : 1;
  cfg.cpuCap = argc > 5 ? std::atof(argv[5]) : 1.0;
  cfg.population = argc > 6 ? std::atoi(argv[6]) : 100;
  cfg.display = argc > 7 ? std::atoi(argv[7]) != 0 : false;
  cfg.log = [](int level, const std::string& s) {
    static const char* tag[] = {"debug", "info", "WARN", "ERROR"};
    std::printf("[%s] %s\n", tag[level & 3], s.c_str());
    std::fflush(stdout);
  };
  Arcade a;
  const auto t0 = std::chrono::steady_clock::now();
  a.Start(cfg);
  double lastPrint = 0;
  uint64_t serial = 0;
  std::vector<uint32_t> frame;
  int frames = 0;
  while (true)
  {
    std::this_thread::sleep_for(std::chrono::milliseconds(100));
    const double t = std::chrono::duration<double>(std::chrono::steady_clock::now() - t0).count();
    if (a.CopyFrame(serial, frame))
      frames++;
    if (t - lastPrint >= 10.0 || t >= seconds)
    {
      lastPrint = t;
      Stats s = a.GetStats();
      std::printf("  %5.0fs  %s | %s | gen %d (%d/%d) | best %.1f | %d species | archive %d | %.3f h | show: %s "
                  "value %.2f%s\n",
                  t, s.title.c_str(), s.status.empty() ? PhaseName(s.phase) : s.status.c_str(), s.generation,
                  s.evaluated, s.populationSize, s.bestFitness, s.species, s.archive, s.hours, s.mode.c_str(), s.value,
                  s.noveltyOnly ? " (novelty only)" : "");
      std::fflush(stdout);
    }
    if (t >= seconds)
      break;
  }
  const auto s0 = std::chrono::steady_clock::now();
  a.Stop();
  std::printf("stopped in %.0f ms; %d display frames seen\n",
              std::chrono::duration<double, std::milli>(std::chrono::steady_clock::now() - s0).count(), frames);
  return 0;
}
