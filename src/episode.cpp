#include "episode.hpp"

#include <cmath>

namespace episode {
namespace {
bool is_opcode(const Command& c, Opcode opcode) noexcept {
    return c.opcode == static_cast<std::uint16_t>(opcode);
}
std::optional<AckStatus> prefix(const Command& c,
                                const std::optional<Command>& last) noexcept {
    if (!is_opcode(c, Opcode::ARM) && !is_opcode(c, Opcode::LAUNCH)
        && !is_opcode(c, Opcode::ABORT)) return AckStatus::REJECTED_OPCODE;
    if (last) {
        if (c.cmd_seq == last->cmd_seq) {
            if (c.opcode == last->opcode && c.effective_tick == last->effective_tick)
                return AckStatus::DUPLICATE;
            return AckStatus::REJECTED_IDENTITY;
        }
        const std::uint32_t gap = c.cmd_seq - last->cmd_seq;
        if (gap == 0 || gap >= 0x80000000U) return AckStatus::REJECTED_STALE;
    }
    return std::nullopt;
}
Ack apply(State& next, const Command& c, std::uint64_t tick) noexcept {
    Reason reason = Reason::NONE;
    if (is_opcode(c, Opcode::ARM) && next.mode == Mode::INIT) {
        next.mode = Mode::ARMED;
    } else if (is_opcode(c, Opcode::LAUNCH) && next.mode == Mode::ARMED) {
        next.mode = Mode::FLYING;
    } else if (is_opcode(c, Opcode::ABORT)
               && (next.mode == Mode::ARMED || next.mode == Mode::FLYING)) {
        next.mode = Mode::TERMINATED;
        reason = Reason::GROUND_ABORT;
        next.terminal = TerminalResult{reason, tick};
    } else {
        return {c.cmd_seq, AckStatus::REJECTED_STATE, 0, next.mode, reason};
    }
    const auto status = c.effective_tick == tick ? AckStatus::APPLIED : AckStatus::APPLIED_LATE;
    return {c.cmd_seq, status, tick, next.mode, reason};
}
AckBatch batch(const std::optional<Ack>& arrival, const std::optional<Ack>& pending) noexcept {
    AckBatch result{};
    if (arrival) result.values[result.count++] = *arrival;
    if (pending) result.values[result.count++] = *pending;
    return result;
}
}  // namespace

State initial(bool auto_arm) noexcept {
    return {Mode::INIT, control::initial(), 0, {}, {}, {}, auto_arm};
}

Transition step(const State& state, const Inputs& inputs) noexcept {
    if (state.mode == Mode::TERMINATED) return {state, +0.0, {}};

    State next = state;
    const auto& held = inputs.held;
    if (!held) {
        next.settle_count = 0;
    } else if (std::abs(held->theta) <= 0.02 && std::abs(held->omega) <= 0.02) {
        if (next.settle_count < 1000) ++next.settle_count;
    } else {
        next.settle_count = 0;
    }

    const auto sim = inputs.sim_reason;
    Reason reason = Reason::NONE;
    if (sim && *sim != 1 && *sim != 2 && *sim != 3) {
        reason = Reason::INTERNAL;
    } else if (inputs.stop_reason) {
        reason = *inputs.stop_reason;
    } else if (sim == 2 || sim == 3) {
        reason = Reason::DIVERGED;
    } else if (inputs.fresh && std::abs(held->theta) > 0.30) {
        reason = Reason::DIVERGED;
    } else if (inputs.staleness >= 21) {
        reason = Reason::SENSOR_LOST;
    } else if (inputs.horizon_reached || sim == 1) {
        reason = next.settle_count == 1000 ? Reason::STABILIZED : Reason::NOT_SETTLED;
    }

    const auto& command = inputs.command;
    std::optional<Ack> arrival_ack, pending_ack;
    if (reason != Reason::NONE) {
        next.mode = Mode::TERMINATED;
        next.terminal = TerminalResult{reason, inputs.tick};
        if (command) {
            const auto status = prefix(*command, next.last_accepted).value_or(AckStatus::REJECTED_STATE);
            arrival_ack = Ack{command->cmd_seq, status, 0, next.mode, reason};
        }
        if (next.pending) {
            pending_ack = Ack{next.pending->cmd_seq, AckStatus::REJECTED_STATE, 0, next.mode, reason};
            next.pending.reset();
        }
        return {next, +0.0, batch(arrival_ack, pending_ack)};
    }

    next.terminal.reset();
    if (command) {
        auto status = prefix(*command, next.last_accepted);
        if (!status && next.pending) {
            if (is_opcode(*command, Opcode::ABORT) && !is_opcode(*next.pending, Opcode::ABORT)) {
                // Capture cancellation before the replacement can terminate.
                pending_ack = Ack{next.pending->cmd_seq, AckStatus::PREEMPTED, 0,
                                  next.mode, Reason::NONE};
                next.pending.reset();
            } else {
                status = AckStatus::REJECTED_PENDING;
            }
        }
        if (status) {
            arrival_ack = Ack{command->cmd_seq, *status, 0, next.mode, Reason::NONE};
        } else {
            next.last_accepted = command;
            if (command->effective_tick > inputs.tick) {
                next.pending = command;
                arrival_ack = Ack{command->cmd_seq, AckStatus::QUEUED, 0, next.mode, Reason::NONE};
            } else {
                arrival_ack = apply(next, *command, inputs.tick);
            }
        }
    }
    if (next.pending && next.pending->effective_tick <= inputs.tick) {
        const auto due = *next.pending;
        next.pending.reset();
        pending_ack = apply(next, due, inputs.tick);
    }

    double delta = +0.0;
    if (!next.terminal) {
        if (state.auto_arm && inputs.fresh) {
            if (next.mode == Mode::INIT) next.mode = Mode::ARMED;
            if (next.mode == Mode::ARMED) next.mode = Mode::FLYING;
        }
        if (next.mode == Mode::FLYING) {
            if (inputs.fresh) delta = control::step(next.pid, *held);
            else if (inputs.staleness <= 8) delta = next.pid.last_delta;
        }
    }
    return {next, delta, batch(arrival_ack, pending_ack)};
}
}  // namespace episode
