# Documents

Where things are written down. The engineering plan governs; everything else
sits under it.

| Document | What it governs |
|---|---|
| [docs/engineering-plan.md](engineering-plan.md) | project identity, architecture principles, modeling philosophy, evidence policy, capability progression, release dependencies, project invariants |
| [docs/design/v0.2b.md](design/v0.2b.md) | the exact technical contract of v0.2b |
| [docs/adr/](adr/) | consequential architectural decisions; every affected governing document is updated in the same PR, so the committed tree contains one current answer |
| [docs/methodology.md](methodology.md) | how measurements are taken |
| [docs/qualification.md](qualification.md) | the qualified measurement platform |
| [docs/results.md](results.md) | what was observed, with the environment and cycle counts |

## Releases

| Release | Ships | Check |
|---|---|---|
| [v0.1](results.md) | Harness with corrected methodology; qualified ProBook 465 G11; six-level campaign with repeats | A stranger reproduces the README figure from the committed CSVs |
| [v0.2a](results.md#v02a-telemetry-at-no-measured-cost-and-the-c-state-floor) | Framing, CRC-32C, SPSC ring, drain thread; unit tests and sanitizers in CI | Jitter CCDF unchanged with telemetry enabled |
| [v0.2b](design/v0.2b.md) | Simulation, PID, link impairment, ground station, episode machine, latency budget | In design. The design file carries its own acceptance predicate |

Later capability phases live in the engineering plan, not here. Nothing past
v0.2b is scheduled.
