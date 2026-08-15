# 0017: results writeup and regression gate
Date: 2026-08-15
PR: #18 (merge eb40a61)
Agent: Claude Code (Fable 5, controller-direct)
Produced: docs/results.md (the campaign level by level, including the L2 null result and the L3 placement lottery), the README headline and CCDF figure regenerated from committed CSVs, and scripts/bench_gate.py with unit tests: the measurement-machine regression gate comparing a fresh campaign's L5 p99.9 median against the committed baselines.
Human: Mamadou reviewed the prose and merged. The analysis of the campaign data was a joint read: the human ran and observed the campaigns, the agent identified the C-state exit signature, the placement lottery, and the drift arithmetic.
Verification: gate unit tests green; container gate green both trees; self-comparison smoke passes; style scans clean.
