# 0033: pinned-timer campaign, configuration of record

Date: 2026-08-29
PR: #35 (0924204fdd292c50993613d8422a38e9e9c177c4)
Agent: Claude Code (Fable 5); the campaign ran unattended on the ProBook,
launched and read back over SSH.
Produced: the GRUB change to isolcpus=domain,managed_irq,6,7 and the
post-reboot discipline, the 21-run campaign under the pinned-timer
discipline (commit 0fafb7c, 3.6 hours, 67 to 69 C), the level-by-level
comparison against v0.2a, the gate checks, the results.md campaign
section and headline, the README headline and figure, the qualification
and methodology updates, the gate repoint (baseline
2026-08-29-pinned-timer-campaign, tolerance 50 percent), and the
baselines directory.
Human: Mamadou chose the pinned-timer discipline as the configuration
of record, the 50 percent gate, and the new README headline from three
decisions put to him with a recommendation each; he merged the text as
drafted.
Verification: nine pinned runs, p99.9 16.0 to 17.6 us, p99.99 under
21, worst cycle 86 us, zero misses and drops, every summary recording
timer_migration 0 and eight disabled idle states; the gate passes the
campaign against itself and the v0.2a campaign (7.5 us) and fails a
timer-migrated run (380 us); bench_gate unit tests green.
Prediction record: the writeup's expectation that managed_irq would
move the two NVMe queues was wrong; the flag leaves single-CPU managed
masks alone, and the queues stayed silent anyway (zero interrupts on
the pair in 3.6 hours). The unpinned levels getting worse under the
new discipline was not predicted before the run; it follows from the
same mechanism and is now in the writeup as a stated cost.
