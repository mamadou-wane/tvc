# 0012: script executable bits
Date: 2026-08-15
PR: #12 (merge 6f775e6)
Agent: Claude Code (Fable 5, controller-direct)
Produced: mode bits 100644 to 100755 on scripts/sweep.py and scripts/plot_jitter.py, no content change. The verbatim zip import preserved the scripts' non-executable permissions (noted in the PR #1 review) and the documented ./scripts/ invocation failed on a fresh clone, first hit during ProBook bring-up.
Human: Mamadou hit the failure on the machine, reviewed, and merged.
Verification: git diff shows mode-only changes, zero content hunks.
