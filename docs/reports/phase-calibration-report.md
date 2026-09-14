# Phase-offset calibration: no qualifying offset

Date: 2026-09-14

## Summary

None of the three tested phase offsets met the predeclared latency limits. The
measurements showed that the free-run schedule placed approximately one
additional 2 ms control period inside the sensor-to-actuator path: subtracting
the phase offset from each run's p99.9 served latency leaves 1973 to 1985 us at
every offset. Coverage, integrity and machine discipline passed on all nine
runs. The experiment was valid and complete. Its result is that the schedule, not
the machine, set the latency floor. The architectural correction
that followed is [ADR-002](../adr/002-freerun-phase-alignment.md).

## Experiment

**Question.** Which of 200, 400 or 800 us is the smallest phase offset whose
three runs all satisfy the predeclared coverage, integrity and latency
criteria?

**Machine.** HP ProBook 465 G11, kernel 7.0.0-30-generic, CPUs 6 and 7 isolated
(`isolcpus=domain,managed_irq,6,7 nohz_full=6,7 rcu_nocbs=6,7`), control loop
pinned to CPU 7, on AC, under the pinned-timer configuration described in the
[platform qualification record](../qualification.md): performance governor and energy
preference, IRQ mask `ff3f`, idle states disabled on CPUs 6 and 7 only,
`timer_migration=0`. The configuration was verified before the first run and
is recorded in every run's summary.

**Source.** Commit `83f38a113f8ee12f9e5a961ba547f27c8e01b148`, implementation
source identity `f11e2bf2023c9ed5aff06ad31a5e9a9ff51a1edd0d241dd371c248f37501b633`,
g++ 15.2.0.

**Design, fixed before the first run.**

| element | value |
|---|---|
| phase grid | 200, 400, 800 us, no extension after results |
| runs | three per offset, nine total, interleaved `for repeat: for offset` |
| run length | 300,000 recorded cycles after 5,000 warmup cycles at 500 Hz |
| peer | S1-hold scenario, seed 1, zero modeled loss, 305,033 ticks, no explicit actuator delay |
| selection | smallest offset whose three runs all pass every criterion below |
| criteria | served coverage >= 0.99 per run and median >= 0.995 per offset; zero recorded actuator send failures; zero unexplained missing traffic in either direction; terminal agreement with every required leg complete; zero malformed ingress; served latency p99.9 <= 1000 us and max <= 2000 us; machine-discipline predicate clean |

A run counts as void only when the machine discipline fails, the mode is wrong,
or an interruption or artifact failure prevents a complete measurement. A
completed run that fails a criterion is an outcome and is not repeated.

**Procedure.** One invocation of `scripts/sweep.py --cpu 7 --rate 500
--cycles 300000 --repeat 3 --interleave --only L8 --phase-us 200,400,800`,
from a shell with the full CPU affinity mask, without elevated privileges,
13:32 to 15:06 local time. Selection by `scripts/latency.py --calibration`
over the nine summaries, reconciliation records and recordings. Machine
observations captured before, during and after: interrupt counts per CPU,
package temperature, timer placement samples.

## Results

| run | served coverage | p99.9 (us) | max (us) | p99.9 minus phase (us) |
|---|---|---|---|---|
| phase 200, run 1 | 0.999993 | 2183.17 | 2420.74 | 1983.17 |
| phase 400, run 1 | 0.999987 | 2379.78 | 2459.65 | 1979.78 |
| phase 800, run 1 | 0.999997 | 2783.23 | 2889.73 | 1983.23 |
| phase 200, run 2 | 0.999953 | 2181.12 | 2299.90 | 1981.12 |
| phase 400, run 2 | 0.999987 | 2379.78 | 2459.65 | 1979.78 |
| phase 800, run 2 | 0.999997 | 2785.28 | 2902.01 | 1985.28 |
| phase 200, run 3 | 0.999990 | 2185.22 | 2277.38 | 1985.22 |
| phase 400, run 3 | 0.999957 | 2373.63 | 2453.50 | 1973.63 |
| phase 800, run 3 | 0.999983 | 2772.99 | 2871.30 | 1972.99 |

Median served coverage: 0.999990 at 200 us, 0.999987 at 400 us, 0.999997 at
800 us. Every run recorded zero actuator send failures, zero missed deadlines,
zero unexplained missing traffic, zero malformed frames, terminal agreement
with the required legs complete, and a clean discipline predicate. Wakeup
jitter p99.9 was 10 to 12 us. The analyzer reported `no offset qualifies` and
exited 1; the only failing criteria were the two latency limits, on all nine
runs.

Served p50 was about 2084 to 2142 us at 200 us, 2290 to 2294 us at 400 us and
2689 to 2699 us at 800 us. The p99.9 values move with the phase at slope one
(2380 - 2183 = 197; 2783 - 2380 = 403).

An independent recomputation of the selection rule from the per-run fields
reproduced the medians and verdicts exactly.

## Analysis

Under the schedule in force, the simulator ran body `k` at `sim_origin + k * P`
and sent observation `k + 1` immediately after. The vehicle woke for cycle `n`
at `sim_origin + t0 + phase + n * P` and consumed observation `n`, which had
been produced at body `n - 1`, one period plus the phase earlier; observation
`n + 1` was already parked in the vehicle's future ring. With `t0` the prologue
transport, `c` the vehicle compute time and `lag` the simulator's wake-plus-step
time,

    served latency = P + phase + t0 + c - lag

The predeclared limit p99.9 <= 1000 us would require `phase + t0 + c - lag`
to be below -1000 us, which no positive phase can satisfy. The measured
intercept of about 1980 us is `P` less the simulator's lag tail.

The same structure appears in a development-container recording of the same
code at phase 400: the observation a cycle consumed had been sent a median
2115 us before the cycle's deadline, while the next observation had been sent
115 us before it. That measurement is not timing evidence; it corroborates the
mechanism.

The experiment therefore falsified the assumption behind the latency limits,
that served latency at the qualified machine is the phase plus small residuals.
It also showed that under this schedule coverage does not depend on the phase:
every offset exceeded 0.99995, because a frame had a full period to arrive.
The schedule change that resolves this is recorded in
[ADR-002](../adr/002-freerun-phase-alignment.md). This calibration is not
re-analyzed under the corrected schedule; selecting a phase requires a new
experiment.

## Observations and limitations

Package temperature read 46 C before the discipline was applied and 69.6 to
73.9 C during the runs. Two brief spikes, 92.8 C and 81.6 C on single reads,
occurred at run boundaries and were back to 73 C within 16 s. Their cause was
not determined; no load or power telemetry was captured at those moments.

CPU 7 recorded about 3.1 local timer interrupts per control cycle during the
sampled interval, above the earlier harness rate of about 2 per cycle. The
additional interrupts were not traced.

Two of three timer-placement samples showed the loop's wakeup timer on CPU 7
on the 2 ms grid; the third sample fell between arming points. The two NVMe
queues whose affinity includes the isolated pair delivered no interrupts during
the session.

The terminal handshake's downlink leg reads `unresolved` on every run: of
twelve terminal copies the vehicle sends, seven left the socket and five failed
locally after the simulator had already exited, with the first copy delivered.
The reconciliation rules classify this as an answered handshake with an
unresolved trailing residual, which is not a failure criterion. The same
signature appears in development runs of the same code.

The served endpoint runs from the simulator's send stamp to the vehicle's local
send completion. It contains neither downlink transport nor the simulator's
scheduling, so nothing in this report bounds when a command reached the
simulator.

## Evidence

The nine-run raw population, 150 files and 3.15 GB including full sensor and
control recordings, simulator reports, timing series and logs, is retained
outside the repository on the measurement machine. It is too large to publish,
so the complete recording-level analysis cannot be reproduced from this
repository alone.

An inventory written at the end of the session records SHA-256 values for the
retained artifacts. Its self-entry is invalid because it was computed while
the inventory was still being written; the remaining hashes have not been
independently rechecked.

The report is based on the run summaries, reconciliation records, analyzer
output and session captures; the full raw recordings remain outside the
repository.

Measurement definitions: [methodology](../methodology.md). Platform record:
[qualification](../qualification.md). Selection rule:
[scripts/latency.py](../../scripts/latency.py). Discipline predicate:
[scripts/bench_gate.py](../../scripts/bench_gate.py).
