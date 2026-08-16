# 0022: v0.2a telemetry design spec

Date: 2026-08-16
PR: #23 (e13d42ad225c435c6bcd05cc0dfd7c5130a049c7)
Agent: Claude Code (Fable 5)
Produced: the v0.2a telemetry spec (frame layout, decoder rules with
defined counters, 56-byte record, recording file header, pinned golden
corpus, C++ ring and drain design, test matrix, five-PR rollout) and
the AGENTS.md clock invariant amendment scoping CLOCK_MONOTONIC-only
to timing math and the control path.
Human: picked every design decision in the brainstorm: file sink,
sweep level L6 as the demo, ground/wire.py as the codec home, plain
assert C++ test executables, POD records through the ring with
drain-side encoding, the epoch-anchor carve-out, and the ubuntu:26.04
container base. Caught that toolchain verification ran on ubuntu:24.04
(the current container base) instead of 26.04, the ProBook OS and
platform of record; the re-run on 26.04 confirmed the same pip
behavior and surfaced the Python 3.12 vs 3.14 skew that motivated the
base bump. Verification environment of record is now Ubuntu 26.04.
Verification: three-agent adversarial review before the PR opened
(internal consistency and byte math, implementability from the spec
alone, repo fit against real code), which caught the cycles+warmup
record count, unpinned corpus inputs, undefined sequence and resync
counters, the guard-scope hook placement, the mkdir ordering, and the
test_sweep.py level-list break. CRC-32C known answers passed two
independent ways: a local table implementation against five standard
vectors, and google-crc32c 1.8.0 in a live ubuntu:26.04 container,
both giving schema_hash 0xA871CD84.
