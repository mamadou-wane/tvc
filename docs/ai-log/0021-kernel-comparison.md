# 0021: kernel comparison writeup
Date: 2026-08-15
PR: #22 (merge bb39e1a)
Agent: Claude Code (Fable 5, controller-direct)
Produced: the generic vs PREEMPT_RT section of docs/results.md with the RT figure regenerated from committed CSVs, and the qualification note for the RT kernel. Findings: 3.7x median improvement for the pinned FIFO loop, a p99.9 tie within spread, an unchanged beyond-p99.99 population (narrowing it to non-preemptible work), and roughly 2x cost to unpinned SCHED_OTHER runs. The regression gate stays on the generic kernel.
Human: Mamadou ran both campaigns and merged. Prediction record, kept because the log exists for exactly this: before the RT run the agent predicted the median would barely move and the far tail would shrink. The data showed the opposite on both counts. The measurement decided, as the project intends.
Verification: every number in the section computed from the committed summaries; style scans clean.
