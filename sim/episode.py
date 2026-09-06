"""Pure logical episode policy; transport and actuator application live outside."""

from enum import IntEnum
from typing import NamedTuple

from sim import control_ref
from sim.control_ref import ControlState
from sim.types import Observation


class Mode(IntEnum):
    INIT = 0
    ARMED = 1
    FLYING = 2
    TERMINATED = 3


class Reason(IntEnum):
    NONE = 0
    STABILIZED = 1
    DIVERGED = 2
    GROUND_ABORT = 3
    SENSOR_LOST = 4
    PEER_LOST = 5
    SIGNAL = 6
    NOT_SETTLED = 7
    INTERNAL = 8


class Opcode(IntEnum):
    ARM = 1
    LAUNCH = 2
    ABORT = 3


class AckStatus(IntEnum):
    QUEUED = 0
    APPLIED = 1
    APPLIED_LATE = 2
    DUPLICATE = 3
    REJECTED_PENDING = 4
    REJECTED_STATE = 5
    REJECTED_IDENTITY = 6
    REJECTED_OPCODE = 7
    REJECTED_STALE = 8
    PREEMPTED = 9
    REJECTED_OVERFLOW = 10


class SimReason(IntEnum):
    SIM_NONE = 0
    SIM_HORIZON = 1
    SIM_LOC_ANGLE = 2
    SIM_LOC_NONFINITE = 3
    SIM_VEHICLE_TERMINAL = 4
    SIM_PEER_LOST = 6


class Command(NamedTuple):
    cmd_seq: int
    opcode: int
    effective_tick: int


class Ack(NamedTuple):
    cmd_seq: int
    status: AckStatus
    applied_tick: int
    state: Mode
    reason: Reason


class TerminalResult(NamedTuple):
    reason: Reason
    tick: int


class EpisodeState(NamedTuple):
    mode: Mode
    pid: ControlState
    settle_count: int
    pending: Command | None
    last_accepted: Command | None
    terminal: TerminalResult | None
    auto_arm: bool


class EpisodeInput(NamedTuple):
    tick: int
    held: Observation | None
    fresh: bool
    staleness: int
    command: Command | None
    horizon_reached: bool
    sim_reason: int | None
    stop_reason: Reason | None


class EpisodeOutput(NamedTuple):
    state: EpisodeState
    requested_delta: float
    acks: tuple[Ack, ...]


def initial(*, auto_arm: bool) -> EpisodeState:
    return EpisodeState(Mode.INIT, control_ref.initial(), 0, None, None, None, auto_arm)


def _prefix(command: Command, last: Command | None) -> AckStatus | None:
    if command.opcode not in (Opcode.ARM, Opcode.LAUNCH, Opcode.ABORT):
        return AckStatus.REJECTED_OPCODE
    if last is not None:
        if command.cmd_seq == last.cmd_seq:
            if command.opcode == last.opcode and command.effective_tick == last.effective_tick:
                return AckStatus.DUPLICATE
            return AckStatus.REJECTED_IDENTITY
        gap = (command.cmd_seq - last.cmd_seq) & 0xffffffff
        if not 1 <= gap < 0x80000000:
            return AckStatus.REJECTED_STALE
    return None


def _apply(mode: Mode, command: Command, tick: int) -> tuple[Mode, TerminalResult | None, Ack]:
    terminal = None
    reason = Reason.NONE
    if command.opcode == Opcode.ARM and mode == Mode.INIT:
        mode = Mode.ARMED
    elif command.opcode == Opcode.LAUNCH and mode == Mode.ARMED:
        mode = Mode.FLYING
    elif command.opcode == Opcode.ABORT and mode in (Mode.ARMED, Mode.FLYING):
        mode = Mode.TERMINATED
        reason = Reason.GROUND_ABORT
        terminal = TerminalResult(reason, tick)
    else:
        return mode, None, Ack(command.cmd_seq, AckStatus.REJECTED_STATE, 0, mode, reason)
    status = AckStatus.APPLIED if command.effective_tick == tick else AckStatus.APPLIED_LATE
    return mode, terminal, Ack(command.cmd_seq, status, tick, mode, reason)


def step(state: EpisodeState, inputs: EpisodeInput) -> EpisodeOutput:
    """Advance one logical cycle from admitted observations and ordered inputs."""
    if state.mode == Mode.TERMINATED:
        return EpisodeOutput(state, +0.0, ())

    held = inputs.held
    if held is None:
        count = 0
    elif abs(held.theta) <= 0.02 and abs(held.omega) <= 0.02:
        count = min(state.settle_count + 1, 1000)
    else:
        count = 0

    reason = Reason.NONE
    if inputs.sim_reason is not None and inputs.sim_reason not in (
        SimReason.SIM_HORIZON, SimReason.SIM_LOC_ANGLE, SimReason.SIM_LOC_NONFINITE
    ):
        reason = Reason.INTERNAL
    elif inputs.stop_reason is not None:
        reason = inputs.stop_reason
    elif inputs.sim_reason in (SimReason.SIM_LOC_ANGLE, SimReason.SIM_LOC_NONFINITE):
        reason = Reason.DIVERGED
    elif inputs.fresh and abs(held.theta) > 0.30:
        reason = Reason.DIVERGED
    elif inputs.staleness >= 21:
        reason = Reason.SENSOR_LOST
    elif inputs.horizon_reached or inputs.sim_reason == SimReason.SIM_HORIZON:
        reason = Reason.STABILIZED if count == 1000 else Reason.NOT_SETTLED

    command = inputs.command
    pending = state.pending
    last = state.last_accepted
    arrival_ack = pending_ack = None
    if reason != Reason.NONE:
        terminal = TerminalResult(reason, inputs.tick)
        if command is not None:
            status = _prefix(command, last)
            if status is None:
                status = AckStatus.REJECTED_STATE
            arrival_ack = Ack(command.cmd_seq, status, 0, Mode.TERMINATED, reason)
        if pending is not None:
            pending_ack = Ack(pending.cmd_seq, AckStatus.REJECTED_STATE, 0, Mode.TERMINATED, reason)
        acks = tuple(ack for ack in (arrival_ack, pending_ack) if ack is not None)
        next_state = EpisodeState(Mode.TERMINATED, state.pid, count, None, last, terminal, state.auto_arm)
        return EpisodeOutput(next_state, +0.0, acks)

    mode = state.mode
    terminal = None
    if command is not None:
        status = _prefix(command, last)
        if status is None and pending is not None:
            if command.opcode == Opcode.ABORT and pending.opcode != Opcode.ABORT:
                # Capture cancellation before the replacing ABORT can change mode.
                pending_ack = Ack(pending.cmd_seq, AckStatus.PREEMPTED, 0, mode, Reason.NONE)
                pending = None
            else:
                status = AckStatus.REJECTED_PENDING
        if status is not None:
            arrival_ack = Ack(command.cmd_seq, status, 0, mode, Reason.NONE)
        else:
            last = command
            if command.effective_tick > inputs.tick:
                pending = command
                arrival_ack = Ack(command.cmd_seq, AckStatus.QUEUED, 0, mode, Reason.NONE)
            else:
                mode, terminal, arrival_ack = _apply(mode, command, inputs.tick)

    if pending is not None and pending.effective_tick <= inputs.tick:
        due = pending
        pending = None
        mode, terminal, pending_ack = _apply(mode, due, inputs.tick)

    # A newly queued command is not due; a displaced command cannot also apply.
    acks = tuple(ack for ack in (arrival_ack, pending_ack) if ack is not None)
    pid = state.pid
    delta = +0.0
    if terminal is None:
        if state.auto_arm and inputs.fresh:
            if mode == Mode.INIT:
                mode = Mode.ARMED
            if mode == Mode.ARMED:
                mode = Mode.FLYING
        if mode == Mode.FLYING:
            if inputs.fresh:
                delta, pid = control_ref.step(pid, held)
            elif inputs.staleness <= 8:
                delta = pid.last_delta

    next_state = EpisodeState(mode, pid, count, pending, last, terminal, state.auto_arm)
    return EpisodeOutput(next_state, delta, acks)
