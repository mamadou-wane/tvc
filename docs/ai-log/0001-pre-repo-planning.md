# 0001: pre-repo planning and stress test

Date: 2026-08-14
PR: none (pre-repo)
Agent: Claude Code (Fable 5); earlier drafting sessions also used Claude

Produced: the two draft documents (project overview, phased plan) and the
measurement harness were drafted in collaboration with Claude before this
repo existed. On 2026-08-14 a 15-agent adversarial review (7 lenses,
independent verification of every candidate blocker) produced 103
findings, 7 confirmed blockers, and 1 refuted finding, then the approved
restructure spec in docs/superpowers/specs/.

Human: chose the project, the two goals, and the hardware; set the 3-week
v0.1 target; approved the PR-body attribution carve-out; approved the spec
after review. The stress test rejected several claims in the human- and
AI-authored drafts alike (CI jitter gate on VMs, misapplied coordinated
omission correction, undesigned TMR input alignment, SMT-blind core
isolation); the week-1 PR series fixes them.

Verification: findings were adversarially verified by independent agents
against the documents, the code, and primary sources before being acted on.
