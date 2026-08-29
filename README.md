# One-Axis TVC

A hard real-time control and telemetry stack: a 500 Hz C++20 control loop on
Linux, measured as a latency distribution, with a Python ground station,
simulation, and fault injection to follow.

![Wakeup jitter CCDF under the pinned-timer discipline](docs/jitter-pinned.svg)

**p99.9 wakeup jitter: 16.5 microseconds at 500 Hz, worst cycle 86 us
over 2.7 million pinned cycles**, on a stock Ubuntu generic kernel with
one core isolated, its idle states off, and the loop's wakeup timer
pinned to it, with **per-cycle telemetry enabled at 5 percent cost**
(17.3 against 16.5 us at p99.9, zero ring drops). Two earlier numbers
on the same code: 88.4 us with C-states left on (v0.1), 7.5 us with all
sixteen threads polling at 25 W (v0.2a). Both were set by the
housekeeping cores. nohz_full had moved the loop's wakeup timer onto
them, so their idle exits were the tail, including the 300 to 1,000 us
events beyond p99.99 that the 7.5 us configuration kept. Pinning the
timer removes them with two cores awake, and costs the median: 12.7 us
against 3.6. The naive baseline drifts whole seconds off schedule and
cannot see it in its own measurement. Seven mitigations, applied one at
a time, each measured in isolation: [docs/results.md](docs/results.md).

Status: v0.2a complete: wire codec in both languages against a pinned
golden corpus, SPSC ring with a TSan-verified drop path, drain thread,
and the campaign above. Next: the v0.2b ground station, and the
PREEMPT_RT rematch with the timer pinned.

## Layout

    src/         control-cycle timing harness (C++20)
    scripts/     campaign runner, plotting, regression gate
    baselines/   committed campaign data the gate diffs against
    tests/       functional and unit tests (container-run for C++)
    docs/        results, methodology, qualification, plan, ADRs, AI log
      results.md       the campaign, level by level
      methodology.md   measurement methodology
      qualification.md measured platform record
      plan.md          release plan

## Build and test

Measurement runs happen on bare-metal Linux only. Functional builds and
tests run anywhere Docker does:

    docker build -t tvc-dev docker/
    docker run --rm -v "$PWD":/w -w /w --cap-add=IPC_LOCK \
      --ulimit memlock=-1:-1 tvc-dev bash tests/ci.sh
