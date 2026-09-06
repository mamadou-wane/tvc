#include "../../src/model_types.hpp"
#include "../../src/control.hpp"

#include <array>
#include <bit>
#include <cfloat>
#include <cinttypes>
#include <cstdio>
#include <cstdlib>
#include <iostream>
#include <limits>
#include <span>
#include <sstream>
#include <string>
#include <type_traits>
#include <vector>

#define CHECK(cond) do { if (!(cond)) { \
    std::fprintf(stderr, "FAIL %s:%d: %s\n", __FILE__, __LINE__, #cond); \
    std::exit(1); } } while (0)

static_assert(sizeof(double) == sizeof(std::uint64_t));
static_assert(std::numeric_limits<double>::is_iec559);
static_assert(std::numeric_limits<double>::radix == 2);
static_assert(std::numeric_limits<double>::digits == 53);
static_assert(FLT_EVAL_METHOD == 0);
static_assert(std::is_aggregate_v<Observation>);
static_assert(std::is_aggregate_v<control::State>);
static_assert(std::is_same_v<decltype(Observation::tick), std::uint64_t>);
static_assert(std::is_same_v<decltype(Observation::theta), double>);
static_assert(std::is_same_v<decltype(Observation::omega), double>);
static_assert(std::is_same_v<decltype(Observation::valid), bool>);
static_assert(std::is_same_v<decltype(control::State::i_state), double>);
static_assert(std::is_same_v<decltype(control::State::d_prev), double>);
static_assert(std::is_same_v<decltype(control::State::last_delta), double>);
static_assert(std::is_same_v<decltype(&control::initial), control::State (*)() noexcept>);
static_assert(std::is_same_v<decltype(&control::step),
                             double (*)(control::State&, const Observation&) noexcept>);

namespace {

struct Step {
    std::array<std::uint64_t, 2> observation;
    std::array<std::uint64_t, 4> expected;
};

struct Vector {
    const char* name;
    std::array<std::uint64_t, 3> state;
    Step step;
};

// Independent words: input I/D/last, theta/omega, expected delta/I/D/last.
constexpr Vector kVectors[] = {
    {"V01", {0x0000000000000000ULL, 0x0000000000000000ULL, 0x0000000000000000ULL},
     {{0x0000000000000000ULL, 0x0000000000000000ULL},
      {0x0000000000000000ULL, 0x0000000000000000ULL, 0x0000000000000000ULL, 0x0000000000000000ULL}}},
    {"V02", {0xbf2f75104d551d69ULL, 0x0000000000000000ULL, 0x3fb0000000000000ULL},
     {{0x3f90000000000000ULL, 0x0000000000000000ULL},
      {0x3faa374bc6a7ef9eULL, 0x0000000000000000ULL, 0x0000000000000000ULL, 0x3faa374bc6a7ef9eULL}}},
    {"V03", {0x0000000000000000ULL, 0x3fd0000000000000ULL, 0x3fb0000000000000ULL},
     {{0x3f80000000000000ULL, 0xbfc0000000000000ULL},
      {0x3fb079042d8c2a45ULL, 0x3f1f75104d551d69ULL, 0x3fc0000000000000ULL, 0x3fb079042d8c2a45ULL}}},
    {"V04", {0xbfa0000000000000ULL, 0x3fb0000000000000ULL, 0x3fb0000000000000ULL},
     {{0xbfb0000000000000ULL, 0xbfe0000000000000ULL},
      {0xbfbeb851eb851eb8ULL, 0xbfa0000000000000ULL, 0xbfc0000000000000ULL, 0xbfbeb851eb851eb8ULL}}},
    {"V05", {0x3fbeb851eb851eb8ULL, 0x0000000000000000ULL, 0x3fbeb851eb851eb8ULL},
     {{0xbf90000000000000ULL, 0x3ff8000000000000ULL},
      {0x3fbeb851eb851eb8ULL, 0x3fbea897635e7429ULL, 0x3fe0000000000000ULL, 0x3fbeb851eb851eb8ULL}}},
    {"V06", {0x3fbeb851eb851eb8ULL, 0xbfc8000000000000ULL, 0x3fa0000000000000ULL},
     {{0x3f90000000000000ULL, 0xbfc8000000000000ULL},
      {0x3fbcfef9db22d0e6ULL, 0x3fbeb851eb851eb8ULL, 0xbfc8000000000000ULL, 0x3fbcfef9db22d0e6ULL}}},
    {"V07", {0xbfbeb851eb851eb8ULL, 0x3fc8000000000000ULL, 0xbfa0000000000000ULL},
     {{0xbf90000000000000ULL, 0x3fc8000000000000ULL},
      {0xbfbcfef9db22d0e6ULL, 0xbfbeb851eb851eb8ULL, 0x3fc8000000000000ULL, 0xbfbcfef9db22d0e6ULL}}},
    {"V08", {0x3fb18cf1800a7c59ULL, 0x0000000000000000ULL, 0x0000000000000000ULL},
     {{0x3f90000000000000ULL, 0x0000000000000000ULL},
      {0x3fbeb851eb851eb7ULL, 0x3fb19cac083126e8ULL, 0x0000000000000000ULL, 0x3fbeb851eb851eb7ULL}}},
    {"V09", {0x3fb18cf1800a7c5aULL, 0x0000000000000000ULL, 0x0000000000000000ULL},
     {{0x3f90000000000000ULL, 0x0000000000000000ULL},
      {0x3fbeb851eb851eb8ULL, 0x3fb19cac083126e9ULL, 0x0000000000000000ULL, 0x3fbeb851eb851eb8ULL}}},
    {"V10", {0x3fb18cf1800a7c5bULL, 0x0000000000000000ULL, 0x0000000000000000ULL},
     {{0x3f90000000000000ULL, 0x0000000000000000ULL},
      {0x3fbeb851eb851eb8ULL, 0x3fb18cf1800a7c5bULL, 0x0000000000000000ULL, 0x3fbeb851eb851eb8ULL}}},
    {"V11", {0xbfb18cf1800a7c5aULL, 0x0000000000000000ULL, 0x0000000000000000ULL},
     {{0xbf90000000000000ULL, 0x0000000000000000ULL},
      {0xbfbeb851eb851eb8ULL, 0xbfb19cac083126e9ULL, 0x0000000000000000ULL, 0xbfbeb851eb851eb8ULL}}},
    {"V12", {0x8000000000000000ULL, 0x8000000000000000ULL, 0xbfb0000000000000ULL},
     {{0x8000000000000000ULL, 0x8000000000000000ULL},
      {0x0000000000000000ULL, 0x8000000000000000ULL, 0x0000000000000000ULL, 0x0000000000000000ULL}}},
};

constexpr Step kT1[] = {
    {{0x3f90000000000000ULL, 0x0000000000000000ULL},
     {0x3faa56c0d6f544bbULL, 0x3f2f75104d551d69ULL, 0x0000000000000000ULL, 0x3faa56c0d6f544bbULL}},
    {{0x3f90000000000000ULL, 0x0000000000000000ULL},
     {0x3faa7635e74299d9ULL, 0x3f3f75104d551d69ULL, 0x0000000000000000ULL, 0x3faa7635e74299d9ULL}},
    {{0x3f90000000000000ULL, 0x0000000000000000ULL},
     {0x3faa95aaf78feef6ULL, 0x3f4797cc39ffd60fULL, 0x0000000000000000ULL, 0x3faa95aaf78feef6ULL}},
};

constexpr Step kT2[] = {
    {{0x0000000000000000ULL, 0x3fd8000000000000ULL},
     {0x3fa3c6a7ef9db22dULL, 0x0000000000000000ULL, 0x3fc0000000000000ULL, 0x3fa3c6a7ef9db22dULL}},
    {{0x0000000000000000ULL, 0x0000000000000000ULL},
     {0x3f9a5e353f7ced92ULL, 0x0000000000000000ULL, 0x3fb5555555555556ULL, 0x3f9a5e353f7ced92ULL}},
    {{0x0000000000000000ULL, 0x0000000000000000ULL},
     {0x3f9194237fa89e62ULL, 0x0000000000000000ULL, 0x3fac71c71c71c71eULL, 0x3f9194237fa89e62ULL}},
};

constexpr Step kT3[] = {
    {{0x3fb0000000000000ULL, 0x3fe0000000000000ULL},
     {0x3fbeb851eb851eb8ULL, 0x3fa0000000000000ULL, 0x3fc0000000000000ULL, 0x3fbeb851eb851eb8ULL}},
    {{0x3fb0000000000000ULL, 0x0000000000000000ULL},
     {0x3fbeb851eb851eb8ULL, 0x3fa0000000000000ULL, 0x3fb5555555555556ULL, 0x3fbeb851eb851eb8ULL}},
    {{0xbf90000000000000ULL, 0x0000000000000000ULL},
     {0xbf68caf1720f58a8ULL, 0x3f9fc115df6555c5ULL, 0x3fac71c71c71c71eULL, 0xbf68caf1720f58a8ULL}},
    {{0xbf90000000000000ULL, 0x0000000000000000ULL},
     {0xbf8268a848299436ULL, 0x3f9f822bbecaab8aULL, 0x3fa2f684bda12f6aULL, 0xbf8268a848299436ULL}},
};

struct Trace {
    const char* name;
    std::array<std::uint64_t, 3> initial;
    std::span<const Step> steps;
};

constexpr Trace kTraces[] = {
    {"T1", {0x0000000000000000ULL, 0x0000000000000000ULL, 0x0000000000000000ULL}, kT1},
    {"T2", {0x0000000000000000ULL, 0x0000000000000000ULL, 0x0000000000000000ULL}, kT2},
    {"T3", {0x3fa0000000000000ULL, 0xbfb0000000000000ULL, 0xbfb0000000000000ULL}, kT3},
};

double from_bits(std::uint64_t word) {
    return std::bit_cast<double>(word);
}

void check_word(double actual, std::uint64_t expected, const char* name,
                const char* field, std::size_t step = 0) {
    const auto word = std::bit_cast<std::uint64_t>(actual);
    if (word != expected) {
        std::fprintf(stderr, "%s[%zu] %s: got 0x%016" PRIx64 ", expected 0x%016" PRIx64 "\n",
                     name, step, field, word, expected);
        std::exit(1);
    }
}

control::State state_from_words(const std::array<std::uint64_t, 3>& words) {
    return {from_bits(words[0]), from_bits(words[1]), from_bits(words[2])};
}

void check_step(control::State& state, const Observation& obs,
                const std::array<std::uint64_t, 4>& expected,
                const char* name, std::size_t step = 0) {
    const double delta = control::step(state, obs);
    check_word(delta, expected[0], name, "delta", step);
    check_word(state.i_state, expected[1], name, "i_state", step);
    check_word(state.d_prev, expected[2], name, "d_prev", step);
    check_word(state.last_delta, expected[3], name, "last_delta", step);
}

void test_records_and_initial_state() {
    Observation obs{17, -0.0, 0.125, false};
    auto& [tick, theta, omega, valid] = obs;
    CHECK(&tick == &obs.tick);
    CHECK(&theta == &obs.theta);
    CHECK(&omega == &obs.omega);
    CHECK(&valid == &obs.valid);
    CHECK(obs.tick == 17 && !obs.valid);
    check_word(obs.theta, 0x8000000000000000ULL, "Observation", "theta");
    check_word(obs.omega, 0x3fc0000000000000ULL, "Observation", "omega");

    control::State state{-0.0, 0.25, -0.0625};
    auto& [i, d, last] = state;
    CHECK(&i == &state.i_state);
    CHECK(&d == &state.d_prev);
    CHECK(&last == &state.last_delta);
    check_word(state.i_state, 0x8000000000000000ULL, "State", "i_state");
    check_word(state.d_prev, 0x3fd0000000000000ULL, "State", "d_prev");
    check_word(state.last_delta, 0xbfb0000000000000ULL, "State", "last_delta");

    const auto initial = control::initial();
    check_word(initial.i_state, 0x0000000000000000ULL, "initial", "i_state");
    check_word(initial.d_prev, 0x0000000000000000ULL, "initial", "d_prev");
    check_word(initial.last_delta, 0x0000000000000000ULL, "initial", "last_delta");
}

void test_constants() {
    const struct { const char* name; double value; std::uint64_t expected; } cases[] = {
        {"KP", control::KP, 0x400a374bc6a7ef9eULL},
        {"KI", control::KI, 0x401eb851eb851eb8ULL},
        {"KD", control::KD, 0x3fd3c6a7ef9db22dULL},
        {"DT", control::DT, 0x3f60624dd2f1a9fcULL},
        {"KI_DT", control::KI_DT, 0x3f8f75104d551d69ULL},
        {"BETA_D", control::BETA_D, 0x3fd5555555555555ULL},
        {"DELTA_MAX", control::DELTA_MAX, 0x3fbeb851eb851eb8ULL},
        {"I_MAX", control::I_MAX, 0x3fbeb851eb851eb8ULL},
        {"THETA_SP", control::THETA_SP, 0x0000000000000000ULL},
    };
    for (const auto& c : cases)
        check_word(c.value, c.expected, "constants", c.name);
    check_word(control::NEG_DELTA_MAX, 0xbfbeb851eb851eb8ULL, "constants", "NEG_DELTA_MAX");
    check_word(control::NEG_I_MAX, 0xbfbeb851eb851eb8ULL, "constants", "NEG_I_MAX");
}

void test_vectors() {
    for (const auto& c : kVectors) {
        auto state = state_from_words(c.state);
        const Observation obs{41, from_bits(c.step.observation[0]),
                              from_bits(c.step.observation[1]), true};
        check_step(state, obs, c.step.expected, c.name);
    }
}

void test_traces() {
    constexpr std::uint64_t ticks[] = {7, 19, 20, 200};
    for (const auto& trace : kTraces) {
        auto state = state_from_words(trace.initial);
        for (std::size_t n = 0; n < trace.steps.size(); ++n) {
            const auto& step = trace.steps[n];
            const Observation obs{ticks[n], from_bits(step.observation[0]),
                                  from_bits(step.observation[1]), true};
            // The next call receives the real mutated state, never expected state.
            check_step(state, obs, step.expected, trace.name, n + 1);
        }
    }
}

void test_metadata_and_prior_output_are_irrelevant() {
    constexpr std::uint64_t ticks[] = {0, 41, 0xffffffffffffffffULL};
    constexpr std::uint64_t last_words[] = {
        0x0000000000000000ULL, 0x8000000000000000ULL,
        0x3fbeb851eb851eb8ULL, 0xbfbeb851eb851eb8ULL,
    };
    for (const auto& c : kVectors) {
        // Metadata variation proves no arithmetic dependence, not admission policy.
        for (const auto tick : ticks) {
            for (const bool valid : {false, true}) {
                auto state = state_from_words(c.state);
                const Observation obs{tick, from_bits(c.step.observation[0]),
                                      from_bits(c.step.observation[1]), valid};
                check_step(state, obs, c.step.expected, c.name);
            }
        }
        for (const auto last_word : last_words) {
            auto state = state_from_words(c.state);
            state.last_delta = from_bits(last_word);
            const Observation obs{41, from_bits(c.step.observation[0]),
                                  from_bits(c.step.observation[1]), true};
            check_step(state, obs, c.step.expected, c.name);
        }
    }
}

[[noreturn]] void protocol_error(const char* message) {
    std::fprintf(stderr, "control_tests: corpus protocol error: %s\n", message);
    std::exit(2);
}

std::vector<std::string> record(const char* type, std::size_t count) {
    std::string line;
    if (!std::getline(std::cin, line) || std::cin.eof())
        protocol_error("missing or non-LF-terminated record");
    for (const unsigned char ch : line) {
        if (ch != '\t' && (ch < 0x20 || ch > 0x7e))
            protocol_error("non-ASCII or forbidden control character");
    }
    std::istringstream input(line);
    std::vector<std::string> fields;
    for (std::string field; input >> field;)
        fields.push_back(field);
    if (fields.size() != count || fields[0] != type)
        protocol_error("unexpected record type or field count");
    return fields;
}

void identifier(const std::string& actual, const std::string& expected) {
    if (actual != expected)
        protocol_error("missing, duplicate, reordered or unexpected identifier");
}

std::uint64_t word(const std::string& text) {
    if (text.size() != 18 || text.substr(0, 2) != "0x")
        protocol_error("malformed binary64 word");
    std::uint64_t value = 0;
    for (std::size_t n = 2; n < text.size(); ++n) {
        const char ch = text[n];
        unsigned digit;
        if (ch >= '0' && ch <= '9')
            digit = static_cast<unsigned>(ch - '0');
        else if (ch >= 'a' && ch <= 'f')
            digit = static_cast<unsigned>(ch - 'a' + 10);
        else
            protocol_error("malformed binary64 word");
        value = (value << 4) | digit;
    }
    return value;
}

template<std::size_t N>
std::array<std::uint64_t, N> words(const std::vector<std::string>& fields,
                                 std::size_t start) {
    std::array<std::uint64_t, N> result;
    for (std::size_t n = 0; n < N; ++n)
        result[n] = word(fields.at(start + n));
    return result;
}

void supplied_step(control::State& state, const std::vector<std::string>& fields,
                   std::size_t start, const char* name, std::size_t step = 0) {
    const auto observation = words<2>(fields, start);
    const auto expected = words<4>(fields, start + 2);
    const Observation obs{0, from_bits(observation[0]), from_bits(observation[1]), true};
    check_step(state, obs, expected, name, step);
}

int corpus_stdin() {
    std::size_t constants = 0, vectors = 0, traces = 0, calls = 0;
    const struct { const char* name; double value; } compiled[] = {
        {"KP", control::KP}, {"KI", control::KI}, {"KD", control::KD},
        {"DT", control::DT}, {"KI_DT", control::KI_DT}, {"BETA_D", control::BETA_D},
        {"DELTA_MAX", control::DELTA_MAX}, {"I_MAX", control::I_MAX},
        {"THETA_SP", control::THETA_SP},
    };
    for (const auto& constant : compiled) {
        const auto fields = record("CONST", 3);
        identifier(fields[1], constant.name);
        check_word(constant.value, word(fields[2]), "constants", constant.name);
        ++constants;
    }
    for (unsigned n = 1; n <= 12; ++n) {
        const std::string name = (n < 10 ? "V0" : "V") + std::to_string(n);
        const auto fields = record("VECTOR", 11);
        identifier(fields[1], name);
        auto state = state_from_words(words<3>(fields, 2));
        supplied_step(state, fields, 5, name.c_str());
        ++calls;
        ++vectors;
    }
    for (unsigned n = 1; n <= 3; ++n) {
        const std::string name = "T" + std::to_string(n);
        const auto fields = record("TRACE", 5);
        identifier(fields[1], name);
        auto state = state_from_words(words<3>(fields, 2));
        const unsigned length = n == 3 ? 4 : 3;
        for (unsigned step = 1; step <= length; ++step) {
            const auto values = record("STEP", 8);
            identifier(values[1], std::to_string(step));
            // Carry the real state, not expected state, across supplied trace steps.
            supplied_step(state, values, 2, name.c_str(), step);
            ++calls;
        }
        ++traces;
    }
    record("END", 1);
    if (std::cin.peek() != std::char_traits<char>::eof() || std::cin.bad())
        protocol_error("expected immediate EOF after END");
    if (constants != 9 || vectors != 12 || traces != 3 || calls != 22)
        protocol_error("incomplete corpus consumption");
    std::puts("control_tests: corpus ok constants=9 vectors=12 traces=3 calls=22");
    return 0;
}

}  // namespace

int main(int argc, char** argv) {
    if (argc == 2 && std::string(argv[1]) == "--corpus-stdin")
        return corpus_stdin();
    if (argc != 1) {
        std::fputs("usage: control_tests [--corpus-stdin]\n", stderr);
        return 2;
    }
    test_records_and_initial_state();
    test_constants();
    test_vectors();
    test_traces();
    test_metadata_and_prior_output_are_irrelevant();
    std::puts("control_tests: ok (9 constants, 12 vectors, 10 trace calls)");
    return 0;
}
