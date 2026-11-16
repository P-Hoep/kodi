#include "Emu.h"

#include "api/NstApiCheats.hpp"
#include "api/NstApiEmulator.hpp"
#include "api/NstApiInput.hpp"
#include "api/NstApiMachine.hpp"
#include "api/NstApiSound.hpp"
#include "api/NstApiVideo.hpp"

#include <sstream>

namespace arcade
{

using namespace Nes::Api;

struct Emu::Impl
{
  Nes::Api::Emulator emulator;
  Input::Controllers controllers;
  Video::Output video;
};

Emu::Emu() : m(new Impl) {}

Emu::~Emu()
{
  if (m_loaded)
  {
    Machine machine(m->emulator);
    machine.Power(false);
    machine.Unload();
  }
}

bool Emu::Load(const std::vector<uint8_t>& image, std::string* error)
{
  Machine machine(m->emulator);
  std::string buf(reinterpret_cast<const char*>(image.data()), image.size());
  std::istringstream in(buf);
  const Nes::Result r = machine.Load(in, Machine::FAVORED_NES_NTSC);
  if (NES_FAILED(r))
  {
    if (error)
    {
      switch (r)
      {
        case Nes::RESULT_ERR_UNSUPPORTED_MAPPER: *error = "unsupported mapper"; break;
        case Nes::RESULT_ERR_CORRUPT_FILE: *error = "corrupt file"; break;
        case Nes::RESULT_ERR_INVALID_FILE: *error = "invalid file"; break;
        case Nes::RESULT_ERR_OUT_OF_MEMORY: *error = "out of memory"; break;
        default: *error = "load failed (" + std::to_string(static_cast<int>(r)) + ")"; break;
      }
    }
    return false;
  }
  if (machine.Is(Machine::DISK) || machine.Is(Machine::SOUND))
  {
    if (error)
      *error = "not a cartridge";
    machine.Unload();
    return false;
  }
  machine.SetMode(Machine::NTSC);

  Input input(m->emulator);
  input.ConnectController(0, Input::PAD1);
  input.ConnectController(1, Input::UNCONNECTED);

  Video video(m->emulator);
  Video::RenderState rs;
  rs.filter = Video::RenderState::FILTER_NONE;
  rs.width = Video::Output::WIDTH;
  rs.height = Video::Output::HEIGHT;
  rs.bits.count = 32;
  // little-endian R G B X bytes, ready for a GL_RGBA texture
  rs.bits.mask.r = 0x000000ff;
  rs.bits.mask.g = 0x0000ff00;
  rs.bits.mask.b = 0x00ff0000;
  if (NES_FAILED(video.SetRenderState(rs)))
  {
    if (error)
      *error = "render state rejected";
    machine.Unload();
    return false;
  }
  video.EnableUnlimSprites(false);

  Sound(m->emulator).Mute(true);
  machine.SetRamPowerState(0); // zeros: power-on is deterministic
  machine.Power(true);
  m_loaded = true;
  m_frames = 0;
  return true;
}

void Emu::Power()
{
  if (!m_loaded)
    return;
  Machine machine(m->emulator);
  machine.Power(false);
  machine.Power(true);
}

void Emu::Frame(uint8_t buttons, uint32_t* rgba)
{
  if (!m_loaded)
    return;
  m->controllers.pad[0].buttons = buttons;
  if (rgba)
  {
    m->video.pixels = rgba;
    m->video.pitch = kScreenW * 4;
    m->emulator.Execute(&m->video, nullptr, &m->controllers);
  }
  else
  {
    m->emulator.Execute(nullptr, nullptr, &m->controllers);
  }
  m_frames++;
}

const uint8_t* Emu::Ram() const
{
  Cheats cheats(m->emulator);
  return cheats.GetRam();
}

bool Emu::Save(std::string& out) const
{
  if (!m_loaded)
    return false;
  std::ostringstream os(std::ios::out | std::ios::binary);
  if (NES_FAILED(Machine(m->emulator).SaveState(os, Machine::NO_COMPRESSION)))
    return false;
  out = os.str();
  return true;
}

bool Emu::Restore(const std::string& state)
{
  if (!m_loaded || state.empty())
    return false;
  std::istringstream is(state, std::ios::in | std::ios::binary);
  return NES_SUCCEEDED(Machine(m->emulator).LoadState(is));
}

} // namespace arcade
