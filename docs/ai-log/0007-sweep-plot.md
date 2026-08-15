# 0007: sweep and plot correctness
Date: 2026-08-15
PR: #6 (merge 266940c)
Agent: Claude Code (Sonnet 5 implementer, directed by Fable 5); Codex authoring begins once the Codex CLI is verified on this machine (see ADR-000)
Produced: the campaign now stops at the first level that cannot run (previously L5 ran unpinned when --cpu was absent, silently breaking the one-change-per-level invariant); table rows are gated on summary.json applied config; --repeat N reports median p99.9 with spread; plot_jitter derives its y floor from cycle counts, guards the empty-results case, and floors x above the early-wakeup clamp.
Human: Mamadou reviewed and merged. Review noted a follow-up: plot_jitter's label parsing does not yet understand --repeat filenames.
Verification: six unit tests red-then-green natively; container gate green both trees; unprivileged smoke run halted at the first failing mitigation with exit 2 and no tabulated row.
