# 2026-09-15: v0.2b qualified L5/L7/L8 campaign

Qualified bare-metal timing evidence for the v0.2b closed loop: 24
predeclared runs on the qualified machine, eight interleaved repeats of L5
(open-loop harness, telemetry off), L7 (harness, control record on) and L8
(free-run closed loop against the simulator peer), each 300,000 recorded
cycles after 5,000 warmup at 500 Hz. Writeup: docs/results.md, "v0.2b: the
closed loop on the qualified machine". Every number there traces to a file
in this directory.

This is timing evidence and nothing else. The deterministic release
predicate, S2-gust at 30% modeled loss over 200 seeds and two actuator
delays (D=0 and D=1), 400 of 400 cases passing, is lockstep evidence proved in the canonical container
(tests/golden/lockstep/campaign-v02b.json) and is not established or
touched by these runs. The 400 cases are a predeclared synthetic matrix,
not a reliability probability.

## Configuration, frozen before run 1

Vehicle on CPU 7 under SCHED_FIFO 80 with mlockall and absolute deadlines;
L8 peer `sim/run_sim.py` S1-hold, seed 1, zero loss, one-tick actuator FIFO
(`--delay-ticks=1`), horizon 305,033 ticks, pinned to CPU 11 under
SCHED_OTHER; free-run phase offset 400 us (baselines/2026-09-15-phase-
calibration); idle states disabled on CPUs 6, 7 and 11 for the whole
session; governor and EPP performance, IRQ mask ff3f, timer_migration 0,
AC, kernel 7.0.0-30-generic. Source identity
0294935f67fc7ea62de83689f2eb3d50009a7dae6c2e71f7242c22b60c7300fd, built
from main 7e7b70e9bc34b421928a0596c7db5dc4d6f86359; `tvc_harness` sha256
07aa6f61fad5d82d03a7c3edcadf4079f2eaec2a1a14ea66220a636216b99c92.

Order: L5.r1, L7.r1, L8.r1, ..., L5.r8, L7.r8, L8.r8; launch 16:37:51
EDT, sweep exit 0 at 20:43:54 (session-observations.txt, closeout.txt). No row was rerun, replaced, repeated or void; nothing
was changed after a result was seen; no privileged command ran inside the
window (the optional /proc/timer_list observation was omitted on purpose).

## Acceptance, as predeclared

| Rule | Result |
|---|---|
| L5 p99.9 median against baselines/2026-08-29-pinned-timer-campaign, +50% | pass: 19.1 us vs 16.5 us, limit 24.8 (gate-L5.txt) |
| L8, every row: served coverage >= 0.99, served p99.9 <= 1000 us, max <= 2000 us, zero recorded actuator send failures, reconciliation valid, zero unexplained missing, session discipline | pass: coverage 0.99990 to 0.99997, p99.9 401.4 to 432.9 us, max 452.4 to 484.9 us (latency.json, gate-L8.txt) |
| eight paired L8 minus L7 wakeup p99.9 differences, median <= +2.0 us | pass: median -0.32 us, every pair negative, -0.624 to -0.048 (compare.json) |
| sign test | 8 negative, 0 positive, 0 tied, two-sided p = 0.0078; supplemental, decides nothing |

The run is the experiment unit. Every figure above is a per-run statistic
or a comparison of per-run statistics; nothing pools the 7.2 million
cycles into one population, and no cycle-level inference is made.

L5 environment difference. The 16.5 us reference (2026-08-29) was
collected with idle states disabled on the isolated pair, CPUs 6 and 7,
only. This session, because it declares the simulator peer CPU, holds
them disabled on CPUs 6, 7 and 11 for every row, L5 and L7 included. The
baseline and its tolerance are unchanged; the machine configurations are
not identical, and the 19.1 versus 16.5 us gap is reported under that
difference without a cause being assigned.

## Wakeup jitter per level (us), eight runs each

| Level | p99.9 median (min to max) | worst cycle | missed deadlines |
|---|---|---|---|
| L5 | 19.10 (18.75 to 19.58) | 109.6 | 0 |
| L7 | 18.29 (18.13 to 18.56) | 57.4 | 0 |
| L8 | 17.96 (17.81 to 18.13) | 89.0 | 0 |

## Served latency per L8 run

Served sensor-to-actuator latency is measured from the simulator's send
stamp to the vehicle's local send completion, over the served
observations only (the cycles whose actuator command was computed from
the fresh frame and transmitted). It is not an all-cycle latency: the
coast cycles, 9 to 30 per run, held the previous command and are counted
in the coverage, not in the latency population.

| Run | served / 300,000 | coverage | p50 | p99.9 | max | coast |
|---|---|---|---|---|---|---|
| L8.r1 | 299,991 | 0.99997 | 396.5 | 407.6 | 455.7 | 9 |
| L8.r2 | 299,987 | 0.99996 | 401.2 | 409.1 | 452.4 | 13 |
| L8.r3 | 299,984 | 0.99995 | 401.9 | 410.4 | 452.6 | 16 |
| L8.r4 | 299,973 | 0.99991 | 419.3 | 432.9 | 475.1 | 27 |
| L8.r5 | 299,970 | 0.99990 | 396.5 | 404.0 | 455.4 | 30 |
| L8.r6 | 299,978 | 0.99993 | 394.8 | 401.4 | 484.9 | 22 |
| L8.r7 | 299,977 | 0.99992 | 400.6 | 408.1 | 473.6 | 23 |
| L8.r8 | 299,983 | 0.99994 | 397.6 | 404.2 | 465.7 | 17 |

Recorded actuator send failures 0 on every run; unexplained missing
traffic 0 in both directions (reconcile.json); vehicle compute p50 5.5 to
5.7 us and p99.9 14.6 to 15.9 us on every run. L8.r4 sits about 22 us at
p50 and 25 us at p99.9 above the other seven runs' medians (not at the
maximum, where L8.r6 is higher): its uplink wait p99.9 is 427.0 us against 392.7
to 399.9 on the other runs, with the vehicle's own wake and compute
figures unchanged, which is consistent with a peer-side run-scale shift;
no retained diagnostic establishes the cause and none is assigned.

## Session captures

session-observations.txt (verbatim pre-run verification block, launch
time, the timer_list omission), interrupts-before/after.txt and
irq-delta.txt (LOC on CPU 7 14,609,181 over the session, 1.996 per cycle;
no NVMe or device interrupt on CPUs 6 or 7), cpuidle-before/after.txt
(12 states disabled before run 1 and after run 24; which CPUs is read
from the per-CPU lines in session-observations.txt and restore.txt,
CPUs 6, 7 and 11; the two capture files are the unlabeled output of
`cat /sys/devices/system/cpu/cpu*/cpuidle/state*/disable` in bash under
en_US.UTF-8, whose full-path collation orders cpu0, cpu10, cpu11, ...,
cpu15, cpu1, cpu2, ..., cpu9, four states each, so the ones at positions
9 to 12 are CPU 11 and those at 49 to 56 are CPUs 6 and 7; decoded under
LC_ALL=C the same positions would misread as CPU 10),
temp-during.txt (package 73.3 to 74.3 C across the in-session samples,
72.5 C at the seal; the 85.9 C sample at 17:39:11 falls between rows and
the session holds no per-row timestamp to place it exactly; no cause is
assigned), sweep-console.log. The "ALL 22 PASS" line in
session-observations.txt is the operator's console note about a local
preflight script that is not part of the repository; the primary outputs
are the verbatim verification block above it in the same file.

## Files

| File | What it is |
|---|---|
| sweep.json | roster of the 24 runs in execution order, with peer provenance on the L8 rows |
| L*.r*.summary.json | per-run summary written by the vehicle |
| L*.r*.result.json | per-run process result as recorded in the roster |
| L8.r*.reconcile.json | per-run reconciliation of recorded against transported traffic |
| latency.json | exact stdout of `scripts/latency.py --results` |
| gate-L5.txt, gate-L8.txt | exact output of the two `scripts/bench_gate.py` invocations |
| compare.json | exact stdout of `scripts/compare_arms.py --a L7 --b L8` |
| session-observations.txt, irq-delta.txt, interrupts-*.txt, cpuidle-*.txt, temp-during.txt, sweep-console.log | session captures, above |
| closeout.txt | the closeout note written before the seal |
| raw-inventory.txt | SHA-256 of every retained raw artifact, sealed after the analysis |
| raw-sizes.txt | byte size of every file in that sealed population |
| redactions.txt | the 26 public files that are redacted derivatives, with sealed and published hashes |
| restore.txt | post-seal closeout metadata: the machine restoration after the session; deliberately outside the sealed population |

The latency figure the plot script wrote from the raw series is committed
as docs/latency.svg and docs/latency.png, byte-identical to the sealed
files; it cannot be regenerated from this directory. The figure is
stamped diagnostic and every free-run summary carries
`timing_qualified: false`: the harness and the plot script never assert
qualification themselves; the gates above do.

Redacted derivatives. Twenty-six files (the 24 result records, sweep.json
and sweep-console.log) carry the measurement machine's absolute home path
in recorded command lines. The public copies replace the exact prefix
`/home/wane` with `/home/<user>` and change nothing else; they are
deterministic derivatives of the sealed originals and therefore do not
hash-identically to them. redactions.txt lists each with its
sealed-original and published-copy SHA-256; reversing the substitution
reproduces the sealed hash. Every other file is byte-identical to its
sealed original.

What is not here. The raw evidence (control and input recordings, replay
metadata with the simulator reports, timing series, peer and vehicle
logs, about 3.16 GB) stays on the measurement machine under
results/2026-09-15-v02b-campaign, bound by raw-inventory.txt: 264 files,
3,163,255,987 bytes, sealed after the analysis and hash-verified. Git alone
is not sufficient to rerun the raw-recording analysis; the gate tools
cannot load this compact directory as an L8 results set.

## Not in this campaign

The v0.2b design also described a standalone 150,000-cycle free-run
S2-gust episode under 30% loss. It was deferred from this publication:
the runner did not support it as written and the exact L8 evidence window
excludes it from qualified status. Neither the deterministic 400-case
campaign nor the short container tests establish that long-duration
free-run result under loss; it remains unmeasured.
