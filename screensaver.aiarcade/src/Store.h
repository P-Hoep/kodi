// Files, compression and hashing: everything the trainer needs from the disk.
// Saves go to a temporary file first and are renamed into place, so a crash
// or power cut never leaves half a file behind.
#pragma once

#include <cstdint>
#include <string>
#include <vector>

namespace arcade
{

bool ReadFile(const std::string& path, std::vector<uint8_t>& out);
bool ReadFile(const std::string& path, std::string& out);
bool WriteFileAtomic(const std::string& path, const std::string& data);
bool MakeDirs(const std::string& path);
bool FileExists(const std::string& path);
bool RemoveTree(const std::string& path);
// Sub-directories of a directory (names only).
std::vector<std::string> ListDirs(const std::string& path);
// .nes files under a directory (full paths), sorted.
std::vector<std::string> ListNesFiles(const std::string& dir, bool recursive);

// zlib with a 4-byte length prefix. Decompress fails cleanly on bad input.
std::string Compress(const std::string& raw, int level = 6);
bool Decompress(const std::string& z, std::string& raw);

// SHA-1 as 40 lowercase hex digits.
std::string Sha1Hex(const uint8_t* data, size_t len);

// Little binary writer and reader for the .bin files.
struct BinWriter
{
  std::string s;
  void U8(uint8_t v) { s.push_back(static_cast<char>(v)); }
  void U32(uint32_t v)
  {
    for (int i = 0; i < 4; i++)
      s.push_back(static_cast<char>((v >> (8 * i)) & 0xFF));
  }
  void U64(uint64_t v)
  {
    U32(static_cast<uint32_t>(v));
    U32(static_cast<uint32_t>(v >> 32));
  }
  void I32(int32_t v) { U32(static_cast<uint32_t>(v)); }
  void F32(float v)
  {
    uint32_t u;
    static_assert(sizeof u == sizeof v, "float");
    __builtin_memcpy(&u, &v, 4);
    U32(u);
  }
  void F64(double v)
  {
    uint64_t u;
    __builtin_memcpy(&u, &v, 8);
    U64(u);
  }
  void Str(const std::string& v)
  {
    U32(static_cast<uint32_t>(v.size()));
    s += v;
  }
};

struct BinReader
{
  const std::string& s;
  size_t p = 0;
  bool ok = true;
  explicit BinReader(const std::string& str) : s(str) {}
  bool Need(size_t n)
  {
    if (!ok || p + n > s.size())
      ok = false;
    return ok;
  }
  uint8_t U8() { return Need(1) ? static_cast<uint8_t>(s[p++]) : 0; }
  uint32_t U32()
  {
    if (!Need(4))
      return 0;
    uint32_t v = 0;
    for (int i = 0; i < 4; i++)
      v |= static_cast<uint32_t>(static_cast<uint8_t>(s[p + i])) << (8 * i);
    p += 4;
    return v;
  }
  uint64_t U64()
  {
    const uint64_t lo = U32();
    return lo | (static_cast<uint64_t>(U32()) << 32);
  }
  int32_t I32() { return static_cast<int32_t>(U32()); }
  float F32()
  {
    const uint32_t u = U32();
    float v;
    __builtin_memcpy(&v, &u, 4);
    return v;
  }
  double F64()
  {
    const uint64_t u = U64();
    double v;
    __builtin_memcpy(&v, &u, 8);
    return v;
  }
  std::string Str(size_t maxLen = 64u << 20)
  {
    const uint32_t n = U32();
    if (n > maxLen || !Need(n))
    {
      ok = false;
      return {};
    }
    std::string v = s.substr(p, n);
    p += n;
    return v;
  }
};

} // namespace arcade
