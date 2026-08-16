# v0.2a telemetry design

Date: 2026-08-16. Status: approved for implementation.
Parent: 2026-08-14-tvc-restructure-design.md, which fixes the wire rules
(little-endian, CRC-32C Castagnoli, max frame 512 bytes, u32 sequence,
one frame per datagram) but no byte layout. This document is the byte
layout, the C++ and Python components, the tests, and the rollout.

## What ships

Framing, CRC-32C, SPSC ring, drain thread, unit tests and sanitizers.
Acceptance: jitter CDF unchanged with telemetry enabled, quantified in
"Campaign" below.

## Decisions

- Sink is a recording file. UDP transport waits for the v0.2b ground
  station; frame type codes for command and ack are reserved now.
- The ring carries fixed-size POD records. The drain thread does all
  framing, CRC, and file I/O. The hot path does one memcpy and one
  release store.
- The demo is sweep level L6 (`--telemetry`), cumulative on L5, so the
  L5/L6 pair isolates telemetry exactly.
- Python codec lives in `ground/wire.py`, starting the directory the
  v0.2b ground station builds around.
- C++ tests are plain assert executables, no framework.
- The recording header carries one CLOCK_REALTIME read, taken in main
  before the loop starts. AGENTS.md's clock invariant is reworded to
  scope it to timing math and the control path (see "Invariant
  amendment").

## Frame layout

All multi-byte fields little-endian. The sync word is the u16 0xEB90,
so the first two bytes on the wire are 0x90 0xEB. Fixed offsets:

| offset | size | field   | value / rule                                  |
|--------|------|---------|-----------------------------------------------|
| 0      | 2    | sync    | 0xEB90                                        |
| 2      | 1    | version | 1                                             |
| 3      | 1    | type    | 1 = telemetry record; 2 = command, 3 = ack (reserved, v0.2b) |
| 4      | 2    | length  | payload byte count, 0 to 498                  |
| 6      | 4    | seq     | u32, +1 per frame, wraps mod 2^32             |
| 10     | len  | payload |                                               |
| 10+len | 4    | crc     | CRC-32C over bytes 2 through 9+len            |

Total frame = 14 + length bytes; the 512-byte max frame caps length at
498. CRC-32C is the Castagnoli polynomial 0x1EDC6F41, reflected, init
0xFFFFFFFF, final xor 0xFFFFFFFF: the value google-crc32c computes. The
CRC covers everything after the sync word: version, type, length, seq,
payload. It is stored little-endian like every other field.

## Decoder rules

The v0.2a decoder operates on a complete buffer (read_recording reads
the whole file); incremental feeding is out of scope.

Frame validity, checked in this order at a sync match: version == 1,
type in {1, 2, 3}, length <= 498, at least 14 + length bytes remain,
CRC matches. A frame passing all five is valid; only valid frames are
yielded.

Counters:

- frames_ok: valid frames, all types.
- crc_errors: candidates that reached the CRC check and failed it.
- version_mismatch: candidates whose version byte is not 1. The
  version is checked first, immediately after the sync match, so the
  decoder never trusts an unknown version's length field. Corrupted
  regions can inflate this counter; accepted.
- resyncs: loss-of-lock events. The decoder is locked at buffer start
  and after each valid frame. The first validation failure while
  locked counts one resync; further failures during the same scan do
  not. Version mismatches follow the same rule and additionally count
  version_mismatch.
- seq_discontinuities: see the sequence rule.
- lost: frames inferred missing, per the sequence rule.
- skipped_bytes: every byte not consumed by a valid frame, including
  the unconsumed tail.

Scan rule: on any validation failure, advance one byte and rescan for
the sync pattern. End of input: when a sync match's frame would extend
past the buffer, stop scanning; the remaining bytes count toward
skipped_bytes only (no crc_error, no resync), since truncation and
awaiting-more-data are indistinguishable.

Sequence rule: expected starts unset; the first valid frame adopts its
seq with no gap counted. After a valid frame with sequence s, expected
becomes (s + 1) mod 2^32. Invalid bytes never advance expected, so a
corrupted frame's seq is not consumed and surfaces as a gap at the
next valid frame. For each valid frame, gap = (seq - expected) mod
2^32. A gap in [1, 2^31) adds gap to lost. A gap of 2^31 or more is a
discontinuity: adopt the new seq, add one to seq_discontinuities, add
nothing to lost.

## Telemetry record (type 1, version 1)

Payload is exactly 56 bytes, seven 8-byte fields, no padding:

| field       | type | meaning                                          |
|-------------|------|--------------------------------------------------|
| tick        | u64  | cycle index n, from 0, warmup included           |
| deadline_ns | i64  | origin + n * period, CLOCK_MONOTONIC             |
| woke_ns     | i64  | wakeup timestamp                                 |
| done_ns     | i64  | cycle-end timestamp                              |
| theta       | f64  | plant angle after step                           |
| cmd         | f64  | last actuator command                            |
| drops       | u64  | cumulative try_push failures before this record  |

Jitter and exec time derive as woke_ns - deadline_ns (may be negative:
early wakeup) and done_ns - woke_ns. The drops field is the in-stream
drop counter the parent spec requires. Every loop iteration produces a
record, warmup included: main.cpp runs cycles + warmup iterations, so
a clean run's recording holds cycles + warmup records, and tick makes
warmup filterable offline. Python struct format: `<QqqqddQ`.

Canonical schema string, ASCII, no trailing newline:

    telemetry_v1:tick:u64,deadline_ns:i64,woke_ns:i64,done_ns:i64,theta:f64,cmd:f64,drops:u64

schema_hash = CRC-32C of that string = 0xA871CD84. Both
implementations hardcode this value as a known answer (computed here
with a CRC-32C implementation that passes all five known answers
below; google-crc32c must agree or the Python tests fail).

## Recording file

Extension `.tvcrec`, path `<outdir>/<label>.telemetry.tvcrec`. A
32-byte header, then frames back to back, no footer. Mid-frame
truncation is detectable (the final partial frame fails validation);
truncation on an exact frame boundary is not detectable from the file
alone and is caught by cross-checking summary.json's records count,
which the functional test does.

| offset | size | field             | value / rule                        |
|--------|------|-------------------|-------------------------------------|
| 0      | 8    | magic             | ASCII "TVCRECRD"                    |
| 8      | 2    | version           | 1, equals the wire version          |
| 10     | 2    | reserved          | 0                                   |
| 12     | 4    | schema_hash       | 0xA871CD84                          |
| 16     | 8    | start_monotonic_ns| CLOCK_MONOTONIC at file open        |
| 24     | 8    | start_epoch_ns    | CLOCK_REALTIME at file open         |

Both timestamps are read by main at file open, before the control loop
starts, off the hot path. A decoder refuses a file whose magic or
version it does not recognize, and reports (not refuses) a schema_hash
it does not know.

## C++ components

New files `src/telemetry.hpp` and `src/telemetry.cpp`, namespace
`telem`. `main.cpp` gains the flag, the file open, the thread start,
and the hook. The ring and drain exist only when `--telemetry` is set;
L0 through L5 behavior is byte-for-byte unchanged.

Record: the 56-byte struct above, `static_assert` on
`sizeof(Record) == 56` and `std::is_trivially_copyable_v`.

CRC-32C: hand-rolled byte-wise table, constexpr-generated, in
telemetry.cpp. Drain-side only, so throughput is irrelevant; the known
answers and the corpus pin correctness. No new dependency.

SPSC ring:
- 4096 slots of Record, compile-time constant, about 224 KB, allocated
  before the loop so mlockall(MCL_FUTURE) covers it. 4096 slots is
  about 8 seconds of buffer at 500 Hz.
- head and tail are `std::atomic<uint64_t>`, monotonically increasing,
  indexed by mask, each `alignas(64)` on its own cache line.
- try_push (control thread): check fullness against a cached tail;
  refresh the cache with one acquire load if apparently full; if still
  full, increment a producer-owned plain u64 drop counter and return
  false. Otherwise copy the record into the slot and
  `head.store(head + 1, release)`. No allocation, no syscall, no CAS,
  no wait.
- pop (drain thread): `head.load(acquire)`, copy out up to a batch
  limit, `tail.store(release)`.
- Policy is drop-newest. The reject path is one comparison, cheaper
  than the accept path.

Startup ordering in main, when `--telemetry` is set:
1. Create the output directory (today main.cpp mkdirs it only after
   the loop; the telemetry path needs it at startup, so main mkdirs
   before the file open; the post-loop mkdir stays and tolerates
   EEXIST as it does now).
2. Open the recording file and write the header (both header
   timestamps read here). Failure is synchronous and is a failed
   mitigation: telemetry recorded as not applied, exit 2. This
   happens before applied_json is assembled, so the result feeds it
   naturally.
3. Spawn the drain thread with the open FILE*.
4. Only then apply rt setup (`set_fifo_priority`, `pin_to_cpu`). Those
   act on the calling thread only, so the drain inherits SCHED_OTHER
   and the default affinity mask; isolcpus keeps that mask off CPUs 6
   and 7. No per-thread scheduling API is added.

Drain thread loop: batch-pop up to 512 records, wrap each in a frame
(seq assigned here, starting at 0, so a healthy recording is gapless;
ring losses surface through the in-stream drops field), CRC, buffered
fwrite; sleep 1 ms via clock_nanosleep between batches. The alloc
guard's violation flag is thread_local, so the drain may allocate and
do formatted I/O freely; only the control thread is policed. This is
the case alloc_guard.hpp anticipated.

Shutdown: after the loop, main sets a stop flag; the drain empties the
ring, flushes, closes the file, and joins. A write failure in the
drain sets an error flag that main turns into exit 4 after the loop;
the run is not publishable.

Hook in main.cpp: after `done = now_ns()`, so all three timestamps are
final, open a second `guard::Cycle` scope (the existing scope closes
before done is taken; Cycle is two integer ops, so a second scope per
iteration is cheap) and inside it build the Record on the stack and
try_push. Under L6 the guard runs in abort mode, so the runtime itself
proves the push never allocates. Telemetry adds no timing math and
does not touch deadline computation.

Flag and reporting: `--telemetry` enables the path. config_string()
appends "telemetry" so L5 and L6 rows are distinguishable in the sweep
table and summaries. The `applied` dict gains a `telemetry` key when
requested, following the existing requested-and-applied semantics
(verify the exact row_problem contract at implementation).
summary.json gains `"telemetry": {"records": N, "dropped": N,
"bytes": N}` where records counts frames written to the file (equal to
cycles + warmup on a clean run), dropped counts try_push failures, and
bytes is the final file size.

## Python codec

`ground/wire.py`, with an empty `ground/__init__.py`. Tests insert the
repo root into sys.path and use `from ground import wire`; the CLI is
run from the repo root as `python3 -m ground.wire <file>`. Surface:

- `crc32c(data: bytes) -> int`, backed by google-crc32c. Never
  zlib.crc32; the import error message says how to install.
- `SYNC`, `VERSION`, `TYPE_TELEMETRY`, `SCHEMA`, `SCHEMA_HASH`
  constants.
- `encode_frame(ftype, seq, payload) -> bytes`. Raises ValueError when
  len(payload) > 498 or ftype is not in {1, 2, 3}; seq is taken mod
  2^32.
- `decode_stream(data: bytes) -> (frames, counters)`: frames is a
  list of (ftype, seq, payload) tuples, valid frames only, all types;
  counters is a dict with exactly the seven decoder-rule keys
  (frames_ok, crc_errors, version_mismatch, resyncs,
  seq_discontinuities, lost, skipped_bytes).
- `pack_record` / `unpack_record` for the 56-byte payload; unpack
  returns a namedtuple with the seven field names.
- `read_recording(path)` returning (header, records, counters).
  Raises ValueError on unknown magic or version. header is a dict of
  the five header fields plus schema_known (bool). records is the
  unpacked namedtuples from type-1 frames, in file order; a CRC-valid
  type-1 frame whose payload is not 56 bytes raises ValueError (that
  is an encoder bug and must be loud). Other valid types count in
  frames_ok but produce no record.
- A CLI printing one key=value line per counter plus records=N, used
  by hand; the functional test imports the module instead of parsing
  CLI output.

## Golden corpus

`tests/golden/`: checked-in binary files plus manifest.json, all
produced by `tests/golden/generate.py` from ground/wire.py. Every
input is pinned so any two correct implementations produce identical
bytes.

Record formula, record(n): tick = n, deadline_ns = 1000000000 +
2000000 * n, woke_ns = deadline_ns + 12800, done_ns = woke_ns + 18700,
theta = n * 0.125, cmd = n * -0.25, drops = 0. All values are exact in
binary.

| file                 | contents                                        |
|----------------------|-------------------------------------------------|
| frame_record.bin     | type 1, seq 0, record(0)                        |
| frame_empty.bin      | type 2, seq 1, empty payload                    |
| frame_max.bin        | type 3, seq 2, payload = (bytes(range(256)) * 2)[:498] |
| frames_seqwrap.bin   | type 1 seq 0xFFFFFFFF record(0), then type 1 seq 0 record(1) |
| frame_badcrc.bin     | type 1, seq 3, record(3), final byte XOR 0xFF   |
| frame_truncated.bin  | type 1, seq 4, record(4), first 30 bytes only   |
| recording_mini.tvcrec| header, then six type-1 frames seq 0..5 with record(0)..record(5); the seq-2 frame's final byte XOR 0xFF |

The mini recording's header uses fixed constants: start_monotonic_ns =
1000000000, start_epoch_ns = 1755000000000000000. Intended decode
results (manifest.json is authoritative; a disagreement at
implementation time is a spec bug to raise): frames_seqwrap decodes
with frames_ok = 2 and lost = 0 (the second frame's gap is 0 after the
wrap); frame_badcrc with crc_errors = 1, resyncs = 1, skipped_bytes =
70; frame_truncated with skipped_bytes = 30 and all else 0; the mini
recording with frames_ok = 5, crc_errors = 1, resyncs = 1, lost = 1.

manifest.json shape: top level {"schema_hash": "0xA871CD84", "files":
[...]}; each entry {file, description, roundtrip (bool), expect:
{the seven counter keys}}. generate.py writes it with
json.dumps(indent=2, sort_keys=True) plus a trailing newline and must
be byte-stable on regeneration.

## Tests

C++ (`tests/cpp/`, plain main() + assert, two CMake targets):
- `wire_tests`: CRC-32C known answers ("123456789" gives 0xE3069283,
  the standard check value; from RFC 3720 appendix B.4: 32 zero bytes
  give 0x8A9136AA, 32 0xFF bytes give 0x62A8AB43, bytes 0x00..0x1F
  give 0x46DD794E, bytes 0x1F..0x00 give 0x113FDB5C), the schema_hash
  known answer 0xA871CD84, frame round-trip, truncation at every byte
  boundary, a corruption sweep (flip each byte in turn; every flip
  must fail validation), sequence gap rule cases including the
  0xFFFFFFFF to 0 wrap and a discontinuity, and corpus verification:
  for roundtrip files, decode, re-encode, compare byte-exact; for the
  rest, assert the counters in the manifest.
- `ring_stress`: producer thread and consumer thread, at least two
  million records with randomized consumer stalls; asserts FIFO order,
  no torn records (fields are correlated so tearing is detectable),
  and exact accounting: pushed + dropped == attempted, popped ==
  pushed.

tests/ci.sh grows a third tree, build-tsan, with `-fsanitize=thread`,
building and running ring_stress. Both test binaries also build and
run in the normal and ASan trees.

Python (`tests/unit/test_wire.py`): the same known answers computed
via google-crc32c (independently hardcoded; duplication is the point
of a known-answer test), round-trip, truncation and corruption, the
gap rule, recording header parse, corpus verification as above, and a
byte-stability case: run generate.py into a temp dir and byte-compare
every file plus manifest.json against the checked-in corpus.

Functional (`tests/functional/test_telemetry.py`): short run with
`--telemetry` (existing pattern: --rate=1000 --cycles=2000
--warmup=100), decode with ground.wire, assert a valid header, record
count equal to cycles + warmup, count of records with tick >= warmup
equal to cycles, gapless seq, zero CRC errors, zero drops, and a
summary.json telemetry block that matches the file. A telemetry-off
run asserts no recording appears.

Toolchain: docker/Dockerfile adds python3-pip via apt and then
`pip3 install --break-system-packages google-crc32c` (ubuntu:24.04's
system Python is PEP 668 externally managed, so plain pip3 fails the
image build; the apt package python3-crc32c is a different module and
is not a substitute). The native unit-test lane on macOS installs the
same wheel with a normal pip install.

## Campaign

sweep.py appends `("L6", "+ telemetry ring + drain", ["--telemetry"])`,
cumulative on L5, preserving one change per adjacent pair. bench_gate's
`{level}*` glob does not collide ("L6" does not prefix-match "L5").
tests/unit/test_sweep.py pins the expected level chain and must be
extended to include L6 in the same PR.

Acceptance, two checks on a fresh L0-L6 x 3-repeat campaign on the
ProBook:
1. L6 median p99.9 within 10% of L5 median in the same campaign.
2. The existing L5 gate passes against baselines/2026-08-15-campaign-2.

The figure is the L5/L6 CCDF overlay, which plot_jitter.py already
produces from one results directory. The campaign lands as a new
baselines/ entry including L6, and docs/results.md gets a v0.2a
section.

Prerequisite: the ProBook is still on the PREEMPT_RT kernel from the
one-shot grub-reboot. Reboot to generic (the config of record) and
reapply runtime discipline (governor, EPP, cpuidle, IRQ affinity)
before the gated run.

## Rollout

Five PRs, each small, each with the AI-assistance section, each
followed by an ai-log entry (next number 0022):

1. This spec plus the AGENTS.md invariant amendment. Claude Code.
2. Codex's first PR per ADR-000: ground/wire.py + __init__.py,
   tests/unit/test_wire.py, tests/golden/ with generate.py, Dockerfile
   pip + google-crc32c. Claude Code reviews by running the tests.
   Prerequisite: Codex CLI verified on this machine (ai-log 0007).
3. src/telemetry.{hpp,cpp} (record, CRC, encoder, ring), tests/cpp/
   both targets, CMake wiring, ci.sh TSan tree. Claude Code. Consumes
   the corpus from PR 2.
4. Drain thread, main.cpp integration (mkdir/open/spawn ordering,
   hook, --telemetry, config_string, summary block), sweep L6,
   tests/unit/test_sweep.py update, test_telemetry.py. Claude Code.
5. Campaign results: baselines, figure, results.md addendum. Human-run
   measurement on the ProBook.

PRs 2 through 4 are sequential by dependency and may stack; head-branch
auto-delete keeps stacked PRs retargeting on merge.

## Invariant amendment

AGENTS.md currently reads "CLOCK_MONOTONIC only. Never CLOCK_REALTIME,
never std::chrono::high_resolution_clock." It becomes:

    All timing math and the control path use CLOCK_MONOTONIC only.
    Never std::chrono::high_resolution_clock. One CLOCK_REALTIME read
    is allowed off the hot path to date a recording file header.

## Non-goals

- UDP transport, command uplink, and acks: frame types reserved,
  implementation is v0.2b.
- Live plotting (first cut per the parent spec) and the schema
  compiler (explicitly not before v0.2b).
- Replay integration; recordings are forward-compatible with it via
  tick stamps but replay stays out of v0.2a.
- Incremental (feed-style) decoding; the v0.2a decoder takes complete
  buffers.

## Consequences

- The harness gains a second thread when --telemetry is set. With
  --mlock also set (cumulative at L6), MCL_FUTURE locks the drain
  thread's default 8 MB stack in addition to the 224 KB ring;
  acceptable on the 16 GB ProBook with unlimited memlock, noted for
  rlimit accounting.
- A hand-rolled CRC and codec means two independent implementations to
  keep in sync; the corpus and known answers are the guard, and any
  format change bumps the wire version.
- The 10% acceptance tolerance is looser than the run-to-run spread
  seen in v0.1 campaigns (88 to 89 us at p99.9); if telemetry costs
  less than spread, the check cannot prove it costs zero, only that it
  costs less than 10%.
