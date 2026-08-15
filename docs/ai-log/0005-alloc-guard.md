# 0005: alloc guard atomic mode
Date: 2026-08-14
PR: #4 (merge 45e70c6)
Agent: Claude Code (Haiku 4.5 implementer, directed by Fable 5)
Produced: made the guard's mode flag a relaxed std::atomic<int> (was a plain int read cross-thread, a data race once the planned drain thread exists); single-load-into-local at both read sites; constant initialization preserved.
Human: Mamadou reviewed and merged; no changes requested.
Verification: two new pinning tests (count mode sees the naive log path; clean path reports clean) pass before and after the refactor, both container trees.
