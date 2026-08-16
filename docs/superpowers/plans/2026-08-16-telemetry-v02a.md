# v0.2a telemetry implementation plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Ship the v0.2a telemetry path: Python wire codec plus golden corpus (PR 2, Codex), C++ codec plus SPSC ring plus TSan lane (PR 3, Claude), drain thread plus harness integration plus sweep level L6 (PR 4, Claude), leaving PR 5 as a human-run ProBook campaign.

**Architecture:** The control thread pushes 56-byte POD records into a single-producer single-consumer ring; a SCHED_OTHER drain thread frames them (sync, version, type, length, seq, CRC-32C trailer) and writes a `.tvcrec` recording file. Python decodes recordings offline. A pinned golden corpus forces the two codecs to agree byte-for-byte.

**Tech Stack:** C++20 (no new dependencies; hand-rolled CRC-32C table), Python 3 stdlib `struct` + `google-crc32c`, CMake, stdlib `unittest`, Docker (ubuntu:26.04), TSan/ASan/UBSan.

**Spec:** `docs/superpowers/specs/2026-08-16-telemetry-v02a-design.md` — the plan argues from the spec; executors read both.

## Global constraints

- RT invariants (AGENTS.md): no allocation, locks, blocking syscalls, or formatted I/O inside the control cycle; deadlines from `origin + n * period`; timing math and control path use CLOCK_MONOTONIC only (one CLOCK_REALTIME read allowed off the hot path to date a recording header).
- Wire rules (spec): little-endian; sync `0xEB90` (bytes `0x90 0xEB` on the wire); CRC-32C Castagnoli (poly 0x1EDC6F41 reflected, init 0xFFFFFFFF, xorout 0xFFFFFFFF) over bytes 2 through 9+len; max payload 498; `schema_hash = 0xA871CD84`.
- Python CRC is `google-crc32c` only. Never `zlib.crc32`, never the apt `python3-crc32c` module.
- Container is a functional gate only, never a timing source. Build/test on macOS happens inside the tvc-dev container: `docker run --rm -v "$PWD":/w -w /w --cap-add=IPC_LOCK --ulimit memlock=-1:-1 tvc-dev bash -c '<cmd>'`. Python unit tests also run natively (`python3 -m unittest discover -s tests/unit`), which needs `pip3 install google-crc32c` on the Mac once.
- Commit subjects: short, imperative, lowercase, no bodies, no AI attribution. PR bodies end with the AI-assistance section from AGENTS.md. After each merge: ai-log entry `docs/ai-log/NNNN-slug.md` committed to main (next number at plan time: 0023).
- Roles (ADR-000): Tasks 1-6 are Codex work (Claude Code reviews by running the tests); Tasks 7-14 are Claude Code work (human review only).
- Branches: PR 2 = `telemetry-codec` (off main; carries this plan file as its first commit), PR 3 = `telemetry-cpp` (stacked on `telemetry-codec`), PR 4 = `telemetry-integration` (stacked on `telemetry-cpp`). Head-branch auto-delete retargets stacked PRs on merge.
- The seven decoder counters, exact names everywhere: `frames_ok`, `crc_errors`, `version_mismatch`, `resyncs`, `seq_discontinuities`, `lost`, `skipped_bytes`. `skipped_bytes` is computed as buffer length minus bytes consumed by valid frames.

## File structure

| file | responsibility | PR |
|---|---|---|
| `ground/__init__.py` | empty package marker | 2 |
| `ground/wire.py` | Python codec: crc32c, framing, record pack/unpack, recording reader, CLI | 2 |
| `tests/unit/test_wire.py` | KATs, round-trip, decoder rules, corpus verification, generate.py byte-stability | 2 |
| `tests/golden/generate.py` | deterministic corpus generator | 2 |
| `tests/golden/*.bin`, `recording_mini.tvcrec`, `manifest.json` | golden corpus | 2 |
| `docker/Dockerfile` | base ubuntu:26.04, pip, google-crc32c | 2 |
| `src/telemetry.hpp` / `src/telemetry.cpp` | namespace `telem`: Record, crc32c, encode/decode, SpscRing, Drain, recording header | 3, 4 |
| `tests/cpp/wire_tests.cpp` | C++ KATs, round-trip, decoder rules, corpus verification | 3 |
| `tests/cpp/ring_stress.cpp` | two-thread SPSC stress (FIFO, tearing, drop accounting) | 3 |
| `CMakeLists.txt` | `wire_tests` and `ring_stress` targets; telemetry.cpp into tvc_harness | 3, 4 |
| `tests/ci.sh` | run test binaries in normal+ASan trees; new TSan tree | 3 |
| `src/main.cpp` | `--telemetry` flag, startup ordering, hook, applied/config/summary | 4 |
| `src/loop_stats.hpp` / `.cpp` | `write_json` gains optional telemetry block | 4 |
| `tests/functional/test_telemetry.py` | end-to-end recording vs summary | 4 |
| `scripts/sweep.py` + `tests/unit/test_sweep.py` | level L6 | 4 |

---

## PR 2 — Python codec and golden corpus (Codex; branch `telemetry-codec`)

Setup once: `git checkout main && git pull && git checkout -b telemetry-codec`, commit this plan file (`git add docs/superpowers/plans/2026-08-16-telemetry-v02a.md && git commit -m "add v0.2a telemetry implementation plan"`). On the Mac, once: `pip3 install google-crc32c`.

### Task 1: ground package, crc32c, constants

**Files:**
- Create: `ground/__init__.py` (empty), `ground/wire.py`
- Test: `tests/unit/test_wire.py`

**Interfaces:**
- Produces: `wire.crc32c(data: bytes) -> int`; constants `SYNC = 0xEB90`, `VERSION = 1`, `TYPE_TELEMETRY = 1`, `TYPES = (1, 2, 3)`, `MAX_PAYLOAD = 498`, `SCHEMA` (the canonical string), `SCHEMA_HASH = 0xA871CD84`, `MAGIC = b"TVCRECRD"`.

- [ ] **Step 1: Write the failing test**

```python
# tests/unit/test_wire.py
import pathlib, sys, unittest
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[2]))
from ground import wire


class Crc32c(unittest.TestCase):
    def test_known_answers(self):
        # "123456789" is the standard CRC-32C check value; the four
        # 32-byte vectors are RFC 3720 appendix B.4.
        self.assertEqual(wire.crc32c(b"123456789"), 0xE3069283)
        self.assertEqual(wire.crc32c(bytes(32)), 0x8A9136AA)
        self.assertEqual(wire.crc32c(bytes([0xFF] * 32)), 0x62A8AB43)
        self.assertEqual(wire.crc32c(bytes(range(32))), 0x46DD794E)
        self.assertEqual(wire.crc32c(bytes(range(31, -1, -1))), 0x113FDB5C)

    def test_schema_hash(self):
        self.assertEqual(wire.crc32c(wire.SCHEMA.encode("ascii")), 0xA871CD84)
        self.assertEqual(wire.SCHEMA_HASH, 0xA871CD84)


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python3 -m unittest tests.unit.test_wire -v` (from repo root)
Expected: FAIL with `ModuleNotFoundError: No module named 'ground'`

- [ ] **Step 3: Write minimal implementation**

Create empty `ground/__init__.py`, then:

```python
# ground/wire.py
"""v0.2a wire codec.

Implements docs/superpowers/specs/2026-08-16-telemetry-v02a-design.md:
little-endian framing, CRC-32C over everything after the sync word, the
56-byte telemetry record, and the .tvcrec recording format.
"""
import collections
import struct
import sys

try:
    import google_crc32c
except ImportError as e:
    raise ImportError(
        "google-crc32c is required (never zlib.crc32): "
        "pip3 install --break-system-packages google-crc32c") from e

SYNC = 0xEB90
VERSION = 1
TYPE_TELEMETRY = 1
TYPES = (1, 2, 3)
MAX_PAYLOAD = 498
SCHEMA = ("telemetry_v1:tick:u64,deadline_ns:i64,woke_ns:i64,done_ns:i64,"
          "theta:f64,cmd:f64,drops:u64")
SCHEMA_HASH = 0xA871CD84
MAGIC = b"TVCRECRD"

HEADER = struct.Struct("<8sHHIqq")    # magic, version, reserved, schema_hash, mono, epoch
FRAME_HEAD = struct.Struct("<HBBHI")  # sync, version, type, length, seq
RECORD = struct.Struct("<QqqqddQ")
CRC = struct.Struct("<I")

Record = collections.namedtuple(
    "Record", "tick deadline_ns woke_ns done_ns theta cmd drops")


def crc32c(data: bytes) -> int:
    return google_crc32c.value(data)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python3 -m unittest tests.unit.test_wire -v`
Expected: 2 tests PASS

- [ ] **Step 5: Commit**

```bash
git add ground/__init__.py ground/wire.py tests/unit/test_wire.py
git commit -m "add ground wire module with crc32c known answers"
```

### Task 2: encode_frame

**Files:**
- Modify: `ground/wire.py`
- Test: `tests/unit/test_wire.py`

**Interfaces:**
- Consumes: Task 1 constants and `crc32c`.
- Produces: `wire.encode_frame(ftype: int, seq: int, payload: bytes) -> bytes`. Raises ValueError when `len(payload) > 498` or `ftype not in (1, 2, 3)`; seq taken mod 2^32.

- [ ] **Step 1: Write the failing test** (append to `tests/unit/test_wire.py`)

```python
class EncodeFrame(unittest.TestCase):
    def test_layout(self):
        f = wire.encode_frame(1, 7, b"ab")
        self.assertEqual(len(f), 16)                  # 14 overhead + 2
        self.assertEqual(f[0:2], b"\x90\xeb")         # sync on the wire
        self.assertEqual(f[2], 1)                     # version
        self.assertEqual(f[3], 1)                     # type
        self.assertEqual(f[4:6], (2).to_bytes(2, "little"))
        self.assertEqual(f[6:10], (7).to_bytes(4, "little"))
        self.assertEqual(f[10:12], b"ab")
        crc = int.from_bytes(f[12:16], "little")
        self.assertEqual(crc, wire.crc32c(f[2:12]))   # everything after sync

    def test_seq_wraps(self):
        f = wire.encode_frame(1, 2**32 + 5, b"")
        self.assertEqual(f[6:10], (5).to_bytes(4, "little"))

    def test_rejects_oversize_payload(self):
        wire.encode_frame(1, 0, bytes(498))           # boundary ok
        with self.assertRaises(ValueError):
            wire.encode_frame(1, 0, bytes(499))

    def test_rejects_bad_type(self):
        for t in (0, 4, 255):
            with self.assertRaises(ValueError):
                wire.encode_frame(t, 0, b"")
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python3 -m unittest tests.unit.test_wire -v`
Expected: FAIL with `AttributeError: module 'ground.wire' has no attribute 'encode_frame'`

- [ ] **Step 3: Write minimal implementation** (append to `ground/wire.py`)

```python
def encode_frame(ftype: int, seq: int, payload: bytes) -> bytes:
    if ftype not in TYPES:
        raise ValueError(f"bad frame type {ftype}")
    if len(payload) > MAX_PAYLOAD:
        raise ValueError(f"payload {len(payload)} exceeds {MAX_PAYLOAD}")
    head = FRAME_HEAD.pack(SYNC, VERSION, ftype, len(payload), seq % 2**32)
    return head + payload + CRC.pack(crc32c(head[2:] + payload))
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python3 -m unittest tests.unit.test_wire -v`
Expected: all PASS

- [ ] **Step 5: Commit**

```bash
git add ground/wire.py tests/unit/test_wire.py
git commit -m "add frame encoder"
```

### Task 3: decode_stream

**Files:**
- Modify: `ground/wire.py`
- Test: `tests/unit/test_wire.py`

**Interfaces:**
- Consumes: `encode_frame`, `crc32c`, constants.
- Produces: `wire.decode_stream(data: bytes) -> tuple[list, dict]` — frames is a list of `(ftype, seq, payload)` tuples (valid frames only, all types); counters is a dict with exactly the seven keys from Global constraints. Decoder rules are the spec's: version checked first at each sync match; validity = version 1, type in {1,2,3}, length <= 498, complete, CRC ok; on failure advance one byte and rescan; a candidate extending past the buffer stops the scan; `expected` starts unset, adopts the first valid seq, advances only on valid frames; gap in [1, 2^31) adds to `lost`, gap >= 2^31 adds one `seq_discontinuities`; `resyncs` counts loss-of-lock events (first failure while locked; locked at start and after each valid frame; version failures also count `version_mismatch`).

- [ ] **Step 1: Write the failing test** (append)

```python
def counters(**overrides):
    base = dict.fromkeys(
        ("frames_ok", "crc_errors", "version_mismatch", "resyncs",
         "seq_discontinuities", "lost", "skipped_bytes"), 0)
    base.update(overrides)
    return base


class DecodeStream(unittest.TestCase):
    def test_round_trip(self):
        data = (wire.encode_frame(1, 0, b"hello") +
                wire.encode_frame(2, 1, b"") +
                wire.encode_frame(3, 2, bytes(498)))
        frames, ctr = wire.decode_stream(data)
        self.assertEqual(frames, [(1, 0, b"hello"), (2, 1, b""),
                                  (3, 2, bytes(498))])
        self.assertEqual(ctr, counters(frames_ok=3))

    def test_empty_buffer(self):
        self.assertEqual(wire.decode_stream(b""), ([], counters()))

    def test_truncation_at_every_boundary(self):
        f = wire.encode_frame(1, 0, b"abc")           # 17 bytes
        for cut in range(len(f)):
            frames, ctr = wire.decode_stream(f[:cut])
            self.assertEqual(frames, [], f"cut={cut}")
            self.assertEqual(ctr["frames_ok"], 0, f"cut={cut}")
            self.assertEqual(ctr["skipped_bytes"], cut, f"cut={cut}")

    def test_corruption_sweep(self):
        f = wire.encode_frame(1, 9, b"abc")
        for i in range(len(f)):
            bad = f[:i] + bytes([f[i] ^ 0xFF]) + f[i + 1:]
            frames, ctr = wire.decode_stream(bad)
            self.assertEqual(frames, [], f"flip at {i}")
            self.assertEqual(ctr["skipped_bytes"], len(f), f"flip at {i}")

    def test_version_mismatch_counts_and_resyncs(self):
        f = bytearray(wire.encode_frame(1, 0, b"x"))
        f[2] = 2                                      # future version
        frames, ctr = wire.decode_stream(bytes(f))
        self.assertEqual(frames, [])
        self.assertEqual(ctr["version_mismatch"], 1)
        self.assertEqual(ctr["resyncs"], 1)

    def test_gap_counts_lost(self):
        data = wire.encode_frame(1, 5, b"") + wire.encode_frame(1, 8, b"")
        _, ctr = wire.decode_stream(data)
        self.assertEqual(ctr["lost"], 2)
        self.assertEqual(ctr["seq_discontinuities"], 0)

    def test_wrap_is_gapless(self):
        data = (wire.encode_frame(1, 0xFFFFFFFF, b"") +
                wire.encode_frame(1, 0, b""))
        _, ctr = wire.decode_stream(data)
        self.assertEqual(ctr["lost"], 0)
        self.assertEqual(ctr["seq_discontinuities"], 0)

    def test_backward_seq_is_discontinuity(self):
        data = wire.encode_frame(1, 100, b"") + wire.encode_frame(1, 50, b"")
        _, ctr = wire.decode_stream(data)
        self.assertEqual(ctr["lost"], 0)
        self.assertEqual(ctr["seq_discontinuities"], 1)

    def test_corrupt_frame_between_good_ones(self):
        good = [wire.encode_frame(1, n, bytes([n])) for n in range(3)]
        mid = bytearray(good[1])
        mid[-1] ^= 0xFF
        frames, ctr = wire.decode_stream(good[0] + bytes(mid) + good[2])
        self.assertEqual([f[1] for f in frames], [0, 2])
        self.assertEqual(ctr["crc_errors"], 1)
        self.assertEqual(ctr["resyncs"], 1)
        self.assertEqual(ctr["lost"], 1)              # seq 1 not consumed
        self.assertEqual(ctr["skipped_bytes"], len(good[1]))
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python3 -m unittest tests.unit.test_wire -v`
Expected: FAIL with `AttributeError: ... no attribute 'decode_stream'`

- [ ] **Step 3: Write the implementation** (append)

```python
def decode_stream(data: bytes):
    """Decode a complete buffer per the spec's decoder rules.
    Returns (frames, counters): frames is [(ftype, seq, payload)]."""
    ctr = dict.fromkeys(
        ("frames_ok", "crc_errors", "version_mismatch", "resyncs",
         "seq_discontinuities", "lost", "skipped_bytes"), 0)
    frames = []
    expected = None
    consumed = 0
    locked = True      # at buffer start and after each valid frame
    pos = 0
    while True:
        sync_at = data.find(b"\x90\xeb", pos)
        if sync_at < 0:
            break
        pos = sync_at
        if pos + FRAME_HEAD.size > len(data):
            break      # header cut off: end of input, tail stays skipped
        _, ver, ftype, length, seq = FRAME_HEAD.unpack_from(data, pos)
        if ver != VERSION:
            ctr["version_mismatch"] += 1
            if locked:
                ctr["resyncs"] += 1
                locked = False
            pos += 1
            continue
        if ftype not in TYPES or length > MAX_PAYLOAD:
            if locked:
                ctr["resyncs"] += 1
                locked = False
            pos += 1
            continue
        end = pos + FRAME_HEAD.size + length + CRC.size
        if end > len(data):
            break      # frame extends past buffer: stop, no resync
        (crc,) = CRC.unpack_from(data, end - CRC.size)
        if crc != crc32c(data[pos + 2:end - CRC.size]):
            ctr["crc_errors"] += 1
            if locked:
                ctr["resyncs"] += 1
                locked = False
            pos += 1
            continue
        payload = data[pos + FRAME_HEAD.size:end - CRC.size]
        frames.append((ftype, seq, payload))
        ctr["frames_ok"] += 1
        consumed += end - pos
        if expected is not None:
            gap = (seq - expected) % 2**32
            if 1 <= gap < 2**31:
                ctr["lost"] += gap
            elif gap >= 2**31:
                ctr["seq_discontinuities"] += 1
        expected = (seq + 1) % 2**32
        locked = True
        pos = end
    ctr["skipped_bytes"] = len(data) - consumed
    return frames, ctr
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python3 -m unittest tests.unit.test_wire -v`
Expected: all PASS

- [ ] **Step 5: Commit**

```bash
git add ground/wire.py tests/unit/test_wire.py
git commit -m "add stream decoder with spec counters"
```

### Task 4: record pack/unpack, read_recording, CLI

**Files:**
- Modify: `ground/wire.py`
- Test: `tests/unit/test_wire.py`

**Interfaces:**
- Consumes: `decode_stream`, `HEADER`, `RECORD`, `Record`.
- Produces: `wire.pack_record(rec) -> bytes` (56 bytes); `wire.unpack_record(payload: bytes) -> Record`; `wire.read_recording(path) -> (header: dict, records: list[Record], counters: dict)` where header has keys `magic, version, schema_hash, start_monotonic_ns, start_epoch_ns, schema_known`; ValueError on unknown magic or version, and on a valid type-1 frame whose payload is not 56 bytes; non-type-1 valid frames count in `frames_ok` but yield no record. CLI: `python3 -m ground.wire <file>` prints `records=N`, one `key=value` per counter (sorted), and `schema_known=...`.

- [ ] **Step 1: Write the failing test** (append)

```python
class Records(unittest.TestCase):
    def test_pack_unpack_round_trip(self):
        rec = wire.Record(tick=42, deadline_ns=10**9, woke_ns=10**9 + 12_800,
                          done_ns=10**9 + 31_500, theta=0.125, cmd=-0.5,
                          drops=3)
        packed = wire.pack_record(rec)
        self.assertEqual(len(packed), 56)
        self.assertEqual(wire.unpack_record(packed), rec)

    def test_negative_jitter_survives(self):
        rec = wire.Record(0, 100, 90, 120, 0.0, 0.0, 0)   # woke before deadline
        self.assertEqual(wire.unpack_record(wire.pack_record(rec)).woke_ns, 90)


class ReadRecording(unittest.TestCase):
    def make(self, tmp, header=None, frames=b""):
        if header is None:
            header = wire.HEADER.pack(wire.MAGIC, wire.VERSION, 0,
                                      wire.SCHEMA_HASH, 1, 2)
        p = pathlib.Path(tmp) / "r.tvcrec"
        p.write_bytes(header + frames)
        return p

    def test_reads_header_and_records(self):
        import tempfile
        rec = wire.Record(0, 10, 20, 30, 1.0, -1.0, 0)
        with tempfile.TemporaryDirectory() as d:
            p = self.make(d, frames=wire.encode_frame(1, 0, wire.pack_record(rec)))
            header, records, ctr = wire.read_recording(p)
            self.assertEqual(header["start_monotonic_ns"], 1)
            self.assertEqual(header["start_epoch_ns"], 2)
            self.assertTrue(header["schema_known"])
            self.assertEqual(records, [rec])
            self.assertEqual(ctr["frames_ok"], 1)

    def test_rejects_bad_magic(self):
        import tempfile
        with tempfile.TemporaryDirectory() as d:
            p = self.make(d, header=wire.HEADER.pack(b"NOTMAGIC", 1, 0, 0, 0, 0))
            with self.assertRaises(ValueError):
                wire.read_recording(p)

    def test_rejects_bad_version(self):
        import tempfile
        with tempfile.TemporaryDirectory() as d:
            p = self.make(d, header=wire.HEADER.pack(wire.MAGIC, 9, 0, 0, 0, 0))
            with self.assertRaises(ValueError):
                wire.read_recording(p)

    def test_unknown_schema_reported_not_refused(self):
        import tempfile
        with tempfile.TemporaryDirectory() as d:
            p = self.make(d, header=wire.HEADER.pack(wire.MAGIC, 1, 0, 0xDEAD, 0, 0))
            header, records, ctr = wire.read_recording(p)
            self.assertFalse(header["schema_known"])

    def test_wrong_size_type1_payload_raises(self):
        import tempfile
        with tempfile.TemporaryDirectory() as d:
            p = self.make(d, frames=wire.encode_frame(1, 0, b"short"))
            with self.assertRaises(ValueError):
                wire.read_recording(p)

    def test_non_record_types_skipped(self):
        import tempfile
        with tempfile.TemporaryDirectory() as d:
            p = self.make(d, frames=wire.encode_frame(2, 0, b"cmd"))
            header, records, ctr = wire.read_recording(p)
            self.assertEqual(records, [])
            self.assertEqual(ctr["frames_ok"], 1)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python3 -m unittest tests.unit.test_wire -v`
Expected: FAIL with `AttributeError: ... no attribute 'pack_record'`

- [ ] **Step 3: Write the implementation** (append)

```python
def pack_record(rec) -> bytes:
    return RECORD.pack(*rec)


def unpack_record(payload: bytes) -> Record:
    return Record(*RECORD.unpack(payload))


def read_recording(path):
    with open(path, "rb") as f:
        data = f.read()
    if len(data) < HEADER.size:
        raise ValueError("recording shorter than its header")
    magic, ver, _reserved, schema_hash, mono, epoch = HEADER.unpack_from(data)
    if magic != MAGIC:
        raise ValueError(f"bad magic {magic!r}")
    if ver != VERSION:
        raise ValueError(f"unsupported recording version {ver}")
    header = {"magic": magic, "version": ver, "schema_hash": schema_hash,
              "start_monotonic_ns": mono, "start_epoch_ns": epoch,
              "schema_known": schema_hash == SCHEMA_HASH}
    frames, ctr = decode_stream(data[HEADER.size:])
    records = []
    for ftype, _seq, payload in frames:
        if ftype != TYPE_TELEMETRY:
            continue
        if len(payload) != RECORD.size:
            raise ValueError(
                f"type-1 frame with {len(payload)}-byte payload: encoder bug")
        records.append(unpack_record(payload))
    return header, records, ctr


def main(argv):
    if len(argv) != 2:
        print("usage: python3 -m ground.wire <recording.tvcrec>",
              file=sys.stderr)
        return 1
    header, records, ctr = read_recording(argv[1])
    print(f"records={len(records)}")
    for key in sorted(ctr):
        print(f"{key}={ctr[key]}")
    print(f"schema_known={header['schema_known']}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python3 -m unittest tests.unit.test_wire -v`
Expected: all PASS. Spot-check the CLI on a garbage file: `python3 -m ground.wire /etc/hosts` should raise ValueError (bad magic).

- [ ] **Step 5: Commit**

```bash
git add ground/wire.py tests/unit/test_wire.py
git commit -m "add record codec, recording reader, and cli"
```

### Task 5: golden corpus

**Files:**
- Create: `tests/golden/generate.py`, plus its outputs: `frame_record.bin`, `frame_empty.bin`, `frame_max.bin`, `frames_seqwrap.bin`, `frame_badcrc.bin`, `frame_truncated.bin`, `recording_mini.tvcrec`, `manifest.json`
- Test: `tests/unit/test_wire.py`

**Interfaces:**
- Consumes: everything from Tasks 1-4.
- Produces: the corpus files (consumed by Task 9's C++ tests) and `generate.main(out_dir)` for the byte-stability test. `manifest.json`: top level `{"schema_hash": "0xA871CD84", "files": [...]}`, each entry `{file, description, roundtrip, expect: {seven counters}}`, written with `json.dumps(doc, indent=2, sort_keys=True) + "\n"`.

- [ ] **Step 1: Write the generator**

```python
#!/usr/bin/env python3
# tests/golden/generate.py — regenerate the golden corpus. Byte-stable:
# every input is a fixed constant, so the output never changes.
import json
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[2]))
from ground import wire


def record(n):
    base = 1_000_000_000 + 2_000_000 * n
    return wire.pack_record(wire.Record(
        tick=n, deadline_ns=base, woke_ns=base + 12_800,
        done_ns=base + 12_800 + 18_700,
        theta=n * 0.125, cmd=n * -0.25, drops=0))


def corrupt_last(frame: bytes) -> bytes:
    return frame[:-1] + bytes([frame[-1] ^ 0xFF])


DESCRIPTIONS = {
    "frame_record.bin": "canonical type-1 record frame",
    "frame_empty.bin": "type-2 frame with empty payload",
    "frame_max.bin": "type-3 frame with the 498-byte max payload",
    "frames_seqwrap.bin": "two record frames across the u32 seq wrap",
    "frame_badcrc.bin": "record frame with its final CRC byte flipped",
    "frame_truncated.bin": "record frame cut after 30 bytes",
    "recording_mini.tvcrec":
        "header + six record frames, seq-2 frame corrupted, proving resync",
}
ROUNDTRIP = {
    "frame_record.bin": True, "frame_empty.bin": True, "frame_max.bin": True,
    "frames_seqwrap.bin": True, "frame_badcrc.bin": False,
    "frame_truncated.bin": False, "recording_mini.tvcrec": False,
}


def build():
    files = {
        "frame_record.bin": wire.encode_frame(1, 0, record(0)),
        "frame_empty.bin": wire.encode_frame(2, 1, b""),
        "frame_max.bin": wire.encode_frame(3, 2, (bytes(range(256)) * 2)[:498]),
        "frames_seqwrap.bin": (wire.encode_frame(1, 0xFFFFFFFF, record(0)) +
                               wire.encode_frame(1, 0, record(1))),
        "frame_badcrc.bin": corrupt_last(wire.encode_frame(1, 3, record(3))),
        "frame_truncated.bin": wire.encode_frame(1, 4, record(4))[:30],
    }
    frames = [wire.encode_frame(1, n, record(n)) for n in range(6)]
    frames[2] = corrupt_last(frames[2])
    header = wire.HEADER.pack(wire.MAGIC, wire.VERSION, 0, wire.SCHEMA_HASH,
                              1_000_000_000, 1_755_000_000_000_000_000)
    files["recording_mini.tvcrec"] = header + b"".join(frames)
    return files


def main(out_dir=None):
    out = pathlib.Path(out_dir) if out_dir else pathlib.Path(__file__).resolve().parent
    files = build()
    entries = []
    for name in sorted(files):
        data = files[name]
        (out / name).write_bytes(data)
        body = data[wire.HEADER.size:] if name.endswith(".tvcrec") else data
        _, ctr = wire.decode_stream(body)
        entries.append({"file": name, "description": DESCRIPTIONS[name],
                        "roundtrip": ROUNDTRIP[name], "expect": ctr})
    doc = {"schema_hash": "0xA871CD84", "files": entries}
    (out / "manifest.json").write_text(
        json.dumps(doc, indent=2, sort_keys=True) + "\n")


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else None)
```

- [ ] **Step 2: Generate and eyeball the manifest**

Run: `python3 tests/golden/generate.py && cat tests/golden/manifest.json`
Expected intended counters (a mismatch here is a spec bug to raise, not to paper over): `frame_badcrc` -> crc_errors 1, resyncs 1, skipped_bytes 70; `frame_truncated` -> skipped_bytes 30, all else 0; `frames_seqwrap` -> frames_ok 2, lost 0, seq_discontinuities 0; `recording_mini` -> frames_ok 5, crc_errors 1, resyncs 1, lost 1, skipped_bytes 70; the three simple frames -> frames_ok 1.

- [ ] **Step 3: Write the corpus tests** (append to `tests/unit/test_wire.py`)

```python
import json

GOLDEN = pathlib.Path(__file__).resolve().parents[2] / "tests" / "golden"


class GoldenCorpus(unittest.TestCase):
    def setUp(self):
        self.manifest = json.loads((GOLDEN / "manifest.json").read_text())

    def test_schema_hash_recorded(self):
        self.assertEqual(self.manifest["schema_hash"], "0xA871CD84")

    def test_counters_match_manifest(self):
        for entry in self.manifest["files"]:
            data = (GOLDEN / entry["file"]).read_bytes()
            body = data[wire.HEADER.size:] if entry["file"].endswith(".tvcrec") else data
            _, ctr = wire.decode_stream(body)
            self.assertEqual(ctr, entry["expect"], entry["file"])

    def test_roundtrip_files_reencode_byte_exact(self):
        for entry in self.manifest["files"]:
            if not entry["roundtrip"]:
                continue
            data = (GOLDEN / entry["file"]).read_bytes()
            frames, _ = wire.decode_stream(data)
            re = b"".join(wire.encode_frame(t, s, p) for t, s, p in frames)
            self.assertEqual(re, data, entry["file"])

    def test_generate_is_byte_stable(self):
        import tempfile
        sys.path.insert(0, str(GOLDEN))
        import generate
        with tempfile.TemporaryDirectory() as d:
            generate.main(d)
            regenerated = sorted(p.name for p in pathlib.Path(d).iterdir())
            for name in regenerated:
                self.assertEqual((pathlib.Path(d) / name).read_bytes(),
                                 (GOLDEN / name).read_bytes(), name)
            checked_in = sorted(p.name for p in GOLDEN.iterdir()
                                if p.name not in ("generate.py", "__pycache__"))
            self.assertEqual(regenerated, checked_in)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python3 -m unittest tests.unit.test_wire -v`
Expected: all PASS

- [ ] **Step 5: Commit**

```bash
git add tests/golden tests/unit/test_wire.py
git commit -m "add golden corpus with pinned inputs and manifest"
```

### Task 6: Dockerfile and PR 2

**Files:**
- Modify: `docker/Dockerfile`

**Interfaces:**
- Produces: a tvc-dev image on ubuntu:26.04 with google-crc32c, so ci.sh's unit-test phase can import ground.wire.

- [ ] **Step 1: Update the Dockerfile**

```dockerfile
FROM ubuntu:26.04
RUN apt-get update && apt-get install -y --no-install-recommends \
    g++ cmake git ca-certificates python3 python3-matplotlib python3-pip make \
    && rm -rf /var/lib/apt/lists/*
# System Python is PEP 668 externally managed; this image is disposable.
RUN pip3 install --break-system-packages google-crc32c
```

- [ ] **Step 2: Rebuild the image and run the full gate**

Run: `docker build -t tvc-dev docker/`
Then: `docker run --rm -v "$PWD":/w -w /w --cap-add=IPC_LOCK --ulimit memlock=-1:-1 tvc-dev bash tests/ci.sh`
Expected: `ci.sh: all green` (existing tests plus all test_wire cases).

- [ ] **Step 3: Commit and open PR 2**

```bash
git add docker/Dockerfile
git commit -m "move container to ubuntu 26.04 and add google-crc32c"
git push -u origin telemetry-codec
```

Open the PR with base `main`, title "v0.2a python wire codec and golden corpus". Body describes the codec, decoder rules, corpus, and container change, and ends with the AI-assistance section (Agent: Codex, with model; Scope: Tasks 1-6; Human changes: filled at review; Verification: the exact commands above and their results). Claude Code reviews by running the tests before Mamadou reviews.

---

## PR 3 — C++ codec, ring, TSan lane (Claude Code; branch `telemetry-cpp`, stacked on `telemetry-codec`)

Setup: `git checkout telemetry-codec && git checkout -b telemetry-cpp`.
All C++ builds and test runs happen in the container. Quick loop:
`docker run --rm -v "$PWD":/w -w /w tvc-dev bash -c 'cmake -S . -B build && cmake --build build -j && ./build/wire_tests && ./build/ring_stress'`

Both test binaries use this check macro instead of `<cassert>` (assert would vanish if NDEBUG ever entered the flags):

```cpp
#define CHECK(cond) do { if (!(cond)) { \
    std::fprintf(stderr, "FAIL %s:%d: %s\n", __FILE__, __LINE__, #cond); \
    std::exit(1); } } while (0)
```

### Task 7: telem Record, crc32c, wire_tests target

**Files:**
- Create: `src/telemetry.hpp`, `src/telemetry.cpp`, `tests/cpp/wire_tests.cpp`
- Modify: `CMakeLists.txt`

**Interfaces:**
- Produces (in `namespace telem`): `struct Record { std::uint64_t tick; std::int64_t deadline_ns, woke_ns, done_ns; double theta, cmd; std::uint64_t drops; };` with static_asserts; `std::uint32_t crc32c(const void* data, std::size_t len) noexcept`; constants `kSync = 0xEB90`, `kVersion = 1`, `kTypeTelemetry = 1`, `kSchemaHash = 0xA871CD84u`, `kMaxPayload = 498`, `kFrameOverhead = 14`, `kSchema` (the canonical string).

- [ ] **Step 1: Write the failing test**

```cpp
// tests/cpp/wire_tests.cpp — codec unit tests. Plain main() + CHECK.
#include "../../src/telemetry.hpp"

#include <cstdio>
#include <cstdlib>
#include <cstring>
#include <string>
#include <vector>

#define CHECK(cond) do { if (!(cond)) { \
    std::fprintf(stderr, "FAIL %s:%d: %s\n", __FILE__, __LINE__, #cond); \
    std::exit(1); } } while (0)

namespace {

void test_crc_known_answers() {
    CHECK(telem::crc32c("123456789", 9) == 0xE3069283u);
    unsigned char buf[32];
    std::memset(buf, 0x00, 32);
    CHECK(telem::crc32c(buf, 32) == 0x8A9136AAu);
    std::memset(buf, 0xFF, 32);
    CHECK(telem::crc32c(buf, 32) == 0x62A8AB43u);
    for (int i = 0; i < 32; ++i) buf[i] = static_cast<unsigned char>(i);
    CHECK(telem::crc32c(buf, 32) == 0x46DD794Eu);
    for (int i = 0; i < 32; ++i) buf[i] = static_cast<unsigned char>(31 - i);
    CHECK(telem::crc32c(buf, 32) == 0x113FDB5Cu);
    CHECK(telem::crc32c(telem::kSchema, std::strlen(telem::kSchema)) ==
          telem::kSchemaHash);
}

}  // namespace

int main() {
    test_crc_known_answers();
    std::puts("wire_tests: ok");
    return 0;
}
```

- [ ] **Step 2: Add the CMake target and verify the build fails**

Append to `CMakeLists.txt` (and add `src/telemetry.cpp` to the `add_executable(tvc_harness ...)` source list while here):

```cmake
add_executable(wire_tests tests/cpp/wire_tests.cpp src/telemetry.cpp)
target_compile_definitions(wire_tests PRIVATE _GNU_SOURCE)
target_compile_options(wire_tests PRIVATE -Wall -Wextra -Wpedantic)
```

Run the container build. Expected: FAIL, `telemetry.hpp` not found.

- [ ] **Step 3: Write the implementation**

```cpp
// src/telemetry.hpp — v0.2a telemetry: record, wire codec, SPSC ring, drain.
// Spec: docs/superpowers/specs/2026-08-16-telemetry-v02a-design.md.
#pragma once
#include <cstddef>
#include <cstdint>
#include <type_traits>

namespace telem {

// One control cycle, exactly the 56-byte wire payload: the drain frames
// records by header-wrap, never field-by-field marshal.
struct Record {
    std::uint64_t tick;
    std::int64_t  deadline_ns;
    std::int64_t  woke_ns;
    std::int64_t  done_ns;
    double        theta;
    double        cmd;
    std::uint64_t drops;   // cumulative try_push failures before this record
};
static_assert(sizeof(Record) == 56);
static_assert(std::is_trivially_copyable_v<Record>);

inline constexpr std::uint16_t kSync          = 0xEB90;
inline constexpr std::uint8_t  kVersion       = 1;
inline constexpr std::uint8_t  kTypeTelemetry = 1;
inline constexpr std::uint32_t kSchemaHash    = 0xA871CD84u;
inline constexpr std::size_t   kMaxPayload    = 498;
inline constexpr std::size_t   kFrameOverhead = 14;
inline constexpr const char*   kSchema =
    "telemetry_v1:tick:u64,deadline_ns:i64,woke_ns:i64,done_ns:i64,"
    "theta:f64,cmd:f64,drops:u64";

// CRC-32C (Castagnoli), reflected, init/xorout 0xFFFFFFFF: the value
// google-crc32c computes. Byte-wise table; drain-side only.
std::uint32_t crc32c(const void* data, std::size_t len) noexcept;

}  // namespace telem
```

```cpp
// src/telemetry.cpp
#include "telemetry.hpp"

#include <array>

namespace telem {
namespace {

constexpr std::array<std::uint32_t, 256> make_crc_table() {
    std::array<std::uint32_t, 256> t{};
    for (std::uint32_t i = 0; i < 256; ++i) {
        std::uint32_t c = i;
        for (int k = 0; k < 8; ++k)
            c = (c & 1u) ? (c >> 1) ^ 0x82F63B78u : c >> 1;
        t[i] = c;
    }
    return t;
}
constexpr auto kCrcTable = make_crc_table();

}  // namespace

std::uint32_t crc32c(const void* data, std::size_t len) noexcept {
    const auto* p = static_cast<const unsigned char*>(data);
    std::uint32_t c = 0xFFFFFFFFu;
    for (std::size_t i = 0; i < len; ++i)
        c = kCrcTable[(c ^ p[i]) & 0xFFu] ^ (c >> 8);
    return c ^ 0xFFFFFFFFu;
}

}  // namespace telem
```

- [ ] **Step 4: Build and run**

Container: `cmake --build build -j && ./build/wire_tests`
Expected: `wire_tests: ok`

- [ ] **Step 5: Commit**

```bash
git add src/telemetry.hpp src/telemetry.cpp tests/cpp/wire_tests.cpp CMakeLists.txt
git commit -m "add telemetry record and crc32c with known-answer tests"
```

### Task 8: C++ frame encoder

**Files:**
- Modify: `src/telemetry.hpp`, `src/telemetry.cpp`, `tests/cpp/wire_tests.cpp`

**Interfaces:**
- Produces: `std::size_t encode_frame(std::uint8_t type, std::uint32_t seq, const void* payload, std::size_t len, unsigned char* out) noexcept` — writes `kFrameOverhead + len` bytes into `out` and returns that count. Caller guarantees `len <= kMaxPayload` and a large-enough buffer (this is the hot-path-adjacent API; validation lives at the Python edge and in tests).

- [ ] **Step 1: Write the failing test** (add to wire_tests.cpp and call from main)

```cpp
void test_encode_frame_layout() {
    unsigned char out[64];
    const std::size_t n = telem::encode_frame(1, 7, "ab", 2, out);
    CHECK(n == 16);
    CHECK(out[0] == 0x90 && out[1] == 0xEB);          // sync on the wire
    CHECK(out[2] == 1 && out[3] == 1);                // version, type
    CHECK(out[4] == 2 && out[5] == 0);                // length LE
    CHECK(out[6] == 7 && out[7] == 0 && out[8] == 0 && out[9] == 0);
    CHECK(out[10] == 'a' && out[11] == 'b');
    std::uint32_t crc = static_cast<std::uint32_t>(out[12]) |
                        static_cast<std::uint32_t>(out[13]) << 8 |
                        static_cast<std::uint32_t>(out[14]) << 16 |
                        static_cast<std::uint32_t>(out[15]) << 24;
    CHECK(crc == telem::crc32c(out + 2, 10));         // everything after sync
}
```

- [ ] **Step 2: Build and verify failure** — container build. Expected: link error, `encode_frame` undefined.

- [ ] **Step 3: Implement** (telemetry.cpp; declare in the header)

```cpp
namespace {
inline void put16(unsigned char* p, std::uint16_t v) noexcept {
    p[0] = static_cast<unsigned char>(v);
    p[1] = static_cast<unsigned char>(v >> 8);
}
inline void put32(unsigned char* p, std::uint32_t v) noexcept {
    p[0] = static_cast<unsigned char>(v);
    p[1] = static_cast<unsigned char>(v >> 8);
    p[2] = static_cast<unsigned char>(v >> 16);
    p[3] = static_cast<unsigned char>(v >> 24);
}
}  // namespace

std::size_t encode_frame(std::uint8_t type, std::uint32_t seq,
                         const void* payload, std::size_t len,
                         unsigned char* out) noexcept {
    put16(out, kSync);
    out[2] = kVersion;
    out[3] = type;
    put16(out + 4, static_cast<std::uint16_t>(len));
    put32(out + 6, seq);
    std::memcpy(out + 10, payload, len);
    put32(out + 10 + len, crc32c(out + 2, 8 + len));
    return kFrameOverhead + len;
}
```

(`#include <cstring>` in telemetry.cpp.)

- [ ] **Step 4: Build and run** — expected `wire_tests: ok`.

- [ ] **Step 5: Commit**

```bash
git add src/telemetry.hpp src/telemetry.cpp tests/cpp/wire_tests.cpp
git commit -m "add c++ frame encoder"
```

### Task 9: C++ decoder and corpus verification

**Files:**
- Modify: `src/telemetry.hpp`, `src/telemetry.cpp`, `tests/cpp/wire_tests.cpp`

**Interfaces:**
- Consumes: corpus files from Task 5 (branch is stacked on `telemetry-codec`).
- Produces: `struct DecodeCounters { std::uint64_t frames_ok, crc_errors, version_mismatch, resyncs, seq_discontinuities, lost, skipped_bytes; }` (all zero-initialized); `struct DecodedFrame { std::uint8_t type; std::uint32_t seq; std::size_t payload_off, payload_len; };` (offsets into the caller's buffer, no ownership); `DecodeCounters decode_stream(const unsigned char* data, std::size_t len, std::vector<DecodedFrame>& out)`. Rules identical to Task 3's Python — the two implementations plus the pinned corpus are the cross-check.

- [ ] **Step 1: Write the failing tests** (add; `wire_tests` gains `int main(int argc, char** argv)` with corpus dir `argv[1]` defaulting to `"tests/golden"`, so ci.sh runs it from the repo root)

```cpp
std::vector<unsigned char> slurp(const std::string& path) {
    std::FILE* f = std::fopen(path.c_str(), "rb");
    CHECK(f != nullptr);
    std::vector<unsigned char> data;
    unsigned char buf[4096];
    std::size_t n;
    while ((n = std::fread(buf, 1, sizeof buf, f)) > 0)
        data.insert(data.end(), buf, buf + n);
    std::fclose(f);
    return data;
}

void test_decode_round_trip() {
    unsigned char buf[600];
    std::size_t n = telem::encode_frame(1, 5, "hello", 5, buf);
    n += telem::encode_frame(2, 6, "", 0, buf + n);
    std::vector<telem::DecodedFrame> frames;
    const auto ctr = telem::decode_stream(buf, n, frames);
    CHECK(frames.size() == 2 && ctr.frames_ok == 2);
    CHECK(frames[0].type == 1 && frames[0].seq == 5 && frames[0].payload_len == 5);
    CHECK(std::memcmp(buf + frames[0].payload_off, "hello", 5) == 0);
    CHECK(ctr.lost == 0 && ctr.skipped_bytes == 0);
}

void test_gap_rules() {
    unsigned char buf[600];
    std::size_t n = telem::encode_frame(1, 0xFFFFFFFFu, "", 0, buf);
    n += telem::encode_frame(1, 0, "", 0, buf + n);
    std::vector<telem::DecodedFrame> frames;
    auto ctr = telem::decode_stream(buf, n, frames);
    CHECK(ctr.lost == 0 && ctr.seq_discontinuities == 0);   // wrap is gapless

    n = telem::encode_frame(1, 5, "", 0, buf);
    n += telem::encode_frame(1, 8, "", 0, buf + n);
    frames.clear();
    ctr = telem::decode_stream(buf, n, frames);
    CHECK(ctr.lost == 2);

    n = telem::encode_frame(1, 100, "", 0, buf);
    n += telem::encode_frame(1, 50, "", 0, buf + n);
    frames.clear();
    ctr = telem::decode_stream(buf, n, frames);
    CHECK(ctr.lost == 0 && ctr.seq_discontinuities == 1);
}

void test_truncation_and_corruption() {
    unsigned char buf[64];
    const std::size_t n = telem::encode_frame(1, 0, "abc", 3, buf);
    for (std::size_t cut = 0; cut < n; ++cut) {
        std::vector<telem::DecodedFrame> frames;
        const auto ctr = telem::decode_stream(buf, cut, frames);
        CHECK(frames.empty() && ctr.skipped_bytes == cut);
    }
    for (std::size_t i = 0; i < n; ++i) {
        unsigned char bad[64];
        std::memcpy(bad, buf, n);
        bad[i] ^= 0xFF;
        std::vector<telem::DecodedFrame> frames;
        const auto ctr = telem::decode_stream(bad, n, frames);
        CHECK(frames.empty() && ctr.skipped_bytes == n);
    }
}

// Counter values mirror tests/golden/manifest.json; update both together.
struct Expect {
    const char* file;
    telem::DecodeCounters ctr;
    bool roundtrip;
    bool recording;   // strip the 32-byte header first
};

void test_golden_corpus(const std::string& dir) {
    const Expect cases[] = {
        {"frame_record.bin",    {1, 0, 0, 0, 0, 0, 0},  true,  false},
        {"frame_empty.bin",     {1, 0, 0, 0, 0, 0, 0},  true,  false},
        {"frame_max.bin",       {1, 0, 0, 0, 0, 0, 0},  true,  false},
        {"frames_seqwrap.bin",  {2, 0, 0, 0, 0, 0, 0},  true,  false},
        {"frame_badcrc.bin",    {0, 1, 0, 1, 0, 0, 70}, false, false},
        {"frame_truncated.bin", {0, 0, 0, 0, 0, 0, 30}, false, false},
        {"recording_mini.tvcrec", {5, 1, 0, 1, 0, 1, 70}, false, true},
    };
    for (const auto& c : cases) {
        auto data = slurp(dir + "/" + c.file);
        const unsigned char* body = data.data() + (c.recording ? 32 : 0);
        const std::size_t body_len = data.size() - (c.recording ? 32 : 0);
        std::vector<telem::DecodedFrame> frames;
        const auto ctr = telem::decode_stream(body, body_len, frames);
        CHECK(ctr.frames_ok == c.ctr.frames_ok);
        CHECK(ctr.crc_errors == c.ctr.crc_errors);
        CHECK(ctr.version_mismatch == c.ctr.version_mismatch);
        CHECK(ctr.resyncs == c.ctr.resyncs);
        CHECK(ctr.seq_discontinuities == c.ctr.seq_discontinuities);
        CHECK(ctr.lost == c.ctr.lost);
        CHECK(ctr.skipped_bytes == c.ctr.skipped_bytes);
        if (!c.roundtrip) continue;
        std::vector<unsigned char> re;
        unsigned char frame[512];
        for (const auto& fr : frames) {
            const std::size_t m = telem::encode_frame(
                fr.type, fr.seq, body + fr.payload_off, fr.payload_len, frame);
            re.insert(re.end(), frame, frame + m);
        }
        CHECK(re.size() == body_len);
        CHECK(std::memcmp(re.data(), body, body_len) == 0);
    }
}
```

- [ ] **Step 2: Build and verify failure** — expected: `DecodeCounters` undeclared.

- [ ] **Step 3: Implement decode_stream** (header declares the two structs and the function; telemetry.cpp)

```cpp
DecodeCounters decode_stream(const unsigned char* data, std::size_t len,
                             std::vector<DecodedFrame>& out) {
    DecodeCounters ctr{};
    bool locked = true;
    bool have_expected = false;
    std::uint32_t expected = 0;
    std::size_t consumed = 0;
    std::size_t pos = 0;
    while (pos + 2 <= len) {
        if (!(data[pos] == 0x90 && data[pos + 1] == 0xEB)) { ++pos; continue; }
        if (pos + kFrameOverhead - 4 > len) break;    // header cut off
        const std::uint8_t ver = data[pos + 2];
        const std::uint8_t type = data[pos + 3];
        const std::size_t plen = data[pos + 4] |
                                 static_cast<std::size_t>(data[pos + 5]) << 8;
        const auto fail = [&](bool is_version, bool is_crc) {
            if (is_version) ++ctr.version_mismatch;
            if (is_crc) ++ctr.crc_errors;
            if (locked) { ++ctr.resyncs; locked = false; }
            ++pos;
        };
        if (ver != kVersion) { fail(true, false); continue; }
        if (!(type >= 1 && type <= 3) || plen > kMaxPayload) {
            fail(false, false); continue;
        }
        const std::size_t end = pos + kFrameOverhead + plen;
        if (end > len) break;                          // frame extends past buffer
        const std::uint32_t crc =
            static_cast<std::uint32_t>(data[end - 4]) |
            static_cast<std::uint32_t>(data[end - 3]) << 8 |
            static_cast<std::uint32_t>(data[end - 2]) << 16 |
            static_cast<std::uint32_t>(data[end - 1]) << 24;
        if (crc != crc32c(data + pos + 2, 8 + plen)) { fail(false, true); continue; }
        const std::uint32_t seq =
            static_cast<std::uint32_t>(data[pos + 6]) |
            static_cast<std::uint32_t>(data[pos + 7]) << 8 |
            static_cast<std::uint32_t>(data[pos + 8]) << 16 |
            static_cast<std::uint32_t>(data[pos + 9]) << 24;
        out.push_back({type, seq, pos + 10, plen});
        ++ctr.frames_ok;
        consumed += kFrameOverhead + plen;
        if (have_expected) {
            const std::uint32_t gap = seq - expected;   // u32 wrap is the mod
            if (gap >= 1 && gap < 0x80000000u) ctr.lost += gap;
            else if (gap >= 0x80000000u) ++ctr.seq_discontinuities;
        }
        expected = seq + 1;
        have_expected = true;
        locked = true;
        pos = end;
    }
    ctr.skipped_bytes = len - consumed;
    return ctr;
}
```

(`#include <vector>` in the header for the signature.)

- [ ] **Step 4: Build and run from the repo root** — `./build/wire_tests` — expected `wire_tests: ok`. Any corpus counter mismatch means the two decoders disagree: stop and reconcile against the spec's decoder rules before touching the expected values.

- [ ] **Step 5: Commit**

```bash
git add src/telemetry.hpp src/telemetry.cpp tests/cpp/wire_tests.cpp
git commit -m "add c++ decoder with corpus verification"
```

### Task 10: SpscRing, ring_stress, TSan lane, PR 3

**Files:**
- Modify: `src/telemetry.hpp`, `CMakeLists.txt`, `tests/ci.sh`
- Create: `tests/cpp/ring_stress.cpp`

**Interfaces:**
- Produces: `class SpscRing` (header-only, in telemetry.hpp):
  - `bool try_push(const Record& r) noexcept` — control thread only; false and counts a drop when full.
  - `std::size_t pop_batch(Record* out, std::size_t max) noexcept` — drain thread only.
  - `std::uint64_t drops() const noexcept` — producer-owned counter; call from the producer thread (or after it stops).
  - `static constexpr std::size_t kSlots = 4096;`

- [ ] **Step 1: Write the failing stress test**

```cpp
// tests/cpp/ring_stress.cpp — SPSC correctness under two real threads.
// Runs in the normal, ASan, and TSan trees; TSan is the reason it exists.
#include "../../src/telemetry.hpp"

#include <atomic>
#include <chrono>
#include <cstdio>
#include <cstdlib>
#include <random>
#include <thread>

#define CHECK(cond) do { if (!(cond)) { \
    std::fprintf(stderr, "FAIL %s:%d: %s\n", __FILE__, __LINE__, #cond); \
    std::exit(1); } } while (0)

namespace {

// Fields derived from tick so a torn read cannot go unnoticed.
telem::Record make(std::uint64_t i, std::uint64_t drops) {
    return {i, static_cast<std::int64_t>(3 * i + 1),
            static_cast<std::int64_t>(5 * i + 2),
            static_cast<std::int64_t>(7 * i + 3),
            static_cast<double>(i), -static_cast<double>(i), drops};
}

void check(const telem::Record& r) {
    const std::uint64_t i = r.tick;
    CHECK(r.deadline_ns == static_cast<std::int64_t>(3 * i + 1));
    CHECK(r.woke_ns == static_cast<std::int64_t>(5 * i + 2));
    CHECK(r.done_ns == static_cast<std::int64_t>(7 * i + 3));
    CHECK(r.theta == static_cast<double>(i));
    CHECK(r.cmd == -static_cast<double>(i));
}

}  // namespace

int main() {
    constexpr std::uint64_t kAttempts = 2'000'000;
    telem::SpscRing ring;
    std::atomic<bool> producer_done{false};
    std::uint64_t pushed = 0;

    std::thread producer([&] {
        for (std::uint64_t i = 0; i < kAttempts; ++i)
            if (ring.try_push(make(i, ring.drops()))) ++pushed;
        producer_done.store(true, std::memory_order_release);
    });

    std::uint64_t popped = 0, last_tick = 0;
    bool first = true;
    std::mt19937 rng(42);
    telem::Record batch[512];
    for (;;) {
        const std::size_t n = ring.pop_batch(batch, 512);
        for (std::size_t i = 0; i < n; ++i) {
            check(batch[i]);
            if (!first) CHECK(batch[i].tick > last_tick);   // FIFO, no dupes
            last_tick = batch[i].tick;
            first = false;
        }
        popped += n;
        if (n == 0) {
            if (producer_done.load(std::memory_order_acquire) &&
                ring.pop_batch(batch, 512) == 0) break;
            if (rng() % 8 == 0)   // stall to force full-ring drops
                std::this_thread::sleep_for(std::chrono::microseconds(200));
        }
    }
    producer.join();
    CHECK(popped == pushed);
    CHECK(pushed + ring.drops() == kAttempts);
    std::printf("ring_stress: ok (%llu pushed, %llu dropped)\n",
                static_cast<unsigned long long>(pushed),
                static_cast<unsigned long long>(ring.drops()));
    return 0;
}
```

Add to `CMakeLists.txt`:

```cmake
add_executable(ring_stress tests/cpp/ring_stress.cpp src/telemetry.cpp)
target_compile_definitions(ring_stress PRIVATE _GNU_SOURCE)
target_compile_options(ring_stress PRIVATE -Wall -Wextra -Wpedantic)
target_link_libraries(ring_stress PRIVATE Threads::Threads)
```

- [ ] **Step 2: Build and verify failure** — expected: `SpscRing` undeclared.

- [ ] **Step 3: Implement the ring** (telemetry.hpp; needs `<array>`, `<atomic>`)

```cpp
// Single-producer single-consumer ring. Producer is the control thread:
// try_push is allocation-free, syscall-free, lock-free, and wait-free.
// Drop-newest on full; the producer-owned drop counter is published
// in-stream via Record::drops.
class SpscRing {
public:
    static constexpr std::size_t kSlots = 4096;   // power of two, ~8 s at 500 Hz

    bool try_push(const Record& r) noexcept {
        const std::uint64_t head = head_.load(std::memory_order_relaxed);
        if (head - cached_tail_ == kSlots) {
            cached_tail_ = tail_.load(std::memory_order_acquire);
            if (head - cached_tail_ == kSlots) { ++drops_; return false; }
        }
        slots_[head & (kSlots - 1)] = r;
        head_.store(head + 1, std::memory_order_release);
        return true;
    }

    std::size_t pop_batch(Record* out, std::size_t max) noexcept {
        const std::uint64_t head = head_.load(std::memory_order_acquire);
        std::uint64_t tail = tail_.load(std::memory_order_relaxed);
        std::size_t n = 0;
        while (tail != head && n < max) out[n++] = slots_[tail++ & (kSlots - 1)];
        tail_.store(tail, std::memory_order_release);
        return n;
    }

    std::uint64_t drops() const noexcept { return drops_; }

private:
    std::array<Record, kSlots> slots_{};
    alignas(64) std::atomic<std::uint64_t> head_{0};
    alignas(64) std::atomic<std::uint64_t> tail_{0};
    alignas(64) std::uint64_t cached_tail_ = 0;   // producer-owned
    std::uint64_t drops_ = 0;                     // producer-owned
};
```

- [ ] **Step 4: Build and run** — `./build/ring_stress` — expected `ring_stress: ok (...)` with a nonzero drop count (the stalls force fulls).

- [ ] **Step 5: Extend tests/ci.sh** — run both binaries in the existing trees and add the TSan tree. After the normal build line (`cmake --build build -j`) add:

```bash
./build/wire_tests
./build/ring_stress
```

After the ASan functional run add:

```bash
./build-asan/wire_tests
./build-asan/ring_stress
cmake -S . -B build-tsan -DCMAKE_BUILD_TYPE=RelWithDebInfo \
  -DCMAKE_CXX_FLAGS="-fsanitize=thread"
cmake --build build-tsan --target ring_stress -j
./build-tsan/ring_stress
```

- [ ] **Step 6: Run the full gate** — `docker run --rm -v "$PWD":/w -w /w --cap-add=IPC_LOCK --ulimit memlock=-1:-1 tvc-dev bash tests/ci.sh` — expected `ci.sh: all green`. TSan findings are real bugs; fix the ring, never the test.

- [ ] **Step 7: Commit and open PR 3**

```bash
git add src/telemetry.hpp tests/cpp/ring_stress.cpp CMakeLists.txt tests/ci.sh
git commit -m "add spsc ring with tsan stress lane"
git push -u origin telemetry-cpp
```

PR with base `telemetry-codec`, title "v0.2a c++ codec and spsc ring". AI-assistance section: Agent: Claude Code (model); Verification: the ci.sh run.

---

## PR 4 — drain thread and harness integration (Claude Code; branch `telemetry-integration`, stacked on `telemetry-cpp`)

Setup: `git checkout telemetry-cpp && git checkout -b telemetry-integration`.

### Task 11: recording header and Drain

**Files:**
- Modify: `src/telemetry.hpp`, `src/telemetry.cpp`

**Interfaces:**
- Produces: `std::size_t encode_recording_header(std::int64_t mono_ns, std::int64_t epoch_ns, unsigned char* out) noexcept` — writes exactly 32 bytes, returns 32. `class Drain`:
  - `explicit Drain(SpscRing& ring)`
  - `void start(std::FILE* f)` — takes an open file whose 32-byte header is already written; spawns the thread. Call before rt setup so the thread inherits SCHED_OTHER.
  - `void stop()` — signals, drains the ring empty, flushes, closes the file, joins. Idempotent-free: call exactly once, after the loop.
  - After stop(): `bool write_failed() const noexcept`, `std::uint64_t records_written() const noexcept`, `std::uint64_t bytes_written() const noexcept` (frame bytes; the caller adds 32 for the header when reporting file size).

- [ ] **Step 1: Write the failing test** (add to wire_tests.cpp and call all three from main — the drain is testable without the harness: fill a ring, run a drain against a file, decode the bytes with the Task 9 decoder)

```cpp
void test_header_layout() {
    unsigned char h[32];
    CHECK(telem::encode_recording_header(1000, 2000, h) == 32);
    CHECK(std::memcmp(h, "TVCRECRD", 8) == 0);
    CHECK(h[8] == 1 && h[9] == 0);                    // version LE
    CHECK(h[10] == 0 && h[11] == 0);                  // reserved
    const std::uint32_t sh = static_cast<std::uint32_t>(h[12]) |
        static_cast<std::uint32_t>(h[13]) << 8 |
        static_cast<std::uint32_t>(h[14]) << 16 |
        static_cast<std::uint32_t>(h[15]) << 24;
    CHECK(sh == telem::kSchemaHash);
    CHECK(h[16] == 0xE8 && h[17] == 0x03);            // 1000 LE
}

void test_drain_counters() {
    telem::SpscRing ring;
    for (std::uint64_t i = 0; i < 100; ++i) {
        telem::Record r{i, 1, 2, 3, 0.5, -0.5, 0};
        CHECK(ring.try_push(r));
    }
    std::FILE* f = std::tmpfile();
    CHECK(f != nullptr);
    telem::Drain drain(ring);
    drain.start(f);
    drain.stop();        // drains until empty, then flushes and closes f
    CHECK(!drain.write_failed());
    CHECK(drain.records_written() == 100);
    CHECK(drain.bytes_written() == 100 * 70);
}
```

And a decodable-output case using a named file (run from the repo root, so build/ exists):

```cpp
void test_drain_output_decodes() {
    telem::SpscRing ring;
    for (std::uint64_t i = 0; i < 5; ++i)
        CHECK(ring.try_push({i, 1, 2, 3, 0.0, 0.0, 0}));
    const char* path = "build/drain_test.bin";
    std::FILE* f = std::fopen(path, "wb+");
    CHECK(f != nullptr);
    telem::Drain drain(ring);
    drain.start(f);
    drain.stop();
    auto data = slurp(path);
    CHECK(data.size() == 5 * 70);
    std::vector<telem::DecodedFrame> frames;
    const auto ctr = telem::decode_stream(data.data(), data.size(), frames);
    CHECK(ctr.frames_ok == 5 && ctr.lost == 0 && ctr.skipped_bytes == 0);
    for (std::size_t i = 0; i < 5; ++i) {
        CHECK(frames[i].seq == i);                    // seq assigned by drain
        CHECK(frames[i].type == telem::kTypeTelemetry);
    }
    std::remove(path);
}
```

- [ ] **Step 2: Build and verify failure** — expected: `Drain` undeclared.

- [ ] **Step 3: Implement** (header declares; telemetry.cpp; needs `<thread>`, `<ctime>`, `<cstdio>`)

```cpp
// header:
std::size_t encode_recording_header(std::int64_t mono_ns,
                                    std::int64_t epoch_ns,
                                    unsigned char* out) noexcept;

// Consumer side of the ring. Runs SCHED_OTHER off the isolated core (it
// inherits scheduling from whoever calls start(); call before rt setup).
// The alloc guard's flag is thread_local, so this thread may allocate.
class Drain {
public:
    explicit Drain(SpscRing& ring) : ring_(ring) {}
    void start(std::FILE* f);
    void stop();
    bool write_failed() const noexcept {
        return write_failed_.load(std::memory_order_relaxed);
    }
    std::uint64_t records_written() const noexcept { return records_; }
    std::uint64_t bytes_written() const noexcept { return bytes_; }

private:
    void run();
    SpscRing& ring_;
    std::FILE* file_ = nullptr;
    std::thread thread_;
    std::atomic<bool> stop_{false};
    std::atomic<bool> write_failed_{false};
    std::uint64_t records_ = 0;   // thread-owned; read after stop()
    std::uint64_t bytes_ = 0;
    std::uint32_t seq_ = 0;
};
```

```cpp
// telemetry.cpp:
namespace {
inline void put64(unsigned char* p, std::uint64_t v) noexcept {
    for (int i = 0; i < 8; ++i) p[i] = static_cast<unsigned char>(v >> (8 * i));
}
}  // namespace

std::size_t encode_recording_header(std::int64_t mono_ns,
                                    std::int64_t epoch_ns,
                                    unsigned char* out) noexcept {
    std::memcpy(out, "TVCRECRD", 8);
    put16(out + 8, 1);
    put16(out + 10, 0);
    put32(out + 12, kSchemaHash);
    put64(out + 16, static_cast<std::uint64_t>(mono_ns));
    put64(out + 24, static_cast<std::uint64_t>(epoch_ns));
    return 32;
}

void Drain::start(std::FILE* f) {
    file_ = f;
    thread_ = std::thread([this] { run(); });
}

void Drain::stop() {
    stop_.store(true, std::memory_order_release);
    thread_.join();
}

void Drain::run() {
    Record batch[512];
    unsigned char frame[kFrameOverhead + sizeof(Record)];
    for (;;) {
        const std::size_t n = ring_.pop_batch(batch, 512);
        for (std::size_t i = 0; i < n; ++i) {
            const std::size_t len = encode_frame(
                kTypeTelemetry, seq_++, &batch[i], sizeof(Record), frame);
            if (std::fwrite(frame, 1, len, file_) != len)
                write_failed_.store(true, std::memory_order_relaxed);
            else { ++records_; bytes_ += len; }
        }
        if (n == 0) {
            if (stop_.load(std::memory_order_acquire)) break;
            const timespec ts{0, 1000000};   // 1 ms poll; no futex from the producer
            ::clock_nanosleep(CLOCK_MONOTONIC, 0, &ts, nullptr);
        }
    }
    if (std::fflush(file_) != 0)
        write_failed_.store(true, std::memory_order_relaxed);
    std::fclose(file_);
}
```

- [ ] **Step 4: Build and run** — `./build/wire_tests` from the repo root — expected `wire_tests: ok`.

- [ ] **Step 5: Commit**

```bash
git add src/telemetry.hpp src/telemetry.cpp tests/cpp/wire_tests.cpp
git commit -m "add recording header and drain thread"
```

### Task 12: main.cpp and loop_stats integration

**Files:**
- Modify: `src/main.cpp`, `src/loop_stats.hpp:67-70`, `src/loop_stats.cpp:102-137`

**Interfaces:**
- Consumes: `telem::SpscRing`, `telem::Drain`, `telem::encode_recording_header`, `telem::Record`.
- Produces: `--telemetry` flag; `applied` gains `"telemetry"` (always present, true when not requested or requested-and-ok, matching the mlock/fifo/cpu pattern at main.cpp:308-311); `config_string` appends `"telemetry"`; summary.json gains `"telemetry": {"records": N, "dropped": N, "bytes": N}` when enabled (bytes = 32 + frame bytes = file size); exit 2 on open failure, exit 4 on drain write failure. `LoopStats::write_json` gains a trailing `const std::string& telemetry_json` parameter (empty string = omit the key).

- [ ] **Step 1: Make the changes.** In order through main.cpp:

1. `#include "telemetry.hpp"`, `#include <memory>` (top).
2. `Config` gains `bool telemetry = false;` (after `naive_log`).
3. `usage()` gains, after the `--alloc-guard` line: `"  --telemetry         framed telemetry through the SPSC ring to <label>.telemetry.tvcrec\n"`.
4. `parse()` gains: `else if (!std::strcmp(a, "--telemetry")) c.telemetry = true;`.
5. `config_string()` gains, after the naive-log line: `if (c.telemetry) s += "telemetry ";`.
6. Between the prctl call (line 278) and the privileges block (line 286), the telemetry startup (order per spec: mkdir, open + header, spawn drain, and only then rt setup):

```cpp
    // ---- telemetry sink, before rt setup: the drain thread inherits
    // SCHED_OTHER and the default affinity mask (isolcpus keeps it off
    // the isolated core) ----
    bool ok_telem = !cfg.telemetry;
    std::unique_ptr<telem::SpscRing> ring;
    std::unique_ptr<telem::Drain> drain;
    if (cfg.telemetry) {
        ::mkdir(cfg.outdir.c_str(), 0755);
        const std::string tpath =
            cfg.outdir + "/" + cfg.label + ".telemetry.tvcrec";
        std::FILE* tf = std::fopen(tpath.c_str(), "wb");
        if (tf) {
            unsigned char hdr[32];
            timespec rt{};
            // One-shot wall anchor for the header, off the hot path; the
            // control path itself never reads CLOCK_REALTIME.
            ::clock_gettime(CLOCK_REALTIME, &rt);
            telem::encode_recording_header(
                now_ns(), rt.tv_sec * kNsPerSec + rt.tv_nsec, hdr);
            ok_telem = std::fwrite(hdr, 1, sizeof hdr, tf) == sizeof hdr;
            if (!ok_telem) std::fclose(tf);
        }
        if (tf && ok_telem) {
            ring = std::make_unique<telem::SpscRing>();
            drain = std::make_unique<telem::Drain>(*ring);
            drain->start(tf);
        } else {
            ok_telem = false;
        }
        std::printf("  telemetry  %-4s %s\n", ok_telem ? "ok" : "FAIL",
                    tpath.c_str());
    }
```

7. `applied_json` (line 308) gains: `+ ", \"telemetry\": " + b(!cfg.telemetry || ok_telem)` before the closing brace.
8. The hook, after `const std::int64_t done = now_ns();` (line 371):

```cpp
        if (ring) {
            guard::Cycle telem_cycle;   // the push must stay allocation-free
            telem::Record rec;
            rec.tick        = static_cast<std::uint64_t>(n);
            rec.deadline_ns = deadline;
            rec.woke_ns     = woke;
            rec.done_ns     = done;
            rec.theta       = plant.theta;
            rec.cmd         = plant.last_cmd;
            rec.drops       = ring->drops();
            ring->try_push(rec);
        }
```

9. After `guard::set_mode(guard::Mode::Off);` (line 382): `if (drain) drain->stop();` — before the report, so the counters below are final.
10. Before the write_json call, build the block and pass it:

```cpp
    std::string telemetry_json;
    if (drain)
        telemetry_json =
            "{ \"records\": " + std::to_string(drain->records_written()) +
            ", \"dropped\": " + std::to_string(ring->drops()) +
            ", \"bytes\": " + std::to_string(32 + drain->bytes_written()) + " }";
```

11. Exit codes (lines 441-447): add `const bool telem_failed = drain && drain->write_failed();` and change the write check to `if (!wrote_ok || telem_failed) return 4;`. Open failure already lands in exit 2 through `ok_telem`: extend `mitigation_failed` with `|| (cfg.telemetry && !ok_telem)`.

12. `loop_stats.hpp`: `write_json(..., std::int64_t cycles_requested, const std::string& telemetry_json)`. `loop_stats.cpp`: drop the trailing `"}\n"` from the big format string (end it after the exec_us line with `"  \"exec_us\": { \"p50\": %.3f, \"p99.9\": %.3f, \"max\": %.3f }"`), then:

```cpp
    if (!telemetry_json.empty())
        std::fprintf(f, ",\n  \"telemetry\": %s", telemetry_json.c_str());
    std::fputs("\n}\n", f);
```

Call site in main.cpp passes `telemetry_json`.

- [ ] **Step 2: Build and run the existing functional suite** (regression check before the new test lands):

`docker run --rm -v "$PWD":/w -w /w --cap-add=IPC_LOCK --ulimit memlock=-1:-1 tvc-dev bash -c 'cmake -S . -B build && cmake --build build -j && python3 -m unittest discover -s tests/unit -v && TVC_BIN=$PWD/build/tvc_harness python3 -m unittest discover -s tests/functional -v'`
Expected: all PASS (test_summary parses summary.json, so a malformed telemetry splice fails here).

- [ ] **Step 3: Commit**

```bash
git add src/main.cpp src/loop_stats.hpp src/loop_stats.cpp
git commit -m "wire telemetry flag, hook, and summary block into the harness"
```

### Task 13: functional test

**Files:**
- Create: `tests/functional/test_telemetry.py`

**Interfaces:**
- Consumes: the built harness via `TVC_BIN`, `ground.wire`.

- [ ] **Step 1: Write the test**

```python
import json
import os
import pathlib
import subprocess
import sys
import tempfile
import unittest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[2]))
from ground import wire

BIN = os.environ["TVC_BIN"]


class Telemetry(unittest.TestCase):
    def test_recording_matches_summary(self):
        with tempfile.TemporaryDirectory() as d:
            rc = subprocess.run(
                [BIN, "--label=t", f"--out={d}", "--rate=1000",
                 "--cycles=2000", "--warmup=100", "--telemetry"]).returncode
            self.assertEqual(rc, 0)
            rec_path = pathlib.Path(d) / "t.telemetry.tvcrec"
            header, records, ctr = wire.read_recording(rec_path)
            self.assertTrue(header["schema_known"])
            self.assertEqual(len(records), 2100)          # cycles + warmup
            self.assertEqual(sum(1 for r in records if r.tick >= 100), 2000)
            self.assertEqual(ctr["crc_errors"], 0)
            self.assertEqual(ctr["lost"], 0)
            self.assertEqual(ctr["seq_discontinuities"], 0)
            self.assertEqual(ctr["skipped_bytes"], 0)
            self.assertEqual(records[-1].drops, 0)        # 4096-slot ring > run
            summary = json.loads((pathlib.Path(d) / "t.summary.json").read_text())
            self.assertTrue(summary["applied"]["telemetry"])
            self.assertIn("telemetry", summary["config"])
            t = summary["telemetry"]
            self.assertEqual(t["records"], 2100)
            self.assertEqual(t["dropped"], 0)
            self.assertEqual(t["bytes"], rec_path.stat().st_size)

    def test_no_flag_no_recording(self):
        with tempfile.TemporaryDirectory() as d:
            rc = subprocess.run(
                [BIN, "--label=t", f"--out={d}", "--rate=1000",
                 "--cycles=500", "--warmup=50"]).returncode
            self.assertEqual(rc, 0)
            self.assertFalse((pathlib.Path(d) / "t.telemetry.tvcrec").exists())
            summary = json.loads((pathlib.Path(d) / "t.summary.json").read_text())
            self.assertNotIn("telemetry", summary)
            self.assertTrue(summary["applied"]["telemetry"])  # not requested

    def test_unwritable_outdir_is_failed_mitigation(self):
        rc = subprocess.run(
            [BIN, "--label=t", "--out=/proc/no_such_dir", "--rate=1000",
             "--cycles=100", "--warmup=10", "--telemetry"]).returncode
        self.assertIn(rc, (2, 4))   # open fails: mitigation failed (2); the
                                    # summary write also fails there (4 wins
                                    # only if wrote_ok check precedes)
```

Note on the third test: main returns 4 before 2 when both fail (`if (!wrote_ok ...) return 4;` precedes the mitigation check), and with an unwritable outdir both do fail. Keep the assertion on the pair; the point is a loud nonzero exit either way.

- [ ] **Step 2: Run to verify it passes**

`docker run --rm -v "$PWD":/w -w /w --cap-add=IPC_LOCK --ulimit memlock=-1:-1 tvc-dev bash -c 'cmake --build build -j && TVC_BIN=$PWD/build/tvc_harness python3 -m unittest tests.functional.test_telemetry -v'`
Expected: 3 tests PASS. (Written after the implementation, so no red step; the earlier regression run covered the pre-state.)

- [ ] **Step 3: Commit**

```bash
git add tests/functional/test_telemetry.py
git commit -m "add functional telemetry test"
```

### Task 14: sweep L6, gate, PR 4

**Files:**
- Modify: `scripts/sweep.py:26-33`, `tests/unit/test_sweep.py:5-15`

- [ ] **Step 1: Extend the failing test first** — in `tests/unit/test_sweep.py`, `test_full_chain_with_cpu` expected list becomes `["L0", "L1", "L2", "L3", "L4", "L5", "L6"]`. Run `python3 -m unittest tests.unit.test_sweep -v`: FAIL.

- [ ] **Step 2: Append the level** to `LEVELS` in sweep.py:

```python
    ("L6", "+ telemetry ring + drain thread", ["--telemetry"]),
```

Run again: PASS. (`test_chain_breaks_at_first_skipped_level` still expects the stop at L3 and stays untouched; bench_gate's `L5*` glob does not match L6 labels.)

- [ ] **Step 3: Full gate** — `docker run --rm -v "$PWD":/w -w /w --cap-add=IPC_LOCK --ulimit memlock=-1:-1 tvc-dev bash tests/ci.sh` — expected `ci.sh: all green`.

- [ ] **Step 4: Commit and open PR 4**

```bash
git add scripts/sweep.py tests/unit/test_sweep.py
git commit -m "add sweep level l6 for telemetry"
git push -u origin telemetry-integration
```

PR with base `telemetry-cpp`, title "v0.2a drain thread and harness integration". AI-assistance section: Agent: Claude Code (model); Verification: full ci.sh output plus the functional telemetry run.

---

## PR 5 — campaign (human-run, ProBook)

Not agent tasks; the runbook for Mamadou after PRs 2-4 merge:

1. Reboot the ProBook to the generic kernel (config of record; it is still on PREEMPT_RT from the one-shot grub-reboot) and reapply runtime discipline: governor, EPP, cpuidle, IRQ affinity per docs/qualification.md.
2. Pull main, rebuild: `cmake -S . -B build && cmake --build build -j`.
3. `./scripts/sweep.py --cpu 7 --repeat 3 --out results/2026-MM-DD-telemetry-campaign` (L0-L6).
4. Acceptance check 1: L6 median p99.9 within 10% of L5 median in this campaign (sweep table shows both).
5. Acceptance check 2: `python3 scripts/bench_gate.py --results results/2026-MM-DD-telemetry-campaign` (L5 vs baselines/2026-08-15-campaign-2) passes.
6. Sanity: `python3 -m ground.wire results/2026-MM-DD-telemetry-campaign/L6.r1.telemetry.tvcrec` — records 305000, zero crc_errors, drops per the in-stream counter.
7. Figure: `./scripts/plot_jitter.py --results results/2026-MM-DD-telemetry-campaign`.
8. PR: campaign dir into baselines/, figure, results.md v0.2a section. ai-log entry after merge.

## Plan-wide verification

- After PR 2: `python3 -m unittest discover -s tests/unit` green natively and in the container; corpus regenerates byte-stable.
- After PR 3: full ci.sh green including the TSan lane.
- After PR 4: full ci.sh green; functional telemetry test green in normal and ASan trees.
- After PR 5: both acceptance checks pass; the CDF overlay shows L5 and L6 on top of each other.
