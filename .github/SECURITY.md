# Security policy

TVC is pre-1.0 and experimental. It is not approved for operational
flight and it is not intended for any safety-critical use. Nothing here
has been through hazard analysis or flight qualification. Treat it as a
measurement harness on a workstation.

What exists today is a 500 Hz control loop, a framed CRC-32C telemetry
stream, a wire codec, and an SPSC ring. The vehicle model, the
controller, the impaired sensor and actuator links, episode semantics,
and the ground station are not implemented, so no claim covers them.

## Supported versions

| Version | Status |
| --- | --- |
| main | Actively maintained. Fixes land here first. |
| Tagged releases | No backports unless the advisory says otherwise. |

If you pin a tag, read the advisory before assuming a fix reached you.

## Reporting a vulnerability

Do not open a public issue for a security vulnerability.

Report it through GitHub private vulnerability reporting:
https://github.com/mamadou-wane/tvc/security/advisories/new

That form is the only channel. One maintainer reads the queue, so a
first reply can take days. Silence is not a rejection.

A report the maintainer can act on names:

- the commit SHA or tag it affects
- what breaks, and what an attacker gains if anything: memory
  corruption, a frame that passes a CRC-32C check it should fail
- steps to reproduce, ideally against the container test gate
- the environment: kernel, distribution, CPU, container or bare metal
- any mitigation you already found, even a partial one

Measurements are part of the product. A defect that corrupts or
mislabels a measurement counts as critical here even with no attacker
involved.

## Not a vulnerability

Ordinary correctness bugs and build failures go in the bug report form:
https://github.com/mamadou-wane/tvc/issues/new/choose

Timing numbers measured on a hosted CI runner are meaningless. Those
runners are shared Azure VMs, and a pull request only runs the
functional gate there. A jitter number from one is not a finding.
