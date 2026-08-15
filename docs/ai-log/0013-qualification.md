# 0013: firmware stall qualification
Date: 2026-08-15
PR: #13 (merge d1a047e)
Agent: Claude Code (Fable 5, controller-direct); measurements captured by Mamadou on the ProBook
Produced: qualification.md gains the post-reboot isolation verification, the one-hour hwlatdetect record (two events, max 129 us, neither on the isolated pair), the cleared verdict with the rate arithmetic, and the AMD correction that turbostat's SMI column is an Intel-only MSR.
Human: Mamadou ran the hour and merged.
Verification: numbers trace verbatim to captured output.
