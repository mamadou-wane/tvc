# Measurement harness

The instrumentation layer for the One-Axis TVC control loop. It runs a fixed-rate cycle, measures how well that cycle holds its deadline, and lets each real-time mitigation be switched on independently so the contribution of each one is measurable in isolation.

Everything is off by default. The default build is the naive loop, and that is the point.

```
cmake -S . -B build && cmake --build build -j
./scripts/sweep.py --cpu 3
./scripts/plot_jitter.py --results results
```

HdrHistogram is fetched automatically at configure time; there is nothing else to install.

---

## What it measures

Two quantities, kept apart, because conflating them makes both uninterpretable.

**Wakeup jitter**: the gap between the cycle's intended deadline and the moment the loop actually resumed. This is the platform's contribution: scheduler latency, page faults, interrupts, frequency transitions.

**Execution time**: how long the loop body took once running. This is the code's contribution.

A p99.9 of 8 ms means very different things depending on which of the two produced it, and the fix is different in each case.

### Coordinated omission

This harness has no coordinated omission by construction. Every cycle is
measured against its intended absolute deadline (origin + n x period), and
every cycle produces exactly one sample: when one cycle runs long, the
displaced cycles behind it wake immediately and record their true lateness.
Nothing is omitted, so nothing needs correcting.

A second series, jitter_naive, records what a self-referencing measurement
(previous wakeup + period) would have reported. After a stall, that scheme
sees the very next cycle as on time, which is exactly how naive harnesses
hide their worst behavior. The gap between the two series is the
demonstration; the primary series is the only published number.

### Deadline misses

A cycle that finishes after the next cycle's deadline slipped the schedule
by a full period. These are counted separately and also appear in the
histogram: the cycle did run, and its lateness is real data. The miss
counter is the cross-check that the tail is being read honestly.

---

## The allocation guard

Global `operator new` and `delete` are replaced. A thread-local depth counter, set by an RAII marker around the cycle body, means heap activity inside the cycle can be counted or made fatal.

The guard intercepts C++ operator new and delete only; direct malloc-family
calls from C code bypass it. The hot path is all C++, so this scope is
sufficient today, and the limit is stated so the claim stays honest.

| Mode | Behaviour |
|---|---|
| `--alloc-guard=off` | no bookkeeping (default) |
| `--alloc-guard=count` | tally allocations, frees and the largest block; report at exit |
| `--alloc-guard=abort` | write the offending size to fd 2 and abort immediately |

The workflow is `count` first to find out what is there, then `abort` to keep it gone. Under `abort` the process dies inside `operator new`, so the allocation site is directly in the backtrace:

```
gdb ./build/tvc_harness
(gdb) run --alloc-guard=abort
(gdb) bt
```

The guard is thread-local by design. A drain thread doing I/O and formatting is free to allocate; only the control thread is constrained.

`--no-naive-log` removes the deliberately allocating telemetry path: a `std::string` built per cycle, which is what a first-draft logger looks like. With it on, the guard reports 4200 allocations and 4200 frees per 2100 cycles on the reference toolchain (gcc, libstdc++, Ubuntu 24.04); the exact count is toolchain-dependent, which is why the harness measures it instead of asserting it. That is the thing Phase 01 exists to eliminate.

---

## Host preparation

Numbers from a VM, WSL, or a container are not usable. Bare metal only.
The reference machine is an HP ProBook 465 G11 (Ryzen 7 7735U: 8 cores,
16 threads, homogeneous Zen 3+) on Ubuntu 26.04 LTS, generic kernel 7.0.
The measured platform record lives in qualification.md; NO_HZ_FULL and
RCU_NOCB_CPU are confirmed enabled in this kernel, so the boot parameters
below actually engage.

**Identify the topology first.** `lscpu --all --extended` and
`cat /sys/devices/system/cpu/cpu*/topology/thread_siblings_list`. On this
machine, SMT siblings are adjacent pairs: core N is CPUs 2N and 2N+1, so
the pairs are (0,1), (2,3) ... (14,15). Measured, not assumed; see
qualification.md.

**Isolate a full physical core.** Both SMT siblings. The reference
configuration uses core 3, CPUs 6 and 7:

    isolcpus=6,7 nohz_full=6,7 rcu_nocbs=6,7

in GRUB_CMDLINE_LINUX_DEFAULT, then update-grub and reboot. Pin the loop
to CPU 7 and leave 6 idle. Core 0 is avoided because it carries default
housekeeping and IRQ load. Isolating a lone SMT thread is not isolation:
the sibling shares the core's execution units and caches. `nosmt` is the
simpler alternative when the core count can be spared.

**The comparison kernel is one package away.** From 26.04 the PREEMPT_RT
kernel ships free in the archive, version-matched to generic
(`linux-image-realtime`, 7.0.0-29 against 7.0.0-29-generic at the time of
qualification). The campaign's kernel comparison axis reruns the sweep on
it with everything else held constant.

**Allow real-time priority without root.** In /etc/security/limits.conf:

    @realtime  -  rtprio   99
    @realtime  -  memlock  unlimited

then `sudo groupadd realtime && sudo usermod -aG realtime $USER` and log
back in. Running under sudo works too, but changes the environment being
measured.

**Move interrupts away.** Stop irqbalance if it is running; write masks
excluding the isolated pair to /proc/irq/*/smp_affinity. Some kernel-
managed IRQs refuse the write; that is expected. Verify with
/proc/interrupts deltas during a run.

**Benchmark on AC power, always.** power-profiles-daemon rewrites the
energy performance preference on AC/battery transitions; mask it for the
run and pin EPP to performance under amd_pstate. Disable deep idle on the
isolated pair only (per-CPU cpuidle sysfs or /dev/cpu_dma_latency), not
machine-wide: forcing 16 threads to C0 in a 15 W thin chassis invites
thermal throttling mid-run.

**Qualify the platform before trusting it.** An hour of hwlatdetect at
idle, and the SMI counter (turbostat) logged across every run. Firmware
stalls are invisible to the kernel and no setting removes them; if this
chassis has them, that is a finding to publish, not to discover in an
interview.

**Real-time throttling.** The kernel default (sched_rt_runtime_us =
950000) leaves 5% of each second to non-RT tasks and is the actual
runaway-loop protection on a stock kernel; this loop's duty cycle is
around 1%, far from the limit. Priority 80 rather than 99 is convention
plus headroom for future higher-criticality threads, not a safety
mechanism.

---

## The campaign

`scripts/sweep.py` runs six levels, each adding exactly one mitigation to the previous one, so any difference between adjacent runs is attributable to a single change.

| | Adds |
|---|---|
| L0 | baseline: sleep_for(period) from now, the naive drifting loop |
| L1 | absolute deadlines, `clock_nanosleep(CLOCK_MONOTONIC, TIMER_ABSTIME)` |
| L2 | `mlockall` plus pre-faulted stack and heap |
| L3 | `SCHED_FIFO` priority 80 |
| L4 | pinned to the isolated core |
| L5 | allocation-free hot path, guard set to `abort` |

Without `--cpu`, there is no core to pin to, so the campaign stops after L3.

Deadlines derive from a single origin (`origin + n × period`), never from `now + period`. The latter lets error accumulate silently and is the most common bug in fixed-rate loops.

Priority 80 rather than 99 leaves headroom above the loop for kernel threads. At 99 a runaway loop competes with the machinery keeping the system alive, and the machine stops responding.

Expect L1 and L4 to produce the largest single improvements. If L3 makes things *worse*, the loop is not pinned yet and `SCHED_FIFO` is fighting the rest of the system for a shared core; that is L4's job.

Run each level long enough for the tail to be real. At 500 Hz, 300,000 cycles is ten minutes, which puts roughly 300 samples beyond p99.9. Fewer than that and the figure is noise.

---

## Output

Per run, into `--out`:

```
L3.jitter.csv          wakeup jitter, microseconds, the published series
L3.jitter_naive.csv    the naive self-referenced series, for the demonstration only
L3.exec.csv            loop body execution time
L3.summary.json        config and key percentiles
```

`plot_jitter.py` renders all runs in a directory as a complementary CDF: x is jitter, y is the fraction of cycles worse than that value, log on both axes so the tail gets space proportional to how much it matters. A linear-y CDF compresses everything interesting into the top two percent of the plot, which is why latency work uses this form.

`--naive` plots the naive series instead of the published one, for the "Coordinated omission" demonstration above. The naive series is never a published number.

---

## Notes

- The build uses `-O2 -g -fno-omit-frame-pointer`. Optimised, because a debug build's timings say nothing about the binary you would ship; frame pointers, because `perf` needs them to unwind and they cost under one percent.
- `-ffast-math` is deliberately absent. It permits floating-point reassociation and sets FTZ/DAZ at startup, which breaks bit-identical replay across builds; -ffp-contract=off is set for the same reason.
- `CLOCK_MONOTONIC` throughout. Never `CLOCK_REALTIME`, which NTP steps, and never `std::chrono::high_resolution_clock`, which on libstdc++ is an alias for `system_clock`, the realtime clock.
- The plant stand-in's clamps are branches on data, but they are perfectly predicted in steady state; the workload's contribution to jitter is negligible either way, and the claim is scoped accordingly.
- Linux only. CMake fails fast elsewhere; functional work on other hosts uses the tvc-dev container.

## Layout

```
CMakeLists.txt
src/
  main.cpp          timing loop, CLI, mitigation switches
  loop_stats.*      histograms, percentiles, CSV and JSON output
  alloc_guard.*     global operator new/delete replacement
  rt_setup.*        mlockall, SCHED_FIFO, CPU affinity
scripts/
  sweep.py          runs the campaign, prints the comparison table
  plot_jitter.py    renders the CDF figure
```
