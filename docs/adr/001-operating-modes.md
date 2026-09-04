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
evidence of different kinds, and one of them cannot produce timing evidence at
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
- Only an absent `mode` field, and only under a committed `baselines/` path, may
  classify as `harness (legacy)`. An explicit value outside
  `{harness, lockstep, freerun}` is an error everywhere, committed baselines
  included: it never reaches the grandfather clause, because that clause tests
  for an absent field.
- Nothing is ever inferred as `freerun`.

## Consequences

The mode field prevents cross-mode substitution: a lockstep or free-run summary
can no longer be published as though it came from the harness workload, and a
row whose mode does not match its level definition leaves the campaign table with
a named reason. That is the whole of what the field proves.

It does not prove the harness workload stayed the same. Two other things carry
that: the frozen compatibility fixture, which pins the deterministic columns of a
fixed-length harness run against a binary built before the refactor, and the
unchanged L0 through L6 level definitions in `scripts/sweep.py`.

The cost is one field in every summary, one grandfather clause scoped to a path
prefix, and a small edit to the fixtures in `tests/unit/test_sweep.py`, which
construct summaries with no mode.

The grandfather clause is the one tolerance in the system, and it is the piece
most likely to be abused later. It is bound to a committed `baselines/` path
rather than to directory depth or to the absence of the field alone, so a new
run cannot fall through it.
