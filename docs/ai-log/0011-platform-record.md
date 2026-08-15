# 0011: measured platform record
Date: 2026-08-14
PR: #11 (merge 3a8a799)
Agent: Claude Code (Fable 5, controller-direct); all platform data captured by Mamadou on the ProBook
Produced: docs/qualification.md, the measured platform record (Ubuntu 26.04 LTS kernel 7.0.0-29-generic, NO_HZ_FULL and RCU_NOCB_CPU confirmed, adjacent SMT sibling pairs, version-matched realtime kernel in the archive); host preparation corrected for the real machine (26.04 pin, adjacent-pair sibling map replacing the wrong N/N+8 example, reference isolation on core 3 = CPUs 6,7) and the real-time privileges section restored after an earlier rewrite dropped it.
Human: Mamadou ran the qualification commands on the machine, pasted the output, and reviewed and merged. The measured topology overruled the AI's earlier N/N+8 sibling assumption, and the machine's actual distro (26.04, not the planned 24.04) was kept after verifying the two facts the plan depends on rather than reinstalling.
Verification: every claim in the diff traces to captured command output; em-dash and banned-word scans clean.
