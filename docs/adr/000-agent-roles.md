# ADR-000: agent roles and review direction

Date: 2026-08-14. Status: accepted.

## Context

The project uses two coding agents. The obvious symmetric setup (each
reviews the other) is contradicted by the one controlled study on this
pair: arXiv 2607.21656 (116 tasks) found Claude reviewing Codex raised
task pass rates from 71.6% to 89.7%, while Codex reviewing Claude lowered
them from 91.4% to 82.8%.

## Decision

- Codex implements well-specified, testable subtasks: scripts, codecs,
  plotting, schema work.
- Claude Code implements RT-sensitive C++ and reviews all Codex output.
- The reverse review direction is not used.
- Mamadou reviews everything and performs every merge.
- Each PR records which agent authored it, so the division is auditable.

## Consequences

Claude review time becomes the bottleneck on Codex-authored work. Because
the reverse review direction is unused, Claude-authored C++ gets no
automated reviewer; the human review is the only gate, so those PRs stay
small.
