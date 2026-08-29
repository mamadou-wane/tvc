# 2026-08-29: timer migration session

One directory per run, in the order they were taken. Kernel
7.0.0-30-generic, governor and EPP performance, IRQ mask ff3f, AC.
Writeup: docs/results.md, the far tail. Not a gate target: the gate
stays on baselines/2026-08-16-telemetry-campaign until a full campaign
runs under the pinned-timer discipline.

| Dir | Level | Cycles | Idle states off on | timer_migration | Shows |
|---|---|---|---|---|---|
| cpuidle-before | L5 | 15k | no CPU | 1 | acceptance check, env cpuidle disabled 0 |
| cpuidle-after | L5 | 15k | all 16 CPUs | 1 | acceptance check, disabled 16 |
| cpuidle-pair | L5 | 15k | CPUs 6, 7 | 1 | pair-only discipline, tail returns |
| osnoise-A-pair | L6 | 15k | CPUs 6, 7 | 1 | osnoise: 85 us quantum, empty windows |
| timerdiag-mig1 | L5 | 15k | CPUs 6, 7 | 1 | timer on housekeeping CPUs, tail |
| timerdiag-mig0 | L5 | 15k | CPUs 6, 7 | 0 | timer pinned, tail gone |
| osnoise-B-all | L6 | 60k | all 16 CPUs | 1 | v0.2a discipline on 7.0.0-30, 93 LOC on CPU 7 |
| osnoise-C-mig0 | L6 | 300k | CPUs 6, 7 | 0 | ten-minute run, max 78 us |

The osnoise directories carry tail-report.txt (tools/osnoise_tail.py:
late cycles matched to the noise events on CPU 7, thresholds 50, 50,
and 30 us, warmup records skipped), irq-delta.txt (tools/irq_delta.py:
per-IRQ counts that landed on CPUs 6 and 7, with irq 55 and 56 always
printed), ipi-to-cpu7.txt (ipi:ipi_send_cpu filtered to cpu == 7), and
tick-stop.txt (the timer:tick_stop lines). osnoise-C-mig0 also has its
run.log. session-observations.txt holds the console captures no file
above carries. The raw traces (up to 157 MB) and the recordings stay on
the measurement machine.

Regenerate the reports on the measurement machine, where the
recordings and traces live, from the repo root:

    python3 baselines/2026-08-29-timer-migration/tools/osnoise_tail.py <L6.telemetry.tvcrec> <osnoise-cpu7.txt> 30 5000
    python3 baselines/2026-08-29-timer-migration/tools/irq_delta.py <interrupts.before> <interrupts.after> 55,56
