# 0006: timing loop honesty
Date: 2026-08-15
PR: #5 (merge e584dc6)
Agent: Claude Code (Sonnet 5 implementer, directed by Fable 5)
Produced: made L0 the genuinely drifting naive loop the docs describe; pinned timer slack to 1 ns so the SCHED_FIFO level measures policy rather than slack removal; strict exit codes (0 ok, 1 usage, 2 mitigation failed, 3 interrupted, 4 write failed); summary.json now records applied config and an environment block; argument parsing rejects garbage instead of silently running a wrong configuration.
Human: Mamadou reviewed and merged. Review deferred two minors to the final pass: int narrowing before fifo/cpu range validation, and env.timer_slack_ns reporting the requested rather than read-back value.
Verification: four new strict-exit tests red-then-green; full container gate green in both trees; earlier tests unchanged.
