#include "Trainer.h"

#include "Archive.h"
#include "Episode.h"
#include "Neat.h"
#include "Objectives.h"
#include "Store.h"
#include "nlohmann/json.hpp"

#include <chrono>
#include <condition_variable>
#include <cstdarg>
#include <cstdio>
#include <ctime>
#include <mutex>
#include <random>

namespace arcade
{

using json = nlohmann::json;
using Clock = std::chrono::steady_clock;

namespace
{
constexpr int kSchema = 1;
constexpr int64_t kFindMaxFrames = 18000;    // 5 minutes of emulated time
constexpr int64_t kExploreMinFrames = 36000; // 10 minutes
constexpr int64_t kExploreMaxFrames = 144000;
constexpr int kExploreMinCells = 300;
constexpr int kRelearnEvery = 20;
constexpr double kAutosaveSeconds = 300.0;
constexpr int kHistoryKeep = 1000;
constexpr char kStateMagic[] = "AIARCADE-STATE";
constexpr char kArchiveMagic[] = "AIARCADE-ARCHIVE";
constexpr char kNeatMagic[] = "AIARCADE-NEAT";
constexpr char kChampMagic[] = "AIARCADE-CHAMPION";

std::string JoinPath(const std::string& a, const std::string& b)
{
  if (a.empty())
    return b;
  const char last = a.back();
  return (last == '/' || last == '\\') ? a + b : a + "/" + b;
}

std::string BaseTitle(const std::string& path)
{
  size_t s = path.find_last_of("/\\");
  std::string name = s == std::string::npos ? path : path.substr(s + 1);
  const size_t dot = name.find_last_of('.');
  if (dot != std::string::npos)
    name = name.substr(0, dot);
  return name;
}

int64_t Now() { return static_cast<int64_t>(std::time(nullptr)); }

bool ReadJson(const std::string& path, json& out)
{
  std::string text;
  if (!ReadFile(path, text))
    return false;
  try
  {
    out = json::parse(text);
    return out.is_object();
  }
  catch (...)
  {
    return false;
  }
}

std::string Magic(const char* m) { return std::string(m) + "\n"; }

// "<magic>\n" + u32 schema + payload, the payload zlib-compressed
bool WriteBlob(const std::string& path, const char* magic, const std::string& payload, int level = 6)
{
  BinWriter w;
  w.s = Magic(magic);
  w.U32(kSchema);
  w.s += Compress(payload, level);
  return WriteFileAtomic(path, w.s);
}

bool ReadBlob(const std::string& path, const char* magic, std::string& payload)
{
  std::string data;
  if (!ReadFile(path, data))
    return false;
  const std::string m = Magic(magic);
  if (data.compare(0, m.size(), m) != 0 || data.size() < m.size() + 4)
    return false;
  BinReader r(data);
  r.p = m.size();
  if (r.U32() != kSchema)
    return false;
  return Decompress(data.substr(r.p), payload);
}

} // namespace

const char* PhaseName(Phase p)
{
  switch (p)
  {
    case Phase::FindGameplay: return "finding gameplay";
    case Phase::Explore: return "exploring";
    case Phase::Learn: return "learning";
    case Phase::Evolve: return "evolving";
    default: return "starting";
  }
}

static const char* PhaseKey(Phase p)
{
  switch (p)
  {
    case Phase::Explore: return "explore";
    case Phase::Learn: return "learn";
    case Phase::Evolve: return "evolve";
    default: return "find";
  }
}

struct Rom
{
  std::string path, id, title;
  double hours = 0;
  int64_t lastPlayed = 0;
  bool bad = false;
};

struct Session
{
  Rom* rom = nullptr;
  std::string dir;
  std::vector<uint8_t> image;
  Emu emu;
  Phase phase = Phase::FindGameplay;

  std::string startState; // raw
  std::array<uint8_t, kRamSize> startRam{};
  uint64_t startKey = 0;

  Archive archive;
  bool archiveDirty = false;
  int64_t exploreFrames = 0;

  Objectives obj;
  int objCounter = 0;
  bool learned = false;
  int lastLearnGen = 0, lastLearnDepth = 0;

  Neat neat;
  Genome champion;
  bool hasChampion = false;
  double champFitness = 0;
  int champVersion = -1;

  std::vector<float> histBest, histAvg;
  double hours = 0;
  Clock::time_point since = Clock::now();

  std::vector<uint32_t> buf = std::vector<uint32_t>(kScreenW * kScreenH);
  std::string raw;

  // what the display sees
  std::shared_ptr<const std::string> pubStart;
  std::shared_ptr<const std::array<uint8_t, kRamSize>> pubStartRam;
  std::shared_ptr<const Objectives> pubObj;
  std::shared_ptr<const Genome> pubChamp;
};

struct Job
{
  const std::vector<Genome*>* genomes = nullptr;
  Episode::Setup setup;
  std::vector<EpisodeResult>* out = nullptr;
  std::atomic<int> next{0}, finished{0};
};

struct Arcade::Impl
{
  Config cfg;
  std::atomic<bool> stop{false};
  std::thread train, display;
  std::vector<std::thread> helpers;
  Rng rng;
  Throttle throttle;

  // display inputs and the HUD
  std::mutex mu;
  uint64_t romSerial = 0;
  std::shared_ptr<const std::vector<uint8_t>> romImage;
  std::shared_ptr<const std::string> startState;
  std::shared_ptr<const std::array<uint8_t, kRamSize>> startRam;
  uint64_t startKey = 0;
  std::shared_ptr<const std::string> deepest;
  std::shared_ptr<const Objectives> obj;
  std::shared_ptr<const Genome> champion;
  Phase phase = Phase::Idle;
  Stats stats;

  // the display frame
  std::mutex frameMu;
  std::vector<uint32_t> frame;
  uint64_t frameSerial = 0;

  // parallel evaluation
  std::mutex jobMu;
  std::condition_variable jobCv, doneCv;
  Job* job = nullptr;
  uint64_t jobSerial = 0;
  int jobBusy = 0;
  std::shared_ptr<const std::vector<uint8_t>> jobImage;
  uint64_t jobImageSerial = 0;
  Job* activeJob = nullptr; // the training thread's, for progress

  void Log(int level, const char* fmt, ...)
  {
    char buf[1024];
    va_list ap;
    va_start(ap, fmt);
    std::vsnprintf(buf, sizeof buf, fmt, ap);
    va_end(ap);
    if (cfg.log)
      cfg.log(level, buf);
  }

  void Tick()
  {
    throttle.Tick(stop);
    if (activeJob)
    {
      std::lock_guard<std::mutex> lock(mu);
      stats.evaluated = activeJob->finished.load();
    }
  }

  void SetStatus(const std::string& s)
  {
    std::lock_guard<std::mutex> lock(mu);
    stats.status = s;
  }

  // ---- library (spec 3) ---------------------------------------------------------

  bool ReadRomFile(const std::string& path, std::vector<uint8_t>& out)
  {
    return cfg.readFile ? cfg.readFile(path, out) : ReadFile(path, out);
  }

  static bool ValidInes(const std::vector<uint8_t>& d, size_t& prgChrStart, size_t& prgChrSize)
  {
    if (d.size() < 16 || d[0] != 0x4E || d[1] != 0x45 || d[2] != 0x53 || d[3] != 0x1A)
      return false;
    const size_t prg = static_cast<size_t>(d[4]) * 16384, chr = static_cast<size_t>(d[5]) * 8192;
    const size_t trainer = (d[6] & 0x04) ? 512 : 0;
    prgChrStart = 16 + trainer;
    prgChrSize = prg + chr;
    return prg > 0 && d.size() >= 16 + trainer + prg + chr;
  }

  std::vector<Rom> ScanLibrary()
  {
    std::vector<Rom> roms;
    std::vector<std::string> paths;
    if (!cfg.onlyRom.empty())
      paths.push_back(cfg.onlyRom);
    else
    {
      if (!cfg.bundledDir.empty())
        paths = ListNesFiles(cfg.bundledDir, true);
      if (!cfg.romDir.empty())
      {
        auto more = cfg.listRoms ? cfg.listRoms(cfg.romDir, cfg.recursive) : ListNesFiles(cfg.romDir, cfg.recursive);
        paths.insert(paths.end(), more.begin(), more.end());
      }
    }
    std::vector<uint8_t> data;
    for (const std::string& p : paths)
    {
      if (stop)
        break;
      if (!ReadRomFile(p, data))
      {
        Log(2, "cannot read %s", p.c_str());
        continue;
      }
      size_t start = 0, size = 0;
      if (!ValidInes(data, start, size))
      {
        Log(2, "not a valid iNES file: %s", p.c_str());
        continue;
      }
      Rom r;
      r.path = p;
      r.id = Sha1Hex(data.data() + start, size);
      r.title = BaseTitle(p);
      bool dup = false;
      for (const Rom& o : roms)
        dup |= o.id == r.id;
      if (dup)
        continue;
      const std::string dir = JoinPath(cfg.dataDir, r.id);
      json meta;
      if (ReadJson(JoinPath(dir, "meta.json"), meta) && meta.value("schema_version", 0) == kSchema)
      {
        r.hours = meta.value("hours_trained", 0.0);
        r.lastPlayed = meta.value("last_played", static_cast<int64_t>(0));
        r.bad = meta.value("bad", false);
      }
      else
      {
        // a new ROM: try it once in Nestopia (unsupported mappers are skipped from now on)
        Emu test;
        std::string err;
        r.bad = !test.Load(data, &err);
        MakeDirs(dir);
        json m = {{"schema_version", kSchema}, {"title", r.title}, {"hours_trained", 0.0}, {"last_played", 0},
                  {"bad", r.bad},             {"phase", "find"}};
        if (r.bad)
        {
          m["error"] = err;
          Log(2, "%s: cannot run (%s); skipped", r.title.c_str(), err.c_str());
        }
        WriteFileAtomic(JoinPath(dir, "meta.json"), m.dump(1));
      }
      roms.push_back(std::move(r));
    }
    return roms;
  }

  int PickRom(std::vector<Rom>& roms)
  {
    std::vector<int> ok;
    for (size_t i = 0; i < roms.size(); i++)
      if (!roms[i].bad)
        ok.push_back(static_cast<int>(i));
    if (ok.empty())
      return -1;
    // exclude the last 3 played (fewer when the library is small)
    std::vector<int> recent;
    for (int i : ok)
      if (roms[static_cast<size_t>(i)].lastPlayed > 0)
        recent.push_back(i);
    std::sort(recent.begin(), recent.end(),
              [&](int a, int b) { return roms[static_cast<size_t>(a)].lastPlayed > roms[static_cast<size_t>(b)].lastPlayed; });
    const size_t exclude = std::min<size_t>({3, recent.size(), ok.size() - 1});
    std::vector<int> pool;
    for (int i : ok)
      if (std::find(recent.begin(), recent.begin() + static_cast<long>(exclude), i) == recent.begin() + static_cast<long>(exclude))
        pool.push_back(i);
    // weight 1 / (1 + hours_trained)
    double total = 0;
    for (int i : pool)
      total += 1.0 / (1.0 + roms[static_cast<size_t>(i)].hours);
    double r = rng.Uniform() * total;
    for (int i : pool)
    {
      r -= 1.0 / (1.0 + roms[static_cast<size_t>(i)].hours);
      if (r <= 0)
        return i;
    }
    return pool.back();
  }

  // ---- persistence (spec 3, "Storage") ---------------------------------------------

  void AddHours(Session& s)
  {
    const auto now = Clock::now();
    s.hours += std::chrono::duration<double>(now - s.since).count() / 3600.0;
    s.since = now;
    s.rom->hours = s.hours;
  }

  void SaveMeta(Session& s)
  {
    AddHours(s);
    json m = {{"schema_version", kSchema},
              {"title", s.rom->title},
              {"hours_trained", s.hours},
              {"last_played", s.rom->lastPlayed},
              {"bad", false},
              {"phase", PhaseKey(s.phase)},
              {"generation", s.neat.generation()},
              {"best_fitness", s.hasChampion ? s.champFitness : 0.0},
              {"archive_size", s.archive.size()},
              {"explore_frames", s.exploreFrames},
              {"objectives", s.obj.Describe()}};
    const size_t from = s.histBest.size() > kHistoryKeep ? s.histBest.size() - kHistoryKeep : 0;
    m["history"] = {{"best", std::vector<float>(s.histBest.begin() + static_cast<long>(from), s.histBest.end())},
                    {"avg", std::vector<float>(s.histAvg.begin() + static_cast<long>(from), s.histAvg.end())}};
    WriteFileAtomic(JoinPath(s.dir, "meta.json"), m.dump(1));
  }

  void SaveStart(Session& s)
  {
    if (!s.startState.empty())
      WriteBlob(JoinPath(s.dir, "start.state"), kStateMagic, s.startState);
  }

  void SaveArchive(Session& s)
  {
    if (!s.archiveDirty)
      return;
    BinWriter w;
    w.U64(s.archive.iteration());
    w.U32(static_cast<uint32_t>(s.archive.size()));
    for (const Cell& c : s.archive.cells())
    {
      w.U64(c.key);
      w.U64(c.parent);
      w.I32(c.depth);
      w.U32(c.visits);
      w.U64(c.added);
      w.Str(c.zstate ? *c.zstate : std::string());
    }
    // the savestates are compressed already; the RAM snapshots go in one zlib block
    std::string rams;
    rams.reserve(static_cast<size_t>(s.archive.size()) * kRamSize);
    for (const Cell& c : s.archive.cells())
      rams.append(reinterpret_cast<const char*>(c.ram.data()), kRamSize);
    w.Str(Compress(rams, 1));
    if (WriteBlob(JoinPath(s.dir, "archive.bin"), kArchiveMagic, w.s, 0))
      s.archiveDirty = false;
  }

  void SaveObjectives(Session& s)
  {
    json list = json::array();
    for (const Objective& o : s.obj.list)
      list.push_back({{"lo", o.lo}, {"hi", o.hi}, {"rho", o.rho}, {"weight", o.weight}, {"name", o.Name()}, {"values", o.sorted}});
    json j = {{"schema_version", kSchema},
              {"version", s.obj.version},
              {"learned", s.learned},
              {"learned_generation", s.lastLearnGen},
              {"learned_depth", s.lastLearnDepth},
              {"objectives", list}};
    WriteFileAtomic(JoinPath(s.dir, "objectives.json"), j.dump());
  }

  void SaveNeat(Session& s)
  {
    if (!s.neat.initialised())
      return;
    BinWriter w;
    for (uint64_t v : rng.s)
      w.U64(v);
    s.neat.Save(w);
    WriteBlob(JoinPath(s.dir, "neat.bin"), kNeatMagic, w.s);
  }

  void SaveChampion(Session& s)
  {
    if (!s.hasChampion)
      return;
    BinWriter w;
    w.F64(s.champFitness);
    w.I32(s.champVersion);
    WriteGenome(w, s.champion);
    WriteBlob(JoinPath(s.dir, "champion.bin"), kChampMagic, w.s);
  }

  void SaveAll(Session& s)
  {
    MakeDirs(s.dir);
    SaveMeta(s);
    SaveStart(s);
    SaveArchive(s);
    if (s.learned)
      SaveObjectives(s);
    SaveNeat(s);
    SaveChampion(s);
  }

  bool LoadStart(Session& s)
  {
    std::string raw;
    if (!ReadBlob(JoinPath(s.dir, "start.state"), kStateMagic, raw) || !s.emu.Restore(raw))
      return false;
    s.startState = raw;
    std::copy(s.emu.Ram(), s.emu.Ram() + kRamSize, s.startRam.begin());
    s.emu.Frame(0, s.buf.data());
    s.startKey = CellKey(s.buf.data());
    s.emu.Restore(raw);
    return true;
  }

  bool LoadArchive(Session& s)
  {
    std::string payload;
    if (!ReadBlob(JoinPath(s.dir, "archive.bin"), kArchiveMagic, payload))
      return false;
    BinReader r(payload);
    const uint64_t iter = r.U64();
    const uint32_t n = r.U32();
    if (!r.ok || n == 0 || n > static_cast<uint32_t>(Archive::kCap))
      return false;
    s.archive.Clear();
    std::vector<Cell>& cells = s.archive.mutableCells();
    cells.reserve(n);
    for (uint32_t i = 0; i < n; i++)
    {
      Cell c;
      c.key = r.U64();
      c.parent = r.U64();
      c.depth = r.I32();
      c.visits = r.U32();
      c.added = r.U64();
      c.zstate = std::make_shared<const std::string>(r.Str());
      if (!r.ok || c.key == 0 || c.depth < 0)
        return false;
      cells.push_back(std::move(c));
    }
    std::string rams;
    if (!Decompress(r.Str(), rams) || !r.ok || rams.size() != static_cast<size_t>(n) * kRamSize)
      return false;
    for (uint32_t i = 0; i < n; i++)
      std::copy(rams.begin() + static_cast<long>(i) * kRamSize, rams.begin() + static_cast<long>(i + 1) * kRamSize,
                reinterpret_cast<char*>(cells[i].ram.data()));
    s.archive.SetIteration(iter);
    s.archive.Rebuild();
    return true;
  }

  bool LoadObjectives(Session& s)
  {
    json j;
    if (!ReadJson(JoinPath(s.dir, "objectives.json"), j) || j.value("schema_version", 0) != kSchema ||
        !j.value("learned", false))
      return false;
    try
    {
      Objectives o;
      o.version = j.at("version").get<int>();
      for (const json& e : j.at("objectives"))
      {
        Objective ob;
        ob.lo = e.at("lo").get<int>();
        ob.hi = e.at("hi").get<int>();
        ob.rho = e.at("rho").get<double>();
        ob.weight = e.at("weight").get<double>();
        ob.sorted = e.at("values").get<std::vector<uint16_t>>();
        if (ob.lo < 0 || ob.lo >= kRamSize || ob.hi >= kRamSize || ob.hi < -1 || ob.sorted.empty())
          return false;
        if (!std::is_sorted(ob.sorted.begin(), ob.sorted.end()))
          std::sort(ob.sorted.begin(), ob.sorted.end());
        o.list.push_back(std::move(ob));
      }
      if (o.list.size() > 8)
        return false;
      s.obj = std::move(o);
      s.objCounter = s.obj.version;
      s.lastLearnGen = j.value("learned_generation", 0);
      s.lastLearnDepth = j.value("learned_depth", 0);
      s.learned = true;
      return true;
    }
    catch (...)
    {
      return false;
    }
  }

  bool LoadNeat(Session& s)
  {
    std::string payload;
    if (!ReadBlob(JoinPath(s.dir, "neat.bin"), kNeatMagic, payload))
      return false;
    BinReader r(payload);
    Rng saved;
    for (uint64_t& v : saved.s)
      v = r.U64();
    Neat n;
    if (!r.ok || !n.Load(r))
      return false;
    s.neat = std::move(n);
    if (cfg.seed == 0)
      rng = saved; // resume the run's random stream
    return true;
  }

  bool LoadChampion(Session& s)
  {
    std::string payload;
    if (!ReadBlob(JoinPath(s.dir, "champion.bin"), kChampMagic, payload))
      return false;
    BinReader r(payload);
    const double fit = r.F64();
    const int ver = r.I32();
    Genome g;
    if (!r.ok || !ReadGenome(r, g) || !std::isfinite(fit))
      return false;
    s.champion = std::move(g);
    s.champFitness = fit;
    s.champVersion = ver;
    s.hasChampion = true;
    return true;
  }

  // Each stage that fails to load restarts from there (spec 3).
  void LoadSession(Session& s)
  {
    json meta;
    if (ReadJson(JoinPath(s.dir, "meta.json"), meta) && meta.value("schema_version", 0) == kSchema)
    {
      s.hours = meta.value("hours_trained", 0.0);
      s.exploreFrames = meta.value("explore_frames", static_cast<int64_t>(0));
      try
      {
        if (meta.contains("history"))
        {
          s.histBest = meta["history"].at("best").get<std::vector<float>>();
          s.histAvg = meta["history"].at("avg").get<std::vector<float>>();
          if (s.histAvg.size() != s.histBest.size())
            s.histBest.clear(), s.histAvg.clear();
        }
      }
      catch (...)
      {
        s.histBest.clear();
        s.histAvg.clear();
      }
    }
    const std::string metaPhase = meta.is_object() ? meta.value("phase", std::string("find")) : std::string("find");

    s.phase = Phase::FindGameplay;
    if (!LoadStart(s))
      return;
    s.phase = Phase::Explore;
    if (!LoadArchive(s))
    {
      if (FileExists(JoinPath(s.dir, "archive.bin")))
        Log(2, "%s: archive.bin unreadable; exploring again", s.rom->title.c_str());
      s.archive.Clear();
      AddRoot(s);
      s.exploreFrames = 0;
      return;
    }
    if (metaPhase == "explore" || metaPhase == "find")
      return;
    s.phase = Phase::Learn;
    if (!LoadObjectives(s))
      return;
    s.phase = Phase::Evolve;
    if (!LoadNeat(s) && FileExists(JoinPath(s.dir, "neat.bin")))
      Log(2, "%s: neat.bin unreadable; starting a new population", s.rom->title.c_str());
    if (!LoadChampion(s) && FileExists(JoinPath(s.dir, "champion.bin")))
      Log(2, "%s: champion.bin unreadable", s.rom->title.c_str());
  }

  void AddRoot(Session& s)
  {
    Cell root;
    root.key = s.startKey;
    root.parent = 0;
    root.depth = 0;
    root.zstate = std::make_shared<const std::string>(Compress(s.startState, 1));
    root.ram = s.startRam;
    s.archive.Add(std::move(root));
    s.archiveDirty = true;
  }

  // ---- display hand-off -----------------------------------------------------------------

  void Publish(Session& s)
  {
    if (!s.startState.empty() && (!s.pubStart || *s.pubStart != s.startState))
    {
      s.pubStart = std::make_shared<const std::string>(s.startState);
      s.pubStartRam = std::make_shared<const std::array<uint8_t, kRamSize>>(s.startRam);
    }
    if (!s.pubObj || s.pubObj->version != s.obj.version || s.pubObj->list.size() != s.obj.list.size())
      s.pubObj = std::make_shared<const Objectives>(s.obj);
    std::lock_guard<std::mutex> lock(mu);
    startState = s.pubStart;
    startRam = s.pubStartRam;
    startKey = s.startKey;
    deepest = s.archive.deepest() >= 0 ? s.archive.at(s.archive.deepest()).zstate : nullptr;
    obj = s.learned ? s.pubObj : nullptr;
    champion = s.pubChamp;
    phase = s.phase;
    UpdateStatsLocked(s);
  }

  void UpdateStatsLocked(Session& s)
  {
    stats.title = s.rom->title;
    stats.phase = s.phase;
    stats.noveltyOnly = s.learned && s.obj.empty();
    stats.generation = s.neat.generation();
    stats.species = s.neat.speciesCount();
    stats.archive = s.archive.size();
    stats.objectives = static_cast<int>(s.obj.list.size());
    stats.objectivesText = s.learned ? s.obj.Describe() : std::string();
    stats.bestFitness = s.hasChampion ? s.champFitness : 0.0;
    stats.hours = s.hours + std::chrono::duration<double>(Clock::now() - s.since).count() / 3600.0;
    stats.populationSize = s.neat.initialised() ? static_cast<int>(s.neat.population().size()) : cfg.population;
    const size_t n = s.histBest.size(), from = n > 100 ? n - 100 : 0;
    stats.histBest.assign(s.histBest.begin() + static_cast<long>(from), s.histBest.end());
    stats.histAvg.assign(s.histAvg.begin() + static_cast<long>(from), s.histAvg.end());
    stats.status.clear();
  }

  void UpdateStats(Session& s)
  {
    std::lock_guard<std::mutex> lock(mu);
    UpdateStatsLocked(s);
  }

  // ---- FIND_GAMEPLAY (spec 4.1) ----------------------------------------------------------

  void RunFind(Session& s)
  {
    Emu& e = s.emu;
    e.Power();
    int64_t f = 0;
    int streak = 0, bestDiff = -1;
    std::string probeState, firstLive, bestState;
    std::array<uint8_t, kRamSize> ram1{};
    uint8_t motif = 0;
    int motifLeft = 0;
    bool liveRun = false; // stop pressing Start while probes look live (Start would pause the game)
    while (!stop)
    {
      if (f > 0 && f % 120 == 0)
      {
        // input-sensitivity probe: 60 frames idle vs 60 frames Right+A
        e.Save(probeState);
        for (int i = 0; i < 60; i++)
          e.Frame(0);
        std::copy(e.Ram(), e.Ram() + kRamSize, ram1.begin());
        e.Restore(probeState);
        for (int i = 0; i < 60; i++)
          e.Frame(BTN_RIGHT | BTN_A);
        int diff = 0;
        for (int i = 0; i < kRamSize; i++)
          diff += ram1[static_cast<size_t>(i)] != e.Ram()[i];
        e.Restore(probeState);
        if (diff > bestDiff)
        {
          bestDiff = diff;
          bestState = probeState;
        }
        if (diff >= 10)
        {
          if (streak == 0)
            firstLive = probeState;
          streak++;
          liveRun = true;
          if (streak >= 3)
          {
            FoundStart(s, firstLive, f, diff);
            return;
          }
        }
        else
        {
          streak = 0;
          liveRun = false;
        }
        Tick();
      }
      if (f >= kFindMaxFrames)
      {
        Log(1, "%s: no live probe in %lld frames; using the most input-sensitive one (%d bytes)", s.rom->title.c_str(),
            static_cast<long long>(f), bestDiff);
        FoundStart(s, bestState, f, bestDiff);
        return;
      }
      if (motifLeft-- <= 0)
      {
        motif = RandomMotifButtons(rng);
        motifLeft = RandomMotifLength(rng);
      }
      uint8_t b = motif;
      if (!liveRun && f % 90 < 5)
        b |= BTN_START;
      if (rng.Chance(0.10))
        b |= BTN_A;
      e.Frame(b);
      f++;
    }
  }

  void FoundStart(Session& s, const std::string& state, int64_t frames, int diff)
  {
    s.startState = state;
    s.emu.Restore(state);
    std::copy(s.emu.Ram(), s.emu.Ram() + kRamSize, s.startRam.begin());
    s.emu.Frame(0, s.buf.data());
    s.startKey = CellKey(s.buf.data());
    s.archive.Clear();
    AddRoot(s);
    s.exploreFrames = 0;
    s.phase = Phase::Explore;
    Log(1, "%s: gameplay found after %lld frames (%d RAM bytes react to input)", s.rom->title.c_str(),
        static_cast<long long>(frames), diff);
    SaveStart(s);
    SaveArchive(s);
    SaveMeta(s);
    Publish(s);
  }

  // ---- EXPLORE (spec 4.2) ------------------------------------------------------------------

  int ExploreIteration(Session& s)
  {
    Archive& ar = s.archive;
    const int idx = ar.Pick(rng);
    if (idx < 0)
      return 0;
    Cell& picked = ar.at(idx);
    picked.visits++;
    const std::shared_ptr<const std::string> z = picked.zstate;
    int depth = picked.depth;
    uint64_t parent = picked.key;
    if (!z || !Decompress(*z, s.raw) || !s.emu.Restore(s.raw))
      return 0;
    int frames = 0;
    for (int m = 0; m < 10 && !stop; m++)
    {
      const uint8_t b = RandomMotifButtons(rng);
      const int len = RandomMotifLength(rng);
      for (int i = 0; i < len; i++)
        s.emu.Frame(b, i == len - 1 ? s.buf.data() : nullptr);
      frames += len;
      depth++;
      const uint64_t key = CellKey(s.buf.data());
      if (!ar.Has(key))
      {
        Cell c;
        c.key = key;
        c.parent = parent;
        c.depth = depth;
        std::string raw;
        if (s.emu.Save(raw))
        {
          c.zstate = std::make_shared<const std::string>(Compress(raw, 1));
          std::copy(s.emu.Ram(), s.emu.Ram() + kRamSize, c.ram.begin());
          ar.Add(std::move(c));
          s.archiveDirty = true;
        }
      }
      parent = key;
    }
    ar.NextIteration();
    return frames;
  }

  // untilReady: the EXPLORE phase (10 minutes and 300 cells); otherwise a
  // background budget of frames during EVOLVE (spec 4.5)
  void RunExplore(Session& s, int64_t budget, bool untilReady)
  {
    int64_t done = 0;
    int lastDeepest = s.archive.deepest(), lastDepth = s.archive.maxDepth();
    auto lastPublish = Clock::now();
    while (!stop)
    {
      if (untilReady)
      {
        const bool ready = s.exploreFrames >= kExploreMinFrames && s.archive.size() >= kExploreMinCells;
        if (ready || s.exploreFrames >= kExploreMaxFrames)
        {
          Log(1, "%s: explored %lld frames, %d cells, deepest %d motifs", s.rom->title.c_str(),
              static_cast<long long>(s.exploreFrames), s.archive.size(), s.archive.maxDepth());
          s.phase = Phase::Learn;
          SaveArchive(s);
          SaveMeta(s);
          Publish(s);
          return;
        }
      }
      else if (done >= budget)
        return;
      const int f = ExploreIteration(s);
      done += f;
      s.exploreFrames += f;
      Tick();
      const auto now = Clock::now();
      if (s.archive.deepest() != lastDeepest || s.archive.maxDepth() != lastDepth ||
          std::chrono::duration<double>(now - lastPublish).count() > 1.0)
      {
        lastDeepest = s.archive.deepest();
        lastDepth = s.archive.maxDepth();
        lastPublish = now;
        Publish(s);
      }
      if (f == 0)
        break;
    }
  }

  // ---- LEARN_OBJECTIVES (spec 4.3, 4.5) -----------------------------------------------------

  void RunLearn(Session& s, bool relearn)
  {
    LearnStats st;
    Objectives fresh = LearnObjectives(s.emu, s.archive, rng, &st, &stop);
    if (stop)
      return;
    const bool had = s.learned && !s.obj.empty();
    bool switched = true;
    if (relearn && had)
    {
      RefitObjectives(s.obj, s.archive);
      switched = !fresh.empty() && fresh.topRho() > s.obj.topRho();
      if (switched)
        s.obj = std::move(fresh);
    }
    else
      s.obj = std::move(fresh);
    s.obj.version = ++s.objCounter;
    s.learned = true;
    s.lastLearnGen = s.neat.generation();
    s.lastLearnDepth = s.archive.maxDepth();
    Log(1, "%s: %s objectives (%d cells, %d constant and %d clock bytes dropped, %d candidates, %d with rho >= 0.30): %s",
        s.rom->title.c_str(), !relearn ? "learned" : switched ? "re-learned" : "kept", s.archive.size(),
        st.constantDropped, st.clockDropped, st.candidates, st.passed, s.obj.Describe().c_str());
    s.phase = Phase::Evolve;
    SaveObjectives(s);
    SaveMeta(s);
    if (s.hasChampion)
      RescoreChampion(s);
    if (s.neat.initialised())
      for (Genome& g : s.neat.population())
        g.evaluated = false;
    Publish(s);
  }

  // ---- EVOLVE (spec 4.4) -------------------------------------------------------------------------

  static void RunJob(Emu& emu, Job& job, const std::atomic<bool>& stop, const std::function<void()>& tick)
  {
    const int n = static_cast<int>(job.genomes->size());
    Episode ep;
    for (int i; (i = job.next.fetch_add(1)) < n;)
    {
      if (stop)
        break;
      ep.Begin(emu, *(*job.genomes)[static_cast<size_t>(i)], job.setup);
      ep.Run(stop, tick);
      (*job.out)[static_cast<size_t>(i)] = std::move(ep.result());
      job.finished.fetch_add(1);
    }
  }

  void Evaluate(Session& s, const std::vector<Genome*>& genomes, const Episode::Setup& setup, std::vector<EpisodeResult>& out)
  {
    out.assign(genomes.size(), EpisodeResult());
    Job job;
    job.genomes = &genomes;
    job.setup = setup;
    job.out = &out;
    {
      std::lock_guard<std::mutex> lock(jobMu);
      job_ptr_set(&job);
    }
    jobCv.notify_all();
    activeJob = &job;
    RunJob(s.emu, job, stop, [this] { Tick(); });
    activeJob = nullptr;
    std::unique_lock<std::mutex> lock(jobMu);
    this->job = nullptr;
    doneCv.wait(lock, [&] { return jobBusy == 0; });
  }

  void job_ptr_set(Job* j)
  {
    job = j;
    jobSerial++;
  }

  void HelperMain(int index)
  {
    Emu emu;
    uint64_t loaded = 0, seen = 0;
    Throttle th(cfg.cpuCap);
    std::function<void()> tick = [&] { th.Tick(stop); };
    (void)index;
    while (true)
    {
      Job* j = nullptr;
      std::shared_ptr<const std::vector<uint8_t>> image;
      uint64_t imageSerial = 0;
      {
        std::unique_lock<std::mutex> lock(jobMu);
        jobCv.wait(lock, [&] { return stop || (job && jobSerial != seen); });
        if (stop)
          return;
        seen = jobSerial;
        j = job;
        jobBusy++;
        image = jobImage;
        imageSerial = jobImageSerial;
      }
      if (imageSerial != loaded && image)
      {
        emu.Load(*image);
        loaded = imageSerial;
      }
      th.Reset();
      if (emu.Loaded())
        RunJob(emu, *j, stop, tick);
      {
        std::lock_guard<std::mutex> lock(jobMu);
        jobBusy--;
      }
      doneCv.notify_all();
    }
  }

  void RescoreChampion(Session& s)
  {
    std::vector<Genome*> one{&s.champion};
    std::vector<EpisodeResult> res;
    auto known = s.archive.KeySet();
    Episode::Setup setup = StartSetup(s, s.startState, s.startKey, 0, known.get(), false);
    Evaluate(s, one, setup, res);
    if (stop)
      return;
    const double old = s.champFitness;
    s.champFitness = res[0].Fitness();
    s.champVersion = s.obj.version;
    s.champion.fitness = s.champFitness;
    Log(1, "%s: champion re-scored under objectives v%d: %.1f -> %.1f", s.rom->title.c_str(), s.obj.version, old,
        s.champFitness);
    SaveChampion(s);
  }

  Episode::Setup StartSetup(Session& s, const std::string& state, uint64_t key, int depth,
                            const std::unordered_set<uint64_t>* known, bool collect)
  {
    Episode::Setup setup;
    setup.startState = &state;
    setup.startKey = key;
    setup.startDepth = depth;
    setup.obj = &s.obj;
    setup.startRam = s.startRam.data();
    setup.known = known;
    setup.collect = collect;
    return setup;
  }

  void RunGeneration(Session& s)
  {
    if (!s.neat.initialised())
    {
      s.neat.Init(cfg.population, rng);
      Log(1, "%s: new population of %d", s.rom->title.c_str(), cfg.population);
    }
    s.neat.SetPopulationSize(cfg.population);
    if (s.hasChampion && s.champVersion != s.obj.version)
      RescoreChampion(s);

    // every genome of a generation starts from the same place: start.state,
    // or half the time a random cell from the top 10% by Value
    std::string start = s.startState;
    uint64_t startKey = s.startKey;
    int startDepth = 0;
    bool fromStart = true;
    if (s.archive.size() >= 10 && rng.Chance(0.5))
    {
      std::vector<std::pair<double, int>> ranked;
      for (int i = 0; i < s.archive.size(); i++)
      {
        const Cell& c = s.archive.at(i);
        ranked.push_back({s.obj.Value(c.ram.data()) * 1e6 + c.depth, i});
      }
      std::sort(ranked.begin(), ranked.end(), [](const auto& a, const auto& b) { return a.first > b.first; });
      const int top = std::max(1, static_cast<int>(ranked.size()) / 10);
      const Cell& c = s.archive.at(ranked[static_cast<size_t>(rng.Int(top))].second);
      std::string raw;
      if (c.zstate && Decompress(*c.zstate, raw))
      {
        start = raw;
        startKey = c.key;
        startDepth = c.depth;
        fromStart = false;
      }
    }

    auto known = s.archive.KeySet();
    std::vector<Genome*> genomes;
    for (Genome& g : s.neat.population())
      genomes.push_back(&g);
    std::vector<EpisodeResult> res;
    {
      std::lock_guard<std::mutex> lock(mu);
      stats.evaluated = 0;
    }
    const auto t0 = Clock::now();
    Evaluate(s, genomes, StartSetup(s, start, startKey, startDepth, known.get(), true), res);
    if (stop)
      return;
    const double secs = std::chrono::duration<double>(Clock::now() - t0).count();

    int best = 0;
    double sum = 0;
    int64_t frames = 0;
    for (size_t i = 0; i < genomes.size(); i++)
    {
      genomes[i]->fitness = res[i].Fitness();
      genomes[i]->evaluated = true;
      sum += genomes[i]->fitness;
      frames += res[i].frames;
      if (genomes[i]->fitness > genomes[static_cast<size_t>(best)]->fitness)
        best = static_cast<int>(i);
    }
    const double genBest = genomes[static_cast<size_t>(best)]->fitness, avg = sum / static_cast<double>(genomes.size());
    s.histBest.push_back(static_cast<float>(genBest));
    s.histAvg.push_back(static_cast<float>(avg));

    // the champion plays from start.state, so it is judged from start.state:
    // a generation that started elsewhere has its best re-played from there
    double candFit = genBest;
    int newCellsChamp = res[static_cast<size_t>(best)].newCells;
    if (!fromStart)
    {
      std::vector<Genome*> one{genomes[static_cast<size_t>(best)]};
      std::vector<EpisodeResult> r1;
      Evaluate(s, one, StartSetup(s, s.startState, s.startKey, 0, known.get(), true), r1);
      if (stop)
        return;
      candFit = r1[0].Fitness();
      newCellsChamp = r1[0].newCells;
      for (Cell& c : r1[0].found)
        res[static_cast<size_t>(best)].found.push_back(std::move(c));
    }
    const bool newChamp = !s.hasChampion || candFit > s.champFitness;
    if (newChamp)
    {
      s.champion = *genomes[static_cast<size_t>(best)];
      s.champion.fitness = candFit;
      s.champFitness = candFit;
      s.champVersion = s.obj.version;
      s.hasChampion = true;
      s.pubChamp = std::make_shared<const Genome>(s.champion);
      SaveChampion(s);
    }
    else if (!s.pubChamp && s.hasChampion)
      s.pubChamp = std::make_shared<const Genome>(s.champion);

    // novelty: the cells the genomes reached join the archive
    int added = 0;
    for (EpisodeResult& r : res)
      for (Cell& c : r.found)
        if (!s.archive.Has(c.key))
        {
          s.archive.Add(std::move(c));
          added++;
        }
    if (added)
      s.archiveDirty = true;

    Log(1, "%s: generation %d from %s: best %.1f, mean %.1f, %d species, %lld frames in %.1f s (%.0f fps), +%d cells "
           "(%d)%s",
        s.rom->title.c_str(), s.neat.generation(), fromStart ? "start" : "a deep cell", genBest, avg,
        s.neat.speciesCount(), static_cast<long long>(frames), secs, secs > 0 ? frames / secs : 0.0, added,
        s.archive.size(), newChamp ? " - new champion" : "");
    (void)newCellsChamp;

    // background exploration, about a tenth of the generation's frames
    RunExplore(s, std::max<int64_t>(frames / 10, 2000), false);
    if (stop)
      return;

    s.neat.Epoch(rng);

    // re-learn every 20 generations, or sooner when the archive got 25% deeper
    const int depth = s.archive.maxDepth();
    if (s.neat.generation() - s.lastLearnGen >= kRelearnEvery ||
        (depth >= s.lastLearnDepth + 4 && depth >= s.lastLearnDepth * 5 / 4))
      RunLearn(s, true);
    Publish(s);
  }

  // ---- the session loop --------------------------------------------------------------------------

  void RunSession(Rom& rom)
  {
    Session s;
    s.rom = &rom;
    s.dir = JoinPath(cfg.dataDir, rom.id);
    MakeDirs(s.dir);
    std::string err;
    if (!ReadRomFile(rom.path, s.image) || !s.emu.Load(s.image, &err))
    {
      Log(3, "%s: cannot load (%s)", rom.title.c_str(), err.c_str());
      rom.bad = true;
      return;
    }
    rom.lastPlayed = Now();
    s.hours = rom.hours;
    s.since = Clock::now();
    LoadSession(s);
    s.hours = std::max(s.hours, rom.hours);
    if (s.hasChampion)
      s.pubChamp = std::make_shared<const Genome>(s.champion);
    Log(1, "%s: id %s, %.2f h trained, phase %s, generation %d, %d archive cells", rom.title.c_str(), rom.id.c_str(),
        s.hours, PhaseName(s.phase), s.neat.generation(), s.archive.size());
    {
      std::lock_guard<std::mutex> lock(mu);
      romSerial++;
      romImage = std::make_shared<const std::vector<uint8_t>>(s.image);
      std::lock_guard<std::mutex> jl(jobMu);
      jobImage = romImage;
      jobImageSerial = romSerial;
    }
    Publish(s);
    SaveMeta(s);

    const auto began = Clock::now();
    auto lastSave = began;
    throttle.Reset();
    while (!stop)
    {
      if (cfg.switchMinutes > 0 &&
          std::chrono::duration<double>(Clock::now() - began).count() >= cfg.switchMinutes * 60.0 && cfg.onlyRom.empty())
        break;
      switch (s.phase)
      {
        case Phase::FindGameplay: RunFind(s); break;
        case Phase::Explore: RunExplore(s, 0, true); break;
        case Phase::Learn: RunLearn(s, false); break;
        case Phase::Evolve: RunGeneration(s); break;
        default: s.phase = Phase::FindGameplay; break;
      }
      if (std::chrono::duration<double>(Clock::now() - lastSave).count() >= kAutosaveSeconds)
      {
        SaveAll(s);
        lastSave = Clock::now();
      }
      UpdateStats(s);
    }
    const auto t0 = Clock::now();
    SaveAll(s);
    Log(1, "%s: saved in %.0f ms (%.2f h trained)", rom.title.c_str(),
        std::chrono::duration<double, std::milli>(Clock::now() - t0).count(), s.hours);
  }

  void TrainMain()
  {
    SetStatus("Scanning ROMs...");
    MakeDirs(cfg.dataDir);
    if (cfg.resetAll)
    {
      int n = 0;
      for (const std::string& d : ListDirs(cfg.dataDir))
        if (d.size() == 40 && d.find_first_not_of("0123456789abcdef") == std::string::npos)
          n += RemoveTree(JoinPath(cfg.dataDir, d)) ? 1 : 0;
      Log(1, "reset: removed the learning of %d ROMs", n);
    }
    std::vector<Rom> roms = ScanLibrary();
    {
      std::lock_guard<std::mutex> lock(mu);
      stats.roms = 0;
      for (const Rom& r : roms)
        stats.roms += r.bad ? 0 : 1;
    }
    Log(1, "%zu ROMs found in %s%s%s (%d playable)", roms.size(), cfg.bundledDir.c_str(), cfg.romDir.empty() ? "" : " and ",
        cfg.romDir.c_str(), stats.roms);
    while (!stop)
    {
      const int i = PickRom(roms);
      if (i < 0)
      {
        SetStatus("No playable .nes ROMs: add some to the add-on's roms folder or choose a ROM folder");
        while (!stop)
          std::this_thread::sleep_for(std::chrono::milliseconds(50));
        return;
      }
      RunSession(roms[static_cast<size_t>(i)]);
    }
  }

  // ---- display thread (spec 5) -----------------------------------------------------------------

  void PublishFrame(const std::vector<uint32_t>& px)
  {
    std::lock_guard<std::mutex> lock(frameMu);
    frame = px;
    frameSerial++;
  }

  void DisplayMain()
  {
    Emu emu;
    uint64_t loadedSerial = 0;
    bool loaded = false;
    std::vector<uint32_t> px(kScreenW * kScreenH, 0);
    Rng drng(cfg.seed ? cfg.seed * 7 + 1 : std::random_device{}());
    enum Mode
    {
      M_NONE,
      M_FIND,
      M_EXPLORE,
      M_CHAMP,
      M_HOLD
    } mode = M_NONE;
    Episode ep;
    std::shared_ptr<const Genome> champ;
    std::shared_ptr<const Objectives> objHold;
    std::shared_ptr<const std::string> startHold;
    std::shared_ptr<const std::array<uint8_t, kRamSize>> ramHold;
    int seg = 0, hold = 0, motifLeft = 0;
    uint8_t motif = 0;
    double runBest = 0;
    std::string raw;
    const auto period = std::chrono::duration<double>(1.0 / 60.0988);
    auto next = Clock::now();
    while (!stop)
    {
      uint64_t serial;
      std::shared_ptr<const std::vector<uint8_t>> image;
      std::shared_ptr<const std::string> st, deep;
      std::shared_ptr<const std::array<uint8_t, kRamSize>> sram;
      std::shared_ptr<const Objectives> ob;
      std::shared_ptr<const Genome> ch;
      uint64_t skey;
      Phase ph;
      {
        std::lock_guard<std::mutex> lock(mu);
        serial = romSerial;
        image = romImage;
        st = startState;
        sram = startRam;
        skey = startKey;
        deep = deepest;
        ob = obj;
        ch = champion;
        ph = phase;
      }
      if (serial != loadedSerial)
      {
        loadedSerial = serial;
        loaded = image && emu.Load(*image);
        mode = M_NONE;
      }
      if (!loaded)
      {
        std::this_thread::sleep_for(std::chrono::milliseconds(30));
        next = Clock::now();
        continue;
      }
      if (mode == M_NONE)
      {
        seg = 0;
        if (ch && st && sram && ob && ph == Phase::Evolve)
        {
          champ = ch;
          objHold = ob;
          startHold = st;
          ramHold = sram;
          Episode::Setup setup;
          setup.startState = startHold.get();
          setup.startKey = skey;
          setup.obj = objHold.get();
          setup.startRam = ramHold->data();
          mode = ep.Begin(emu, *champ, setup) ? M_CHAMP : M_NONE;
          runBest = 0;
        }
        if (mode == M_NONE && deep && Decompress(*deep, raw) && emu.Restore(raw))
          mode = M_EXPLORE;
        if (mode == M_NONE)
        {
          emu.Power();
          mode = M_FIND;
        }
      }
      bool ran = true;
      switch (mode)
      {
        case M_CHAMP:
          if (!ep.Step(px.data()))
          {
            mode = M_HOLD;
            hold = 60;
          }
          runBest = std::max(runBest, ep.value());
          break;
        case M_HOLD:
          ran = false;
          if (--hold <= 0)
            mode = M_NONE;
          break;
        case M_EXPLORE:
        case M_FIND:
        {
          if (motifLeft-- <= 0)
          {
            motif = RandomMotifButtons(drng);
            motifLeft = RandomMotifLength(drng);
          }
          uint8_t b = motif;
          if (mode == M_FIND)
          {
            if (seg % 90 < 5)
              b |= BTN_START;
            if (drng.Chance(0.10))
              b |= BTN_A;
          }
          emu.Frame(b, px.data());
          seg++;
          // explore segments last 10 s; leave "find" as soon as there is something better
          if ((mode == M_EXPLORE && seg >= 600) || (mode == M_FIND && (seg >= kFindMaxFrames || (deep && seg % 300 == 0))))
            mode = M_NONE;
          if (mode == M_EXPLORE && ch && ph == Phase::Evolve && seg % 60 == 0)
            mode = M_NONE;
          break;
        }
        default: break;
      }
      if (ran)
        PublishFrame(px);
      {
        std::lock_guard<std::mutex> lock(mu);
        stats.mode = mode == M_CHAMP || mode == M_HOLD ? "champion" : mode == M_EXPLORE ? "exploring" : "finding gameplay";
        stats.value = mode == M_CHAMP || mode == M_HOLD ? ep.value() : 0.0;
        stats.runBest = runBest;
        stats.runFrame = mode == M_CHAMP || mode == M_HOLD ? ep.frame() : seg;
      }
      next += std::chrono::duration_cast<Clock::duration>(period);
      const auto now = Clock::now();
      if (next < now - std::chrono::milliseconds(250))
        next = now;
      // sleep in small steps so Stop() is answered within a frame
      while (!stop && Clock::now() < next)
        std::this_thread::sleep_for(std::min<Clock::duration>(next - Clock::now(), std::chrono::milliseconds(5)));
    }
  }
};

Arcade::Arcade() : m(new Impl) {}

Arcade::~Arcade() { Stop(); }

void Arcade::Start(const Config& cfg)
{
  Stop();
  m.reset(new Impl);
  m->cfg = cfg;
  m->cfg.threads = std::max(1, cfg.threads);
  m->cfg.population = std::min(300, std::max(25, cfg.population));
  m->throttle.SetCap(cfg.cpuCap);
  m->rng.Seed(cfg.seed ? cfg.seed
                       : (static_cast<uint64_t>(std::random_device{}()) << 32) ^ std::random_device{}() ^
                             static_cast<uint64_t>(Clock::now().time_since_epoch().count()));
  m->stop = false;
  m_running = true;
  for (int i = 1; i < m->cfg.threads; i++)
    m->helpers.emplace_back([this, i] { m->HelperMain(i); });
  m->train = std::thread([this] { m->TrainMain(); });
  if (m->cfg.display)
    m->display = std::thread([this] { m->DisplayMain(); });
}

void Arcade::Stop()
{
  if (!m_running)
    return;
  m->stop = true;
  {
    std::lock_guard<std::mutex> lock(m->jobMu);
  }
  m->jobCv.notify_all();
  m->doneCv.notify_all();
  if (m->display.joinable())
    m->display.join();
  if (m->train.joinable())
    m->train.join();
  for (std::thread& t : m->helpers)
    if (t.joinable())
      t.join();
  m->helpers.clear();
  m_running = false;
}

bool Arcade::CopyFrame(uint64_t& serial, std::vector<uint32_t>& out)
{
  std::lock_guard<std::mutex> lock(m->frameMu);
  if (m->frameSerial == serial || m->frame.empty())
    return false;
  out = m->frame;
  serial = m->frameSerial;
  return true;
}

Stats Arcade::GetStats()
{
  std::lock_guard<std::mutex> lock(m->mu);
  return m->stats;
}

} // namespace arcade
