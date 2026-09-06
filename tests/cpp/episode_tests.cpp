#include "../../src/episode.hpp"

#include <array>
#include <bit>
#include <cfloat>
#include <cstdio>
#include <cstdlib>
#include <limits>
#include <optional>
#include <span>
#include <string_view>
#include <type_traits>

#define CHECK(cond) do { if (!(cond)) { \
    std::fprintf(stderr, "FAIL %s:%d: %s\n", __FILE__, __LINE__, #cond); \
    std::exit(1); } } while (0)

namespace {
struct CommandWords { std::uint32_t seq; std::uint16_t opcode; std::uint64_t tick; };
struct TerminalWords { unsigned reason; std::uint64_t tick; };
struct StateWords {
    unsigned mode;
    std::array<std::uint64_t, 3> pid;
    std::uint32_t count;
    std::optional<CommandWords> pending, last;
    std::optional<TerminalWords> terminal;
    bool auto_arm;
};
struct ObservationWords { std::uint64_t tick, theta, omega; bool valid; };
struct InputWords {
    std::uint64_t tick;
    std::optional<ObservationWords> held;
    bool fresh;
    std::uint32_t age;
    std::optional<CommandWords> command;
    bool horizon;
    std::optional<std::uint32_t> sim;
    std::optional<unsigned> stop;
};
struct AckWords { std::uint32_t seq; unsigned status; std::uint64_t tick; unsigned mode, reason; };
struct Row {
    InputWords input;
    StateWords next;
    std::uint64_t request;
    std::array<AckWords, 2> acks;
    unsigned ack_count, pid_calls;
};
struct Vector { const char* name; StateWords seed; Row row; };
// Direct transcription of the independently approved C/T/B and L/Q/R/K/S/A
// literal sheet. Helpers below decode words and pack records, never policy.
constexpr Vector vectors[] = {
    {"C01", StateWords{0U, {0x0000000000000000ULL, 0x3fd0000000000000ULL, 0x3fb0000000000000ULL}, 0U, std::nullopt, CommandWords{0U, 2U, 5ULL}, std::nullopt, false}, Row{
        InputWords{10ULL, ObservationWords{9ULL, 0x0000000000000000ULL, 0x3fd8000000000000ULL, true}, false, 1U, CommandWords{0U, 0U, 5ULL}, false, std::nullopt, std::nullopt},
        StateWords{0U, {0x0000000000000000ULL, 0x3fd0000000000000ULL, 0x3fb0000000000000ULL}, 0U, std::nullopt, CommandWords{0U, 2U, 5ULL}, std::nullopt, false},
        0x0000000000000000ULL, {AckWords{0U, 7U, 0ULL, 0U, 0U}, AckWords{}}, 1U, 0U}},
    {"C02", StateWords{0U, {0x0000000000000000ULL, 0x3fd0000000000000ULL, 0x3fb0000000000000ULL}, 0U, std::nullopt, CommandWords{0U, 2U, 5ULL}, std::nullopt, false}, Row{
        InputWords{10ULL, ObservationWords{9ULL, 0x0000000000000000ULL, 0x3fd8000000000000ULL, true}, false, 1U, CommandWords{0U, 2U, 5ULL}, false, std::nullopt, std::nullopt},
        StateWords{0U, {0x0000000000000000ULL, 0x3fd0000000000000ULL, 0x3fb0000000000000ULL}, 0U, std::nullopt, CommandWords{0U, 2U, 5ULL}, std::nullopt, false},
        0x0000000000000000ULL, {AckWords{0U, 3U, 0ULL, 0U, 0U}, AckWords{}}, 1U, 0U}},
    {"C03", StateWords{0U, {0x0000000000000000ULL, 0x3fd0000000000000ULL, 0x3fb0000000000000ULL}, 0U, std::nullopt, CommandWords{0U, 2U, 5ULL}, std::nullopt, false}, Row{
        InputWords{10ULL, ObservationWords{9ULL, 0x0000000000000000ULL, 0x3fd8000000000000ULL, true}, false, 1U, CommandWords{0U, 1U, 5ULL}, false, std::nullopt, std::nullopt},
        StateWords{0U, {0x0000000000000000ULL, 0x3fd0000000000000ULL, 0x3fb0000000000000ULL}, 0U, std::nullopt, CommandWords{0U, 2U, 5ULL}, std::nullopt, false},
        0x0000000000000000ULL, {AckWords{0U, 6U, 0ULL, 0U, 0U}, AckWords{}}, 1U, 0U}},
    {"C04", StateWords{0U, {0x0000000000000000ULL, 0x3fd0000000000000ULL, 0x3fb0000000000000ULL}, 0U, std::nullopt, CommandWords{0U, 2U, 5ULL}, std::nullopt, false}, Row{
        InputWords{10ULL, ObservationWords{9ULL, 0x0000000000000000ULL, 0x3fd8000000000000ULL, true}, false, 1U, CommandWords{0U, 2U, 6ULL}, false, std::nullopt, std::nullopt},
        StateWords{0U, {0x0000000000000000ULL, 0x3fd0000000000000ULL, 0x3fb0000000000000ULL}, 0U, std::nullopt, CommandWords{0U, 2U, 5ULL}, std::nullopt, false},
        0x0000000000000000ULL, {AckWords{0U, 6U, 0ULL, 0U, 0U}, AckWords{}}, 1U, 0U}},
    {"C05", StateWords{0U, {0x0000000000000000ULL, 0x3fd0000000000000ULL, 0x3fb0000000000000ULL}, 0U, std::nullopt, CommandWords{0U, 2U, 5ULL}, std::nullopt, false}, Row{
        InputWords{10ULL, ObservationWords{9ULL, 0x0000000000000000ULL, 0x3fd8000000000000ULL, true}, false, 1U, CommandWords{4294967295U, 1U, 10ULL}, false, std::nullopt, std::nullopt},
        StateWords{0U, {0x0000000000000000ULL, 0x3fd0000000000000ULL, 0x3fb0000000000000ULL}, 0U, std::nullopt, CommandWords{0U, 2U, 5ULL}, std::nullopt, false},
        0x0000000000000000ULL, {AckWords{4294967295U, 8U, 0ULL, 0U, 0U}, AckWords{}}, 1U, 0U}},
    {"C06", StateWords{0U, {0x0000000000000000ULL, 0x3fd0000000000000ULL, 0x3fb0000000000000ULL}, 0U, std::nullopt, CommandWords{0U, 2U, 5ULL}, std::nullopt, false}, Row{
        InputWords{10ULL, ObservationWords{9ULL, 0x0000000000000000ULL, 0x3fd8000000000000ULL, true}, false, 1U, CommandWords{2147483648U, 1U, 10ULL}, false, std::nullopt, std::nullopt},
        StateWords{0U, {0x0000000000000000ULL, 0x3fd0000000000000ULL, 0x3fb0000000000000ULL}, 0U, std::nullopt, CommandWords{0U, 2U, 5ULL}, std::nullopt, false},
        0x0000000000000000ULL, {AckWords{2147483648U, 8U, 0ULL, 0U, 0U}, AckWords{}}, 1U, 0U}},
    {"C07", StateWords{0U, {0x0000000000000000ULL, 0x3fd0000000000000ULL, 0x3fb0000000000000ULL}, 0U, std::nullopt, CommandWords{0U, 2U, 5ULL}, std::nullopt, false}, Row{
        InputWords{10ULL, ObservationWords{9ULL, 0x0000000000000000ULL, 0x3fd8000000000000ULL, true}, false, 1U, CommandWords{2147483647U, 1U, 10ULL}, false, std::nullopt, std::nullopt},
        StateWords{1U, {0x0000000000000000ULL, 0x3fd0000000000000ULL, 0x3fb0000000000000ULL}, 0U, std::nullopt, CommandWords{2147483647U, 1U, 10ULL}, std::nullopt, false},
        0x0000000000000000ULL, {AckWords{2147483647U, 1U, 10ULL, 1U, 0U}, AckWords{}}, 1U, 0U}},
    {"C08", StateWords{0U, {0x0000000000000000ULL, 0x3fd0000000000000ULL, 0x3fb0000000000000ULL}, 0U, std::nullopt, CommandWords{4294967295U, 2U, 5ULL}, std::nullopt, false}, Row{
        InputWords{10ULL, ObservationWords{9ULL, 0x0000000000000000ULL, 0x3fd8000000000000ULL, true}, false, 1U, CommandWords{0U, 1U, 10ULL}, false, std::nullopt, std::nullopt},
        StateWords{1U, {0x0000000000000000ULL, 0x3fd0000000000000ULL, 0x3fb0000000000000ULL}, 0U, std::nullopt, CommandWords{0U, 1U, 10ULL}, std::nullopt, false},
        0x0000000000000000ULL, {AckWords{0U, 1U, 10ULL, 1U, 0U}, AckWords{}}, 1U, 0U}},
    {"C09", StateWords{0U, {0x0000000000000000ULL, 0x3fd0000000000000ULL, 0x3fb0000000000000ULL}, 0U, std::nullopt, CommandWords{0U, 2U, 5ULL}, std::nullopt, false}, Row{
        InputWords{10ULL, ObservationWords{9ULL, 0x0000000000000000ULL, 0x3fd8000000000000ULL, true}, false, 1U, CommandWords{0U, 0U, 5ULL}, true, std::nullopt, std::nullopt},
        StateWords{3U, {0x0000000000000000ULL, 0x3fd0000000000000ULL, 0x3fb0000000000000ULL}, 0U, std::nullopt, CommandWords{0U, 2U, 5ULL}, TerminalWords{7U, 10ULL}, false},
        0x0000000000000000ULL, {AckWords{0U, 7U, 0ULL, 3U, 7U}, AckWords{}}, 1U, 0U}},
    {"C10", StateWords{0U, {0x0000000000000000ULL, 0x3fd0000000000000ULL, 0x3fb0000000000000ULL}, 0U, std::nullopt, CommandWords{0U, 2U, 5ULL}, std::nullopt, false}, Row{
        InputWords{10ULL, ObservationWords{9ULL, 0x0000000000000000ULL, 0x3fd8000000000000ULL, true}, false, 1U, CommandWords{0U, 2U, 5ULL}, true, std::nullopt, std::nullopt},
        StateWords{3U, {0x0000000000000000ULL, 0x3fd0000000000000ULL, 0x3fb0000000000000ULL}, 0U, std::nullopt, CommandWords{0U, 2U, 5ULL}, TerminalWords{7U, 10ULL}, false},
        0x0000000000000000ULL, {AckWords{0U, 3U, 0ULL, 3U, 7U}, AckWords{}}, 1U, 0U}},
    {"C11", StateWords{0U, {0x0000000000000000ULL, 0x3fd0000000000000ULL, 0x3fb0000000000000ULL}, 0U, std::nullopt, CommandWords{0U, 2U, 5ULL}, std::nullopt, false}, Row{
        InputWords{10ULL, ObservationWords{9ULL, 0x0000000000000000ULL, 0x3fd8000000000000ULL, true}, false, 1U, CommandWords{0U, 1U, 5ULL}, true, std::nullopt, std::nullopt},
        StateWords{3U, {0x0000000000000000ULL, 0x3fd0000000000000ULL, 0x3fb0000000000000ULL}, 0U, std::nullopt, CommandWords{0U, 2U, 5ULL}, TerminalWords{7U, 10ULL}, false},
        0x0000000000000000ULL, {AckWords{0U, 6U, 0ULL, 3U, 7U}, AckWords{}}, 1U, 0U}},
    {"C12", StateWords{0U, {0x0000000000000000ULL, 0x3fd0000000000000ULL, 0x3fb0000000000000ULL}, 0U, std::nullopt, CommandWords{0U, 2U, 5ULL}, std::nullopt, false}, Row{
        InputWords{10ULL, ObservationWords{9ULL, 0x0000000000000000ULL, 0x3fd8000000000000ULL, true}, false, 1U, CommandWords{4294967295U, 1U, 10ULL}, true, std::nullopt, std::nullopt},
        StateWords{3U, {0x0000000000000000ULL, 0x3fd0000000000000ULL, 0x3fb0000000000000ULL}, 0U, std::nullopt, CommandWords{0U, 2U, 5ULL}, TerminalWords{7U, 10ULL}, false},
        0x0000000000000000ULL, {AckWords{4294967295U, 8U, 0ULL, 3U, 7U}, AckWords{}}, 1U, 0U}},
    {"T01", StateWords{2U, {0x0000000000000000ULL, 0x3fd0000000000000ULL, 0x3fb0000000000000ULL}, 999U, CommandWords{5U, 1U, 200ULL}, CommandWords{5U, 1U, 200ULL}, std::nullopt, false}, Row{
        InputWords{100ULL, ObservationWords{99ULL, 0x0000000000000000ULL, 0x0000000000000000ULL, true}, false, 1U, CommandWords{6U, 3U, 100ULL}, true, std::optional<std::uint32_t>{0U}, std::optional<unsigned>{6U}},
        StateWords{3U, {0x0000000000000000ULL, 0x3fd0000000000000ULL, 0x3fb0000000000000ULL}, 1000U, std::nullopt, CommandWords{5U, 1U, 200ULL}, TerminalWords{8U, 100ULL}, false},
        0x0000000000000000ULL, {AckWords{6U, 5U, 0ULL, 3U, 8U}, AckWords{5U, 5U, 0ULL, 3U, 8U}}, 2U, 0U}},
    {"T02", StateWords{2U, {0x0000000000000000ULL, 0x3fd0000000000000ULL, 0x3fb0000000000000ULL}, 999U, CommandWords{5U, 1U, 200ULL}, CommandWords{5U, 1U, 200ULL}, std::nullopt, false}, Row{
        InputWords{100ULL, ObservationWords{99ULL, 0x0000000000000000ULL, 0x0000000000000000ULL, true}, false, 1U, CommandWords{6U, 3U, 100ULL}, true, std::optional<std::uint32_t>{4U}, std::optional<unsigned>{6U}},
        StateWords{3U, {0x0000000000000000ULL, 0x3fd0000000000000ULL, 0x3fb0000000000000ULL}, 1000U, std::nullopt, CommandWords{5U, 1U, 200ULL}, TerminalWords{8U, 100ULL}, false},
        0x0000000000000000ULL, {AckWords{6U, 5U, 0ULL, 3U, 8U}, AckWords{5U, 5U, 0ULL, 3U, 8U}}, 2U, 0U}},
    {"T03", StateWords{2U, {0x0000000000000000ULL, 0x3fd0000000000000ULL, 0x3fb0000000000000ULL}, 999U, CommandWords{5U, 1U, 200ULL}, CommandWords{5U, 1U, 200ULL}, std::nullopt, false}, Row{
        InputWords{100ULL, ObservationWords{99ULL, 0x0000000000000000ULL, 0x0000000000000000ULL, true}, false, 1U, CommandWords{6U, 3U, 100ULL}, true, std::optional<std::uint32_t>{6U}, std::optional<unsigned>{6U}},
        StateWords{3U, {0x0000000000000000ULL, 0x3fd0000000000000ULL, 0x3fb0000000000000ULL}, 1000U, std::nullopt, CommandWords{5U, 1U, 200ULL}, TerminalWords{8U, 100ULL}, false},
        0x0000000000000000ULL, {AckWords{6U, 5U, 0ULL, 3U, 8U}, AckWords{5U, 5U, 0ULL, 3U, 8U}}, 2U, 0U}},
    {"T04", StateWords{2U, {0x0000000000000000ULL, 0x3fd0000000000000ULL, 0x3fb0000000000000ULL}, 999U, CommandWords{5U, 1U, 200ULL}, CommandWords{5U, 1U, 200ULL}, std::nullopt, false}, Row{
        InputWords{100ULL, ObservationWords{99ULL, 0x0000000000000000ULL, 0x0000000000000000ULL, true}, false, 1U, CommandWords{6U, 3U, 100ULL}, true, std::optional<std::uint32_t>{4294967295U}, std::optional<unsigned>{6U}},
        StateWords{3U, {0x0000000000000000ULL, 0x3fd0000000000000ULL, 0x3fb0000000000000ULL}, 1000U, std::nullopt, CommandWords{5U, 1U, 200ULL}, TerminalWords{8U, 100ULL}, false},
        0x0000000000000000ULL, {AckWords{6U, 5U, 0ULL, 3U, 8U}, AckWords{5U, 5U, 0ULL, 3U, 8U}}, 2U, 0U}},
    {"T05", StateWords{2U, {0x0000000000000000ULL, 0x3fd0000000000000ULL, 0x3fb0000000000000ULL}, 999U, CommandWords{5U, 1U, 200ULL}, CommandWords{5U, 1U, 200ULL}, std::nullopt, false}, Row{
        InputWords{100ULL, ObservationWords{99ULL, 0x0000000000000000ULL, 0x0000000000000000ULL, true}, false, 1U, CommandWords{6U, 3U, 100ULL}, true, std::optional<std::uint32_t>{2U}, std::optional<unsigned>{6U}},
        StateWords{3U, {0x0000000000000000ULL, 0x3fd0000000000000ULL, 0x3fb0000000000000ULL}, 1000U, std::nullopt, CommandWords{5U, 1U, 200ULL}, TerminalWords{6U, 100ULL}, false},
        0x0000000000000000ULL, {AckWords{6U, 5U, 0ULL, 3U, 6U}, AckWords{5U, 5U, 0ULL, 3U, 6U}}, 2U, 0U}},
    {"T06", StateWords{2U, {0x0000000000000000ULL, 0x3fd0000000000000ULL, 0x3fb0000000000000ULL}, 999U, CommandWords{5U, 1U, 200ULL}, CommandWords{5U, 1U, 200ULL}, std::nullopt, false}, Row{
        InputWords{100ULL, ObservationWords{99ULL, 0x0000000000000000ULL, 0x0000000000000000ULL, true}, false, 1U, CommandWords{6U, 3U, 100ULL}, true, std::optional<std::uint32_t>{3U}, std::optional<unsigned>{5U}},
        StateWords{3U, {0x0000000000000000ULL, 0x3fd0000000000000ULL, 0x3fb0000000000000ULL}, 1000U, std::nullopt, CommandWords{5U, 1U, 200ULL}, TerminalWords{5U, 100ULL}, false},
        0x0000000000000000ULL, {AckWords{6U, 5U, 0ULL, 3U, 5U}, AckWords{5U, 5U, 0ULL, 3U, 5U}}, 2U, 0U}},
    {"T07", StateWords{2U, {0x0000000000000000ULL, 0x3fd0000000000000ULL, 0x3fb0000000000000ULL}, 999U, CommandWords{5U, 1U, 200ULL}, CommandWords{5U, 1U, 200ULL}, std::nullopt, false}, Row{
        InputWords{100ULL, ObservationWords{99ULL, 0x0000000000000000ULL, 0x0000000000000000ULL, true}, false, 1U, CommandWords{6U, 3U, 100ULL}, true, std::optional<std::uint32_t>{1U}, std::optional<unsigned>{8U}},
        StateWords{3U, {0x0000000000000000ULL, 0x3fd0000000000000ULL, 0x3fb0000000000000ULL}, 1000U, std::nullopt, CommandWords{5U, 1U, 200ULL}, TerminalWords{8U, 100ULL}, false},
        0x0000000000000000ULL, {AckWords{6U, 5U, 0ULL, 3U, 8U}, AckWords{5U, 5U, 0ULL, 3U, 8U}}, 2U, 0U}},
    {"T08", StateWords{2U, {0x0000000000000000ULL, 0x3fd0000000000000ULL, 0x3fb0000000000000ULL}, 999U, CommandWords{5U, 1U, 200ULL}, CommandWords{5U, 1U, 200ULL}, std::nullopt, false}, Row{
        InputWords{100ULL, ObservationWords{79ULL, 0x0000000000000000ULL, 0x0000000000000000ULL, true}, false, 21U, CommandWords{6U, 3U, 100ULL}, true, std::optional<std::uint32_t>{2U}, std::nullopt},
        StateWords{3U, {0x0000000000000000ULL, 0x3fd0000000000000ULL, 0x3fb0000000000000ULL}, 1000U, std::nullopt, CommandWords{5U, 1U, 200ULL}, TerminalWords{2U, 100ULL}, false},
        0x0000000000000000ULL, {AckWords{6U, 5U, 0ULL, 3U, 2U}, AckWords{5U, 5U, 0ULL, 3U, 2U}}, 2U, 0U}},
    {"T09", StateWords{2U, {0x0000000000000000ULL, 0x3fd0000000000000ULL, 0x3fb0000000000000ULL}, 999U, CommandWords{5U, 1U, 200ULL}, CommandWords{5U, 1U, 200ULL}, std::nullopt, false}, Row{
        InputWords{100ULL, std::nullopt, false, 1U, CommandWords{6U, 3U, 100ULL}, true, std::optional<std::uint32_t>{3U}, std::nullopt},
        StateWords{3U, {0x0000000000000000ULL, 0x3fd0000000000000ULL, 0x3fb0000000000000ULL}, 0U, std::nullopt, CommandWords{5U, 1U, 200ULL}, TerminalWords{2U, 100ULL}, false},
        0x0000000000000000ULL, {AckWords{6U, 5U, 0ULL, 3U, 2U}, AckWords{5U, 5U, 0ULL, 3U, 2U}}, 2U, 0U}},
    {"T10", StateWords{2U, {0x0000000000000000ULL, 0x3fd0000000000000ULL, 0x3fb0000000000000ULL}, 999U, CommandWords{5U, 1U, 200ULL}, CommandWords{5U, 1U, 200ULL}, std::nullopt, false}, Row{
        InputWords{100ULL, ObservationWords{79ULL, 0x3fd3333333333334ULL, 0x0000000000000000ULL, true}, true, 21U, CommandWords{6U, 3U, 100ULL}, true, std::nullopt, std::nullopt},
        StateWords{3U, {0x0000000000000000ULL, 0x3fd0000000000000ULL, 0x3fb0000000000000ULL}, 0U, std::nullopt, CommandWords{5U, 1U, 200ULL}, TerminalWords{2U, 100ULL}, false},
        0x0000000000000000ULL, {AckWords{6U, 5U, 0ULL, 3U, 2U}, AckWords{5U, 5U, 0ULL, 3U, 2U}}, 2U, 0U}},
    {"T11", StateWords{2U, {0x0000000000000000ULL, 0x3fd0000000000000ULL, 0x3fb0000000000000ULL}, 999U, CommandWords{5U, 1U, 200ULL}, CommandWords{5U, 1U, 200ULL}, std::nullopt, false}, Row{
        InputWords{100ULL, ObservationWords{79ULL, 0xbfd3333333333334ULL, 0x0000000000000000ULL, true}, true, 21U, CommandWords{6U, 3U, 100ULL}, true, std::nullopt, std::nullopt},
        StateWords{3U, {0x0000000000000000ULL, 0x3fd0000000000000ULL, 0x3fb0000000000000ULL}, 0U, std::nullopt, CommandWords{5U, 1U, 200ULL}, TerminalWords{2U, 100ULL}, false},
        0x0000000000000000ULL, {AckWords{6U, 5U, 0ULL, 3U, 2U}, AckWords{5U, 5U, 0ULL, 3U, 2U}}, 2U, 0U}},
    {"T12", StateWords{2U, {0x0000000000000000ULL, 0x3fd0000000000000ULL, 0x3fb0000000000000ULL}, 999U, CommandWords{5U, 1U, 200ULL}, CommandWords{5U, 1U, 200ULL}, std::nullopt, false}, Row{
        InputWords{100ULL, ObservationWords{79ULL, 0x3f80000000000000ULL, 0xbfc0000000000000ULL, true}, true, 21U, CommandWords{6U, 3U, 100ULL}, true, std::nullopt, std::nullopt},
        StateWords{3U, {0x0000000000000000ULL, 0x3fd0000000000000ULL, 0x3fb0000000000000ULL}, 0U, std::nullopt, CommandWords{5U, 1U, 200ULL}, TerminalWords{4U, 100ULL}, false},
        0x0000000000000000ULL, {AckWords{6U, 5U, 0ULL, 3U, 4U}, AckWords{5U, 5U, 0ULL, 3U, 4U}}, 2U, 0U}},
    {"T13", StateWords{2U, {0x0000000000000000ULL, 0x3fd0000000000000ULL, 0x3fb0000000000000ULL}, 999U, CommandWords{5U, 1U, 200ULL}, CommandWords{5U, 1U, 200ULL}, std::nullopt, false}, Row{
        InputWords{100ULL, ObservationWords{99ULL, 0x0000000000000000ULL, 0x0000000000000000ULL, true}, false, 1U, CommandWords{5U, 1U, 200ULL}, true, std::nullopt, std::nullopt},
        StateWords{3U, {0x0000000000000000ULL, 0x3fd0000000000000ULL, 0x3fb0000000000000ULL}, 1000U, std::nullopt, CommandWords{5U, 1U, 200ULL}, TerminalWords{1U, 100ULL}, false},
        0x0000000000000000ULL, {AckWords{5U, 3U, 0ULL, 3U, 1U}, AckWords{5U, 5U, 0ULL, 3U, 1U}}, 2U, 0U}},
    {"T14", StateWords{2U, {0x0000000000000000ULL, 0x3fd0000000000000ULL, 0x3fb0000000000000ULL}, 999U, CommandWords{5U, 1U, 200ULL}, CommandWords{5U, 1U, 200ULL}, std::nullopt, false}, Row{
        InputWords{100ULL, ObservationWords{99ULL, 0x0000000000000000ULL, 0x0000000000000000ULL, true}, false, 1U, CommandWords{6U, 3U, 100ULL}, false, std::optional<std::uint32_t>{1U}, std::nullopt},
        StateWords{3U, {0x0000000000000000ULL, 0x3fd0000000000000ULL, 0x3fb0000000000000ULL}, 1000U, std::nullopt, CommandWords{5U, 1U, 200ULL}, TerminalWords{1U, 100ULL}, false},
        0x0000000000000000ULL, {AckWords{6U, 5U, 0ULL, 3U, 1U}, AckWords{5U, 5U, 0ULL, 3U, 1U}}, 2U, 0U}},
    {"T15", StateWords{2U, {0x0000000000000000ULL, 0x3fd0000000000000ULL, 0x3fb0000000000000ULL}, 998U, CommandWords{5U, 1U, 200ULL}, CommandWords{5U, 1U, 200ULL}, std::nullopt, false}, Row{
        InputWords{100ULL, ObservationWords{99ULL, 0x0000000000000000ULL, 0x0000000000000000ULL, true}, false, 1U, CommandWords{6U, 3U, 100ULL}, true, std::nullopt, std::nullopt},
        StateWords{3U, {0x0000000000000000ULL, 0x3fd0000000000000ULL, 0x3fb0000000000000ULL}, 999U, std::nullopt, CommandWords{5U, 1U, 200ULL}, TerminalWords{7U, 100ULL}, false},
        0x0000000000000000ULL, {AckWords{6U, 5U, 0ULL, 3U, 7U}, AckWords{5U, 5U, 0ULL, 3U, 7U}}, 2U, 0U}},
    {"T16", StateWords{2U, {0x0000000000000000ULL, 0x3fd0000000000000ULL, 0x3fb0000000000000ULL}, 999U, CommandWords{5U, 1U, 200ULL}, CommandWords{5U, 1U, 200ULL}, std::nullopt, false}, Row{
        InputWords{100ULL, ObservationWords{79ULL, 0x0000000000000000ULL, 0x0000000000000000ULL, true}, false, 21U, CommandWords{6U, 3U, 100ULL}, true, std::nullopt, std::nullopt},
        StateWords{3U, {0x0000000000000000ULL, 0x3fd0000000000000ULL, 0x3fb0000000000000ULL}, 1000U, std::nullopt, CommandWords{5U, 1U, 200ULL}, TerminalWords{4U, 100ULL}, false},
        0x0000000000000000ULL, {AckWords{6U, 5U, 0ULL, 3U, 4U}, AckWords{5U, 5U, 0ULL, 3U, 4U}}, 2U, 0U}},
    {"B01", StateWords{1U, {0x0000000000000000ULL, 0x3fd0000000000000ULL, 0x3fb0000000000000ULL}, 998U, CommandWords{30U, 2U, 100ULL}, CommandWords{30U, 2U, 100ULL}, std::nullopt, false}, Row{
        InputWords{40ULL, ObservationWords{40ULL, 0x0000000000000000ULL, 0x0000000000000000ULL, true}, true, 0U, CommandWords{31U, 3U, 40ULL}, false, std::nullopt, std::nullopt},
        StateWords{3U, {0x0000000000000000ULL, 0x3fd0000000000000ULL, 0x3fb0000000000000ULL}, 999U, std::nullopt, CommandWords{31U, 3U, 40ULL}, TerminalWords{3U, 40ULL}, false},
        0x0000000000000000ULL, {AckWords{31U, 1U, 40ULL, 3U, 3U}, AckWords{30U, 9U, 0ULL, 1U, 0U}}, 2U, 0U}},
    {"B02", StateWords{0U, {0x0000000000000000ULL, 0x3fd0000000000000ULL, 0x3fb0000000000000ULL}, 0U, CommandWords{30U, 1U, 100ULL}, CommandWords{30U, 1U, 100ULL}, std::nullopt, false}, Row{
        InputWords{40ULL, ObservationWords{40ULL, 0x3f80000000000000ULL, 0xbfc0000000000000ULL, true}, true, 0U, CommandWords{31U, 3U, 40ULL}, false, std::nullopt, std::nullopt},
        StateWords{0U, {0x0000000000000000ULL, 0x3fd0000000000000ULL, 0x3fb0000000000000ULL}, 0U, std::nullopt, CommandWords{31U, 3U, 40ULL}, std::nullopt, false},
        0x0000000000000000ULL, {AckWords{31U, 5U, 0ULL, 0U, 0U}, AckWords{30U, 9U, 0ULL, 0U, 0U}}, 2U, 0U}},
    {"B03", StateWords{0U, {0x0000000000000000ULL, 0x3fd0000000000000ULL, 0x3fb0000000000000ULL}, 0U, std::nullopt, std::nullopt, std::nullopt, false}, Row{
        InputWords{40ULL, ObservationWords{39ULL, 0x0000000000000000ULL, 0x3fd8000000000000ULL, true}, false, 1U, CommandWords{30U, 2U, 40ULL}, false, std::nullopt, std::nullopt},
        StateWords{0U, {0x0000000000000000ULL, 0x3fd0000000000000ULL, 0x3fb0000000000000ULL}, 0U, std::nullopt, CommandWords{30U, 2U, 40ULL}, std::nullopt, false},
        0x0000000000000000ULL, {AckWords{30U, 5U, 0ULL, 0U, 0U}, AckWords{}}, 1U, 0U}},
    {"B04", StateWords{0U, {0x0000000000000000ULL, 0x3fd0000000000000ULL, 0x3fb0000000000000ULL}, 0U, CommandWords{30U, 1U, 39ULL}, CommandWords{30U, 1U, 39ULL}, std::nullopt, false}, Row{
        InputWords{40ULL, ObservationWords{39ULL, 0x0000000000000000ULL, 0x3fd8000000000000ULL, true}, false, 1U, std::nullopt, false, std::nullopt, std::nullopt},
        StateWords{1U, {0x0000000000000000ULL, 0x3fd0000000000000ULL, 0x3fb0000000000000ULL}, 0U, std::nullopt, CommandWords{30U, 1U, 39ULL}, std::nullopt, false},
        0x0000000000000000ULL, {AckWords{30U, 2U, 40ULL, 1U, 0U}, AckWords{}}, 1U, 0U}},
    {"B05", StateWords{2U, {0x0000000000000000ULL, 0x3fd0000000000000ULL, 0x3fb0000000000000ULL}, 0U, std::nullopt, std::nullopt, std::nullopt, false}, Row{
        InputWords{100ULL, ObservationWords{80ULL, 0x3f80000000000000ULL, 0xbfc0000000000000ULL, true}, true, 20U, std::nullopt, false, std::nullopt, std::nullopt},
        StateWords{2U, {0x3f1f75104d551d69ULL, 0x3fc0000000000000ULL, 0x3fb079042d8c2a45ULL}, 0U, std::nullopt, std::nullopt, std::nullopt, false},
        0x3fb079042d8c2a45ULL, {AckWords{}, AckWords{}}, 0U, 1U}},
    {"B06", StateWords{0U, {0x0000000000000000ULL, 0x3fd0000000000000ULL, 0x3fb0000000000000ULL}, 0U, std::nullopt, std::nullopt, std::nullopt, false}, Row{
        InputWords{40ULL, ObservationWords{40ULL, 0x3fd3333333333333ULL, 0x0000000000000000ULL, true}, true, 0U, std::nullopt, false, std::nullopt, std::nullopt},
        StateWords{0U, {0x0000000000000000ULL, 0x3fd0000000000000ULL, 0x3fb0000000000000ULL}, 0U, std::nullopt, std::nullopt, std::nullopt, false},
        0x0000000000000000ULL, {AckWords{}, AckWords{}}, 0U, 0U}},
    {"B07", StateWords{0U, {0x0000000000000000ULL, 0x3fd0000000000000ULL, 0x3fb0000000000000ULL}, 0U, std::nullopt, std::nullopt, std::nullopt, false}, Row{
        InputWords{40ULL, ObservationWords{40ULL, 0xbfd3333333333333ULL, 0x0000000000000000ULL, true}, true, 0U, std::nullopt, false, std::nullopt, std::nullopt},
        StateWords{0U, {0x0000000000000000ULL, 0x3fd0000000000000ULL, 0x3fb0000000000000ULL}, 0U, std::nullopt, std::nullopt, std::nullopt, false},
        0x0000000000000000ULL, {AckWords{}, AckWords{}}, 0U, 0U}},
    {"B08", StateWords{2U, {0x8000000000000000ULL, 0x8000000000000000ULL, 0xbfb0000000000000ULL}, 998U, std::nullopt, std::nullopt, std::nullopt, false}, Row{
        InputWords{100ULL, ObservationWords{92ULL, 0x0000000000000000ULL, 0x0000000000000000ULL, true}, false, 8U, std::nullopt, false, std::nullopt, std::nullopt},
        StateWords{2U, {0x8000000000000000ULL, 0x8000000000000000ULL, 0xbfb0000000000000ULL}, 999U, std::nullopt, std::nullopt, std::nullopt, false},
        0xbfb0000000000000ULL, {AckWords{}, AckWords{}}, 0U, 0U}},
    {"B09", StateWords{2U, {0x8000000000000000ULL, 0x8000000000000000ULL, 0xbfb0000000000000ULL}, 998U, std::nullopt, std::nullopt, std::nullopt, false}, Row{
        InputWords{100ULL, ObservationWords{91ULL, 0x0000000000000000ULL, 0x0000000000000000ULL, true}, false, 9U, std::nullopt, false, std::nullopt, std::nullopt},
        StateWords{2U, {0x8000000000000000ULL, 0x8000000000000000ULL, 0xbfb0000000000000ULL}, 999U, std::nullopt, std::nullopt, std::nullopt, false},
        0x0000000000000000ULL, {AckWords{}, AckWords{}}, 0U, 0U}},
    {"B10", StateWords{0U, {0x0000000000000000ULL, 0x3fd0000000000000ULL, 0x3fb0000000000000ULL}, 998U, std::nullopt, std::nullopt, std::nullopt, false}, Row{
        InputWords{20ULL, std::nullopt, false, 21U, std::nullopt, false, std::nullopt, std::nullopt},
        StateWords{3U, {0x0000000000000000ULL, 0x3fd0000000000000ULL, 0x3fb0000000000000ULL}, 0U, std::nullopt, std::nullopt, TerminalWords{4U, 20ULL}, false},
        0x0000000000000000ULL, {AckWords{}, AckWords{}}, 0U, 0U}},
    {"B11", StateWords{1U, {0x0000000000000000ULL, 0x3fd0000000000000ULL, 0x3fb0000000000000ULL}, 998U, std::nullopt, std::nullopt, std::nullopt, false}, Row{
        InputWords{100ULL, ObservationWords{79ULL, 0x0000000000000000ULL, 0x0000000000000000ULL, true}, true, 21U, std::nullopt, false, std::nullopt, std::nullopt},
        StateWords{3U, {0x0000000000000000ULL, 0x3fd0000000000000ULL, 0x3fb0000000000000ULL}, 999U, std::nullopt, std::nullopt, TerminalWords{4U, 100ULL}, false},
        0x0000000000000000ULL, {AckWords{}, AckWords{}}, 0U, 0U}},
    {"B12", StateWords{0U, {0x0000000000000000ULL, 0x3fd0000000000000ULL, 0x3fb0000000000000ULL}, 998U, std::nullopt, std::nullopt, std::nullopt, false}, Row{
        InputWords{100ULL, ObservationWords{92ULL, 0x0000000000000000ULL, 0xbf947ae147ae147cULL, true}, false, 8U, std::nullopt, false, std::nullopt, std::nullopt},
        StateWords{0U, {0x0000000000000000ULL, 0x3fd0000000000000ULL, 0x3fb0000000000000ULL}, 0U, std::nullopt, std::nullopt, std::nullopt, false},
        0x0000000000000000ULL, {AckWords{}, AckWords{}}, 0U, 0U}},
    {"B13", StateWords{0U, {0x0000000000000000ULL, 0x0000000000000000ULL, 0x0000000000000000ULL}, 0U, std::nullopt, std::nullopt, std::nullopt, true}, Row{
        InputWords{0ULL, ObservationWords{0ULL, 0x0000000000000000ULL, 0x0000000000000000ULL, true}, true, 0U, std::nullopt, false, std::nullopt, std::nullopt},
        StateWords{2U, {0x0000000000000000ULL, 0x0000000000000000ULL, 0x0000000000000000ULL}, 1U, std::nullopt, std::nullopt, std::nullopt, true},
        0x0000000000000000ULL, {AckWords{}, AckWords{}}, 0U, 1U}},
    {"B14", StateWords{0U, {0x0000000000000000ULL, 0x3fc0000000000000ULL, 0x3fa3c6a7ef9db22dULL}, 998U, std::nullopt, std::nullopt, std::nullopt, true}, Row{
        InputWords{50ULL, ObservationWords{50ULL, 0x0000000000000000ULL, 0x0000000000000000ULL, true}, true, 0U, CommandWords{40U, 1U, 50ULL}, false, std::nullopt, std::nullopt},
        StateWords{2U, {0x0000000000000000ULL, 0x3fb5555555555556ULL, 0x3f9a5e353f7ced92ULL}, 999U, std::nullopt, CommandWords{40U, 1U, 50ULL}, std::nullopt, true},
        0x3f9a5e353f7ced92ULL, {AckWords{40U, 1U, 50ULL, 1U, 0U}, AckWords{}}, 1U, 1U}},
    {"B15", StateWords{1U, {0x0000000000000000ULL, 0x3fc0000000000000ULL, 0x3fa3c6a7ef9db22dULL}, 998U, std::nullopt, std::nullopt, std::nullopt, false}, Row{
        InputWords{50ULL, ObservationWords{50ULL, 0x0000000000000000ULL, 0x0000000000000000ULL, true}, true, 0U, CommandWords{40U, 2U, 50ULL}, false, std::nullopt, std::nullopt},
        StateWords{2U, {0x0000000000000000ULL, 0x3fb5555555555556ULL, 0x3f9a5e353f7ced92ULL}, 999U, std::nullopt, CommandWords{40U, 2U, 50ULL}, std::nullopt, false},
        0x3f9a5e353f7ced92ULL, {AckWords{40U, 1U, 50ULL, 2U, 0U}, AckWords{}}, 1U, 1U}},
};
constexpr Row trace_L[] = {
    Row{
        InputWords{0ULL, std::nullopt, false, 1U, CommandWords{1U, 1U, 0ULL}, false, std::nullopt, std::nullopt},
        StateWords{1U, {0x0000000000000000ULL, 0x3fd0000000000000ULL, 0x3fb0000000000000ULL}, 0U, std::nullopt, CommandWords{1U, 1U, 0ULL}, std::nullopt, false},
        0x0000000000000000ULL, {AckWords{1U, 1U, 0ULL, 1U, 0U}, AckWords{}}, 1U, 0U},
    Row{
        InputWords{1ULL, std::nullopt, false, 2U, CommandWords{1U, 1U, 0ULL}, false, std::nullopt, std::nullopt},
        StateWords{1U, {0x0000000000000000ULL, 0x3fd0000000000000ULL, 0x3fb0000000000000ULL}, 0U, std::nullopt, CommandWords{1U, 1U, 0ULL}, std::nullopt, false},
        0x0000000000000000ULL, {AckWords{1U, 3U, 0ULL, 1U, 0U}, AckWords{}}, 1U, 0U},
    Row{
        InputWords{2ULL, std::nullopt, false, 3U, CommandWords{2U, 1U, 2ULL}, false, std::nullopt, std::nullopt},
        StateWords{1U, {0x0000000000000000ULL, 0x3fd0000000000000ULL, 0x3fb0000000000000ULL}, 0U, std::nullopt, CommandWords{2U, 1U, 2ULL}, std::nullopt, false},
        0x0000000000000000ULL, {AckWords{2U, 5U, 0ULL, 1U, 0U}, AckWords{}}, 1U, 0U},
    Row{
        InputWords{3ULL, std::nullopt, false, 4U, CommandWords{3U, 2U, 3ULL}, false, std::nullopt, std::nullopt},
        StateWords{2U, {0x0000000000000000ULL, 0x3fd0000000000000ULL, 0x3fb0000000000000ULL}, 0U, std::nullopt, CommandWords{3U, 2U, 3ULL}, std::nullopt, false},
        0x3fb0000000000000ULL, {AckWords{3U, 1U, 3ULL, 2U, 0U}, AckWords{}}, 1U, 0U},
    Row{
        InputWords{4ULL, std::nullopt, false, 5U, CommandWords{4U, 2U, 4ULL}, false, std::nullopt, std::nullopt},
        StateWords{2U, {0x0000000000000000ULL, 0x3fd0000000000000ULL, 0x3fb0000000000000ULL}, 0U, std::nullopt, CommandWords{4U, 2U, 4ULL}, std::nullopt, false},
        0x3fb0000000000000ULL, {AckWords{4U, 5U, 0ULL, 2U, 0U}, AckWords{}}, 1U, 0U},
    Row{
        InputWords{5ULL, std::nullopt, false, 6U, CommandWords{5U, 1U, 5ULL}, false, std::nullopt, std::nullopt},
        StateWords{2U, {0x0000000000000000ULL, 0x3fd0000000000000ULL, 0x3fb0000000000000ULL}, 0U, std::nullopt, CommandWords{5U, 1U, 5ULL}, std::nullopt, false},
        0x3fb0000000000000ULL, {AckWords{5U, 5U, 0ULL, 2U, 0U}, AckWords{}}, 1U, 0U},
    Row{
        InputWords{6ULL, std::nullopt, false, 7U, CommandWords{6U, 3U, 6ULL}, false, std::nullopt, std::nullopt},
        StateWords{3U, {0x0000000000000000ULL, 0x3fd0000000000000ULL, 0x3fb0000000000000ULL}, 0U, std::nullopt, CommandWords{6U, 3U, 6ULL}, TerminalWords{3U, 6ULL}, false},
        0x0000000000000000ULL, {AckWords{6U, 1U, 6ULL, 3U, 3U}, AckWords{}}, 1U, 0U},
    Row{
        InputWords{7ULL, ObservationWords{7ULL, 0x0000000000000000ULL, 0x0000000000000000ULL, true}, true, 0U, CommandWords{7U, 1U, 7ULL}, true, std::optional<std::uint32_t>{0U}, std::optional<unsigned>{6U}},
        StateWords{3U, {0x0000000000000000ULL, 0x3fd0000000000000ULL, 0x3fb0000000000000ULL}, 0U, std::nullopt, CommandWords{6U, 3U, 6ULL}, TerminalWords{3U, 6ULL}, false},
        0x0000000000000000ULL, {AckWords{}, AckWords{}}, 0U, 0U}
};
constexpr Row trace_Q[] = {
    Row{
        InputWords{10ULL, ObservationWords{9ULL, 0x0000000000000000ULL, 0x3fd8000000000000ULL, true}, false, 1U, CommandWords{10U, 1U, 12ULL}, false, std::nullopt, std::nullopt},
        StateWords{0U, {0x0000000000000000ULL, 0x3fd0000000000000ULL, 0x3fb0000000000000ULL}, 0U, CommandWords{10U, 1U, 12ULL}, CommandWords{10U, 1U, 12ULL}, std::nullopt, false},
        0x0000000000000000ULL, {AckWords{10U, 0U, 0ULL, 0U, 0U}, AckWords{}}, 1U, 0U},
    Row{
        InputWords{11ULL, ObservationWords{9ULL, 0x0000000000000000ULL, 0x3fd8000000000000ULL, true}, false, 2U, CommandWords{11U, 2U, 13ULL}, false, std::nullopt, std::nullopt},
        StateWords{0U, {0x0000000000000000ULL, 0x3fd0000000000000ULL, 0x3fb0000000000000ULL}, 0U, CommandWords{10U, 1U, 12ULL}, CommandWords{10U, 1U, 12ULL}, std::nullopt, false},
        0x0000000000000000ULL, {AckWords{11U, 4U, 0ULL, 0U, 0U}, AckWords{}}, 1U, 0U},
    Row{
        InputWords{12ULL, ObservationWords{9ULL, 0x0000000000000000ULL, 0x3fd8000000000000ULL, true}, false, 3U, CommandWords{10U, 1U, 12ULL}, false, std::nullopt, std::nullopt},
        StateWords{1U, {0x0000000000000000ULL, 0x3fd0000000000000ULL, 0x3fb0000000000000ULL}, 0U, std::nullopt, CommandWords{10U, 1U, 12ULL}, std::nullopt, false},
        0x0000000000000000ULL, {AckWords{10U, 3U, 0ULL, 0U, 0U}, AckWords{10U, 1U, 12ULL, 1U, 0U}}, 2U, 0U},
    Row{
        InputWords{13ULL, ObservationWords{13ULL, 0x3f80000000000000ULL, 0xbfc0000000000000ULL, true}, true, 0U, CommandWords{11U, 2U, 12ULL}, false, std::nullopt, std::nullopt},
        StateWords{2U, {0x3f1f75104d551d69ULL, 0x3fc0000000000000ULL, 0x3fb079042d8c2a45ULL}, 0U, std::nullopt, CommandWords{11U, 2U, 12ULL}, std::nullopt, false},
        0x3fb079042d8c2a45ULL, {AckWords{11U, 2U, 13ULL, 2U, 0U}, AckWords{}}, 1U, 1U},
    Row{
        InputWords{14ULL, ObservationWords{13ULL, 0x3f80000000000000ULL, 0xbfc0000000000000ULL, true}, false, 1U, CommandWords{12U, 1U, 16ULL}, false, std::nullopt, std::nullopt},
        StateWords{2U, {0x3f1f75104d551d69ULL, 0x3fc0000000000000ULL, 0x3fb079042d8c2a45ULL}, 0U, CommandWords{12U, 1U, 16ULL}, CommandWords{12U, 1U, 16ULL}, std::nullopt, false},
        0x3fb079042d8c2a45ULL, {AckWords{12U, 0U, 0ULL, 2U, 0U}, AckWords{}}, 1U, 0U},
    Row{
        InputWords{15ULL, ObservationWords{13ULL, 0x3f80000000000000ULL, 0xbfc0000000000000ULL, true}, false, 2U, std::nullopt, false, std::nullopt, std::nullopt},
        StateWords{2U, {0x3f1f75104d551d69ULL, 0x3fc0000000000000ULL, 0x3fb079042d8c2a45ULL}, 0U, CommandWords{12U, 1U, 16ULL}, CommandWords{12U, 1U, 16ULL}, std::nullopt, false},
        0x3fb079042d8c2a45ULL, {AckWords{}, AckWords{}}, 0U, 0U},
    Row{
        InputWords{16ULL, ObservationWords{13ULL, 0x3f80000000000000ULL, 0xbfc0000000000000ULL, true}, false, 3U, std::nullopt, false, std::nullopt, std::nullopt},
        StateWords{2U, {0x3f1f75104d551d69ULL, 0x3fc0000000000000ULL, 0x3fb079042d8c2a45ULL}, 0U, std::nullopt, CommandWords{12U, 1U, 16ULL}, std::nullopt, false},
        0x3fb079042d8c2a45ULL, {AckWords{12U, 5U, 0ULL, 2U, 0U}, AckWords{}}, 1U, 0U},
    Row{
        InputWords{17ULL, ObservationWords{13ULL, 0x3f80000000000000ULL, 0xbfc0000000000000ULL, true}, false, 4U, CommandWords{12U, 1U, 16ULL}, false, std::nullopt, std::nullopt},
        StateWords{2U, {0x3f1f75104d551d69ULL, 0x3fc0000000000000ULL, 0x3fb079042d8c2a45ULL}, 0U, std::nullopt, CommandWords{12U, 1U, 16ULL}, std::nullopt, false},
        0x3fb079042d8c2a45ULL, {AckWords{12U, 3U, 0ULL, 2U, 0U}, AckWords{}}, 1U, 0U}
};
constexpr Row trace_R[] = {
    Row{
        InputWords{30ULL, ObservationWords{29ULL, 0x0000000000000000ULL, 0x3fd8000000000000ULL, true}, false, 1U, CommandWords{20U, 2U, 35ULL}, false, std::nullopt, std::nullopt},
        StateWords{1U, {0x0000000000000000ULL, 0x3fd0000000000000ULL, 0x3fb0000000000000ULL}, 0U, CommandWords{20U, 2U, 35ULL}, CommandWords{20U, 2U, 35ULL}, std::nullopt, false},
        0x0000000000000000ULL, {AckWords{20U, 0U, 0ULL, 1U, 0U}, AckWords{}}, 1U, 0U},
    Row{
        InputWords{31ULL, ObservationWords{29ULL, 0x0000000000000000ULL, 0x3fd8000000000000ULL, true}, false, 2U, CommandWords{21U, 3U, 34ULL}, false, std::nullopt, std::nullopt},
        StateWords{1U, {0x0000000000000000ULL, 0x3fd0000000000000ULL, 0x3fb0000000000000ULL}, 0U, CommandWords{21U, 3U, 34ULL}, CommandWords{21U, 3U, 34ULL}, std::nullopt, false},
        0x0000000000000000ULL, {AckWords{21U, 0U, 0ULL, 1U, 0U}, AckWords{20U, 9U, 0ULL, 1U, 0U}}, 2U, 0U},
    Row{
        InputWords{32ULL, ObservationWords{29ULL, 0x0000000000000000ULL, 0x3fd8000000000000ULL, true}, false, 3U, CommandWords{22U, 1U, 32ULL}, false, std::nullopt, std::nullopt},
        StateWords{1U, {0x0000000000000000ULL, 0x3fd0000000000000ULL, 0x3fb0000000000000ULL}, 0U, CommandWords{21U, 3U, 34ULL}, CommandWords{21U, 3U, 34ULL}, std::nullopt, false},
        0x0000000000000000ULL, {AckWords{22U, 4U, 0ULL, 1U, 0U}, AckWords{}}, 1U, 0U},
    Row{
        InputWords{33ULL, ObservationWords{29ULL, 0x0000000000000000ULL, 0x3fd8000000000000ULL, true}, false, 4U, CommandWords{22U, 3U, 33ULL}, false, std::nullopt, std::nullopt},
        StateWords{1U, {0x0000000000000000ULL, 0x3fd0000000000000ULL, 0x3fb0000000000000ULL}, 0U, CommandWords{21U, 3U, 34ULL}, CommandWords{21U, 3U, 34ULL}, std::nullopt, false},
        0x0000000000000000ULL, {AckWords{22U, 4U, 0ULL, 1U, 0U}, AckWords{}}, 1U, 0U},
    Row{
        InputWords{34ULL, ObservationWords{29ULL, 0x0000000000000000ULL, 0x3fd8000000000000ULL, true}, false, 5U, CommandWords{21U, 3U, 34ULL}, false, std::nullopt, std::nullopt},
        StateWords{3U, {0x0000000000000000ULL, 0x3fd0000000000000ULL, 0x3fb0000000000000ULL}, 0U, std::nullopt, CommandWords{21U, 3U, 34ULL}, TerminalWords{3U, 34ULL}, false},
        0x0000000000000000ULL, {AckWords{21U, 3U, 0ULL, 1U, 0U}, AckWords{21U, 1U, 34ULL, 3U, 3U}}, 2U, 0U}
};
constexpr Row trace_K[] = {
    Row{
        InputWords{0ULL, ObservationWords{0ULL, 0x0000000000000000ULL, 0x3fd8000000000000ULL, true}, true, 0U, std::nullopt, false, std::nullopt, std::nullopt},
        StateWords{2U, {0x0000000000000000ULL, 0x3fc0000000000000ULL, 0x3fa3c6a7ef9db22dULL}, 0U, std::nullopt, std::nullopt, std::nullopt, false},
        0x3fa3c6a7ef9db22dULL, {AckWords{}, AckWords{}}, 0U, 1U},
    Row{
        InputWords{1ULL, ObservationWords{0ULL, 0x0000000000000000ULL, 0x3fd8000000000000ULL, true}, false, 1U, std::nullopt, false, std::nullopt, std::nullopt},
        StateWords{2U, {0x0000000000000000ULL, 0x3fc0000000000000ULL, 0x3fa3c6a7ef9db22dULL}, 0U, std::nullopt, std::nullopt, std::nullopt, false},
        0x3fa3c6a7ef9db22dULL, {AckWords{}, AckWords{}}, 0U, 0U},
    Row{
        InputWords{2ULL, ObservationWords{0ULL, 0x0000000000000000ULL, 0x3fd8000000000000ULL, true}, false, 2U, std::nullopt, false, std::nullopt, std::nullopt},
        StateWords{2U, {0x0000000000000000ULL, 0x3fc0000000000000ULL, 0x3fa3c6a7ef9db22dULL}, 0U, std::nullopt, std::nullopt, std::nullopt, false},
        0x3fa3c6a7ef9db22dULL, {AckWords{}, AckWords{}}, 0U, 0U},
    Row{
        InputWords{3ULL, ObservationWords{0ULL, 0x0000000000000000ULL, 0x3fd8000000000000ULL, true}, false, 3U, std::nullopt, false, std::nullopt, std::nullopt},
        StateWords{2U, {0x0000000000000000ULL, 0x3fc0000000000000ULL, 0x3fa3c6a7ef9db22dULL}, 0U, std::nullopt, std::nullopt, std::nullopt, false},
        0x3fa3c6a7ef9db22dULL, {AckWords{}, AckWords{}}, 0U, 0U},
    Row{
        InputWords{4ULL, ObservationWords{0ULL, 0x0000000000000000ULL, 0x3fd8000000000000ULL, true}, false, 4U, std::nullopt, false, std::nullopt, std::nullopt},
        StateWords{2U, {0x0000000000000000ULL, 0x3fc0000000000000ULL, 0x3fa3c6a7ef9db22dULL}, 0U, std::nullopt, std::nullopt, std::nullopt, false},
        0x3fa3c6a7ef9db22dULL, {AckWords{}, AckWords{}}, 0U, 0U},
    Row{
        InputWords{5ULL, ObservationWords{0ULL, 0x0000000000000000ULL, 0x3fd8000000000000ULL, true}, false, 5U, std::nullopt, false, std::nullopt, std::nullopt},
        StateWords{2U, {0x0000000000000000ULL, 0x3fc0000000000000ULL, 0x3fa3c6a7ef9db22dULL}, 0U, std::nullopt, std::nullopt, std::nullopt, false},
        0x3fa3c6a7ef9db22dULL, {AckWords{}, AckWords{}}, 0U, 0U},
    Row{
        InputWords{6ULL, ObservationWords{0ULL, 0x0000000000000000ULL, 0x3fd8000000000000ULL, true}, false, 6U, std::nullopt, false, std::nullopt, std::nullopt},
        StateWords{2U, {0x0000000000000000ULL, 0x3fc0000000000000ULL, 0x3fa3c6a7ef9db22dULL}, 0U, std::nullopt, std::nullopt, std::nullopt, false},
        0x3fa3c6a7ef9db22dULL, {AckWords{}, AckWords{}}, 0U, 0U},
    Row{
        InputWords{7ULL, ObservationWords{0ULL, 0x0000000000000000ULL, 0x3fd8000000000000ULL, true}, false, 7U, std::nullopt, false, std::nullopt, std::nullopt},
        StateWords{2U, {0x0000000000000000ULL, 0x3fc0000000000000ULL, 0x3fa3c6a7ef9db22dULL}, 0U, std::nullopt, std::nullopt, std::nullopt, false},
        0x3fa3c6a7ef9db22dULL, {AckWords{}, AckWords{}}, 0U, 0U},
    Row{
        InputWords{8ULL, ObservationWords{0ULL, 0x0000000000000000ULL, 0x3fd8000000000000ULL, true}, false, 8U, std::nullopt, false, std::nullopt, std::nullopt},
        StateWords{2U, {0x0000000000000000ULL, 0x3fc0000000000000ULL, 0x3fa3c6a7ef9db22dULL}, 0U, std::nullopt, std::nullopt, std::nullopt, false},
        0x3fa3c6a7ef9db22dULL, {AckWords{}, AckWords{}}, 0U, 0U},
    Row{
        InputWords{9ULL, ObservationWords{9ULL, 0x0000000000000000ULL, 0x0000000000000000ULL, true}, true, 0U, std::nullopt, false, std::nullopt, std::nullopt},
        StateWords{2U, {0x0000000000000000ULL, 0x3fb5555555555556ULL, 0x3f9a5e353f7ced92ULL}, 1U, std::nullopt, std::nullopt, std::nullopt, false},
        0x3f9a5e353f7ced92ULL, {AckWords{}, AckWords{}}, 0U, 1U},
    Row{
        InputWords{10ULL, ObservationWords{9ULL, 0x0000000000000000ULL, 0x0000000000000000ULL, true}, false, 1U, std::nullopt, false, std::nullopt, std::nullopt},
        StateWords{2U, {0x0000000000000000ULL, 0x3fb5555555555556ULL, 0x3f9a5e353f7ced92ULL}, 2U, std::nullopt, std::nullopt, std::nullopt, false},
        0x3f9a5e353f7ced92ULL, {AckWords{}, AckWords{}}, 0U, 0U},
    Row{
        InputWords{11ULL, ObservationWords{9ULL, 0x0000000000000000ULL, 0x0000000000000000ULL, true}, false, 2U, std::nullopt, false, std::nullopt, std::nullopt},
        StateWords{2U, {0x0000000000000000ULL, 0x3fb5555555555556ULL, 0x3f9a5e353f7ced92ULL}, 3U, std::nullopt, std::nullopt, std::nullopt, false},
        0x3f9a5e353f7ced92ULL, {AckWords{}, AckWords{}}, 0U, 0U},
    Row{
        InputWords{12ULL, ObservationWords{9ULL, 0x0000000000000000ULL, 0x0000000000000000ULL, true}, false, 3U, std::nullopt, false, std::nullopt, std::nullopt},
        StateWords{2U, {0x0000000000000000ULL, 0x3fb5555555555556ULL, 0x3f9a5e353f7ced92ULL}, 4U, std::nullopt, std::nullopt, std::nullopt, false},
        0x3f9a5e353f7ced92ULL, {AckWords{}, AckWords{}}, 0U, 0U},
    Row{
        InputWords{13ULL, ObservationWords{9ULL, 0x0000000000000000ULL, 0x0000000000000000ULL, true}, false, 4U, std::nullopt, false, std::nullopt, std::nullopt},
        StateWords{2U, {0x0000000000000000ULL, 0x3fb5555555555556ULL, 0x3f9a5e353f7ced92ULL}, 5U, std::nullopt, std::nullopt, std::nullopt, false},
        0x3f9a5e353f7ced92ULL, {AckWords{}, AckWords{}}, 0U, 0U},
    Row{
        InputWords{14ULL, ObservationWords{9ULL, 0x0000000000000000ULL, 0x0000000000000000ULL, true}, false, 5U, std::nullopt, false, std::nullopt, std::nullopt},
        StateWords{2U, {0x0000000000000000ULL, 0x3fb5555555555556ULL, 0x3f9a5e353f7ced92ULL}, 6U, std::nullopt, std::nullopt, std::nullopt, false},
        0x3f9a5e353f7ced92ULL, {AckWords{}, AckWords{}}, 0U, 0U},
    Row{
        InputWords{15ULL, ObservationWords{9ULL, 0x0000000000000000ULL, 0x0000000000000000ULL, true}, false, 6U, std::nullopt, false, std::nullopt, std::nullopt},
        StateWords{2U, {0x0000000000000000ULL, 0x3fb5555555555556ULL, 0x3f9a5e353f7ced92ULL}, 7U, std::nullopt, std::nullopt, std::nullopt, false},
        0x3f9a5e353f7ced92ULL, {AckWords{}, AckWords{}}, 0U, 0U},
    Row{
        InputWords{16ULL, ObservationWords{9ULL, 0x0000000000000000ULL, 0x0000000000000000ULL, true}, false, 7U, std::nullopt, false, std::nullopt, std::nullopt},
        StateWords{2U, {0x0000000000000000ULL, 0x3fb5555555555556ULL, 0x3f9a5e353f7ced92ULL}, 8U, std::nullopt, std::nullopt, std::nullopt, false},
        0x3f9a5e353f7ced92ULL, {AckWords{}, AckWords{}}, 0U, 0U},
    Row{
        InputWords{17ULL, ObservationWords{9ULL, 0x0000000000000000ULL, 0x0000000000000000ULL, true}, false, 8U, std::nullopt, false, std::nullopt, std::nullopt},
        StateWords{2U, {0x0000000000000000ULL, 0x3fb5555555555556ULL, 0x3f9a5e353f7ced92ULL}, 9U, std::nullopt, std::nullopt, std::nullopt, false},
        0x3f9a5e353f7ced92ULL, {AckWords{}, AckWords{}}, 0U, 0U},
    Row{
        InputWords{18ULL, ObservationWords{9ULL, 0x0000000000000000ULL, 0x0000000000000000ULL, true}, false, 9U, std::nullopt, false, std::nullopt, std::nullopt},
        StateWords{2U, {0x0000000000000000ULL, 0x3fb5555555555556ULL, 0x3f9a5e353f7ced92ULL}, 10U, std::nullopt, std::nullopt, std::nullopt, false},
        0x0000000000000000ULL, {AckWords{}, AckWords{}}, 0U, 0U},
    Row{
        InputWords{19ULL, ObservationWords{9ULL, 0x0000000000000000ULL, 0x0000000000000000ULL, true}, false, 10U, std::nullopt, false, std::nullopt, std::nullopt},
        StateWords{2U, {0x0000000000000000ULL, 0x3fb5555555555556ULL, 0x3f9a5e353f7ced92ULL}, 11U, std::nullopt, std::nullopt, std::nullopt, false},
        0x0000000000000000ULL, {AckWords{}, AckWords{}}, 0U, 0U},
    Row{
        InputWords{20ULL, ObservationWords{9ULL, 0x0000000000000000ULL, 0x0000000000000000ULL, true}, false, 11U, std::nullopt, false, std::nullopt, std::nullopt},
        StateWords{2U, {0x0000000000000000ULL, 0x3fb5555555555556ULL, 0x3f9a5e353f7ced92ULL}, 12U, std::nullopt, std::nullopt, std::nullopt, false},
        0x0000000000000000ULL, {AckWords{}, AckWords{}}, 0U, 0U},
    Row{
        InputWords{21ULL, ObservationWords{9ULL, 0x0000000000000000ULL, 0x0000000000000000ULL, true}, false, 12U, std::nullopt, false, std::nullopt, std::nullopt},
        StateWords{2U, {0x0000000000000000ULL, 0x3fb5555555555556ULL, 0x3f9a5e353f7ced92ULL}, 13U, std::nullopt, std::nullopt, std::nullopt, false},
        0x0000000000000000ULL, {AckWords{}, AckWords{}}, 0U, 0U},
    Row{
        InputWords{22ULL, ObservationWords{9ULL, 0x0000000000000000ULL, 0x0000000000000000ULL, true}, false, 13U, std::nullopt, false, std::nullopt, std::nullopt},
        StateWords{2U, {0x0000000000000000ULL, 0x3fb5555555555556ULL, 0x3f9a5e353f7ced92ULL}, 14U, std::nullopt, std::nullopt, std::nullopt, false},
        0x0000000000000000ULL, {AckWords{}, AckWords{}}, 0U, 0U},
    Row{
        InputWords{23ULL, ObservationWords{9ULL, 0x0000000000000000ULL, 0x0000000000000000ULL, true}, false, 14U, std::nullopt, false, std::nullopt, std::nullopt},
        StateWords{2U, {0x0000000000000000ULL, 0x3fb5555555555556ULL, 0x3f9a5e353f7ced92ULL}, 15U, std::nullopt, std::nullopt, std::nullopt, false},
        0x0000000000000000ULL, {AckWords{}, AckWords{}}, 0U, 0U},
    Row{
        InputWords{24ULL, ObservationWords{9ULL, 0x0000000000000000ULL, 0x0000000000000000ULL, true}, false, 15U, std::nullopt, false, std::nullopt, std::nullopt},
        StateWords{2U, {0x0000000000000000ULL, 0x3fb5555555555556ULL, 0x3f9a5e353f7ced92ULL}, 16U, std::nullopt, std::nullopt, std::nullopt, false},
        0x0000000000000000ULL, {AckWords{}, AckWords{}}, 0U, 0U},
    Row{
        InputWords{25ULL, ObservationWords{9ULL, 0x0000000000000000ULL, 0x0000000000000000ULL, true}, false, 16U, std::nullopt, false, std::nullopt, std::nullopt},
        StateWords{2U, {0x0000000000000000ULL, 0x3fb5555555555556ULL, 0x3f9a5e353f7ced92ULL}, 17U, std::nullopt, std::nullopt, std::nullopt, false},
        0x0000000000000000ULL, {AckWords{}, AckWords{}}, 0U, 0U},
    Row{
        InputWords{26ULL, ObservationWords{9ULL, 0x0000000000000000ULL, 0x0000000000000000ULL, true}, false, 17U, std::nullopt, false, std::nullopt, std::nullopt},
        StateWords{2U, {0x0000000000000000ULL, 0x3fb5555555555556ULL, 0x3f9a5e353f7ced92ULL}, 18U, std::nullopt, std::nullopt, std::nullopt, false},
        0x0000000000000000ULL, {AckWords{}, AckWords{}}, 0U, 0U},
    Row{
        InputWords{27ULL, ObservationWords{9ULL, 0x0000000000000000ULL, 0x0000000000000000ULL, true}, false, 18U, std::nullopt, false, std::nullopt, std::nullopt},
        StateWords{2U, {0x0000000000000000ULL, 0x3fb5555555555556ULL, 0x3f9a5e353f7ced92ULL}, 19U, std::nullopt, std::nullopt, std::nullopt, false},
        0x0000000000000000ULL, {AckWords{}, AckWords{}}, 0U, 0U},
    Row{
        InputWords{28ULL, ObservationWords{9ULL, 0x0000000000000000ULL, 0x0000000000000000ULL, true}, false, 19U, std::nullopt, false, std::nullopt, std::nullopt},
        StateWords{2U, {0x0000000000000000ULL, 0x3fb5555555555556ULL, 0x3f9a5e353f7ced92ULL}, 20U, std::nullopt, std::nullopt, std::nullopt, false},
        0x0000000000000000ULL, {AckWords{}, AckWords{}}, 0U, 0U},
    Row{
        InputWords{29ULL, ObservationWords{9ULL, 0x0000000000000000ULL, 0x0000000000000000ULL, true}, false, 20U, std::nullopt, false, std::nullopt, std::nullopt},
        StateWords{2U, {0x0000000000000000ULL, 0x3fb5555555555556ULL, 0x3f9a5e353f7ced92ULL}, 21U, std::nullopt, std::nullopt, std::nullopt, false},
        0x0000000000000000ULL, {AckWords{}, AckWords{}}, 0U, 0U},
    Row{
        InputWords{30ULL, ObservationWords{30ULL, 0x0000000000000000ULL, 0x0000000000000000ULL, true}, true, 0U, std::nullopt, false, std::nullopt, std::nullopt},
        StateWords{2U, {0x0000000000000000ULL, 0x3fac71c71c71c71eULL, 0x3f9194237fa89e62ULL}, 22U, std::nullopt, std::nullopt, std::nullopt, false},
        0x3f9194237fa89e62ULL, {AckWords{}, AckWords{}}, 0U, 1U}
};
constexpr Row trace_S[] = {
    Row{
        InputWords{0ULL, ObservationWords{0ULL, 0x3f947ae147ae147bULL, 0xbf947ae147ae147bULL, true}, true, 0U, std::nullopt, false, std::nullopt, std::nullopt},
        StateWords{0U, {0x0000000000000000ULL, 0x3fd0000000000000ULL, 0x3fb0000000000000ULL}, 999U, std::nullopt, std::nullopt, std::nullopt, false},
        0x0000000000000000ULL, {AckWords{}, AckWords{}}, 0U, 0U},
    Row{
        InputWords{1ULL, ObservationWords{0ULL, 0x3f947ae147ae147bULL, 0xbf947ae147ae147bULL, true}, false, 1U, std::nullopt, false, std::nullopt, std::nullopt},
        StateWords{0U, {0x0000000000000000ULL, 0x3fd0000000000000ULL, 0x3fb0000000000000ULL}, 1000U, std::nullopt, std::nullopt, std::nullopt, false},
        0x0000000000000000ULL, {AckWords{}, AckWords{}}, 0U, 0U},
    Row{
        InputWords{2ULL, ObservationWords{2ULL, 0xbf947ae147ae147bULL, 0x3f947ae147ae147bULL, true}, true, 0U, std::nullopt, false, std::nullopt, std::nullopt},
        StateWords{0U, {0x0000000000000000ULL, 0x3fd0000000000000ULL, 0x3fb0000000000000ULL}, 1000U, std::nullopt, std::nullopt, std::nullopt, false},
        0x0000000000000000ULL, {AckWords{}, AckWords{}}, 0U, 0U},
    Row{
        InputWords{3ULL, ObservationWords{3ULL, 0x3f947ae147ae147cULL, 0x0000000000000000ULL, true}, true, 0U, std::nullopt, false, std::nullopt, std::nullopt},
        StateWords{0U, {0x0000000000000000ULL, 0x3fd0000000000000ULL, 0x3fb0000000000000ULL}, 0U, std::nullopt, std::nullopt, std::nullopt, false},
        0x0000000000000000ULL, {AckWords{}, AckWords{}}, 0U, 0U},
    Row{
        InputWords{4ULL, ObservationWords{4ULL, 0xbf947ae147ae147cULL, 0x0000000000000000ULL, true}, true, 0U, std::nullopt, false, std::nullopt, std::nullopt},
        StateWords{0U, {0x0000000000000000ULL, 0x3fd0000000000000ULL, 0x3fb0000000000000ULL}, 0U, std::nullopt, std::nullopt, std::nullopt, false},
        0x0000000000000000ULL, {AckWords{}, AckWords{}}, 0U, 0U},
    Row{
        InputWords{5ULL, ObservationWords{4ULL, 0xbf947ae147ae147cULL, 0x0000000000000000ULL, true}, false, 1U, std::nullopt, false, std::nullopt, std::nullopt},
        StateWords{0U, {0x0000000000000000ULL, 0x3fd0000000000000ULL, 0x3fb0000000000000ULL}, 0U, std::nullopt, std::nullopt, std::nullopt, false},
        0x0000000000000000ULL, {AckWords{}, AckWords{}}, 0U, 0U},
    Row{
        InputWords{6ULL, ObservationWords{6ULL, 0x0000000000000000ULL, 0x3f947ae147ae147cULL, true}, true, 0U, std::nullopt, false, std::nullopt, std::nullopt},
        StateWords{0U, {0x0000000000000000ULL, 0x3fd0000000000000ULL, 0x3fb0000000000000ULL}, 0U, std::nullopt, std::nullopt, std::nullopt, false},
        0x0000000000000000ULL, {AckWords{}, AckWords{}}, 0U, 0U},
    Row{
        InputWords{7ULL, ObservationWords{7ULL, 0x0000000000000000ULL, 0xbf947ae147ae147cULL, true}, true, 0U, std::nullopt, false, std::nullopt, std::nullopt},
        StateWords{0U, {0x0000000000000000ULL, 0x3fd0000000000000ULL, 0x3fb0000000000000ULL}, 0U, std::nullopt, std::nullopt, std::nullopt, false},
        0x0000000000000000ULL, {AckWords{}, AckWords{}}, 0U, 0U},
    Row{
        InputWords{8ULL, ObservationWords{8ULL, 0x0000000000000000ULL, 0x0000000000000000ULL, true}, true, 0U, std::nullopt, false, std::nullopt, std::nullopt},
        StateWords{0U, {0x0000000000000000ULL, 0x3fd0000000000000ULL, 0x3fb0000000000000ULL}, 1U, std::nullopt, std::nullopt, std::nullopt, false},
        0x0000000000000000ULL, {AckWords{}, AckWords{}}, 0U, 0U},
    Row{
        InputWords{9ULL, ObservationWords{8ULL, 0x0000000000000000ULL, 0x0000000000000000ULL, true}, false, 1U, std::nullopt, true, std::nullopt, std::nullopt},
        StateWords{3U, {0x0000000000000000ULL, 0x3fd0000000000000ULL, 0x3fb0000000000000ULL}, 2U, std::nullopt, std::nullopt, TerminalWords{7U, 9ULL}, false},
        0x0000000000000000ULL, {AckWords{}, AckWords{}}, 0U, 0U}
};
constexpr Row trace_A[] = {
    Row{
        InputWords{0ULL, std::nullopt, false, 1U, std::nullopt, false, std::nullopt, std::nullopt},
        StateWords{0U, {0x0000000000000000ULL, 0x3fd0000000000000ULL, 0x3fb0000000000000ULL}, 0U, std::nullopt, std::nullopt, std::nullopt, true},
        0x0000000000000000ULL, {AckWords{}, AckWords{}}, 0U, 0U},
    Row{
        InputWords{1ULL, std::nullopt, false, 2U, CommandWords{1U, 1U, 1ULL}, false, std::nullopt, std::nullopt},
        StateWords{1U, {0x0000000000000000ULL, 0x3fd0000000000000ULL, 0x3fb0000000000000ULL}, 0U, std::nullopt, CommandWords{1U, 1U, 1ULL}, std::nullopt, true},
        0x0000000000000000ULL, {AckWords{1U, 1U, 1ULL, 1U, 0U}, AckWords{}}, 1U, 0U},
    Row{
        InputWords{2ULL, ObservationWords{2ULL, 0x3f80000000000000ULL, 0xbfc0000000000000ULL, true}, true, 0U, std::nullopt, false, std::nullopt, std::nullopt},
        StateWords{2U, {0x3f1f75104d551d69ULL, 0x3fc0000000000000ULL, 0x3fb079042d8c2a45ULL}, 0U, std::nullopt, CommandWords{1U, 1U, 1ULL}, std::nullopt, true},
        0x3fb079042d8c2a45ULL, {AckWords{}, AckWords{}}, 0U, 1U}
};
struct Trace { const char* name; StateWords seed; std::span<const Row> rows; };
constexpr Trace traces[] = {
    {"L", StateWords{0U, {0x0000000000000000ULL, 0x3fd0000000000000ULL, 0x3fb0000000000000ULL}, 0U, std::nullopt, std::nullopt, std::nullopt, false}, trace_L},
    {"Q", StateWords{0U, {0x0000000000000000ULL, 0x3fd0000000000000ULL, 0x3fb0000000000000ULL}, 0U, std::nullopt, std::nullopt, std::nullopt, false}, trace_Q},
    {"R", StateWords{1U, {0x0000000000000000ULL, 0x3fd0000000000000ULL, 0x3fb0000000000000ULL}, 0U, std::nullopt, std::nullopt, std::nullopt, false}, trace_R},
    {"K", StateWords{2U, {0x0000000000000000ULL, 0x0000000000000000ULL, 0x0000000000000000ULL}, 0U, std::nullopt, std::nullopt, std::nullopt, false}, trace_K},
    {"S", StateWords{0U, {0x0000000000000000ULL, 0x3fd0000000000000ULL, 0x3fb0000000000000ULL}, 998U, std::nullopt, std::nullopt, std::nullopt, false}, trace_S},
    {"A", StateWords{0U, {0x0000000000000000ULL, 0x3fd0000000000000ULL, 0x3fb0000000000000ULL}, 0U, std::nullopt, std::nullopt, std::nullopt, true}, trace_A},
};
}  // namespace

namespace {
unsigned step_calls = 0;
unsigned initial_calls = 0;
}

// Test-only ELF interposition. Forward to the unchanged production controller.
extern "C" control::State real_initial() noexcept
    asm("__real__ZN7control7initialEv");
extern "C" double real_step(control::State&, const Observation&) noexcept
    asm("__real__ZN7control4stepERNS_5StateERK11Observation");
extern "C" control::State wrapped_initial() noexcept
    asm("__wrap__ZN7control7initialEv");
extern "C" double wrapped_step(control::State&, const Observation&) noexcept
    asm("__wrap__ZN7control4stepERNS_5StateERK11Observation");

extern "C" control::State wrapped_initial() noexcept {
    ++initial_calls;
    return real_initial();
}
extern "C" double wrapped_step(control::State& state, const Observation& obs) noexcept {
    ++step_calls;
    return real_step(state, obs);
}

static_assert(sizeof(double) == sizeof(std::uint64_t));
static_assert(std::numeric_limits<double>::is_iec559);
static_assert(std::numeric_limits<double>::digits == 53);
static_assert(FLT_EVAL_METHOD == 0);
static_assert(std::is_same_v<decltype(&episode::initial), episode::State (*)(bool) noexcept>);
static_assert(std::is_same_v<decltype(&episode::step),
    episode::Transition (*)(const episode::State&, const episode::Inputs&) noexcept>);
static_assert(std::is_aggregate_v<episode::Command>);
static_assert(std::is_aggregate_v<episode::Ack>);
static_assert(std::is_aggregate_v<episode::TerminalResult>);
static_assert(std::is_aggregate_v<episode::State>);
static_assert(std::is_aggregate_v<episode::Inputs>);
static_assert(std::is_aggregate_v<episode::Transition>);
static_assert(std::is_same_v<decltype(episode::Command::opcode), std::uint16_t>);
static_assert(std::is_same_v<decltype(episode::Inputs::sim_reason), std::optional<std::uint32_t>>);
static_assert(std::is_same_v<decltype(episode::State::pid), control::State>);
static_assert(std::is_same_v<decltype(episode::Inputs::held), std::optional<Observation>>);
static_assert(std::is_same_v<decltype(episode::AckBatch::values), std::array<episode::Ack, 2>>);

static_assert(std::is_same_v<decltype(episode::Command::cmd_seq), std::uint32_t>);
static_assert(std::is_same_v<decltype(episode::Command::effective_tick), std::uint64_t>);
static_assert(std::is_same_v<decltype(episode::Ack::cmd_seq), std::uint32_t>);
static_assert(std::is_same_v<decltype(episode::Ack::status), episode::AckStatus>);
static_assert(std::is_same_v<decltype(episode::Ack::applied_tick), std::uint64_t>);
static_assert(std::is_same_v<decltype(episode::Ack::state), episode::Mode>);
static_assert(std::is_same_v<decltype(episode::Ack::reason), episode::Reason>);
static_assert(std::is_same_v<decltype(episode::TerminalResult::reason), episode::Reason>);
static_assert(std::is_same_v<decltype(episode::TerminalResult::tick), std::uint64_t>);
static_assert(std::is_same_v<decltype(episode::State::mode), episode::Mode>);
static_assert(std::is_same_v<decltype(episode::State::settle_count), std::uint32_t>);
static_assert(std::is_same_v<decltype(episode::State::pending), std::optional<episode::Command>>);
static_assert(std::is_same_v<decltype(episode::State::last_accepted), std::optional<episode::Command>>);
static_assert(std::is_same_v<decltype(episode::State::terminal), std::optional<episode::TerminalResult>>);
static_assert(std::is_same_v<decltype(episode::State::auto_arm), bool>);
static_assert(std::is_same_v<decltype(episode::Inputs::tick), std::uint64_t>);
static_assert(std::is_same_v<decltype(episode::Inputs::fresh), bool>);
static_assert(std::is_same_v<decltype(episode::Inputs::staleness), std::uint32_t>);
static_assert(std::is_same_v<decltype(episode::Inputs::command), std::optional<episode::Command>>);
static_assert(std::is_same_v<decltype(episode::Inputs::horizon_reached), bool>);
static_assert(std::is_same_v<decltype(episode::Inputs::stop_reason), std::optional<episode::Reason>>);
static_assert(std::is_same_v<decltype(episode::Transition::state), episode::State>);
static_assert(std::is_same_v<decltype(episode::Transition::requested_delta), double>);
static_assert(std::is_same_v<decltype(episode::Transition::acks), episode::AckBatch>);
static_assert(std::is_same_v<decltype(episode::AckBatch::count), std::uint8_t>);

namespace {
double from_bits(std::uint64_t x) { return std::bit_cast<double>(x); }
std::uint64_t bits(double x) { return std::bit_cast<std::uint64_t>(x); }
std::array<std::uint64_t, 3> pid_words(const control::State& p) {
    return {bits(p.i_state), bits(p.d_prev), bits(p.last_delta)};
}
std::optional<episode::Command> command(const std::optional<CommandWords>& x) {
    if (!x) return std::nullopt;
    return episode::Command{x->seq, x->opcode, x->tick};
}
episode::State make_state(const StateWords& s) {
    std::optional<episode::TerminalResult> terminal;
    if (s.terminal) terminal = episode::TerminalResult{
        static_cast<episode::Reason>(s.terminal->reason), s.terminal->tick};
    return {static_cast<episode::Mode>(s.mode),
        {from_bits(s.pid[0]), from_bits(s.pid[1]), from_bits(s.pid[2])},
        s.count, command(s.pending), command(s.last), terminal, s.auto_arm};
}
episode::Inputs make_input(const InputWords& x) {
    std::optional<Observation> held;
    if (x.held) held = Observation{x.held->tick, from_bits(x.held->theta),
                                 from_bits(x.held->omega), x.held->valid};
    std::optional<episode::Reason> stop;
    if (x.stop) stop = static_cast<episode::Reason>(*x.stop);
    return {x.tick, held, x.fresh, x.age, command(x.command), x.horizon, x.sim, stop};
}
void check_command(const std::optional<episode::Command>& a,
                   const std::optional<episode::Command>& b) {
    CHECK(a.has_value() == b.has_value());
    if (a) {
        CHECK(a->cmd_seq == b->cmd_seq);
        CHECK(a->opcode == b->opcode);
        CHECK(a->effective_tick == b->effective_tick);
    }
}
void check_state(const episode::State& a, const episode::State& b) {
    CHECK(a.mode == b.mode);
    CHECK(pid_words(a.pid) == pid_words(b.pid));
    CHECK(a.settle_count == b.settle_count);
    check_command(a.pending, b.pending);
    check_command(a.last_accepted, b.last_accepted);
    CHECK(a.terminal.has_value() == b.terminal.has_value());
    if (a.terminal) {
        CHECK(a.terminal->reason == b.terminal->reason);
        CHECK(a.terminal->tick == b.terminal->tick);
    }
    CHECK(a.auto_arm == b.auto_arm);
}
void check_input(const episode::Inputs& a, const episode::Inputs& b) {
    CHECK(a.tick == b.tick);
    CHECK(a.held.has_value() == b.held.has_value());
    if (a.held) {
        CHECK(a.held->tick == b.held->tick);
        CHECK(bits(a.held->theta) == bits(b.held->theta));
        CHECK(bits(a.held->omega) == bits(b.held->omega));
        CHECK(a.held->valid == b.held->valid);
    }
    CHECK(a.fresh == b.fresh);
    CHECK(a.staleness == b.staleness);
    check_command(a.command, b.command);
    CHECK(a.horizon_reached == b.horizon_reached);
    CHECK(a.sim_reason == b.sim_reason);
    CHECK(a.stop_reason == b.stop_reason);
}
unsigned transitions = 0, observed_steps = 0, zero_call_transitions = 0;
episode::State check_row(const episode::State& state, const Row& row) {
    const auto input = make_input(row.input);
    const auto before_state = state;
    const auto before_input = input;
    step_calls = initial_calls = 0;
    const auto result = episode::step(state, input);
    CHECK(step_calls == row.pid_calls);
    CHECK(initial_calls == 0);
    check_state(result.state, make_state(row.next));
    CHECK(bits(result.requested_delta) == row.request);
    CHECK(result.acks.count == row.ack_count);
    CHECK(result.acks.count <= 2);
    for (unsigned i = 0; i < row.ack_count; ++i) {
        const auto& a = result.acks.values[i];
        const auto& e = row.acks[i];
        CHECK(a.cmd_seq == e.seq);
        CHECK(static_cast<unsigned>(a.status) == e.status);
        CHECK(a.applied_tick == e.tick);
        CHECK(static_cast<unsigned>(a.state) == e.mode);
        CHECK(static_cast<unsigned>(a.reason) == e.reason);
    }
    check_state(state, before_state);
    check_input(input, before_input);
    ++transitions;
    observed_steps += step_calls;
    if (step_calls == 0) ++zero_call_transitions;
    return result.state;
}
void check_representation() {
    const auto state = make_state({2, {0x8000000000000000ULL, 0x8000000000000000ULL,
        0xbfb0000000000000ULL}, 998, CommandWords{1, 2, 3}, CommandWords{4, 1, 6},
        TerminalWords{6, 7}, true});
    CHECK(state.pending->cmd_seq == 1 && state.last_accepted->cmd_seq == 4);
    CHECK(state.pending->opcode == 2 && state.pending->effective_tick == 3);
    CHECK(state.terminal->reason == episode::Reason::SIGNAL && state.terminal->tick == 7);
    CHECK(pid_words(state.pid) == (std::array<std::uint64_t, 3>{
        0x8000000000000000ULL, 0x8000000000000000ULL, 0xbfb0000000000000ULL}));
    const episode::Ack ack{11, episode::AckStatus::APPLIED, 12,
                           episode::Mode::ARMED, episode::Reason::NONE};
    CHECK(ack.cmd_seq == 11 && ack.applied_tick == 12);
    CHECK(ack.state == episode::Mode::ARMED && ack.reason == episode::Reason::NONE);
    const episode::Transition output{state, from_bits(0x8000000000000000ULL), {}};
    CHECK(bits(output.requested_delta) == 0x8000000000000000ULL);
    CHECK(output.acks.count == 0);
}

void check_vocabulary() {
#define VALUE(type, name, value) CHECK(static_cast<unsigned>(episode::type::name) == value)
    VALUE(Mode, INIT, 0); VALUE(Mode, ARMED, 1);
    VALUE(Mode, FLYING, 2); VALUE(Mode, TERMINATED, 3);
    VALUE(Reason, NONE, 0); VALUE(Reason, STABILIZED, 1); VALUE(Reason, DIVERGED, 2);
    VALUE(Reason, GROUND_ABORT, 3); VALUE(Reason, SENSOR_LOST, 4); VALUE(Reason, PEER_LOST, 5);
    VALUE(Reason, SIGNAL, 6); VALUE(Reason, NOT_SETTLED, 7); VALUE(Reason, INTERNAL, 8);
    VALUE(Opcode, ARM, 1); VALUE(Opcode, LAUNCH, 2); VALUE(Opcode, ABORT, 3);
    VALUE(AckStatus, QUEUED, 0); VALUE(AckStatus, APPLIED, 1); VALUE(AckStatus, APPLIED_LATE, 2);
    VALUE(AckStatus, DUPLICATE, 3); VALUE(AckStatus, REJECTED_PENDING, 4);
    VALUE(AckStatus, REJECTED_STATE, 5); VALUE(AckStatus, REJECTED_IDENTITY, 6);
    VALUE(AckStatus, REJECTED_OPCODE, 7); VALUE(AckStatus, REJECTED_STALE, 8);
    VALUE(AckStatus, PREEMPTED, 9); VALUE(AckStatus, REJECTED_OVERFLOW, 10);
    VALUE(SimReason, SIM_NONE, 0); VALUE(SimReason, SIM_HORIZON, 1);
    VALUE(SimReason, SIM_LOC_ANGLE, 2); VALUE(SimReason, SIM_LOC_NONFINITE, 3);
    VALUE(SimReason, SIM_VEHICLE_TERMINAL, 4); VALUE(SimReason, SIM_PEER_LOST, 6);
#undef VALUE
}
void wrapper_control(bool negative) {
    step_calls = initial_calls = 0;
    auto bypass = real_initial();
    CHECK(pid_words(bypass) == (std::array<std::uint64_t, 3>{0, 0, 0}));
    CHECK(bits(real_step(bypass, {0, +0.0, +0.0, true})) == 0);
    CHECK(step_calls == 0 && initial_calls == 0);
    auto init = control::initial();
    CHECK(initial_calls == 1);
    CHECK(pid_words(init) == (std::array<std::uint64_t, 3>{0, 0, 0}));
    control::State p{+0.0, from_bits(0x3fd0000000000000ULL), from_bits(0x3fb0000000000000ULL)};
    const double delta = control::step(p, {0, from_bits(0x3f80000000000000ULL),
                                            from_bits(0xbfc0000000000000ULL), true});
    CHECK(bits(delta) == 0x3fb079042d8c2a45ULL);
    CHECK(pid_words(p) == (std::array<std::uint64_t, 3>{
        0x3f1f75104d551d69ULL, 0x3fc0000000000000ULL, 0x3fb079042d8c2a45ULL}));
    if (negative) {
        std::fprintf(stderr, "negative control: deliberately expect zero after a real wrapped PID call\n");
        CHECK(step_calls == 0);
    }
    CHECK(step_calls == 1 && initial_calls == 1);
    std::puts("wrapper control: real bypass=0; wrapped initial=1; wrapped step=1; exact V03 passed");
}
}  // namespace

int main(int argc, char** argv) {
    CHECK(argc == 1 || (argc == 2 && std::string_view(argv[1]) == "--wrapper-negative-control"));
    wrapper_control(argc == 2);
    check_vocabulary();
    check_representation();
    CHECK(std::size(vectors) == 43);
    const unsigned lengths[] = {8, 8, 5, 31, 10, 3};
    CHECK(std::size(traces) == std::size(lengths));
    unsigned ordinal = 0;
    for (const auto& v : vectors) {
        char expected_name[4];
        const char group = ordinal < 12 ? 'C' : ordinal < 28 ? 'T' : 'B';
        const unsigned number = ordinal < 12 ? ordinal + 1 : ordinal < 28 ? ordinal - 11 : ordinal - 27;
        std::snprintf(expected_name, sizeof(expected_name), "%c%02u", group, number);
        CHECK(std::string_view(v.name) == expected_name);
        ++ordinal;
        std::printf("vector %s\n", v.name);
        check_row(make_state(v.seed), v.row);
    }
    const char* trace_names[] = {"L", "Q", "R", "K", "S", "A"};
    for (unsigned i = 0; i < std::size(traces); ++i) {
        const auto& t = traces[i];
        CHECK(t.rows.size() == lengths[i]);
        CHECK(std::string_view(t.name) == trace_names[i]);
        auto state = make_state(t.seed);
        unsigned index = 0;
        for (const auto& row : t.rows) {
            std::printf("trace %s/%u\n", t.name, index++);
            state = check_row(state, row);
        }
    }
    for (bool auto_arm : {false, true}) {
        step_calls = initial_calls = 0;
        const auto state = episode::initial(auto_arm);
        CHECK(initial_calls == 1 && step_calls == 0);
        check_state(state, make_state({0, {0, 0, 0}, 0, {}, {}, {}, auto_arm}));
    }
    CHECK(transitions == 108);
    CHECK(observed_steps == 9);
    CHECK(zero_call_transitions == 99);
    std::puts("episode_tests: 43 vectors, 6 traces/65 calls, 108 transitions, 2 initialization cases; PID steps=9, no-step transitions=99, transition initializations=0; all green");
}
