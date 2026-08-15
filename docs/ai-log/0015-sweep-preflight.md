# 0015: sweep preflight
Date: 2026-08-15
PR: #15 (merge 4e292fe)
Agent: Claude Code (Sonnet 5 implementer, directed by Fable 5)
Produced: a binary-staleness preflight (sweep refuses to run when the binary predates the sources, --allow-stale to bypass) and per-row exclusion reasons replacing the misleading fixed header.
Human: Mamadou reviewed and merged. Field incident behind it: a three-hour campaign ran on a stale binary after a pull without a rebuild; the integrity gate correctly excluded all rows, and the fix makes that failure impossible to repeat silently.
Verification: three new unit tests on the pure staleness check; container gate green both trees.
