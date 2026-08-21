# 0028: harness hardening

Date: 2026-08-21
PR: #29 (e5b7e961a564509d389ca40f93a94df1b4e8a6a2)
Agent: Claude Code (Fable 5) as controller; one Sonnet implementer
subagent per task, task-scoped review after each, Fable whole-branch
review at the end.
Produced: int64 bounds checks for --fifo/--cpu before narrowing (the red
run proved --fifo=4294967296 previously exited 0 with the mitigation
silently dropped), --help exit 0 via a tri-state ParseResult with an
exhaustive switch, a third guard::Cycle enforcing the stats block
allocation-free at runtime (first test combining the guard with
telemetry), and stack_budget moved to rt::detail with the RLIM_INFINITY
branch documented and all three branches unit-tested in both ci.sh
trees.
Human: Mamadou directed the subagent-driven workflow mid-task and made
the scope decisions in the scoping session (no clamp on stack_budget,
sibling guard layout); merged unchanged.
Verification: full container ci.sh green at head across normal,
ASan/UBSan, and TSan trees; TDD red runs recorded at base for both parse
defects; whole-branch review independently re-verified the red case and
confirmed sweep.py and bench_gate.py surfaces unchanged. One review
finding fixed in-branch (the --cpu message misdiagnosed the INT_MAX
rejection); deferred follow-ups recorded in the PR body
(-Werror=switch, redundant rlim_max disjunct).
