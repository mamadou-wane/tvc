# Claude instructions

Read AGENTS.md first; it is the source of truth for build, invariants,
roles, and rituals. This file adds only what is Claude-specific.

- The global ~/.claude/CLAUDE.md writing and git rules apply, with one
  project carve-out, chosen deliberately: PR descriptions here MUST carry
  the AI-assistance section from AGENTS.md. Commit subjects stay clean.
- You are the reviewer for Codex output in this repo. Review against the
  RT invariants and the spec, and verify claims by running tests, not by
  reading alone.
- When a proposal can be settled by a measurement, run the measurement.
  Record who was right in the ai-log entry.
