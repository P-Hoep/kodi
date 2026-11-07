// Just enough JSON to read fonts.json (numbers, strings, arrays, objects).
#pragma once
#include <cstdlib>
#include <fstream>
#include <map>
#include <sstream>
#include <stdexcept>
#include <string>
#include <vector>

namespace sandclock {

struct Json {
    enum Type { Null, Num, Str, Arr, Obj } type = Null;
    double num = 0;
    std::string str;
    std::vector<Json> arr;
    std::map<std::string, Json> obj;

    const Json& at(const std::string& key) const {
        auto it = obj.find(key);
        if (it == obj.end()) throw std::runtime_error("json: missing key " + key);
        return it->second;
    }

    static Json parse(const std::string& text) {
        Parser p{text, 0};
        Json v = p.value();
        return v;
    }

    static std::string read_file(const std::string& path) {
        std::ifstream in(path, std::ios::binary);
        if (!in) throw std::runtime_error("cannot open " + path);
        std::stringstream ss;
        ss << in.rdbuf();
        return ss.str();
    }

private:
    struct Parser {
        const std::string& s;
        size_t i;

        void ws() { while (i < s.size() && (s[i] == ' ' || s[i] == '\n' || s[i] == '\t' || s[i] == '\r')) ++i; }
        void expect(char c) {
            ws();
            if (i >= s.size() || s[i] != c) throw std::runtime_error(std::string("json: expected ") + c);
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
                        case 't': out += '\t'; break;
                        case 'u': out += '?'; i += 4; break;
                        default: out += s[i];
                    }
                } else {
                    out += s[i];
                }
                ++i;
            }
            ++i;
            return out;
        }
        Json value() {
            ws();
            Json v;
            if (i >= s.size()) throw std::runtime_error("json: unexpected end");
            char c = s[i];
            if (c == '{') {
                v.type = Obj;
                ++i;
                ws();
                if (s[i] == '}') { ++i; return v; }
                while (true) {
                    std::string key = string();
                    expect(':');
                    v.obj[key] = value();
                    ws();
                    if (s[i] == ',') { ++i; continue; }
                    expect('}');
                    break;
                }
            } else if (c == '[') {
                v.type = Arr;
                ++i;
                ws();
                if (s[i] == ']') { ++i; return v; }
                while (true) {
                    v.arr.push_back(value());
                    ws();
                    if (s[i] == ',') { ++i; continue; }
                    expect(']');
                    break;
                }
            } else if (c == '"') {
                v.type = Str;
                v.str = string();
            } else if (s.compare(i, 4, "true") == 0) {
                v.type = Num; v.num = 1; i += 4;
            } else if (s.compare(i, 5, "false") == 0) {
                v.type = Num; v.num = 0; i += 5;
            } else if (s.compare(i, 4, "null") == 0) {
                i += 4;
            } else {
                char* end = nullptr;
                v.type = Num;
                v.num = std::strtod(s.c_str() + i, &end);
                if (end == s.c_str() + i) throw std::runtime_error("json: bad value");
                i = end - s.c_str();
            }
            return v;
        }
    };
};

}  // namespace sandclock
