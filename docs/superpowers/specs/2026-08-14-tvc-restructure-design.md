# One-Axis TVC restructure design

Date: 2026-08-14
Status: approved in discussion, pending review of this document
Superseded 2026-08-29 on attribution: commit trailers are allowed, and
AGENTS.md and CLAUDE.md are untracked. The rest stands as the record of
the 2026-08-14 decisions.

## What this is

The validated design for the One-Axis TVC project after the 2026-08-14 stress test (103 findings, 7 confirmed blockers; report artifact "TVC Draft Stress Test"). It replaces the phasing and several claims of the two Desktop drafts. The drafts' technical spine survives: a 500 Hz C++20 control loop on real-time-tuned Linux, measured as a latency distribution, with a Python ground station, simulation, fault injection, and stretch goals of replay and triple modular redundancy.

## Goals

1. A systems engineering artifact whose headline is a defensible p99.9 wakeup-jitter distribution with per-mitigation attribution.
2. A provable AI-augmented workflow: Claude Code and OpenAI Codex working under a documented protocol, with evidence a hiring manager can audit from the founding commit.

The second goal never leads. The repo, README, and resume present the latency result first and the process record one level down.

## Hardware and platform

| Machine | Role |
|---|---|
| HP ProBook 465 G11 (A1RM8UT#ABA), Ryzen 7 7735U, 8c/16t, 16 GB | Only measurement lane. Ubuntu 24.04 LTS, bare metal. |
| MacBook Pro M4 | Functional lane: Python sim, ground station, unit tests, plots, docs. Vehicle C++ builds its portable core here with clang; the RT shell is Linux-only. |

Platform rules, all recorded in the methodology:

- Isolate a full SMT sibling pair for the control core (verify with `lscpu --all --extended` and `thread_siblings_list`; on this part core N typically pairs with N+8), or boot `nosmt`. Never a lone CPU index.
- Benchmarks on AC only; power-profiles-daemon masked for runs; `amd_pstate` EPP pinned; per-run frequency, package temperature, and SMI counter logged into `summary.json`.
- Qualify the box before the first published number: one hour of `hwlatdetect`, SMI counts per run via `turbostat`.
- `prctl(PR_SET_TIMERSLACK, 1)` set unconditionally so the SCHED_FIFO step measures policy, not slack removal.
- Kernel and preemption model recorded with every figure. A PREEMPT_RT comparison axis (Ubuntu Pro real-time kernel, free personal tier) is attempted in v0.1 and moves to v0.1.1 if it threatens the date.

## Repo shape

One public monorepo, `tvc`, at `~/projects/tvc`. MIT license.

```
src/            vehicle C++ (grows out of the measurement harness)
scripts/        sweep.py, plot_jitter.py, bench-gate
sim/            plant + link_sim (Python, v0.2b)
ground/         ground station (Python, v0.2b)
docs/plan.md    the engineering plan
docs/adr/       ADRs, starting with ADR-000 agent roles
docs/ai-log/    one entry per merged PR
AGENTS.md       shared agent instructions (build, RT invariants, review protocol)
CLAUDE.md       thin Claude-specific layer pointing at AGENTS.md
```

The harness is the vehicle skeleton, not a side tool: the measured loop and the flight loop are the same code path, so published numbers always describe the real loop. The harness lands as a reviewed PR series (stats, alloc guard, rt_setup, sweep/plot), never as one large initial commit.

## AI collaboration policy

- Roles (ADR-000): Codex implements well-specified, testable subtasks (codecs, plot scripts, schema work). Claude Code handles RT-sensitive C++ and reviews Codex output; the reverse review direction is not used (arXiv 2607.21656 found it lowers pass rates). The human reviews everything and owns every merge.
- Attribution: commit subjects stay clean, no trailers. Every PR description carries a structured AI-assistance section (agent, scope, what was human-modified). This is a deliberate project-level carve-out from the global no-attribution rule, recorded in the project CLAUDE.md.
- Log: `docs/ai-log/NNNN-slug.md`, written at merge time, about ten lines: date, task, agent and model, what the agent produced, what the human changed or rejected and why, verification performed, merge SHA. Entry 0001 covers the pre-repo planning sessions, including the stress test and this design.
- Writeup rule: for each campaign fix and each bug found, record what the agent proposed, what the human suspected, and what the measurement said. Two or three full transcripts are curated for flagship stories only.
- Resume numbers come from measurements and countable process facts. No invented speed-up percentages.

## System design corrections

These fix the falsified claims from the stress test and bind future work.

- Two modes. Real-time free-run mode produces all jitter numbers (single vehicle instance, isolated core). Lockstep mode (sim advances a tick only after consuming the vehicle response) is the deterministic lane for CI, seed-exact scenarios, replay goldens, and TMR. Seed reproduction is claimed only in lockstep mode; input-log replay of the vehicle binary is claimed everywhere.
- Tick alignment. The sim stamps every sensor frame with a tick number; nodes consume by tick, not arrival. Staleness is `current_tick - newest_consumed_tick`. Commands carry an effective-at tick with margin for retries and are part of the replay record, along with seeds, config hash, build ID, and initial state.
- Coordinated omission. The harness is CO-free by construction (every cycle measured against `origin + n * period`); the corrected series is removed from headline output. A deliberately naive demo mode shows what CO looks like for the writeup.
- Measurement integrity. Failed mitigations exit nonzero; `summary.json` records applied config, not requested; sweep stops the campaign when a level is skipped; repeats with spread reported; topology and environment metadata in every summary.
- Control path. The rule is "no blocking or shared-queue I/O on the hot path": nonblocking `recvmsg`/`sendto` on sensor and actuator sockets, measured inside the exec histogram; telemetry only through the SPSC ring (drop-newest on full, drop counter published in-stream).
- Latency budget. A stated sensor-to-actuator budget, measured as a third distribution; the PID is tuned against the budgeted delay.
- Episode lifecycle. States: init, armed, flying, terminated(stabilized | loss-of-control | aborted), with a recorded reason code. Degradation on stale sensors: brief coast on last command, then gimbal neutral, then loss-of-control termination. There is no recoverable safe state for this plant and the docs say so.
- TMR, when reached (stretch): lockstep or tick-aligned functional mode only, no isolation claims; voter buckets by tick with a fixed vote budget; nodes emit a CRC-32C state digest alongside the command so clamp-masked divergence is caught; honest fault model (tolerates a single vehicle-process fault; voter, host, and kernel are trusted; identical binaries make logic bugs common-mode). Ejection is permanent for a run.
- Numerics. `-ffp-contract=off`; no `-ffast-math` (rationale: cross-build replay reproducibility and FTZ/DAZ, not voter agreement); replay goldens are same-toolchain (pinned container) or CI-generated; a fixed polynomial sine in vehicle code is the preferred long-term fix.
- Wire spec (v0.2a): little-endian, CRC-32C (Castagnoli; Python side uses google-crc32c, never `zlib.crc32`) over everything after the sync word, max frame 512 bytes, u32 sequence with wraparound rule, version-mismatch behavior defined, one frame per datagram. Recording files carry a header: magic, format version, schema hash, start timestamps. Command uplink is at-least-once with sequence dedupe on the vehicle; ack carries the applied sequence.
- Tests and CI. Hosted CI: build, ASan/UBSan, unit tests (CRC known-answer both languages, frame round-trip with truncation and corruption, cross-language golden corpus, SPSC stress under TSan, staleness and episode state machines), lockstep sim suite, replay bit-identity. Jitter gate: `make bench-gate` on the ProBook against committed baselines; never on hosted runners. No self-hosted runner on the public repo.

## Release plan

v0.1 target: ~3 weeks from start (early September 2026). Each release is independently citable.

| Release | Ships | Check |
|---|---|---|
| Founding | Repo with AGENTS.md, CLAUDE.md, LICENSE, README skeleton with Working with AI section, ai-log entry 0001 | Files present at commit 1 |
| v0.1 week 1 | Harness fixes per stress test (CO removal, prefault rewrite, genuinely naive L0, sweep chain-break, strict exits, applied-config, slack, metadata) landed as PR series; SKU already confirmed | PRs green under ASan/UBSan; unprivileged sweep behaves correctly |
| v0.1 week 2 | Ubuntu 24.04 on the ProBook; sibling-pair isolation; qualification report | Topology map, hwlat and SMI numbers committed |
| v0.1 week 3 | Campaign with repeats; writeup; CDF at top of README; CI lane split; PREEMPT_RT axis if it fits | Published CDF; a stranger can follow the README |
| v0.2a | Framing, CRC-32C, SPSC ring, drain thread, unit tests and sanitizers | Jitter CDF unchanged with telemetry enabled |
| v0.2b | Sim, PID, link_sim, ground station, episode machine, latency budget | Pendulum survives 30% loss; GIF in README |
| Stretch | Deterministic replay first, then TMR (lockstep, tick-aligned, digest voting) | Replay bit-identity in CI; voter demo |

Cut order under pressure: live plotting (post-hoc plots instead), TMR, replay. Replay outlives TMR. The cut list contains only scheduled work; the schema compiler is not on it because it is not on the critical path. Never cut: the jitter campaign, the methodology, the writeup, the AI log.

## Draft document corrections

When the overview and plan move into the repo: corrected CO framing; seed-vs-replay claims split; TMR rescoped with the honest fault model; "software-in-the-loop", not "hardware-in-the-loop"; the nondeterminism list rewritten with per-item mechanisms; safe mode replaced by the episode machine; the 100 µs p99.9 target marked provisional until measured on this machine; FIFO-80 rationale rewritten around RT throttling; hardware prerequisite section rewritten for the actual two machines.

## Non-goals

Unchanged from the overview: PID only, one axis, no certification posture, simulated plant. Added: no schema compiler before v0.2b ships; no node readmission protocol (ejection is permanent, stated in an ADR); no AI speed-up metrics anywhere.

## Consequences

The 3-week v0.1 date is protected by dropping the PREEMPT_RT axis and anything else that slips, so v0.1 may ship with a thinner campaign than the draft imagined. Tick alignment adds a small amount of protocol machinery to the sim and vehicle before TMR exists to need it; the cost is paid early so the lockstep lane works from v0.2b. PR-body disclosure makes some PR descriptions longer and puts a documentation obligation on every merge; skipping the ritual breaks the evidence chain, which is the point.
