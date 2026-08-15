# One-Axis TVC

A hard real-time control and telemetry stack: a 500 Hz C++20 control loop on
Linux, measured as a latency distribution, with a Python ground station,
simulation, and fault injection to follow.

![Wakeup jitter CCDF across mitigation levels](docs/jitter.svg)

**p99.9 wakeup jitter: 88.4 microseconds at 500 Hz**, reproducible to
within one microsecond across three independent 300,000-cycle runs, on a
stock Ubuntu generic kernel. The naive baseline drifts 17 seconds off
schedule in the same ten minutes and cannot see it in its own measurement.
Six mitigations, applied one at a time, each measured in isolation:
[docs/results.md](docs/results.md).

Status: v0.1 measurement campaign complete on the qualified platform.
Next: the writeup polish and the telemetry stack (v0.2a).

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
