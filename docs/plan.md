# Engineering plan

The governing document is the spec
(superpowers/specs/2026-08-14-tvc-restructure-design.md). This file is the
working summary of what ships when.

## Releases

| Release | Ships | Check |
|---|---|---|
| v0.1 | Harness with corrected methodology; qualified ProBook 465 G11; six-level campaign with repeats; writeup with the CDF at the top of the README; CI lane split | A stranger can reproduce the figure from the README |
| v0.2a | Framing, CRC-32C, SPSC ring, drain thread; unit tests and sanitizers in CI | Jitter CDF unchanged with telemetry enabled |
| v0.2b | Sim, PID, link_sim, ground station, episode state machine, latency budget | Pendulum survives 30% packet loss; GIF in README |
| Stretch | Deterministic replay, then TMR (lockstep, tick-aligned, digest voting) | Replay bit-identity in CI; voter demo |

## Cut order under pressure

Live plotting, then TMR, then replay. Never cut: the jitter campaign, the
methodology, the writeup, the AI log.

## Two modes

Real-time free-run mode produces all published jitter numbers
(single instance, isolated core). Lockstep mode is the deterministic lane:
CI, seed-exact scenarios, replay goldens, TMR. Seed reproduction is
claimed only in lockstep mode; input-log replay is claimed everywhere.

## Measurement rules

Bare metal only for numbers. AC power, masked power daemon, pinned EPP;
firmware stalls checked with hwlatdetect, since the SMI counter is an
Intel-only MSR this machine lacks (see qualification.md). Every
summary.json carries applied config and environment. The corrected draft documents' remaining content (project
overview) moves into the repo with v0.2b, when the system it describes
exists.
