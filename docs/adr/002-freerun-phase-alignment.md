# ADR-002: Free-run phase alignment

Date: 2026-09-14
Status: Accepted

## Context

In free-run mode the simulator and the vehicle each run a 500 Hz schedule from
their own origin on one monotonic clock. The simulator sends a prologue frame,
tick 0, and the vehicle sets its origin from that frame's arrival plus a phase
offset (`--phase-us`). From then on vehicle cycle `n` wakes at
`origin + n * P` and expects sensor tick `n`.

The control loop is designed with one tick of delay between an observation and
the plant step that applies the command computed from it. In the deterministic
lockstep lane that delay is explicit: a one-deep FIFO in the simulator holds
each arriving command for one step. This record settles where that delay lives
in free-run.

The first phase-offset calibration, run on 2026-09-14 on the qualified machine
([report](../reports/phase-calibration-report.md)), showed that the free-run
schedule then in force put the delay somewhere else. The simulator ran body `k`
at `sim_origin + k * P` and sent observation `k + 1` at once, so the observation
a vehicle cycle consumed had been produced one full period plus the phase
earlier, while the next observation was already waiting in the vehicle's future
ring. Served sensor-to-actuator latency, measured from the simulator's send stamp
to the vehicle's local send completion, was

    served = P + phase + t0 + c - lag

with `P` the 2 ms period, `t0` the prologue transport, `c` the vehicle compute
time and `lag` the simulator's wake-plus-step time. Every run failed the
predeclared limits of p99.9 <= 1000 us and max <= 2000 us by about one period,
and no positive phase could have passed them. The one-tick delay was being
realized as sensor-frame age, which also left the phase offset with almost no
influence on whether a frame arrived in time.

## Decision

The simulator runs body `k` at `sim_origin + (k + 1) * P`, one period after the
prologue for `k = 0`, and the free-run simulator peer applies commands through
the explicit one-deep actuator FIFO (`--delay-ticks=1`). The vehicle is
unchanged: `tick_base` is the prologue's tick, cycle `n` expects
`tick_base + n`, and the prologue is cycle zero's observation.

The intentional one-tick control delay is therefore implemented in the actuator
FIFO, not through sensor-frame age.

## Timing model

Startup and the first steps under the corrected schedule, with `s0` the prologue
send, `W_n` the vehicle wake for cycle `n`, `B_k` the simulator body `k`,
`truth_k` the plant state before step `k` and `delta_n` the command computed at
vehicle cycle `n`:

| time | event | observation to PID | FIFO push / pop | plant step driven by |
|---|---|---|---|---|
| `s0` | prologue, tick 0 sent | | | |
| `W_0 = s0 + t0 + phase` | cycle 0 consumes tick 0, sends `delta_0` | `truth_0` | | |
| `B_0 = s0 + P` | body 0 reads `delta_0`; step 0; sends tick 1 | | push `delta_0`, pop none | hold (neutral) |
| `W_1 = W_0 + P` | cycle 1 consumes tick 1, sends `delta_1` | `truth_1` | | |
| `B_1 = s0 + 2P` | body 1; step 1; sends tick 2 | | push `delta_1`, pop `delta_0` | `delta_0` |
| `W_n`, `B_n` | steady state | `truth_n` | push `delta_n`, pop `delta_{n-1}` | `delta_{n-1}` |

Every observation reaches the controller exactly once, step 0 is the only
neutral step, and observation `j` drives plant step `j + 1`. That is the
lockstep `D = 1` trajectory tick for tick, so the deterministic lane remains
the reference for the closed-loop design point.

Sensor tick `n` is sent at `B_{n-1} + lag`, which is `s0 + n * P + lag`, and is
consumed at `W_n = s0 + t0 + phase + n * P`. The frame therefore has
`phase + t0 - lag` to arrive, and served latency becomes

    served = phase + t0 + c - lag        (n >= 1; phase + t0 + c at n = 0)

The endpoint is unchanged; nothing is subtracted. The phase offset now has its
intended meaning: a larger phase gives the sensor frame more time to arrive; a
smaller phase leaves more margin for the command.

Three delays, kept apart:

| term | meaning | value |
|---|---|---|
| `D_transport` | whole ticks between the boundary that produces an observation and the boundary whose body first reads the command computed from it | 0 |
| `D_flag` | depth of the simulator's actuator FIFO | 1 |
| `D_eff = D_transport + D_flag` | effective control delay, the index of the controller's delay-margin table | 1 |

Served latency and command timing are related but distinct. The command
`delta_n` must be in the simulator's socket before `B_n`, that is
`served_n + lag + t_down < P` with `t_down` the downlink transport. The served
bound is a vehicle response bound; it does not by itself prove that the command
reached the simulator before its boundary. A command that misses `B_n` is
superseded at `B_{n+1}` and that step holds the previous actuator state, an
isolated `D_eff = 2` event that the run's counters record. Nominal `D_eff = 1`
describes the timing regime, not an identity under arbitrary packet timing: a
late frame raises staleness, a late command is superseded, and both are counted.

The predeclared latency limits keep their values and now follow from the model.
p99.9 <= 1000 us, half a period, keeps the command's arrival at least
`P/2 - lag - t_down` ahead of its boundary at the tail. max <= 2000 us, one
period, is the bound past which the command misses its boundary and is applied
one step late.

## Alternatives considered

| alternative | observations reaching PID | neutral steps | equals lockstep D = 1 | served latency | phase controls arrival margin |
|---|---|---|---|---|---|
| keep the previous schedule (`D_transport = 1`, `D_flag = 0`) | all | one | yes | `P + phase + residual` | no |
| vehicle expects tick `n + 1`, prologue as origin anchor only, FIFO depth 1 | tick 0 skipped nominally | two | no | `phase + residual` | yes |
| keep the previous schedule, raise the limits to fit `P + phase` | all | one | yes | `P + phase + residual` | no |
| keep the previous schedule, gate a different quantity or subtract a period | all | one | yes | metric redefined | no |
| **shift the simulator body by one period, FIFO depth 1** | all | one | yes | `phase + residual` | yes |

The previous schedule is rejected because it places a full period inside every
served sample and makes the phase nearly irrelevant to sensor arrival.
Advancing the vehicle's expected tick is rejected because it skips observation 0
at startup and adds a second neutral plant step, so the free-run trajectory no
longer matches the deterministic reference. Raising the limits around the
measured values would preserve the contradiction between the schedule and the
latency contract rather than remove it. Redefining the metric would discard the
meaning of the served endpoint.

## Consequences

- Nominal future-ring occupancy drops from one frame to zero. The configured
  skew window of four ticks is unchanged and now serves as stall tolerance
  alone: a vehicle that wakes late by up to four ticks consumes every frame in
  order while it catches up, where before one slot was already held by the
  parked next frame and three ticks were absorbed. A longer stall remains an
  integrity failure.
- The free-run peer's command line gains `--delay-ticks=1`. Runs with
  `--delay-ticks=0` remain possible as a `D_eff = 0` diagnostic; they are not
  the closed-loop design point.
- The terminal grace loop moves with the body schedule, and the simulator's run
  horizon margin is derived on the shifted schedule.
- The simulator schedule is part of the deterministic source identity, so the
  canonical lockstep evidence is regenerated and compared whenever it changes.
  Because lockstep does not execute the free-run schedule, its deterministic
  artifacts should remain unchanged. Canonical regeneration and comparison
  establish whether that property is preserved.
- The 2026-09-14 calibration stands as valid evidence of the previous schedule
  and is not re-analyzed for selection. Phase selection requires a new
  calibration under this schedule.

## References

- [Phase-offset calibration report, 2026-09-14](../reports/phase-calibration-report.md)
- [sim/freerun.py](../../sim/freerun.py): simulator prologue, body schedule and actuator FIFO
- [src/freerun.cpp](../../src/freerun.cpp): vehicle origin acquisition and cycle schedule
- [sim/actuator.py](../../sim/actuator.py): the actuator holds its state when no command arrives
- [ADR-001](001-operating-modes.md): the three operating modes
