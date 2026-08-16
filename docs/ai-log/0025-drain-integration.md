# 0025: drain thread and harness integration

Date: 2026-08-16
PR: #26 (9c46a21adcd661ebedefa59be17df65f582c459e)
Agent: Claude Code (Fable 5), subagent-driven: fresh implementer per
task, independent reviewer per task, scoped re-review per fix round,
final whole-branch review on the most capable model.
Produced: telem::Drain and encode_recording_header, the main.cpp
integration (--telemetry flag, startup ordering ahead of rt setup,
hot-path hook in a second guard::Cycle scope, applied/config/summary
plumbing, exit codes), loop_stats telemetry parameter,
tests/functional/test_telemetry.py, sweep level L6 (Tasks 11-14 of the
committed plan).
Human: Mamadou reviewed and merged.
Verification: full container gate green (normal, ASan/UBSan, TSan; 49
unit + 11 functional tests); smoke run decoded end-to-end with
byte-exact file size. The task review found a shutdown TOCTOU in the
drain loop, present in the plan's own pseudocode: a stale-empty pop
followed by preemption could observe the stop flag and exit without
re-polling, silently dropping the records nearest shutdown. The
reviewer's sketched fix had its own bug (popped a batch inside the
stop branch, then discarded it); the landed fix is a stop_seen re-poll
whose happens-before chain guarantees the post-stop pop sees the final
push, pinned by a concurrent-push regression test. The final reviewer
hand-tested the SIGINT-mid-run path: exit 3 preserved, partial
recording decodes cleanly, sweep excludes the row. Deferred,
non-blocking: an optional write_failed key in the summary telemetry
block; a one-line spec wording alignment on the applied-key semantics.
