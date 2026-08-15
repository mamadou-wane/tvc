# Agent instructions

Shared instructions for all AI agents (Claude Code, Codex) working in this
repo. CLAUDE.md layers Claude-specific notes on top of this file.

## What this project is

A real-time control loop measurement stack. The product is published
numbers; anything that could corrupt a number is a bug of the highest
severity. Full design: docs/superpowers/specs/2026-08-14-tvc-restructure-design.md.

## Build and test

    docker build -t tvc-dev docker/          # once
    docker run --rm -v "$PWD":/w -w /w --cap-add=IPC_LOCK \
      --ulimit memlock=-1:-1 tvc-dev bash tests/ci.sh

tests/ci.sh builds normal and ASan/UBSan trees and runs all tests. Python
unit tests also run natively: python3 -m unittest discover -s tests/unit.
Container output is functional only; never quote timing numbers from it.

## Real-time invariants

- No allocation, locks, blocking syscalls, or formatted I/O inside the
  control cycle. The alloc guard enforces the allocator part at runtime.
- CLOCK_MONOTONIC only. Never CLOCK_REALTIME, never
  std::chrono::high_resolution_clock.
- Deadlines derive from a single origin (origin + n * period), never from
  now + period.
- Measurement semantics: the harness is coordinated-omission-free by
  construction; do not add "corrected" series.
- Failed mitigations must fail loudly: nonzero exit, applied config
  recorded in summary.json.

## Roles and review

- Codex: well-specified, testable subtasks (scripts, codecs, plotting).
- Claude Code: RT-sensitive C++; reviews Codex output.
- Codex does not review Claude output (see docs/adr/000-agent-roles.md).
- Mamadou reviews everything and owns every merge. Open PRs; never merge,
  never push to main except ai-log entries after a merge.

## Style

- Commit subjects: short, imperative, lowercase, no bodies, no AI
  attribution of any kind.
- Prose: no em dashes, sentence-case headings, concrete over abstract.
- C++ matches the existing files: 4-space indent, trailing return rare,
  comments state constraints, not narration.

## PR description template

Every PR body ends with:

    ## AI assistance
    - Agent: <Claude Code (model) | Codex (model) | none>
    - Scope: <what the agent produced>
    - Human changes: <what was modified or rejected, and why>
    - Verification: <commands run and their result>

## AI log ritual

After a PR merges, commit docs/ai-log/NNNN-slug.md to main (next NNNN in
sequence):

    # NNNN: <task>
    Date: YYYY-MM-DD
    PR: #N (merge SHA)
    Agent: <agent and model>
    Produced: <what the agent wrote>
    Human: <what was changed or rejected, and why>
    Verification: <what proved it correct>
