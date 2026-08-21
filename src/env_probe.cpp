#include "env_probe.hpp"

#include <cerrno>
#include <cstdint>
#include <cstdio>
#include <cstdlib>
#include <glob.h>
#include <vector>

namespace env_probe {

std::string read_sysfs_line(const std::string& path) {
    FILE* f = std::fopen(path.c_str(), "r");
    if (!f) return "";
    char buf[256];
    std::string line;
    if (std::fgets(buf, sizeof(buf), f)) line = buf;
    std::fclose(f);
    while (!line.empty() && (line.back() == '\n' || line.back() == '\r')) line.pop_back();
    return line;
}

std::string sysfs_or_unknown(const std::string& path) {
    const std::string v = read_sysfs_line(path);
    return v.empty() ? "unknown" : v;
}

namespace {

// Same shape as main.cpp's to_i64.
bool to_i64(const char* s, std::int64_t& out) {
    char* end = nullptr;
    errno = 0;
    const long long v = std::strtoll(s, &end, 10);
    if (errno != 0 || end == s || *end != '\0') return false;
    out = v;
    return true;
}

}  // namespace

std::string cpuidle_json(const std::string& cpu_root) {
    const std::string driver = sysfs_or_unknown(cpu_root + "cpuidle/current_driver");

    // Default sorted glob: sorted order only decides which CPU supplies
    // names/latencies, since the kernel registers one state table per
    // driver, so any order is correct.
    glob_t g{};
    std::vector<std::string> cpu_dirs;
    if (glob((cpu_root + "cpu*/cpuidle").c_str(), 0, nullptr, &g) == 0) {
        for (std::size_t i = 0; i < g.gl_pathc; ++i) cpu_dirs.emplace_back(g.gl_pathv[i]);
    }
    globfree(&g);

    std::string states;
    for (int s = 0; ; ++s) {
        const std::string suffix = "/state" + std::to_string(s);
        int disabled = 0;
        int exposed = 0;
        std::string name;
        std::int64_t latency_us = -1;
        for (const auto& dir : cpu_dirs) {
            const std::string disable = read_sysfs_line(dir + suffix + "/disable");
            if (disable.empty()) continue;  // ragged tree: this CPU lacks the state
            if (exposed == 0) {
                name = sysfs_or_unknown(dir + suffix + "/name");
                std::int64_t v;
                latency_us = to_i64(read_sysfs_line(dir + suffix + "/latency").c_str(), v) ? v : -1;
            }
            ++exposed;
            if (disable == "1") ++disabled;
        }
        if (exposed == 0) break;  // no CPU exposes this state: stop
        if (!states.empty()) states += ", ";
        states += "{ \"name\": \"" + name + "\", \"latency_us\": " +
            std::to_string(latency_us) + ", \"disabled\": " + std::to_string(disabled) + " }";
    }

    return "{ \"driver\": \"" + driver + "\", \"cpus\": " + std::to_string(cpu_dirs.size()) +
        ", \"states\": [" + (states.empty() ? "" : " " + states + " ") + "] }";
}

}  // namespace env_probe
