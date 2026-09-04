# TVC engineering plan

This file governs project identity, architecture principles, modeling
philosophy, evidence policy, capability progression, release dependencies, and
the project invariants. It is the highest project-level authority in this
repository. A release design gives one release's exact technical contract; this
file says what every release holds true.

## What TVC is

TVC is a deterministic and real-time flight-control simulation and verification
system for thrust-vector-controlled vehicles: a vehicle model, a controller, an
actuator boundary, a sensor boundary, impairable links between them, and the
evidence machinery that says what a run proves.

Thrust-vector-controlled vehicles are the subject, and every capability below
stays organized around them. Higher fidelity, Monte Carlo, optimization, GPU
propagation, system identification, and independent validation deepen that
subject. None of them turns this into a general flight-simulation framework, and
a proposal that only makes sense for some other vehicle class is out of scope.

It runs in three modes:

- **lockstep**: the deterministic lane. The simulation owns the clock, the
  vehicle reads none, and the run's **declared semantic and golden artifacts**
  are a pure function of model version, scenario, seed, resolved parameters,
  backend and toolchain: they reproduce byte for byte. The release design names
  that artifact set exactly. Transport retry diagnostics sit outside it, because
  a kernel-forced resend moves them and nothing else; a release may bring them
  inside by canonicalizing them. Source of CI correctness, replay goldens,
  seed-exact reproduction, and any future TMR voting. It produces no timing
  evidence.
- **freerun**: the real-time closed-loop lane. Simulation and vehicle each hold
  their own 500 Hz schedule on CLOCK_MONOTONIC. Source of every closed-loop
  timing number, on qualified bare metal only.
- **harness**: the fixed open-loop measurement workload behind the published
  L0 through L6 campaign, unchanged in workload and in the outputs a
  committed compatibility fixture pins. It is the published wakeup-jitter lane
  and it extends to L7.

Those three are the whole runtime mode enum. A binary emits `harness`,
`lockstep` or `freerun` and nothing else. `harness (legacy)` is not a fourth
mode: it is the gate's compatibility classification for committed baseline
summaries that predate the `mode` field, and it exists only inside the analysis
scripts.

The qualifying condition for a published number is the machine and its applied
configuration. The `mode` field says which workload produced it: `harness` for
L0 through L7, `freerun` for L8.

The vehicle model today is reduced order and one axis: the current fidelity, not
the identity. Fidelity rises in versioned steps, and each step leaves older
evidence readable under the identifier it was recorded with.

"Survives 30% packet loss" is one release acceptance campaign: a predeclared
deterministic scenario set with independent Bernoulli loss on both directions, a
seed range, and a written predicate. It is not the project's identity and not a
reliability guarantee.

What exists today: the corrected wakeup-jitter methodology and the qualified
ProBook record (v0.1), the wire format, CRC-32C, SPSC ring and drain thread
(v0.2a), and the pinned-timer campaign that is the configuration of record.
v0.2b is designed in `docs/design/v0.2b.md` and not implemented.

## Why the architecture is shaped this way

One rule sets the shape: the mathematical plant stays callable without UDP,
files, wall-clock scheduling, the ground station, or process orchestration. A
model step stays separable as

```
next_truth = plant.step(truth, applied_actuator, environment, disturbance, dt)
```

Real-time socket-connected execution is one consumer of the simulation and
control components. A later headless campaign runner must run thousands of
independent simulations in one process, with no vehicle process and no UDP
topology per simulation, so any design that makes sockets the only simulation
API is refused at review.

The conceptual flow stays distinct at every fidelity. Some stages are idealized
without being merged away:

```
truth state
  -> sensor model
  -> observation
  -> impaired sensor link
  -> controller
  -> requested actuator command
  -> impaired command link
  -> actuator model
  -> applied actuator state
  -> plant
```

Nine boundaries carry that flow. Interfaces stay narrow and concrete with
explicit units: no plugin framework, no model registry, no dynamic dispatch
before a second implementation exists.

| Rule | How the current release implements it | It protects |
|---|---|---|
| Truth state is not sensor observation. | The simulation holds `(theta, omega)` as truth; the sensor model produces a separate observation, equal in value, and only the observation reaches the link. | Quantization, bias, noise, asynchronous sampling, and state estimation, none of which can be added if the controller reads truth. |
| A requested actuator command is not applied actuator state. | The controller emits a requested gimbal angle; the actuator model produces the applied angle the plant integrates, and both are recorded. | First- and second-order actuator dynamics, rate and stop limits, actuator fault injection. |
| Plant dynamics are not actuator dynamics. | The actuator model is a separate function called before integration; the plant takes an applied angle and knows nothing about how it was produced. | Replacing the actuator with a sourced model without touching plant integration, controller interfaces, or the scenario schema. |
| Environmental effects are not scheduled test disturbances. | The environment supplies the constant flight condition behind the aerodynamic term; the scenario's gust schedule is a separate tick-indexed torque with its own field. | Atmosphere, wind, and aerodynamic models arriving as environment versions without rewriting scenarios. |
| Controller logic is not plant integration. | The controller is a pure function of observation and controller state, in C++ with a bit-exact Python reference, sharing no state with the integrator. | Controller candidates, optimization populations, model-in-the-loop comparison. |
| Deterministic logical time is not wall-clock scheduling. | Lockstep advances on tick index with zero timestamps in hashed artifacts; free-run derives deadlines from `origin + n * period_ns` and logical time from `tick_base + n`. | Replay, goldens, and running a scenario faster or slower than real time without changing its result. |
| The physical model is not transport or process orchestration. | The simulation package computes plant, actuator, sensor, link, and scenario with no socket in the call path; the runner and the sockets sit above it. | Batch campaigns, CPU parallelism, any future GPU propagation. |
| Model payload versions are not the outer wire framing. | Framing v1 (sync, version, type, length, CRC-32C, one frame per datagram) is fixed; each payload type carries its own schema string and hash. | Adding and revising payloads without invalidating the frame corpus or the telemetry stream. |
| A deterministic scenario instance is not campaign generation. | A scenario file names resolved values; a seed selects the loss sequence. | Uncertainty distributions sampled outside the plant and resolved into concrete run parameters, recorded per run. |

## Modeling philosophy

Reduced order first. A model earns fidelity when a claim needs it, not because
higher fidelity sounds better. A one-axis rigid-body pitch model at a frozen
flight condition is enough to state and test a closed-loop control claim under
link impairment, so that is what the current release carries.

Every model, controller, actuator, sensor, and environment carries an explicit
identifier and version. Raising fidelity creates a new version or a new
identifier; it never redefines an old one.

No unsupported fidelity claims. Describe the model as what it is, state its
coordinate frame, sign conventions, and the approximation under which angle of
attack reduces to the modeled pitch error. A pure slew-rate limit is a
slew-rate limit, never a "first-order actuator."

Parameter provenance is written down. A coefficient derived from physical inputs
lists them (density, airspeed, reference area, normal-force slope, center of
pressure, center of gravity, moment arm). A value chosen to make a demonstration
work is labelled a synthetic design parameter in the table where it appears.
Reduced order is acceptable; an unlabelled synthetic number presented as vehicle
data is not. Dimensional consistency is checked at review: units on both sides
of every equation, and no coefficient in N*m/rad multiplied by a dimensionless
function without the model that justifies it.

## Source of truth

| Rank | Document | Governs | May not claim |
|---|---|---|---|
| 1 | `docs/engineering-plan.md` | project identity, architecture principles, modeling philosophy, evidence policy, capability progression, release dependencies, project invariants | the exact contract of one release: no wire offsets, no gains, no thresholds |
| 2 | `docs/design/<release>.md` | the exact technical contract of that release: equations, parameters, wire layouts, recurrences, predicates, proof gates | anything that contradicts rank 1, and anything about another release |
| 3 | tracked ADRs, `docs/adr/001-*.md` onward | consequential architectural decisions, with context and consequences | anything that contradicts rank 1; measurement results, because an ADR records a decision, not evidence |
| 4 | `docs/methodology.md` | measurement methodology and procedure | which platform is qualified, and what the numbers were |
| 5 | `docs/qualification.md` | qualification of measurement environments | methodology, and results |
| 6 | `docs/results.md` | observations and evidence, with the environment and cycle counts they came from | architecture, contracts, or thresholds; it reports, it does not define |
| 7 | `README.md` | a summary and an entry point | anything stronger than the governing documents; no number that is not in `docs/results.md` |

Precedence: this file is the highest project-level authority, and an accepted
ADR does not override it. An ADR records one consequential architectural
decision with its context and consequences. When that decision changes a release
contract, the affected release design is edited in the same PR that accepts the
ADR, so the committed tree holds one current answer and no reader has to rank two
documents that disagree. A tracked ADR that contradicts a release design is a
defect in the PR that landed it, not a precedence rule. `docs/plan.md` is a
navigation index. No public document points at an ignored or unavailable
governing document, and capability 1's proof gate in `docs/design/v0.2b.md`
enforces that mechanically over every tracked markdown file.

Tracked ADRs are numbered from 001. Number 000 is permanently reserved by an
untracked internal document that governs how agents divide work on this
repository. It decides development process, not architecture, so it sits outside
this hierarchy and overrides nothing in it. No tracked document may cite it.

## Evidence policy

Every technical claim names the evidence class that supports it. One class never
implies another.

**Tier 1, exact deterministic evidence.** Bit identity is asserted and proved by
a digest. The current release puts here: wire encoding and the frame corpus, the
RNG known-answer tables, controller arithmetic in the fixed operation order,
episode state-machine transitions, and the fixed-backend lockstep goldens (same
toolchain, with image digest and ISA recorded), including the per-run
trajectories and digests of every run in the loss campaign.

**Tier 2, numerical equivalence within declared tolerances.** A tolerance and a
derived metric are declared before the comparison. The current release ships
nothing here and names one boundary: cross-ISA comparison of vehicle-side
goldens is tier 2, which is why that claim is same-toolchain while the sim-side
claim is cross-platform on the no-libm condition. Higher-fidelity plants,
MATLAB/Simulink validation, and CPU versus GPU propagation land here.

**Tier 3, statistical reproducibility.** Seeds, resolved parameters, model
versions, backend and hardware, sample counts, distributions, and aggregate
metrics are recorded, and the experiment reproduces from them. The current
release puts here: the loss campaign's pass rate read as a statement about 30%
loss, the paired L7/L8 timing comparison, and every percentile in
`docs/results.md`.

The loss campaign is split deliberately across two tiers. Each run reproduces
bit for bit from its committed seed, which is tier 1. The pass rate over the
predeclared seed range is a statistical result about 30% loss, which is tier 3
and is not a bound on every 30% loss sequence. Public wording carries both.

Language rule for percentiles, everywhere including the README, plot captions,
and commit messages: a percentile is an observation over a stated cycle count in
a stated environment. Write "p99.9 observed 16.5 us over 2.7M cycles". Never
"worst case", never "guarantee" anywhere near a percentile, never a percentile
with no denominator.

Claims published before this policy carry no tier label. `docs/results.md`'s
pre-v0.2b sections are grandfathered: re-labelling them would edit historical
claims, which the modeling invariant forbids. A claim that survives an edit
acquires a tier.

## Reproducibility contract

Every stochastic experiment records enough to re-run itself. Six fields, all
present or the run is not published:

| Field | Where it lives |
|---|---|
| model version | `replay.json` and `summary.json`, as the identifier set below |
| scenario version | scenario id plus `scenario_sha256` of the file bytes |
| seed | `seed`, u64 |
| named RNG streams | `rng.streams`: name keying index, resolved 64-bit start state, final state, and draw count |
| resolved parameter values | the full parameter block as used, not as requested |
| backend and toolchain | container image digest, compiler string, `env.machine` ISA, and for a timing run the qualified kernel and applied configuration |

The identifiers ride once per run in `<label>.replay.json` and `summary.json`,
not in every record: the control record is fixed width and the hot path writes
no identity strings. The recording header stays version 1 with its
`schema_hash` (`ground/wire.py:28`), its reserved u16 at offset 10 zero and
available to a future header version carrying a run id. For v0.2b and later
closed-loop or stochastic evidence, a recording without its matching
`replay.json` is unidentified and is not published. Historical v0.1 and v0.2a
artifacts predate the file and the stochastic contract it records, and they keep
the evidence contracts under which they were recorded.

### Identifier grammar

`<word>(-<word>)*-v<integer>`, lowercase ASCII, hyphen separated, ending in `-v`
and a decimal integer with no leading zero. No dots, no `_`, no dates. Six
categories:

| Category | What the identifier names | Current instance |
|---|---|---|
| model | plant equations, state variables, integrator, units, sign conventions | `pitch-frozen-flight-v1` |
| controller | controller form, gains, limits, operation order, anti-windup rule | `pid-v1` |
| actuator | requested-to-applied mapping and its limits | `ideal-angle-v1` |
| sensor | truth-to-observation mapping and its rejection rules | `ideal-v1` |
| environment | the constant flight condition supplying the aerodynamic term | `frozen-flight-v1` |
| scenario schema | the field set and validation of a scenario file | `tvc-scenario-v1` |

The right column illustrates the grammar. `docs/design/v0.2b.md` is the contract
that binds each instance to its equations, values, and limits, and a later
release's design names its own. The actuator ships as `ideal-angle-v1`: PHY-1 is
closed in `docs/design/v0.2b.md`, which carries the probe that settles it and
the cost of the alternative. What this file fixes is the consequence: replacing
an actuator model is a version change under this grammar, not an architecture
change.

### What bumps a version

| Subject | Bump when | Do not bump for |
|---|---|---|
| model | equations, operation order, integrator, state vector, parameter values, units, or sign conventions change | a refactor the goldens prove output-identical |
| controller | form, gains, limits, operation order, filter, or anti-windup rule change | renaming a variable or splitting a function |
| actuator | the requested-to-applied mapping or its limits change | a new call site |
| sensor | the truth-to-observation mapping or a rejection rule changes | a counter or diagnostic added beside it |
| environment | the flight condition or any coefficient derived from it changes | a comment on its provenance |
| scenario schema | a field is added, removed, retyped, or given new meaning; validation tightens in a way that rejects an existing file | a new scenario file under the same schema |
| wire payload (`<name>_v<N>`) | the field set, order, offsets, sizes, endianness, or a field's meaning changes, which is exactly when the schema string and its CRC-32C change; and any change an older decoder would read incorrectly, including redefining a bit that already carried meaning | assigning meaning to a bit the payload already declares reserved, a forward-compatible semantic extension that leaves the layout, schema string and hash untouched and that a conforming older decoder ignores; adding a new type beside it |
| recording schema | the file's type set changes, which changes the file schema hash; or the 32-byte header layout changes, which bumps the header version | appending records of a type the header already declares |

A change to the same concept bumps the integer. A different concept takes a new
name: `planar-3dof-v1` is not `pitch-frozen-flight-v2`. Identifiers are never
reused and never edited after the fact, so evidence recorded under `pid-v1`
keeps saying `pid-v1`. Historical evidence keeps the identifiers it was recorded
with, and a re-run under new identifiers is a new result beside the old one,
never a replacement of it.

### Named RNG streams

Stream identity is part of the reproducibility contract. A result whose stream
identities are not recorded cannot be re-derived and is not published. A stream
name is lowercase ASCII, dot separated, `<category>[.<qualifier>]*`, and appears
in exactly that spelling in code, in `replay.json`, and in every test key. Each
name has a fixed index that is never reassigned:

| Index | Name | Category |
|---|---|---|
| 0 | `link.loss.up` | sensor-direction link loss |
| 1 | `link.loss.down` | actuator-direction link loss |
| 2 | `sensor.noise` | sensor noise |
| 3 | `actuator.fault` | actuator fault |
| 4 | `environment.disturbance` | environmental disturbance |
| 5 | `parameter.sampling` | parameter sampling |
| 6 | `scenario` | scenario stochasticity |

The table is append-only. A release instantiates the streams its features read
and no others, names them in `replay.json`, and takes no placeholder draws for
the rest; the release design says which. Only the simulation draws, and the
vehicle contains no RNG.

Adding a stream never shifts an existing stream's sequence, because seeding is
index-derived: a stream's start state is a function of the master seed and its
own index alone, so a stream that did not exist yesterday cannot consume a draw
that belonged to another, and cross-stream draw order does not enter any single
stream's sequence. `docs/design/v0.2b.md` states the derivation as it is coded.

`tests/unit/test_rng.py` asserts the property rather than leaving it to this
document: the eight-draw prefixes of indices 0 through 3 are identical whether a
run instantiates four streams or all seven, and across masters 1 to 64 and all
seven indices the eight-draw prefixes are distinct with no shifted-window
aliases.

Two practices keep it true. Append a new stream at the next free index and never
renumber. Never let one stream's draw count depend on another stream's outcome.
Within a stream, draws are unconditional per packet event: an override such as a
blackout window or a loss start tick takes its draw and then changes the
outcome, so the stream's position stays a function of its own draw count.

## Project invariants

Future releases and agents do not silently violate these. Each carries the test
a reviewer applies to a diff.

**Measurement.** Published timing evidence comes only from qualified bare-metal
execution under the applied configuration of record. Containers, hosted CI,
lockstep runs, Macs, and development machines prove function and produce no
publishable timing claim. Closed-loop timing evidence, meaning served
sensor-to-actuator latency, discard age, and anything measured at L8, comes only
from a free-run run; the harness workload is the published open-loop
wakeup-jitter lane.
*Test: every published timing number traces to a summary whose mode is
`harness` or `freerun`, taken on the qualified bare-metal machine, that the discipline gate
accepts; a lockstep summary, a container or hosted-CI summary, a Mac summary, or
a summary with no mode outside a committed `baselines/` directory fails it. A
committed baseline summary that predates the `mode` field classifies as
`harness (legacy)` and is admitted as `harness`; that classification lives in
the gate, never in a binary. A closed-loop timing claim fails unless that
summary's mode is `freerun`.*

**Determinism.** Lockstep is the authoritative lane for deterministic scenarios,
CI correctness, seed-exact reproduction, replay goldens, regression, and TMR.
*Test: every seed-reproduction or golden-identity claim names a lockstep run;
no such claim cites a free-run run.*

**Benchmark history.** Historical benchmark levels keep their original workload
and meaning; new capability never redefines what an existing row measured.
*Test: the L0 through L6 rows in `scripts/sweep.py` keep their labels and flags,
and the harness workload reproduces its committed compatibility fixture. The
fixture is a behavioral pin, not a line-range pin: it compares the deterministic
`tick`, `theta` and `cmd` columns of a fixed-length run byte for byte and
compares nothing that is intentionally nondeterministic, so timestamps, jitter,
execution times and drop counts are outside it. A behavior-preserving extraction
that moves those source lines passes; a diff that changes a column fails unless
it adds a new level number.*

**Modeling.** Increasing physical fidelity creates an explicit new model version
or configuration. Historical evidence is never reinterpreted under changed
equations, parameters, actuator, sensor, or environmental behavior.
*Test: re-running an archived scenario under its recorded identifiers reproduces
the archived digests; if it cannot, an identifier should have been bumped.*

**Simulation kernel.** Plant propagation stays usable independently of UDP,
filesystem I/O, wall-clock scheduling, ground-station behavior, and process
orchestration.
*Test: a unit test steps the plant and the reference controller to completion
with no socket, no file, and no clock read in the call path.*

**Control path.** The control path stays understandable, deterministic where
claimed, measurable, and auditable. Offline optimization, ML, GPU compute,
uncertainty sampling, and Monte Carlo infrastructure never enter the hot path
because they exist elsewhere in the project.
The nonblocking rule is scoped by mode, because one mode makes no timing claim.
`harness` and `freerun` obey it: their control cycle is the measured hot path.
`lockstep` may block on the synchronization receive that defines its
transaction, because it produces no timing evidence and the gate refuses its
summaries as timing evidence; that receive stays structurally outside
`run_freerun`, in the lockstep translation unit, so no timing lane can reach it.
The absolute-deadline sleep at the cycle boundary is the scheduling boundary of a
real-time cycle, not blocking work inside the measured path.
*Test: in `harness` and `freerun` the control cycle contains no allocation, lock,
or formatted I/O, and no blocking syscall. Nonblocking receive and send on the
sensor and actuator sockets, CLOCK_MONOTONIC reads, and the absolute-deadline
sleep at the cycle boundary are the only syscalls in it, and no call into
optimization, sampling, or learned-model code appears. The allocation guard in
abort mode passes and the nonblocking checker passes, and the checker asserts
that the lockstep receive appears in no free-run or harness path.*

**Evidence.** Every technical claim states its evidence class: exact identity,
numerical equivalence within declared tolerances, or statistical
reproducibility. One class never implies another.
*Test: every claim added or edited by the diff names its tier, and no tier-3
result is worded as tier-1 identity. Claims predating this policy carry no tier
label and are not re-labelled retroactively.*

**Reproducibility.** Every stochastic experiment makes its stochastic contract
inspectable: model version, scenario version, seed, named RNG streams, resolved
parameter values, and backend or toolchain where relevant.
*Test: for v0.2b and later closed-loop or stochastic evidence, `replay.json`
carries all six fields and a re-run from those fields reproduces the digests it
names. Historical v0.1 and v0.2a artifacts are not held to it.*

**Scope.** New complexity materially improves at least one of physical fidelity,
control fidelity, verification quality, reproducibility, runtime evidence, or
engineering capability. Nothing is added to make the project look broader.
*Test: the PR body names which one and the evidence that it improved; "it is
standard practice" is not an answer.*

## Capability progression

Phases are capability boundaries, not a schedule. Nothing past Phase II is
authorized by this document.

**Phase I, real-time foundation. Done.** Corrected wakeup-jitter methodology,
qualified bare-metal measurement, the seven-mitigation campaign, pinned-timer
discipline, allocation-free hot path, wire format and CRC-32C, SPSC telemetry,
sanitizers, benchmark gates, and the evidence discipline this file formalizes.

**Phase II, closed-loop simulation. v0.2b establishes it.** The reduced-order
one-axis truth model, the controller, the actuator and sensor boundaries,
deterministic lockstep, free-run closed-loop execution, impaired sensor and
actuator links, stale-data behavior, episode semantics, ground tooling,
sensor-to-actuator latency, and a deterministic acceptance campaign. It is where
the identifier set, the stream policy, and the evidence tiers first apply to a
shipped release.

**Phase III, vehicle-model fidelity.** Planar translation and rotation, gravity,
changing mass and inertia, center-of-gravity motion, center-of-pressure effects,
trajectory state, atmosphere, wind, aerodynamic force and moment models, sourced
actuator dynamics, sensor quantization, bias, noise and asynchronous sampling,
state estimation. Six-DOF is this phase's destination, not its next step.

**Phase IV, verification at scale.** Uncertainty distributions, deterministic
fault matrices, Monte Carlo campaigns, robustness envelopes, sensitivity
analysis, parameter sweeps, and CPU-parallel campaigns.

**Phase V, independent model validation.** A MATLAB/Simulink reference plant and
where useful a reference controller, model-in-the-loop comparison, trajectory
and controller-output comparison, saturation and event comparison, numerical
error characterization, software-in-the-loop. None of it is bit identical, so
all of it is tier-2 evidence.

Independent validation needs a stable model of record, not a higher-fidelity
one, so it may begin as soon as Phase II ships one. The first validation target
may be the v0.2b one-axis model: matched equations and parameters, matched
initial conditions, matched controller, matched disturbances, then a comparison
of trajectory, actuator command, saturation and event points, and episode
outcome, under declared numerical tolerances. Later model versions repeat that
comparison and deepen it. Nothing here waits on Phase III.

**Phase VI, accelerated engineering.** Vectorized state propagation, batched
simulation, GPU-parallel propagation, CUDA, large candidate-controller
populations, controller-parameter and trajectory optimization. Entered only when
ordinary CPU execution is a measured bottleneck, with the measurement published
first.

**Phase VII, offline data-driven modeling.** Mass and inertia estimation,
aerodynamic and actuator parameter identification, telemetry-driven system
identification, residual-dynamics learning, surrogate models for expensive
campaign regions. Learned models and optimizers support analysis and generate
candidates; deterministic simulation and declared acceptance predicates remain
the verification authority, and none of it enters the control path.

### Release dependencies

| Phase | Needs | Produces |
|---|---|---|
| I | qualified machine, measurement methodology | jitter and execution methodology, mitigation campaign, framing and CRC, SPSC telemetry, benchmark gates |
| II | I: framing, gates, evidence discipline | model, controller, actuator and sensor identifiers, lockstep lane, free-run closed loop, link impairment, episode semantics, s2a latency, acceptance campaign |
| III | II: the truth, actuator, and environment boundaries; model versioning; goldens | higher-fidelity model versions, sensor models, estimation |
| IV | II: scenario schema, headless kernel, stream reservations; III: a model worth sampling | campaigns, fault matrices, robustness envelopes |
| V | II: a stable model of record; tier-2 tolerance policy. III is not a prerequisite | independent validation and numerical error characterization |
| VI | IV: campaign runner; a measured CPU bottleneck | batched and GPU propagation, optimization populations |
| VII | IV: campaign data; V: validated reference | parameter estimation, residual models, surrogates, none in the hot path |

## What this plan does not authorize

Nothing beyond the scope in the current release design. v0.2b stays deliberately
reduced order and one axis: not a planar or six-DOF simulator, not a CUDA
implementation, not an ML system, not a MATLAB/Simulink implementation, and no
plugin framework, model registry, or abstraction layer built for capabilities no
shipped release uses.

Implementation begins when the owner approves this file and the release design
and the issues exist. Branch names carry the issue number GitHub assigns; no
number is invented in advance.
