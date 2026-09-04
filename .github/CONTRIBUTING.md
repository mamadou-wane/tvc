# Contributing

TVC has a single maintainer and is under active development. Bug
reports and focused contributions are welcome. Issues tagged
`good first issue` or `help wanted` are the easiest places to start.

What runs today is the real-time and telemetry foundation: a 500 Hz
C++20 control loop on Linux, a framed CRC-32C telemetry stream drained
off the control cycle, a wire codec in C++ and Python, and an SPSC
ring. The vehicle model, the controller, impaired sensor and actuator
links, episode semantics, and the Python ground station are not
implemented. v0.2a is complete. The project is pre-1.0 and
experimental, so interfaces move without warning.

Do not file a public issue for a vulnerability. Follow
[SECURITY.md](SECURITY.md) instead.

## Propose substantial work before you build it

If the change is any of these, open a feature-proposal issue and wait
for it to be accepted before you write the code:

- a new feature, or new behavior beyond fixing what is already there
- a new dependency, in C++ or Python
- an architecture change: threading, the wire format, the ring, the
  build
- a refactor reaching past the file the change lives in

A pull request that skips this step can be closed unreviewed, however
good the code is. A bug fix with a reproduction needs no proposal.

New dependencies carry a high bar. Say in the proposal what the
dependency does that the standard library and the existing code
cannot, and what it costs at build time and at run time.

## Sending a change

Fork the repository, branch off `main` with one topic per branch, and
open a pull request against `main`. Keep it to that one topic.
Unrelated cleanup you spot along the way goes in its own pull request
or an issue. Mixing it in makes a change hard to review and hard to
revert.

Say in the pull request what changed, why, and what you ran.

## Running the tests

Functional builds and tests run anywhere Docker does:

```bash
docker build -t tvc-dev docker/
docker run --rm -v "$PWD":/w -w /w --cap-add=IPC_LOCK \
  --ulimit memlock=-1:-1 tvc-dev bash tests/ci.sh
```

Run that before you open the pull request. CI runs the same functional
gate on a hosted `ubuntu-latest` runner, inside the same container.

## Timing claims need qualified bare metal

The functional gate proves the code does what it says. It proves
nothing about latency. Hosted runners are Azure VMs, and containers,
virtual machines, and laptops all inject scheduling noise that swamps
the numbers this project publishes. A green CI run is not timing
evidence.

A pull request carrying a timing or performance claim has to state:

- the machine and its configuration, the way
  [docs/qualification.md](../docs/qualification.md) records one
- the method, matching
  [docs/methodology.md](../docs/methodology.md)
- how many cycles the run covered
- where the campaign output and plots live

Published timing evidence comes from qualified bare metal and nowhere
else. Measurements are part of the product here, so a change that
corrupts, mislabels, or weakens one is a critical defect.

## Documentation

Public docs describe implemented behavior. Planned work is allowed in
them as long as the text labels it planned where a reader will see the
label, not two paragraphs later. Published numbers live in
[docs/results.md](../docs/results.md). README.md carries the headline;
everywhere else, link that file rather than restating a figure
somewhere it can drift.

## Review

You are responsible for understanding the change you submit. Use
whatever tools you like to produce it. You still own the result, and
review means answering questions about why a given line is there.

The maintainer may decline work that is correct and well written
because it conflicts with the project's scope or its current
direction. That is a scope call. It says nothing about the code.
