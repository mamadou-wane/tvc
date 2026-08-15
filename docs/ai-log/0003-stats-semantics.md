# 0003: measurement semantics
Date: 2026-08-14
PR: #2 (merge d67da49)
Agent: Claude Code (Sonnet 5 implementer, directed by Fable 5)
Produced: removed the misapplied coordinated-omission correction (the harness measures every cycle against a fixed absolute origin, so it is CO-free by construction); added a naive self-referenced series as an explicit demo of what CO hides; checked hdr_init/hdr_record_value returns with a dropped-samples counter; added -ffp-contract=off and a fatal CMake check on non-Linux hosts.
Human: Mamadou reviewed and merged. A review agent flagged a stale constructor comment still describing the removed correction; it was fixed before the PR reached him.
Verification: tests/functional/test_summary.py red-then-green in both container trees via tests/ci.sh.
