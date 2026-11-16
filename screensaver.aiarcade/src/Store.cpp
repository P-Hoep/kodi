#include "Store.h"

#include <zlib.h>

#include <algorithm>
#include <cstdio>
#include <cstring>
#include <filesystem>
#include <fstream>
#include <random>
#include <system_error>

namespace fs = std::filesystem;

namespace arcade
{

bool ReadFile(const std::string& path, std::string& out)
{
  std::ifstream f(path, std::ios::binary);
  if (!f)
    return false;
  f.seekg(0, std::ios::end);
  const std::streamoff n = f.tellg();
  if (n < 0 || n > (std::streamoff(256) << 20))
    return false;
  f.seekg(0);
  out.resize(static_cast<size_t>(n));
  if (n > 0)
    f.read(&out[0], n);
  return static_cast<bool>(f);
}

bool ReadFile(const std::string& path, std::vector<uint8_t>& out)
{
  std::string s;
  if (!ReadFile(path, s))
    return false;
  out.assign(s.begin(), s.end());
  return true;
}

bool WriteFileAtomic(const std::string& path, const std::string& data)
{
  static thread_local std::mt19937 rng(std::random_device{}());
  const std::string tmp = path + ".tmp" + std::to_string(rng() % 100000);
  {
    std::ofstream f(tmp, std::ios::binary | std::ios::trunc);
    if (!f)
      return false;
    f.write(data.data(), static_cast<std::streamsize>(data.size()));
    f.flush();
    if (!f)
    {
      std::error_code ec;
      fs::remove(tmp, ec);
      return false;
    }
  }
  std::error_code ec;
  fs::rename(tmp, path, ec);
  if (ec)
  {
    fs::remove(tmp, ec);
    return false;
  }
  return true;
}

bool MakeDirs(const std::string& path)
{
  std::error_code ec;
  fs::create_directories(path, ec);
  return fs::is_directory(path, ec);
}

bool FileExists(const std::string& path)
{
  std::error_code ec;
  return fs::exists(path, ec);
}

bool RemoveTree(const std::string& path)
{
  std::error_code ec;
  fs::remove_all(path, ec);
  return !ec;
}

std::vector<std::string> ListDirs(const std::string& path)
{
  std::vector<std::string> out;
  std::error_code ec;
  for (fs::directory_iterator it(path, ec), end; !ec && it != end; it.increment(ec))
    if (it->is_directory(ec))
      out.push_back(it->path().filename().string());
  std::sort(out.begin(), out.end());
  return out;
}

static bool IsNes(const fs::path& p)
{
  std::string ext = p.extension().string();
  std::transform(ext.begin(), ext.end(), ext.begin(), [](unsigned char c) { return static_cast<char>(std::tolower(c)); });
  return ext == ".nes";
}

std::vector<std::string> ListNesFiles(const std::string& dir, bool recursive)
{
  std::vector<std::string> out;
  std::error_code ec;
  if (recursive)
  {
    for (fs::recursive_directory_iterator it(dir, fs::directory_options::skip_permission_denied, ec), end;
         !ec && it != end; it.increment(ec))
      if (it->is_regular_file(ec) && IsNes(it->path()))
        out.push_back(it->path().string());
  }
  else
  {
    for (fs::directory_iterator it(dir, ec), end; !ec && it != end; it.increment(ec))
      if (it->is_regular_file(ec) && IsNes(it->path()))
        out.push_back(it->path().string());
  }
  std::sort(out.begin(), out.end());
  return out;
}

std::string Compress(const std::string& raw, int level)
{
  uLongf cap = compressBound(static_cast<uLong>(raw.size()));
  std::string out(4 + cap, '\0');
  const uint32_t n = static_cast<uint32_t>(raw.size());
  for (int i = 0; i < 4; i++)
    out[i] = static_cast<char>((n >> (8 * i)) & 0xFF);
  if (compress2(reinterpret_cast<Bytef*>(&out[4]), &cap, reinterpret_cast<const Bytef*>(raw.data()),
                static_cast<uLong>(raw.size()), level) != Z_OK)
    return {};
  out.resize(4 + cap);
  return out;
}

bool Decompress(const std::string& z, std::string& raw)
{
  if (z.size() < 4)
    return false;
  uint32_t n = 0;
  for (int i = 0; i < 4; i++)
    n |= static_cast<uint32_t>(static_cast<uint8_t>(z[i])) << (8 * i);
  if (n > (256u << 20))
    return false;
  raw.resize(n);
  uLongf len = n;
  if (uncompress(reinterpret_cast<Bytef*>(n ? &raw[0] : nullptr), &len, reinterpret_cast<const Bytef*>(z.data() + 4),
                 static_cast<uLong>(z.size() - 4)) != Z_OK ||
      len != n)
    return false;
  return true;
}

// ---- SHA-1 (FIPS 180-4) -----------------------------------------------------

namespace
{
inline uint32_t Rol(uint32_t v, int b) { return (v << b) | (v >> (32 - b)); }

void Sha1Block(uint32_t h[5], const uint8_t* p)
{
  uint32_t w[80];
  for (int i = 0; i < 16; i++)
    w[i] = (uint32_t(p[4 * i]) << 24) | (uint32_t(p[4 * i + 1]) << 16) | (uint32_t(p[4 * i + 2]) << 8) | p[4 * i + 3];
  for (int i = 16; i < 80; i++)
    w[i] = Rol(w[i - 3] ^ w[i - 8] ^ w[i - 14] ^ w[i - 16], 1);
  uint32_t a = h[0], b = h[1], c = h[2], d = h[3], e = h[4];
  for (int i = 0; i < 80; i++)
  {
    uint32_t f, k;
    if (i < 20)
      f = (b & c) | (~b & d), k = 0x5A827999;
    else if (i < 40)
      f = b ^ c ^ d, k = 0x6ED9EBA1;
    else if (i < 60)
      f = (b & c) | (b & d) | (c & d), k = 0x8F1BBCDC;
    else
      f = b ^ c ^ d, k = 0xCA62C1D6;
    const uint32_t t = Rol(a, 5) + f + e + k + w[i];
    e = d;
    d = c;
    c = Rol(b, 30);
    b = a;
    a = t;
  }
  h[0] += a;
  h[1] += b;
  h[2] += c;
  h[3] += d;
  h[4] += e;
}
} // namespace

std::string Sha1Hex(const uint8_t* data, size_t len)
{
  uint32_t h[5] = {0x67452301, 0xEFCDAB89, 0x98BADCFE, 0x10325476, 0xC3D2E1F0};
  size_t i = 0;
  for (; i + 64 <= len; i += 64)
    Sha1Block(h, data + i);
  uint8_t tail[128] = {0};
  const size_t rest = len - i;
  if (rest)
    std::memcpy(tail, data + i, rest);
  tail[rest] = 0x80;
  const size_t tlen = rest + 1 + 8 <= 64 ? 64 : 128;
  const uint64_t bits = static_cast<uint64_t>(len) * 8;
  for (int k = 0; k < 8; k++)
    tail[tlen - 1 - k] = static_cast<uint8_t>(bits >> (8 * k));
  Sha1Block(h, tail);
  if (tlen == 128)
    Sha1Block(h, tail + 64);
  static const char* hex = "0123456789abcdef";
  std::string out;
  for (int k = 0; k < 5; k++)
    for (int s = 28; s >= 0; s -= 4)
      out.push_back(hex[(h[k] >> s) & 0xF]);
  return out;
}

} // namespace arcade
