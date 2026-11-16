// M1 check: the emulator loads a ROM, runs fast, its savestates round-trip,
// and two Emu instances on two threads run independently (bit-identical to
// running them one after the other).
//
//   emu_test <rom.nes> [frames]
#include "Emu.h"
#include "Store.h"

#include <chrono>
#include <cstdio>
#include <cstring>
#include <random>
#include <thread>

using namespace arcade;

static uint64_t Run(Emu& e, uint32_t seed, int frames, bool video, std::vector<uint32_t>* lastFrame = nullptr)
{
  std::mt19937 rng(seed);
  std::vector<uint32_t> px(kScreenW * kScreenH);
  uint8_t b = 0;
  uint64_t h = 1469598103934665603ULL;
  for (int f = 0; f < frames; f++)
  {
    if (f % 8 == 0)
      b = static_cast<uint8_t>(rng() & 0xF7); // no Start
    if (f % 200 == 100)
      b |= BTN_START;
    e.Frame(b, video ? px.data() : nullptr);
    const uint8_t* ram = e.Ram();
    for (int i = 0; i < kRamSize; i++)
      h = (h ^ ram[i]) * 1099511628211ULL;
  }
  if (lastFrame)
    *lastFrame = px;
  return h;
}

int main(int argc, char** argv)
{
  if (argc < 2)
  {
    std::printf("usage: emu_test rom.nes [frames]\n");
    return 2;
  }
  const int frames = argc > 2 ? std::atoi(argv[2]) : 6000;
  std::vector<uint8_t> image;
  if (!ReadFile(argv[1], image))
  {
    std::printf("cannot read %s\n", argv[1]);
    return 1;
  }
  int fails = 0;
  Emu a, b;
  std::string err;
  if (!a.Load(image, &err) || !b.Load(image, &err))
  {
    std::printf("load failed: %s\n", err.c_str());
    return 1;
  }

  using clk = std::chrono::steady_clock;
  auto t0 = clk::now();
  const uint64_t h1 = Run(a, 7, frames, false);
  double s = std::chrono::duration<double>(clk::now() - t0).count();
  std::printf("no video: %d frames in %.2fs = %.0f fps\n", frames, s, frames / s);

  a.Power();
  t0 = clk::now();
  std::vector<uint32_t> last;
  const uint64_t h1v = Run(a, 7, frames, true, &last);
  s = std::chrono::duration<double>(clk::now() - t0).count();
  std::printf("video:    %d frames in %.2fs = %.0f fps\n", frames, s, frames / s);
  if (h1 != h1v)
  {
    std::printf("FAIL: rendering video changed the RAM trajectory\n");
    fails++;
  }

  // savestate round trip and timing
  std::string st;
  t0 = clk::now();
  for (int i = 0; i < 200; i++)
    a.Save(st);
  const double saveUs = std::chrono::duration<double, std::micro>(clk::now() - t0).count() / 200;
  t0 = clk::now();
  for (int i = 0; i < 200; i++)
    a.Restore(st);
  const double loadUs = std::chrono::duration<double, std::micro>(clk::now() - t0).count() / 200;
  std::string z = Compress(st);
  std::printf("state %zu bytes (%zu zlib), save %.0f us, restore %.0f us\n", st.size(), z.size(), saveUs, loadUs);
  const uint64_t ha = Run(a, 99, 600, false);
  a.Restore(st);
  const uint64_t hb = Run(a, 99, 600, false);
  if (ha != hb)
  {
    std::printf("FAIL: restore is not deterministic\n");
    fails++;
  }
  std::string unz;
  if (!Decompress(z, unz) || unz != st)
  {
    std::printf("FAIL: zlib round trip\n");
    fails++;
  }

  // two instances on two threads
  a.Power();
  b.Power();
  uint64_t ta = 0, tb = 0;
  std::thread th1([&] { ta = Run(a, 7, frames, true); });
  std::thread th2([&] { tb = Run(b, 1234, frames, false); });
  th1.join();
  th2.join();
  Emu c;
  c.Load(image);
  const uint64_t tc = Run(c, 1234, frames, false);
  if (ta != h1 || tb != tc)
  {
    std::printf("FAIL: parallel instances differ from serial (%d %d)\n", ta == h1, tb == tc);
    fails++;
  }
  else
    std::printf("two instances in parallel: identical to serial\n");

  // a PPM of the last frame, for a look
  if (FILE* f = std::fopen("/tmp/emu_test.ppm", "wb"))
  {
    std::fprintf(f, "P6\n256 240\n255\n");
    for (uint32_t p : last)
    {
      const unsigned char rgb[3] = {static_cast<unsigned char>(p), static_cast<unsigned char>(p >> 8),
                                    static_cast<unsigned char>(p >> 16)};
      std::fwrite(rgb, 1, 3, f);
    }
    std::fclose(f);
  }
  std::printf(fails ? "FAILED\n" : "OK\n");
  return fails ? 1 : 0;
}
