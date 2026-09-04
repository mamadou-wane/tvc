# Security policy

TVC is pre-1.0 and experimental. It is not approved for operational
flight and it is not intended for any safety-critical use. Nothing here
has been through hazard analysis or flight qualification. Treat it as a
measurement harness on a workstation.

## Supported versions

| Version | Status |
| --- | --- |
| main | Actively maintained. Fixes land here first. |
| Tagged releases | No backports unless the advisory says otherwise. |

If you pin a tag, read the advisory before assuming a fix reached you.

## Reporting a vulnerability

Do not open a public issue for a security vulnerability.

Report privately when crafted or untrusted input can compromise memory
safety, confidentiality, integrity, availability, or the
trustworthiness of recorded evidence.

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

## Not a vulnerability

A correctness defect in a measurement, a decoder, a recording, or an
analysis script that carries no security impact is a high-priority
correctness bug, not a vulnerability. It belongs in the bug report
form, along with ordinary build failures:
https://github.com/mamadou-wane/tvc/issues/new/choose

Timing measured on a GitHub-hosted runner is diagnostic only and not
accepted as published timing evidence. A pull request runs the
functional gate there and nothing else, so a jitter number from one is
not a finding.
