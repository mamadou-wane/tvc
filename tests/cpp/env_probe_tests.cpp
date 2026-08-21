// tests/cpp/env_probe_tests.cpp: cpuidle_json tests. Plain main() + CHECK.
#include "../../src/env_probe.hpp"

#include <cstdio>
#include <cstdlib>
#include <filesystem>
#include <fstream>
#include <string>
#include <vector>

#define CHECK(cond) do { if (!(cond)) { \
    std::fprintf(stderr, "FAIL %s:%d: %s\n", __FILE__, __LINE__, #cond); \
    std::exit(1); } } while (0)

namespace fs = std::filesystem;

namespace {

// Fresh temp dir per test, trailing slash to match cpu_root's contract.
std::string make_root() {
    std::string tmpl = (fs::temp_directory_path() / "env_probe_tests_XXXXXX").string();
    std::vector<char> buf(tmpl.begin(), tmpl.end());
    buf.push_back('\0');
    CHECK(::mkdtemp(buf.data()) != nullptr);
    return std::string(buf.data()) + "/";
}

void write_file(const std::string& path, const std::string& content) {
    fs::create_directories(fs::path(path).parent_path());
    std::ofstream f(path);
    CHECK(f.good());
    f << content;
}

void write_driver(const std::string& root, const std::string& driver) {
    write_file(root + "cpuidle/current_driver", driver);
}

void write_disable(const std::string& root, int cpu, int state, const std::string& value) {
    write_file(root + "cpu" + std::to_string(cpu) + "/cpuidle/state" +
                std::to_string(state) + "/disable", value);
}

void write_name(const std::string& root, int cpu, int state, const std::string& name) {
    write_file(root + "cpu" + std::to_string(cpu) + "/cpuidle/state" +
                std::to_string(state) + "/name", name);
}

void write_latency(const std::string& root, int cpu, int state, long latency) {
    write_file(root + "cpu" + std::to_string(cpu) + "/cpuidle/state" +
                std::to_string(state) + "/latency", std::to_string(latency));
}

// Full state entry: disable + name + latency.
void write_state(const std::string& root, int cpu, int state,
                 const std::string& name, long latency, const std::string& disable) {
    write_name(root, cpu, state, name);
    write_latency(root, cpu, state, latency);
    write_disable(root, cpu, state, disable);
}

void test_uniform_two_cpus_three_states() {
    const std::string root = make_root();
    write_driver(root, "acpi_idle");
    for (int cpu = 0; cpu < 2; ++cpu) {
        write_state(root, cpu, 0, "POLL", 0, "1");
        write_state(root, cpu, 1, "C1", 1, "1");
        write_state(root, cpu, 2, "C2", 18, "1");
    }
    const std::string expected =
        "{ \"driver\": \"acpi_idle\", \"cpus\": 2, \"states\": [ "
        "{ \"name\": \"POLL\", \"latency_us\": 0, \"disabled\": 2 }, "
        "{ \"name\": \"C1\", \"latency_us\": 1, \"disabled\": 2 }, "
        "{ \"name\": \"C2\", \"latency_us\": 18, \"disabled\": 2 } ] }";
    CHECK(env_probe::cpuidle_json(root) == expected);
}

void test_divergent_disable() {
    const std::string root = make_root();
    write_driver(root, "acpi_idle");
    for (int cpu = 0; cpu < 2; ++cpu) {
        write_state(root, cpu, 0, "POLL", 0, "1");
        write_state(root, cpu, 1, "C1", 1, "1");
        write_state(root, cpu, 2, "C2", 18, "1");
    }
    write_disable(root, 1, 1, "0");  // cpu1 state1 diverges
    const std::string expected =
        "{ \"driver\": \"acpi_idle\", \"cpus\": 2, \"states\": [ "
        "{ \"name\": \"POLL\", \"latency_us\": 0, \"disabled\": 2 }, "
        "{ \"name\": \"C1\", \"latency_us\": 1, \"disabled\": 1 }, "
        "{ \"name\": \"C2\", \"latency_us\": 18, \"disabled\": 2 } ] }";
    CHECK(env_probe::cpuidle_json(root) == expected);
}

void test_empty_root() {
    const std::string root = make_root();
    const std::string expected = "{ \"driver\": \"unknown\", \"cpus\": 0, \"states\": [] }";
    CHECK(env_probe::cpuidle_json(root) == expected);
}

void test_ragged_missing_state() {
    const std::string root = make_root();
    write_driver(root, "acpi_idle");
    write_state(root, 0, 0, "POLL", 0, "1");
    write_state(root, 0, 1, "C1", 1, "1");
    write_state(root, 0, 2, "C2", 18, "1");
    write_state(root, 1, 0, "POLL", 0, "1");
    write_state(root, 1, 1, "C1", 1, "1");
    // cpu1 has no state2 dir at all.
    const std::string expected =
        "{ \"driver\": \"acpi_idle\", \"cpus\": 2, \"states\": [ "
        "{ \"name\": \"POLL\", \"latency_us\": 0, \"disabled\": 2 }, "
        "{ \"name\": \"C1\", \"latency_us\": 1, \"disabled\": 2 }, "
        "{ \"name\": \"C2\", \"latency_us\": 18, \"disabled\": 1 } ] }";
    CHECK(env_probe::cpuidle_json(root) == expected);
}

void test_missing_latency_file() {
    const std::string root = make_root();
    write_driver(root, "acpi_idle");
    write_name(root, 0, 0, "POLL");
    write_disable(root, 0, 0, "1");
    // cpu0 state0 has no latency file; cpu1 does (irrelevant: cpu0 is first).
    write_state(root, 1, 0, "POLL", 5, "1");
    const std::string expected =
        "{ \"driver\": \"acpi_idle\", \"cpus\": 2, \"states\": [ "
        "{ \"name\": \"POLL\", \"latency_us\": -1, \"disabled\": 2 } ] }";
    CHECK(env_probe::cpuidle_json(root) == expected);
}

void test_driver_present_no_cpu_dirs() {
    const std::string root = make_root();
    write_driver(root, "intel_idle");
    const std::string expected = "{ \"driver\": \"intel_idle\", \"cpus\": 0, \"states\": [] }";
    CHECK(env_probe::cpuidle_json(root) == expected);
}

}  // namespace

int main() {
    test_uniform_two_cpus_three_states();
    test_divergent_disable();
    test_empty_root();
    test_ragged_missing_state();
    test_missing_latency_file();
    test_driver_present_no_cpu_dirs();
    std::puts("env_probe_tests: ok");
    return 0;
}
