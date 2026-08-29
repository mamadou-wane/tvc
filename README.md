# One-Axis TVC

A hard real-time control and telemetry stack: a 500 Hz C++20 control loop on
Linux, measured as a latency distribution, with a Python ground station,
simulation, and fault injection to follow.

![Wakeup jitter CCDF with the telemetry level](docs/jitter-telemetry.svg)

**p99.9 wakeup jitter: 7.5 microseconds at 500 Hz** on a stock Ubuntu
generic kernel, with per-core isolation and every C-state disabled, and
**per-cycle telemetry enabled at no measured cost** (pooled p99.9 within
48 nanoseconds of the quiet configuration over 2.4 million cycles per
arm, zero ring drops). The 88.4 us v0.1 number was the same stack under
a discipline that left C-states enabled: one power-management knob, a
12x difference. The knob acted at a distance. nohz_full had moved the
loop's wakeup timer onto the housekeeping cores, and their idle exits
set the tail. The naive baseline drifts whole seconds off schedule
and cannot see it in its own measurement. Seven mitigations, applied
one at a time, each measured in isolation:
[docs/results.md](docs/results.md).

Status: v0.2a complete: wire codec in both languages against a pinned
golden corpus, SPSC ring with a TSan-verified drop path, drain thread,
and the campaign above. Next: a campaign under the pinned-timer
discipline (docs/results.md, the far tail) and the v0.2b ground
station.

## Layout

    src/         control-cycle timing harness (C++20)
    scripts/     campaign runner, plotting, regression gate
    baselines/   committed campaign data the gate diffs against
    tests/       functional and unit tests (container-run for C++)
    docs/        results, methodology, qualification, plan, ADRs, AI log
      results.md       the campaign, level by level
      methodology.md   measurement methodology
      qualification.md measured platform record
      plan.md          release plan

## Build and test

Measurement runs happen on bare-metal Linux only. Functional builds and
tests run anywhere Docker does:

    docker build -t tvc-dev docker/
    docker run --rm -v "$PWD":/w -w /w --cap-add=IPC_LOCK \
      --ulimit memlock=-1:-1 tvc-dev bash tests/ci.sh

## Working with AI

This project is deliberately built with AI agents as collaborators: Claude
Code for real-time-sensitive C++ and review, OpenAI Codex for well-specified
subtasks. Every merged PR carries an AI-assistance disclosure in its
description and a matching entry in docs/ai-log/. Roles and review protocol
are defined in docs/adr/000-agent-roles.md. All agent output is
human-reviewed before merge, and agent proposals are accepted or rejected
against measurements.
