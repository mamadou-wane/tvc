# ADR-001: three operating modes, and what a summary's mode means

Date: 2026-09-03. Status: accepted.

## Context

Through v0.2a the harness had one workload: an open-loop control cycle driving a
stand-in plant, measured as a wakeup-jitter distribution. Every published number
in `docs/results.md` comes from it, and the L0 through L6 benchmark levels are
defined by it.

v0.2b adds two more ways to run the same binary. A deterministic lane, where a
simulator owns the clock and a run reproduces bit for bit, is what makes goldens,
seed-exact reproduction and CI correctness possible. A closed-loop real-time
lane, where the vehicle and the simulator each hold their own 500 Hz schedule, is
what makes a sensor-to-actuator latency claim possible. The three produce
evidence of different kinds, and two of them cannot produce timing evidence at
all.

A summary that does not say which workload produced it cannot be checked. The
96 committed baseline summaries were all written before any of this existed and
say nothing.

## Decision

- The runtime mode enum is exactly three values: `harness`, `lockstep`,
  `freerun`. `harness` is the default.
- `harness` keeps the v0.1 and v0.2a workload unchanged, and it stays the
  published open-loop wakeup-jitter lane, L0 through L7.
- `lockstep` is the deterministic lane. It makes no timing claim, calls no
  histogram, and the benchmark gate refuses its summaries as timing evidence.
  It may block on its synchronization receive, which lives outside every
  real-time path.
- `freerun` is the closed-loop timing lane, L8, and it obeys the nonblocking
  control-cycle rule.
- Every summary records its mode, written unconditionally, so no binary from
  v0.2b onward can emit a summary without one.
- A missing mode is an error, not an exclusion, everywhere except a committed
  `baselines/` path, where it classifies as `harness (legacy)` and is admitted as
  `harness`. That classification lives in the analysis scripts. It is not a
  fourth mode and no binary emits it.
- Nothing is ever inferred as `freerun`. An unknown mode value is treated as a
  missing one, in `baselines/` too.

## Consequences

An existing benchmark level cannot be quietly redefined by a later capability:
changing what an L0 through L6 row measures now requires changing the mode it
runs in, and the gate would refuse the result. Cross-mode comparison is
structurally impossible rather than merely discouraged.

The cost is one field in every summary, one grandfather clause scoped to a path
prefix, and a small edit to the fixtures in `tests/unit/test_sweep.py`, which
construct summaries with no mode.

The grandfather clause is the one tolerance in the system, and it is the piece
most likely to be abused later. It is bound to a committed `baselines/` path
rather than to directory depth or to the absence of the field alone, so a new
run cannot fall through it.
