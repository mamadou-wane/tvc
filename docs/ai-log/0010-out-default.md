# 0010: output default and repo hygiene
Date: 2026-08-14
PR: #10 (merge d0f9da6)
Agent: Claude Code (Fable 5, controller-direct)
Produced: --out now defaults to results/ (gitignored) and the harness creates a single missing directory level, so bare runs stop scattering result files at the repo root; the unwritable-out test moved to a two-level missing path so the exit-4 contract holds when the container runs as root; .claude/scheduled_tasks.lock ignored. Alongside the PR: merged remote and local branches deleted, stray run.* probe files removed.
Human: Mamadou reviewed and merged.
Verification: container gate green in both trees (8 tests, 1 designed ASan skip).
