# 2026-09-15: free-run phase-offset calibration (PHASE-1)

Calibration evidence, not release-campaign evidence. These nine runs fix
one parameter, the free-run phase offset, under a rule frozen before the
first run; they make no timing claim and are never a gate baseline.
Writeup: docs/results.md, free-run phase calibration.

Selected offset: 400 us. Grid 200, 400, 800 us; three interleaved runs
of 300,000 recorded cycles (5,000 warmup) per offset at 500 Hz, L8,
S1-hold peer at zero loss, `--peer-cpu 11`. Rule: every run served
coverage at or above 0.99, median coverage per offset at or above 0.995,
zero actuator send failures, reconciliation and integrity valid, zero
malformed traffic, no unexplained missing traffic, served latency p99.9
at or below 1000 us and max at or below 2000 us, complete qualified
discipline; smallest qualifying offset wins. 200 us fails on every run by
the 2000 us maximum (2102 to 2146 us); 400 and 800 qualify; 400 is the
smallest. No threshold, grid entry, run count or ordering changed after a
result was seen; no run was repeated; no run was void.

Machine and discipline: HP ProBook 465 G11, kernel 7.0.0-30-generic,
isolcpus=domain,managed_irq,6,7, vehicle on CPU 7 under SCHED_FIFO 80,
peer on CPU 11 under SCHED_OTHER, idle states off on CPUs 6, 7 and 11
(every summary's env block reads disabled 3), governor and EPP
performance, IRQ mask ff3f, timer_migration 0, AC. Source identity
0294935f67fc7ea62de83689f2eb3d50009a7dae6c2e71f7242c22b60c7300fd, built
from main 91869099b5740fdac925d2e2e042f5cc0d25339f.

Attempt history. Two earlier attempts on 2026-09-14 were valid and
selected no offset: the first under the pre-ADR-002 simulator schedule
(served latency structurally one period plus the phase), the second under
ADR-002 with the peer undisciplined (its housekeeping idle exit set the
coverage). Neither is a void attempt; both stay retained on the
measurement machine and are not committed. This is the third attempt and
the first under the peer-discipline contract.

Files, with the names the sweep and analyzer wrote:

| File | What it is |
|---|---|
| sweep.json | roster of the nine runs in execution order, with peer provenance |
| L8.phase*.r*.summary.json | per-run summary written by the vehicle |
| L8.phase*.r*.result.json | per-run process result as recorded in the roster |
| L8.phase*.r*.reconcile.json | per-run reconciliation of recorded against transported traffic |
| calibration.json | exact stdout of `scripts/latency.py --results ... --calibration` |
| session-observations.txt | pre-run verification block, peer placement, timer_list samples |
| irq-delta.txt | per-IRQ deltas on CPUs 6 and 7 across the session, irq 55 and 56 always printed |
| interrupts-before.txt, interrupts-after.txt | the /proc/interrupts snapshots the deltas came from |
| temp-during.txt | package temperature at session start, middle and end |
| sweep-console.log | the sweep's stdout and stderr |
| raw-inventory.txt | SHA-256 of every retained raw artifact, sealed after the last run |
| raw-sizes.txt | byte size of every file in that sealed population, listed read-only after the seal |
| redactions.txt | the twelve public files that are redacted derivatives, with sealed and published hashes |

Redacted derivatives. Twelve of these files (the nine result records,
sweep.json, sweep-console.log and session-observations.txt) carry the
measurement machine's absolute home path in recorded command lines. The
public copies replace the exact prefix `/home/wane` with `/home/<user>`
and change nothing else; they are deterministic derivatives of the sealed
originals and therefore intentionally do not hash-identically to them.
redactions.txt lists each file with its sealed-original and published-copy
SHA-256; reversing the substitution reproduces the sealed hash. Every
other file is byte-identical to its sealed original.

What is not here. The raw evidence (control and input recordings, replay
metadata with the simulator report, timing series, peer and vehicle logs,
about 3.16 GB) stays on the measurement machine under
results/2026-09-15-phase-cal-peer-disciplined and is bound by
raw-inventory.txt: 159 files, 3,159,770,488 bytes (3,159,785,680 with the
inventory itself), sealed after the last run and hash-verified; the
inventory covers the analyzer, recomputation and diagnostic outputs
written before the seal as well as the recordings. Git alone is not sufficient to rerun the
raw-recording analysis; `bench_gate.candidate_rows` cannot load this
directory as an L8 results set. Two analysis helpers (an independent
recomputation and a diagnostics script) were added to the retained
directory after the seal; they are not part of the sealed raw population
and are not committed.

Non-gating observations from the same runs, recorded without a cause
being assigned: vehicle wakeup p99.9 17.6 to 18.3 us on every row; the
first 400 us run's served p50 was 496 us against 395 to 400 us on the
other two, with its p99.9 and max inside the budget.
