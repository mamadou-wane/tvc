"""Immutable observations of logical execution; no transport or timing state."""

import math
import struct
from typing import NamedTuple

from sim.episode import Command, EpisodeOutput, Mode, Reason, SimReason
from sim.types import ActuatorState, Observation, TruthState


class Row(NamedTuple):
    tick: int
    truth: TruthState
    observation: Observation
    held: Observation | None
    fresh: bool
    staleness: int
    command: Command | None
    episode: EpisodeOutput
    arriving: float | None
    actuator: ActuatorState
    up_drop: bool
    down_drop: bool


class StreamResult(NamedTuple):
    name: str
    start_state: int
    final_state: int
    draws: int


class Trace(NamedTuple):
    ticks_declared: int
    seed: int
    delay_ticks: int
    rows: tuple[Row, ...]
    rng: tuple[StreamResult, ...]
    sim_reason: SimReason

    def to_sim_csv(self) -> str:
        lines = ['tick,has_sample,applied,theta_bits,omega_bits,cmd_applied_bits']
        for row in self.rows:
            values = (row.truth.theta, row.truth.omega, row.actuator.applied)
            words = [f'0x{struct.unpack("<Q", struct.pack("<d", value))[0]:016x}'
                     for value in values]
            lines.append(','.join([str(row.tick), str(int(row.fresh)),
                                   str(int(row.arriving is not None)), *words]))
        return '\n'.join(lines) + '\n'


class Acceptance(NamedTuple):
    termination: bool
    peak: bool
    settled: bool
    cadence: bool
    finiteness: bool

    @property
    def passed(self) -> bool:
        return all(self)


class EvidenceRow(NamedTuple):
    tick: int
    theta: float
    omega: float
    delta: float
    i_state: float
    d_prev: float


def evaluate(trace: Trace) -> Acceptance:
    rows = tuple(EvidenceRow(r.tick, r.truth.theta, r.truth.omega,
                 r.episode.requested_delta, r.episode.state.pid.i_state,
                 r.episode.state.pid.d_prev) for r in trace.rows)
    state = trace.rows[-1].episode.state if trace.rows else None
    return evaluate_rows(rows, trace.ticks_declared, trace.sim_reason,
                         state.mode if state else None, state.terminal if state else None)


def evaluate_rows(rows, ticks_declared, sim_reason, vehicle_state, terminal) -> Acceptance:
    """Apply the same five clauses to observed artifact values or a headless trace."""
    termination = (bool(rows) and sim_reason == SimReason.SIM_HORIZON
                   and rows[-1].tick == ticks_declared - 1
                   and vehicle_state == Mode.TERMINATED
                   and terminal is not None and terminal.reason == Reason.STABILIZED
                   and terminal.tick == ticks_declared - 1)
    peak = bool(rows) and all(abs(r.theta) <= 0.15 for r in rows)
    window = rows[-1000:]
    settled = (ticks_declared >= 1000 and len(window) == 1000
               and all(r.tick == ticks_declared - 1000 + i
                       and abs(r.theta) <= 0.02 and abs(r.omega) <= 0.02
                       for i, r in enumerate(window)))
    cadence = (ticks_declared > 0 and len(rows) == ticks_declared
               and all(r.tick == i for i, r in enumerate(rows)))
    finiteness = bool(rows) and all(math.isfinite(value) for row in rows
                 for value in (row.theta, row.omega, row.delta, row.i_state, row.d_prev))
    return Acceptance(termination, peak, settled, cadence, finiteness)
