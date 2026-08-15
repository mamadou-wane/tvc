# One-Axis TVC

A hard real-time control and telemetry stack: a 500 Hz C++20 control loop on
Linux, measured as a latency distribution, with a Python ground station,
simulation, and fault injection to follow.

Status: v0.1 week 1 complete: harness landed and corrected. Next: Linux
bring-up and qualification on the ProBook 465 G11.

## Layout

    src/         control-cycle timing harness (C++20)
    scripts/     campaign runner and plotting
    tests/       functional and unit tests (container-run for C++)
    docs/        methodology, plan, ADRs, AI log
      methodology.md   measurement methodology
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
