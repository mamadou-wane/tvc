# ADR-001: Three operating modes

Date: 2026-09-03
Status: Accepted

## Context

TVC asks three different questions of one control loop, and each needs a
different kind of evidence.

The first is how well a fixed-rate loop holds its deadline on a given machine.
That is a timing question about the platform: scheduler latency, page faults,
interrupts, frequency transitions. It is answered by an open-loop workload that
drives a stand-in plant and records a wakeup-jitter distribution. Every
published timing number in the [results](../results.md) comes from that workload,
and the L0 through L7 benchmark levels are defined by it.

The second is whether the controller, the plant model and the wire protocol
behave correctly: does a scenario with a given seed and loss pattern reproduce
bit for bit, do the goldens hold, does the episode state machine take the
transitions the specification says. That is a correctness question. It needs a
simulator that owns the clock and advances the vehicle one tick at a time, so
the run is a deterministic function of its inputs and carries no timing at all.

The third is the closed-loop latency from a sensor observation to the actuator
command computed from it, with the simulator and the vehicle each holding their
own 500 Hz schedule. That is a timing question about the integrated system, and
it can only be asked when nothing in the loop blocks on the other side.

One binary serves all three, and a run's evidence is only as good as the
reader's ability to tell which question it answers. A summary that does not say
which workload produced it cannot be checked.

## Decision

The runtime mode is one of exactly three values, and every summary records it.

| mode | what runs | what its evidence can establish |
|---|---|---|
| `harness` | the open-loop timing workload, levels L0 through L7, unchanged from the published campaigns | wakeup jitter and execution time of the control cycle on a qualified machine |
| `lockstep` | the simulator owns the clock; the vehicle answers each tick before the simulator steps | correctness: seed-exact reproduction, goldens, replay, state-machine behavior. No timing claim; the histograms are never called and the benchmark gate refuses its summaries as timing evidence |
| `freerun` | vehicle and simulator on independent 500 Hz schedules, level L8, nonblocking inside the control cycle | closed-loop sensor-to-actuator latency and served coverage on a qualified machine |

`harness` is the default. `lockstep` may block on its synchronization receive,
which lives outside every real-time path. `freerun` obeys the nonblocking
control-cycle rule without exception.

Every summary writes its mode unconditionally. A missing mode is an error, and
nothing is ever inferred as `freerun`.

One compatibility rule exists for history: the baseline summaries committed
before the mode field existed carry no mode. Those, and only those, classify as
`harness (legacy)` and are admitted as `harness`. The rule is bound to a
committed `baselines/` path and to an absent field. An explicit value outside
the three modes is an error everywhere, committed baselines included, and no
binary emits `harness (legacy)`; it exists only inside the analysis scripts.

## Consequences

The mode field prevents cross-mode substitution. A lockstep or free-run summary
can no longer be published as though it came from the harness workload, and a
row whose mode does not match its benchmark level leaves the campaign table with
a named reason. That is the whole of what the field proves.

It does not prove the harness workload stayed the same. Two other things carry
that: a frozen compatibility fixture, which pins the deterministic columns of a
fixed-length harness run against a binary built before the modes existed, and
the unchanged L0 through L6 level definitions in
[scripts/sweep.py](../../scripts/sweep.py).

The compatibility rule is the one tolerance in the system and the piece most
likely to be abused later. Binding it to a committed path and an absent field,
rather than to directory depth or the absence of the field alone, is what keeps a
new run from falling through it.

## References

- [Measurement methodology](../methodology.md): the harness workload and how its jitter is measured.
- [ADR-002](002-freerun-phase-alignment.md): the free-run schedule and its control delay.
- [scripts/sweep.py](../../scripts/sweep.py), [scripts/bench_gate.py](../../scripts/bench_gate.py): level definitions and the mode checks.
