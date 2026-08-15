# 0008: documentation corrections
Date: 2026-08-14
PR: #7 (merge 433eb7e)
Agent: Claude Code (Sonnet 5 implementer, directed by Fable 5)
Produced: rewrote every methodology section the stress test falsified (CO framing, missed-cycle wording, alloc-guard scope with a measured count, host preparation for the ProBook 465 G11, RT-throttling rationale, campaign table); added docs/plan.md; fixed the Output section to match the code's series names and --naive flag.
Human: Mamadou reviewed and merged. Process note: earlier the same day a human-directed CI unblock (dockerfile rename, dfad74f) was pushed to main outside the ai-log-only rule; recorded here for trail completeness.
Verification: em-dash and banned-word scans clean; unit tests green; the measured allocation count came from a live --alloc-guard=count run rather than an asserted number.
