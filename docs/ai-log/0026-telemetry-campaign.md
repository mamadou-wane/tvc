# 0026: v0.2a campaign and c-state discovery

Date: 2026-08-16
PR: #27 (051e2e08acb8d12814e9496e43b25834b3d1e21b)
Agent: Claude Code (Fable 5) for analysis and writeup; all measurements
human-run on the ProBook.
Produced: verification pass over both campaign directories, pooled
exceedance analysis, the CCDF figure, the results.md v0.2a section,
qualification.md power-discipline capture, README headline, gate
repoint to the new baselines with 100 percent tolerance.
Human: Mamadou ran the campaign, both repeat batches, and the recording
decodes, and applied the idle-set discipline that produced the C-state
discovery. He reviewed and merged, and caught three contrastive-negation
sentences in the draft writeup (fixed in df031ca).
Verification: full container gate green with the repointed defaults;
gate smoke-tested both directions (repeat batch passes at 9.7 vs the
14.9 limit; an old-discipline 88.4 us run fails).
Prediction record, both directions. Claude caught the taskset -c 7
launch from console output before any data was used (it would have put
the drain thread on the isolated core and pinned the unpinned levels).
Claude's intermediate conclusion from the first three repeats (a
telemetry-specific 10 to 15 us band cost, called statistically
significant) was wrong: the significance claim assumed cycle-level
independence, the events are run-correlated, and the five extra repeats
per arm Mamadou ran dissolved the effect entirely (pooled p99.9 within
48 ns). The measurement corrected the analyst; the repeat run was the
check that did it.
