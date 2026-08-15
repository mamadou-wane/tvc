# Measurement harness

The instrumentation layer for the One-Axis TVC control loop. It runs a fixed-rate cycle, measures how well that cycle holds its deadline, and lets each real-time mitigation be switched on independently so the contribution of each one is measurable in isolation.

Everything is off by default. The default build is the naive loop — that is the point.

```
cmake -S . -B build && cmake --build build -j
./scripts/sweep.py --cpu 3
./scripts/plot_jitter.py --results results
```

HdrHistogram is fetched automatically at configure time; there is nothing else to install.

---

## What it measures

Two quantities, kept apart, because conflating them makes both uninterpretable.

**Wakeup jitter** — the gap between the cycle's intended deadline and the moment the loop actually resumed. This is the platform's contribution: scheduler latency, page faults, interrupts, frequency transitions.

**Execution time** — how long the loop body took once running. This is the code's contribution.

A p99.9 of 8 ms means very different things depending on which of the two produced it, and the fix is different in each case.

### Coordinated omission

Jitter is recorded twice: raw, and corrected.

When one cycle runs long it displaces the cycles behind it. Those displaced cycles never produce a sample, and their absence flatters the tail — the loop looks better precisely when it is behaving worst. HdrHistogram's correction backfills the missing samples against the expected interval.

Both series are written out, and the console prints the ratio between them. On a badly behaved run the corrected p99.9 can be several times the raw figure. That gap is a real result, and being able to explain it is worth more than the number itself.

### Deadline misses

A cycle that finishes after the *next* cycle's deadline was not merely late — a cycle was skipped outright. These are counted separately and never appear in the histogram, because a sample that was never taken should not be invented.

---

## The allocation guard

Global `operator new` and `delete` are replaced. A thread-local depth counter, set by an RAII marker around the cycle body, means heap activity inside the cycle can be counted or made fatal.

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

`--no-naive-log` removes the deliberately allocating telemetry path — a `std::string` built per cycle, which is what a first-draft logger looks like. With it on, the guard reports two allocations and two frees per cycle. That is the thing Phase 01 exists to eliminate.

---

## Host preparation

Numbers from a VM, WSL, or a container are not usable. Virtualised timers and a shared host scheduler add milliseconds of jitter that have nothing to do with your code. Bare metal only.

**Isolate a core.** In `/etc/default/grub`, on `GRUB_CMDLINE_LINUX_DEFAULT`, for a machine where CPU 3 will be the control core:

```
isolcpus=3 nohz_full=3 rcu_nocbs=3
```

Then `sudo update-grub && sudo reboot`. `isolcpus` keeps the general scheduler off that core, `nohz_full` stops the periodic tick on it, and `rcu_nocbs` moves RCU callback work elsewhere.

**Move interrupts away from it.** Stop `irqbalance`, then for each IRQ in `/proc/interrupts`, write a mask excluding CPU 3 to `/proc/irq/N/smp_affinity`.

**Allow real-time priority without root.** In `/etc/security/limits.conf`:

```
@realtime  -  rtprio  99
@realtime  -  memlock unlimited
```

then `sudo groupadd realtime && sudo usermod -aG realtime $USER` and log back in. Running the harness under `sudo` works too, but changes the environment you are measuring.

**Fix the clock for the duration of a benchmark.** `cpupower frequency-set -g performance` and `cpupower idle-set -D 0` remove frequency and C-state transitions. Both cost power — measure that cost and report it rather than quietly leaving them off.

---

## The campaign

`scripts/sweep.py` runs six levels, each adding exactly one mitigation to the previous one, so any difference between adjacent runs is attributable to a single change.

| | Adds |
|---|---|
| L0 | baseline: `sleep_for`, allocating telemetry path |
| L1 | absolute deadlines — `clock_nanosleep(CLOCK_MONOTONIC, TIMER_ABSTIME)` |
| L2 | `mlockall` plus pre-faulted stack and heap |
| L3 | `SCHED_FIFO` priority 80 |
| L4 | pinned to the isolated core |
| L5 | allocation-free hot path, guard set to `abort` |

Deadlines derive from a single origin — `origin + n × period` — never from `now + period`. The latter lets error accumulate silently and is the most common bug in fixed-rate loops.

Priority 80 rather than 99 leaves headroom above the loop for kernel threads. At 99 a runaway loop competes with the machinery keeping the system alive, and the machine stops responding.

Expect L1 and L4 to produce the largest single improvements. If L3 makes things *worse*, the loop is not pinned yet and `SCHED_FIFO` is fighting the rest of the system for a shared core — that is L4's job.

Run each level long enough for the tail to be real. At 500 Hz, 300,000 cycles is ten minutes, which puts roughly 300 samples beyond p99.9. Fewer than that and the figure is noise.

---

## Output

Per run, into `--out`:

```
L3.jitter_raw.csv          percentile sweep, microseconds
L3.jitter_corrected.csv    same, coordinated-omission corrected
L3.exec.csv                loop body execution time
L3.summary.json            config and key percentiles
```

`plot_jitter.py` renders all runs in a directory as a complementary CDF — x is jitter, y is the fraction of cycles worse than that value, log on both axes so the tail gets space proportional to how much it matters. A linear-y CDF compresses everything interesting into the top two percent of the plot, which is why latency work uses this form.

`--corrected` plots the compensated series. Publish both.

---

## Notes

- The build uses `-O2 -g -fno-omit-frame-pointer`. Optimised, because a debug build's timings say nothing about the binary you would ship; frame pointers, because `perf` needs them to unwind and they cost under one percent.
- `-ffast-math` is deliberately absent. It permits floating-point reassociation, which breaks the bit-identical agreement the Phase 03 voter depends on.
- `CLOCK_MONOTONIC` throughout. Never `CLOCK_REALTIME`, which NTP steps, and never `std::chrono::high_resolution_clock`, which on libstdc++ is an alias for `system_clock` — the realtime clock.
- The plant model is a stand-in with a fixed trip count and no data-dependent branching, so measured jitter is the platform's and not the workload's.

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
