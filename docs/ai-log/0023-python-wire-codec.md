# 0023: python wire codec and golden corpus

Date: 2026-08-16
PR: #24 (72382ed38ea346fbb9d607eeaa0fdc60c5a3214b)
Agent: Codex (gpt-5.6-sol via codex-cli 0.147.0), first Codex PR per
ADR-000; driven task-by-task by Claude Code (Fable 5) from the committed
implementation plan.
Produced: ground/wire.py (crc32c via google-crc32c, frame encoder,
stream decoder with the seven spec counters, record codec, recording
reader, CLI), ground/__init__.py, tests/unit/test_wire.py (27 tests),
tests/golden/ (generator, seven pinned corpus files, manifest), the
docker base move to ubuntu:26.04 with google-crc32c, and it carried the
implementation plan for PRs 2-4. Codex followed the plan's code with no
deviations across all six tasks.
Human: Mamadou reviewed and merged. Process note: Codex's sandbox
mounts .git read-only, so Claude Code made the commits after reviewing
each task; content is Codex's unmodified.
Verification: Claude Code re-ran the unit suite after every task, all
green; corpus manifest counters matched the spec's intended values on
first generation, including the mini recording's resync case; full
container gate (tests/ci.sh) green on the new ubuntu:26.04 image.
