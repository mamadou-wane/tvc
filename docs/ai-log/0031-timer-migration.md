# 0031: far tail root cause, timer migration

Date: 2026-08-29
PR: #32 (25e280ab00153d450430402b5afd27502d05e4dc)
Agent: Claude Code (Fable 5), driving the ProBook over SSH; every run
executed on the measurement machine with Mamadou's approval per run.
Produced: the session runbook; post-reboot discipline applied and gated
over SSH (governor, EPP, IRQ mask ff3f applied for the first time);
the cpuidle acceptance check ai-log 0030 left pending (disabled 0 to 16
on all four states, L5 p99.9 1,155 to 16.4 us); the osnoise procedure
(NO_OSNOISE_WORKLOAD, mono trace clock, ipi_send_cpu filtered to CPU 7)
and the two analysis scripts; the diagnosis that the loop's unpinned
hrtimer migrates to housekeeping CPUs (/proc/timer_list samples, LOC
deltas) and the timer_migration=0 A/B that confirmed it; runs A, B, C;
the results.md far tail section, qualification.md, methodology.md,
README, and baselines/2026-08-29-timer-migration.
Human: Mamadou installed the SSH key and a session sudoers file (removed
at the end), chose pair-only polling over the 25 W machine-wide state
when the package hit 92 C, approved each run, reviewed the draft and
merged it unchanged.
Verification: osnoise-C-mig0, 300,000 cycles under the pinned-timer
discipline, p99.9 21.8 us, max 78 us, 0 drops, 0 missed, 0 trace
overrun; timerdiag-mig1 against timerdiag-mig0, same discipline minutes
apart, p99.9 380 against 16.6 us. A two-agent review (fact-check and
prose) ran before the PR: every number was re-derived from committed
files, and it caught that isolcpus=managed_irq,6,7 would have dropped
domain isolation; the docs say isolcpus=domain,managed_irq,6,7.
Prediction record: the backlog's three suspects (IPIs, TLB shootdowns,
residual tick) were all wrong, refuted by the trace. Claude's first
reading of run A, a package power state paid by CPU 7, was right about
an idle exit and wrong about where; the 93 local-timer interrupts in
run B corrected it. The 92 C reading under machine-wide polling did not
recur in the two-minute run B (68 to 71 C); the 24.96 W reading stands.
