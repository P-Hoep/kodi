// Just enough JSON for the aircraft feed and the font atlas: null, numbers, strings, arrays and
// objects. No Kodi and no GL, so it can be tested on its own. The feed is public data, but it is
// still parsed defensively: a malformed value is skipped, never trusted.
#pragma once
#include <cstdlib>
#include <fstream>
#include <map>
#include <sstream>
#include <stdexcept>
#include <string>
#include <vector>

namespace radar {

struct Json {
  enum Type { Null, Num, Str, Bool, Arr, Obj } type = Null;
  double num = 0;
  bool boolean = false;
  std::string str;
  std::vector<Json> arr;
  std::map<std::string, Json> obj;

  static Json parse(const std::string& text) {
    Parser p{text, 0};
    Json v = p.value();
    p.ws();
    if (p.i != text.size()) throw std::runtime_error("json: trailing text");
    return v;
  }

  static Json read_file(const std::string& path) {
    std::ifstream in(path, std::ios::binary);
    if (!in) throw std::runtime_error("cannot open " + path);
    std::stringstream ss;
    ss << in.rdbuf();
    return parse(ss.str());
  }

  bool is_obj() const { return type == Obj; }
  bool is_arr() const { return type == Arr; }
  bool is_num() const { return type == Num; }
  bool is_str() const { return type == Str; }

  const Json* get(const std::string& key) const {
    auto it = obj.find(key);
    return it == obj.end() ? nullptr : &it->second;
  }

  const Json& at(const std::string& key) const {
    const Json* v = get(key);
    if (!v) throw std::runtime_error("json: missing key " + key);
    return *v;
  }

  // Numbers may arrive as numbers or numeric strings ("ground" is not a number).
  bool number(double* out) const {
    if (type == Num) { *out = num; return true; }
    if (type == Str && !str.empty()) {
      char* end = nullptr;
      const double v = std::strtod(str.c_str(), &end);
      if (end && *end == '\0') { *out = v; return true; }
    }
    return false;
  }
  double num_or(const std::string& key, double fallback) const {
    double v = 0;
    const Json* j = get(key);
    return (j && j->number(&v)) ? v : fallback;
  }
  bool has_num(const std::string& key, double* out) const {
    const Json* j = get(key);
    return j && j->number(out);
  }
  std::string str_or(const std::string& key, const std::string& fallback = "") const {
    const Json* j = get(key);
    if (!j) return fallback;
    if (j->type == Str) return j->str;
    if (j->type == Num) {
      std::ostringstream ss;
      ss << j->num;
      return ss.str();
    }
    return fallback;
  }
  bool bool_or(const std::string& key, bool fallback = false) const {
    const Json* j = get(key);
    if (!j) return fallback;
    if (j->type == Bool) return j->boolean;
    if (j->type == Num) return j->num != 0;
    return fallback;
  }

 private:
  struct Parser {
    const std::string& s;
    size_t i;

    void ws() {
      while (i < s.size() &&
             (s[i] == ' ' || s[i] == '\n' || s[i] == '\t' || s[i] == '\r')) ++i;
    }
    void expect(char c) {
      ws();
      if (i >= s.size() || s[i] != c)
        throw std::runtime_error(std::string("json: expected ") + c);
      ++i;
    }
    std::string string() {
      expect('"');
      std::string out;
      while (i < s.size() && s[i] != '"') {
        if (s[i] == '\\' && i + 1 < s.size()) {
          ++i;
          switch (s[i]) {
            case 'n': out += '\n'; break;
            case 'r': out += '\r'; break;
            case 't': out += '\t'; break;
            case 'b': out += '\b'; break;
            case 'f': out += '\f'; break;
            case 'u': {
              // The feed is ASCII. Keep a placeholder rather than decoding UTF-16; enough to
              // keep the parser in step and to show odd registrations without breaking.
              i += 4;
              out += '?';
              break;
            }
            default: out += s[i];
          }
        } else {
          out += s[i];
        }
        ++i;
      }
      if (i >= s.size()) throw std::runtime_error("json: unterminated string");
      ++i;
      return out;
    }
    Json value() {
      ws();
      Json v;
      if (i >= s.size()) throw std::runtime_error("json: unexpected end");
      const char c = s[i];
      if (c == '{') {
        v.type = Obj;
        ++i;
        ws();
        if (i < s.size() && s[i] == '}') { ++i; return v; }
        while (true) {
          std::string key = string();
          expect(':');
          v.obj[key] = value();
          ws();
          if (i < s.size() && s[i] == ',') { ++i; continue; }
          expect('}');
          break;
        }
      } else if (c == '[') {
        v.type = Arr;
        ++i;
        ws();
        if (i < s.size() && s[i] == ']') { ++i; return v; }
        while (true) {
          v.arr.push_back(value());
          ws();
          if (i < s.size() && s[i] == ',') { ++i; continue; }
          expect(']');
          break;
        }
      } else if (c == '"') {
        v.type = Str;
        v.str = string();
      } else if (s.compare(i, 4, "true") == 0) {
        v.type = Bool;
        v.boolean = true;
        i += 4;
      } else if (s.compare(i, 5, "false") == 0) {
        v.type = Bool;
        v.boolean = false;
        i += 5;
      } else if (s.compare(i, 4, "null") == 0) {
        i += 4;
      } else {
        char* end = nullptr;
        v.type = Num;
        v.num = std::strtod(s.c_str() + i, &end);
        if (end == s.c_str() + i) throw std::runtime_error("json: bad value");
        i = static_cast<size_t>(end - s.c_str());
      }
      return v;
    }
  };
};

}  // namespace radar
