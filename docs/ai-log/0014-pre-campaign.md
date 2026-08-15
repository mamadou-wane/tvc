# 0014: pre-campaign batch
Date: 2026-08-15
PR: #14 (merge 4c666e6)
Agent: Claude Code (Sonnet 5 implementer, directed by Fable 5)
Produced: the plot resolves --repeat filenames to their real labels; the sweep table surfaces dropped samples; summary.json records cycles_requested and the table rejects incomplete or pre-integrity runs; the environment record gains ac_online, governor, EPP, and package temperature with honest unknown fallbacks. A review fix round decoupled the cycle count from histogram capacity (an unconditional iteration counter) so a saturation event shows in the drop column instead of silently excluding its row, and gave the plot's skip messages distinct reasons.
Human: Mamadou reviewed and merged. The review caught the count/integrity interaction before it shipped; the fix landed in the same PR.
Verification: full container gate green in both trees across the fix round; scoped re-review confirmed both findings addressed.
