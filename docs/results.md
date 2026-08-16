# Campaign results

Six mitigation levels, three repeats of 300,000 cycles each (10 minutes per
run at 500 Hz), on the qualified platform (qualification.md). Every number
below traces to a committed summary in baselines/2026-08-15-campaign-2/,
and the figure regenerates from the committed CSVs:

    python3 scripts/plot_jitter.py --results baselines/2026-08-15-campaign-2

![Wakeup jitter CCDF across mitigation levels](jitter.svg)

## Headline

p99.9 wakeup jitter of 7.5 microseconds at 500 Hz on a stock Ubuntu
generic kernel, with per-core isolation and every C-state disabled (the
v0.2a campaign below). Under the original discipline, which left
C-states enabled, the same stack measured 88.4 us: one power-management
knob carried a 12x difference that the recorded environment fields could
not see. The naive baseline drifts whole seconds off schedule and cannot
see that in its own measurement.

## The table

Wakeup jitter in microseconds, median of three repeats with (min-max)
spread for p99.9. Full percentiles per run live in the committed summaries.

| Level | Adds | p99.9 median (spread) | Worst max |
|---|---|---|---|
| L0 | nothing: sleep_for(period), allocating log | 17,163,092 (17.0M-17.2M) | ceiling |
| L1 | absolute deadlines | 565 (494-583) | 1,108 |
| L2 | mlockall + prefaulted stack and heap | 559 (483-642) | 1,349 |
| L3 | SCHED_FIFO 80 | 477 (12-555) | 1,042 |
| L4 | pinned to the isolated, disciplined core | 157 (88-200) | 993 |
| L5 | allocation-free hot path | 88.4 (88-89) | 994 |

## What each level actually did

**L0 is a correctness failure before it is a jitter number.** sleep_for(period)
from "now" drifts by the overshoot every cycle: roughly 57 us per cycle
compounds to 17 seconds behind schedule over ten minutes, saturating the
histogram ceiling (the drop counter caught 1,792 and 11,128 out-of-range
samples in two of the repeats). Meanwhile the naive self-referenced series,
measuring each wakeup against the previous one, reports a p99.9 near 700 us
for the same runs. A harness that measures itself that way would have
called this loop healthy. Absolute deadlines are what separate a control
loop from a metronome sliding off the song.

**L1 makes the loop correct.** Zero missed deadlines from here on. The
remaining ~565 us tail belongs to the platform: the p99 sits almost exactly
at 100 us in every unpinned run, the signature of roughly one wakeup per
hundred paying a full deep-C-state exit on an undisciplined core.

**L2 is an honest null result.** mlockall plus prefaulting changed nothing
here because nothing was faulting; the mlock status line proves residency
with a post-warm minor-fault recheck of zero. It stays in the stack because
the flight software will allocate at startup and must not fault later.

**L3 exposes the placement lottery.** Same flags, three runs: p99.9 of
555, 12, and 477 us. The 12 us run landed on CPU 0, which services constant
interrupt traffic and therefore never sleeps deeply; the others landed on
quiet cores that pay C-state exits. A 40x spread controlled entirely by
where the scheduler put the thread is the argument for pinning.

**L4 removes the lottery.** Pinned to CPU 7 (both SMT siblings isolated at
boot, deep idle disabled on the pair, performance governor and EPP). The
median p99.9 lands at 157 us with the spread still wide (88 to 200); the
first repeats of the pinned levels carry occasional tail events the later
repeats do not, consistent with residual interrupt traffic rather than the
loop itself.

**L5 is the endpoint.** With the allocating log path removed and the
allocation guard set to abort, the loop body runs in 0.3 us at p99.9 and
the wakeup tail settles at 88.4 us, repeat after repeat. The guard proves
the hot path clean at runtime.

## What is left in the tail

Beyond p99.99 each pinned run keeps roughly thirty events in the 400 to
1,000 us range. Platform qualification bounds the firmware contribution
(two stalls per hour, max 129 us), so these are something else, most
likely interrupts still reaching the isolated pair. Characterizing them
with the osnoise tracer is the next measurement. Until then the honest
claim stops at p99.9.

## Kernel comparison: generic vs PREEMPT_RT

From 26.04 the PREEMPT_RT kernel ships free in the archive, version-matched
to generic. Same machine, same discipline, same binary; the kernel is the
only variable. Full RT data: baselines/2026-08-15-rt-campaign.

![Wakeup jitter CCDF on the PREEMPT_RT kernel](jitter-rt.svg)

Medians of three repeats, microseconds; (spread) on p99.9; worst max across
repeats.

| Level | Kernel | p50 | p99.9 (spread) | p99.99 | Worst max |
|---|---|---|---|---|---|
| L1 | generic | 35.4 | 565 (494-583) | 946 | 1,108 |
| L1 | PREEMPT_RT | 112.8 | 1,010 (990-1038) | 1,048 | 2,193 |
| L4 | generic | 12.8 | 157 (88-200) | 586 | 993 |
| L4 | PREEMPT_RT | 3.5 | 154 (91-190) | 619 | 968 |
| L5 | generic | 12.8 | 88.4 (88-89) | 492 | 994 |
| L5 | PREEMPT_RT | 3.5 | 90.5 (90-152) | 539 | 987 |

Three findings. First, PREEMPT_RT cut the pinned loop's median wakeup
latency 3.7x (12.8 to 3.5 us): its wakeup path for a FIFO task is simply
leaner. Second, at p99.9 the kernels tie within spread (88.4 vs 90.5), so
for this isolated, disciplined, pinned workload the generic kernel already
delivers the RT kernel's tail. Third, the population beyond p99.99
survived both kernels unchanged, which narrows its suspect list: threading
every IRQ handler changed nothing, so those events are likely
non-preemptible work such as IPIs, TLB shootdowns, or the residual tick.
The osnoise tracer is the next step and now has a sharper question.

The cost side is equally clear: unpinned SCHED_OTHER runs roughly doubled
(L1 p50 35 to 113 us, p99.9 565 to 1,010) and L1 dropped one deadline in
900,000 cycles. PREEMPT_RT buys determinism for RT threads and charges
everything else for it. The conclusion for this project: PREEMPT_RT is the
tool when isolation is unavailable; with isolation and power discipline,
the generic kernel holds the same p99.9. The baselines and the regression
gate stay on the generic kernel, the configuration of record.

One pattern held across every campaign on both kernels: the first repeat
of each pinned level carries the widest tail (L5 first repeats of 237, and
152 us against later repeats near 88). Recorded as an open observation for
the osnoise pass.

v0.2a caveat: this comparison ran with C-states enabled, and the v0.2a
campaign below showed C-state exits set the 88 us p99.9 floor on this
machine. Both kernels were paying the same power-management cost, so the
tie says the kernels tie under that discipline. Whether they still tie
with C-states disabled is an open question for a rematch.

## v0.2a: telemetry at no measured cost, and the C-state floor

v0.2a added the telemetry path: a 56-byte record per cycle through a
single-producer single-consumer ring, drained by a SCHED_OTHER thread
off the isolated core into a CRC-checked recording file (spec:
superpowers/specs/2026-08-16-telemetry-v02a-design.md). The acceptance
question: does enabling it move the jitter CDF? Campaign of 2026-08-16,
seven levels, three repeats of 300,000 cycles, same protocol as v0.1;
L6 is L5 plus --telemetry. Data:
baselines/2026-08-16-telemetry-campaign and
baselines/2026-08-16-l5l6-repeats.

    python3 scripts/plot_jitter.py --results baselines/2026-08-16-telemetry-campaign

![Wakeup jitter CCDF with the telemetry level](jitter-telemetry.svg)

| Level | Adds | p99.9 median (spread) | Worst max |
|---|---|---|---|
| L0 | nothing: sleep_for(period), allocating log | 1,876,951 (1.88M-1.94M) | 1,946,157 |
| L1 | absolute deadlines | 9.6 (9.6-9.8) | 222 |
| L2 | mlockall + prefaulted stack and heap | 10.0 (9.7-12.8) | 107 |
| L3 | SCHED_FIFO 80 | 13.5 (9.4-13.5) | 713 |
| L4 | pinned to the isolated core | 13.9 (7.6-14.4) | 535 |
| L5 | allocation-free hot path | 7.5 (7.4-7.5) | 471 |
| L6 | telemetry ring + drain thread | 9.6 (7.2-10.4) | 408 |

### The C-state floor

These numbers sit 12x below the v0.1 table, and the code did not
change. The discipline did: this campaign disabled every cpuidle state
on every CPU (cpupower idle-set -D 0) before running. The idle driver
on this machine advertises C2 at 18 us exit latency and C3 at 350 us;
with all states disabled, the tail that sat near 100 us at p99 and
88 us at p99.9 in v0.1 collapses to 8 to 14 us. The v0.1 headline was a
measurement of C-state exit latency. Even L0's drift shrank
9x, because the sleep_for overshoot that compounds it is itself mostly
C-state exit.

The provenance system could not see this. Each summary records
governor, EPP, AC state, and package temperature, and every one of
those fields is identical between the 88.4 us runs and the 7.5 us runs.
cpuidle state joins the environment capture as a follow-up; until it
does, the number to trust is the one whose discipline was captured as
command output in qualification.md.

### Telemetry cost: three repeats said yes, eight said no

The planned check (L6 p99.9 median within 10 percent of L5, three
repeats each) failed: 9.6 vs 7.5 us, +28 percent. Five more repeats of
each level under the same discipline
(baselines/2026-08-16-l5l6-repeats) reversed the sign: L5 median 9.7,
L6 median 8.4. Runs of both configurations intermittently carry a
run-scale mode, a few hundred cycles landing in the 10 to 35 us band;
one L5 repeat put its whole p99 at 13.6 us with no telemetry in the
build, and one L6 repeat put p99.9 at 35.4 us with a normal p99. That
mode owns the tail at this floor, and which arm it visits is luck.

Pooled over all eight runs per arm, 2.4 million cycles each:

| | L5 | L6 |
|---|---|---|
| pooled p99.9 | 13.72 us | 13.67 us |
| cycles above 10 us | 5,381 | 4,021 |
| cycles above 50 us | 132 | 105 |
| cycles above 200 us | 53 | 44 |

The CDF is unchanged within run-to-run variation: 48 nanoseconds of
difference at pooled p99.9, and no threshold where the telemetry arm
systematically exceeds the quiet one. A rank test across the sixteen
per-run p99.9 values agrees (Mann-Whitney U, p = 0.44). The 3-repeat
median check was the wrong instrument at this floor; the v0.2b check
will interleave the two arms within one campaign and judge pooled
exceedance counts, so run-scale environment noise cancels instead of
deciding the verdict.

The recording side held its contract in every run: 305,000 records per
run, zero ring drops across all eight telemetry runs, every recording
decoding CRC-clean at the byte-exact expected size.

### What is left in the tail, revisited

The 300 to 700 us events beyond p99.99 survived C-state disabling in
both arms, which removes deep idle exits from their suspect list; they
had already survived PREEMPT_RT (above). What remains is
non-preemptible work: IPIs, TLB shootdowns, or the residual tick. The
osnoise tracer now has a question sharpened from two directions. The
recordings already contribute: each carries a per-cycle tick stamp, and
decoding the 35.4 us repeat's recording places its 383 cycles above
20 us across the full ten minutes (ticks 87 to 300,940), so that run's
elevated tail was a sustained state across the whole window. Whatever
visited the machine stayed for the run.

### Incidents, recorded

Two discipline mistakes from this campaign, kept because the next
campaign inherits them. First, the initial launch wrapped sweep.py in
taskset -c 7, which would have pinned the unpinned levels to the
isolated core and confined the drain thread's inherited affinity mask
to it; caught from the console output before any data was used, and
rerun without it. A sweep preflight that compares the inherited mask
against /sys/devices/system/cpu/isolated is the guard to add. Second,
the IRQ affinity mask written during setup (ffff3f) carries bits for
CPUs 16 to 23 on a 16-CPU machine; the kernel rejected it with
EOVERFLOW and the per-IRQ loop suppressed the errors, so IRQ affinity
was likely never applied. The correct exclude-6,7 mask is ff3f. The
numbers above were measured without it.

## Regression gate

scripts/bench_gate.py compares a fresh campaign directory against the
committed baselines (as of v0.2a: baselines/2026-08-16-telemetry-campaign,
L5 p99.9 median 7.5 us) and fails when the L5 p99.9 median regresses
beyond tolerance. The default tolerance is 100 percent at this floor,
because identical-config medians ranged 7.4 to 14 us across eight runs;
the gate still polices discipline, since a run taken with C-states
enabled measures near 88 us and fails far past any tolerance:

    python3 scripts/bench_gate.py --results results/<new-dir>

It runs only on the measurement machine. Hosted CI never produces or
judges a timing number; that boundary is the point of the split.

## Provenance

Machine, kernel, topology, isolation, and firmware qualification:
qualification.md. Each summary records its applied config and environment
(governor, EPP, AC state, package temperature) so a run taken under lapsed
discipline identifies itself. Methodology, including why this harness is
coordinated-omission-free by construction: methodology.md.
