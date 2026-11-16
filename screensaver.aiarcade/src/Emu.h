// One NES: a thin wrapper over Nestopia's class-based API (Nes::Api::Emulator).
//
// Each Emu owns its own Nes::Api::Emulator, so several can run side by side
// on different threads (the display thread and the training threads). The
// Nestopia headers stay in Emu.cpp.
#pragma once

#include <cstdint>
#include <memory>
#include <string>
#include <vector>

namespace arcade
{

// Pad bits, in the order of the NEAT outputs: A, B, Select, Start, Up, Down, Left, Right.
enum : uint8_t
{
  BTN_A = 0x01,
  BTN_B = 0x02,
  BTN_SELECT = 0x04,
  BTN_START = 0x08,
  BTN_UP = 0x10,
  BTN_DOWN = 0x20,
  BTN_LEFT = 0x40,
  BTN_RIGHT = 0x80,
};

constexpr int kScreenW = 256, kScreenH = 240, kRamSize = 2048;

class Emu
{
public:
  Emu();
  ~Emu();
  Emu(const Emu&) = delete;
  Emu& operator=(const Emu&) = delete;

  // Load an iNES image (header included) and power the machine on.
  bool Load(const std::vector<uint8_t>& image, std::string* error = nullptr);
  bool Loaded() const { return m_loaded; }
  void Power(); // power cycle: back to the power-on state

  // Run one frame with these buttons held on pad 1. When rgba is given, the
  // finished frame is written there (256 x 240, 4 bytes a pixel, R G B X).
  void Frame(uint8_t buttons, uint32_t* rgba = nullptr);

  const uint8_t* Ram() const; // the 2 KB of CPU RAM

  // Savestates (uncompressed Nestopia state blocks).
  bool Save(std::string& out) const;
  bool Restore(const std::string& state);

  uint64_t frames() const { return m_frames; }

private:
  struct Impl;
  std::unique_ptr<Impl> m;
  bool m_loaded = false;
  uint64_t m_frames = 0;
};

} // namespace arcade
