# 0027: prose cleanup and em-dash gate

Date: 2026-08-21
PR: #28 (4549dd9a810d4b498929ab06a37b2b73f51afa9e)
Agent: Claude Code (Fable 5)
Produced: first PR of the issue #8 cleanup batch, scoped by a 6-agent
audit of every #8/#16 item against main at 827d0ce. Five #8 items were
found already landed (repeat labeling, drop column, interrupted-run
marker, --out default, README tense) and closed by evidence rather than
work. The PR itself: all 18 em dashes out of comments and console
output, a ci.sh grep gate so the rule is enforced rather than
re-reviewed, the naive-log tally comment corrected to 2:2, the
loop_stats.hpp threshold claim corrected, the ADR-000 garbled sentence
rewritten, plan.md's false "SMI counter logged" claim replaced with the
hwlatdetect substitute, and the sweep.py docstring updated to strict
exits.
Human: Mamadou chose abort-over-warn for the affinity preflight, full
aggregation for #16, env_probe extraction, and the ci.sh gate (four
scope decisions); reviewed and merged unchanged.
Verification: full container ci.sh green across all three trees with
the gate running first; negative test proved the gate fires on a
planted em dash; the one native-test error (test_plot, matplotlib
missing on macOS) predates the change.
