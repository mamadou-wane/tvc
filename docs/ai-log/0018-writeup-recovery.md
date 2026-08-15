# 0018: writeup landing recovery
Date: 2026-08-15
PR: #19 (merge 9fcb9c1)
Agent: none; process recovery of already-reviewed content
Produced: no new changes. PR #18 had been merged while its stacked base branch still existed, so its merge commit landed on campaign-baselines instead of main; GitHub retargets a stacked PR only when its base branch is deleted. Mamadou noticed docs/results.md missing from main; this PR carried the reviewed content the last step and made #18's merge commit reachable, keeping entry 0017's citation true.
Human: Mamadou caught the gap, merged the recovery, moved the v0.1.0 tag to a tree that contains the writeup, and enabled automatic head-branch deletion so stacked PRs retarget on merge from now on.
Verification: three-dot diff of the recovery PR was exactly the six reviewed writeup files; docs/results.md and the figure confirmed on origin/main after merge.
