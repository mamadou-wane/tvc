# 0030: cpuidle capture in the env block

Date: 2026-08-21
PR: #31 (c4259e866e9929c5905cb1a56701be568b170bea)
Agent: Claude Code (Fable 5) as controller; Sonnet implementer per task,
task-scoped review after each, Fable whole-branch review, one
comment-level fix wave.
Produced: src/env_probe.{hpp,cpp} (sysfs helpers moved out of main.cpp
plus cpuidle_json emitting per-state user-disable counts across all
CPUs as the last env key), exact-string unit tests over fake sysfs
trees in the normal and ASan lanes, functional shape asserts, a
bench_gate fixture proving the key inert to gating, and the doc updates
striking the pending item and carving the 2026-08-16 baselines out as
predating the field. Closes the provenance blind spot from the C-state
discovery: every recorded env field was identical between the 88.4 and
7.5 us runs.
Human: Mamadou merged unchanged. This entry closes the cleanup batch
(PRs #28-#31, ai-log 0027-0030): issues #8 and #16 closed, both
campaign guards landed.
Verification: full container ci.sh green at head across all three
trees. The whole-branch review verified the kernel side (the disable
sysfs file emits only 0 or 1, masked to the user-disable bit that
cpupower idle-set writes), ran a live harness in the container
(sentinel driver "none", key ordered last), and confirmed per consumer
that nothing reading summary.json touches env. Pending on-ProBook
acceptance: one short run before and after cpupower idle-set -D 0
should flip disabled from 0 to 16 on all four states; record it with
the next campaign.
