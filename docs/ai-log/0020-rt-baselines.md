# 0020: rt campaign baselines
Date: 2026-08-15
PR: #21 (merge 732072a)
Agent: none; all data captured by Mamadou on the measurement machine
Produced: baselines/2026-08-15-rt-campaign, the PREEMPT_RT comparison campaign on linux-image-realtime 7.0.0-29, version-matched to the generic kernel of the primary baselines. Same machine, same discipline, one variable.
Human: Mamadou installed the RT kernel, booted it one-shot via grub-reboot, re-applied the runtime discipline, ran the campaign, and merged.
Verification: all 18 rows pass the integrity gate; every summary records kernel 7.0.0-29-realtime with performance governor and EPP on AC.
