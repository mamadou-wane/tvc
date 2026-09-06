#pragma once

#include "control.hpp"

#include <array>
#include <cstdint>
#include <optional>

namespace episode {

enum class Mode : std::uint8_t { INIT = 0, ARMED = 1, FLYING = 2, TERMINATED = 3 };
enum class Reason : std::uint8_t {
    NONE = 0, STABILIZED = 1, DIVERGED = 2, GROUND_ABORT = 3,
    SENSOR_LOST = 4, PEER_LOST = 5, SIGNAL = 6, NOT_SETTLED = 7, INTERNAL = 8
};
enum class Opcode : std::uint16_t { ARM = 1, LAUNCH = 2, ABORT = 3 };
enum class AckStatus : std::uint16_t {
    QUEUED = 0, APPLIED = 1, APPLIED_LATE = 2, DUPLICATE = 3,
    REJECTED_PENDING = 4, REJECTED_STATE = 5, REJECTED_IDENTITY = 6,
    REJECTED_OPCODE = 7, REJECTED_STALE = 8, PREEMPTED = 9, REJECTED_OVERFLOW = 10
};
enum class SimReason : std::uint32_t {
    SIM_NONE = 0, SIM_HORIZON = 1, SIM_LOC_ANGLE = 2, SIM_LOC_NONFINITE = 3,
    SIM_VEHICLE_TERMINAL = 4, SIM_PEER_LOST = 6
};

struct Command {
    std::uint32_t cmd_seq;
    std::uint16_t opcode;
    std::uint64_t effective_tick;
};
struct Ack {
    std::uint32_t cmd_seq;
    AckStatus status;
    std::uint64_t applied_tick;
    Mode state;
    Reason reason;
};
struct TerminalResult {
    Reason reason;
    std::uint64_t tick;
};
struct State {
    Mode mode;
    control::State pid;
    std::uint32_t settle_count;
    std::optional<Command> pending;
    std::optional<Command> last_accepted;
    std::optional<TerminalResult> terminal;
    bool auto_arm;
};
struct Inputs {
    std::uint64_t tick;
    std::optional<Observation> held;
    bool fresh;
    std::uint32_t staleness;
    std::optional<Command> command;
    bool horizon_reached;
    std::optional<std::uint32_t> sim_reason;
    std::optional<Reason> stop_reason;
};
struct AckBatch {
    // Only [0, count) contains events, in arrival-then-pending order.
    std::array<Ack, 2> values{};
    std::uint8_t count{};
};
struct Transition {
    State state;
    double requested_delta;
    AckBatch acks;
};

State initial(bool auto_arm) noexcept;

// Held observations are admitted/finite; fresh requires held. Live nonfresh
// age is >=1, settle_count is 0..1000, and TERMINATED has a terminal result.
// stop_reason is absent or PEER_LOST/SIGNAL/INTERNAL. No admission occurs here.
Transition step(const State& state, const Inputs& inputs) noexcept;

}  // namespace episode
