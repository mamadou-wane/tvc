# 0029: sweep aggregation and affinity preflight

Date: 2026-08-21
PR: #30 (78d1c51998f8e98d8df0681970d48e88b4e0aa11)
Agent: Codex (gpt-5.6-sol via codex-cli 0.147.0) authored the full diff;
Claude Code (Fable 5) wrote the spec from the scoped design and reviewed
per ADR-000.
Produced: aggregate_row() fixing issue #16 (percentile medians across
repeats, summed drop and missed counters, worst-repeat max, p99.99
spread block under the table), and the affinity preflight from the
2026-08-16 taskset near-miss (abort on a restricted inherited mask,
--allow-restricted-affinity override, drain-thread consequence named
when every allowed CPU is isolated, container and macOS safe). Twelve
new unit tests including the field incident shape.
Human: Mamadou merged unchanged. Closed issues #16 and #8 (the audit
had closed five #8 items by evidence; the rest landed in #28/#29).
Verification: Claude review verified by running, not reading: 23/23
unit tests native and in container, full ci.sh green, and a live
incident reproduction (docker --cpuset-cpus 0 aborts with the
restricted-mask message and exit 1; unrestricted runs L0 clean).
Process note: Codex's first run halted asking approval after reading
Claude-targeted skill instructions in the repo docs; re-prompting with
those explicitly ruled out as non-applicable fixed it. Future Codex
prompts should carry that exclusion up front.
