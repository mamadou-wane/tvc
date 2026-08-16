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


def encode_frame(ftype: int, seq: int, payload: bytes) -> bytes:
    if ftype not in TYPES:
        raise ValueError(f"bad frame type {ftype}")
    if len(payload) > MAX_PAYLOAD:
        raise ValueError(f"payload {len(payload)} exceeds {MAX_PAYLOAD}")
    head = FRAME_HEAD.pack(SYNC, VERSION, ftype, len(payload), seq % 2**32)
    return head + payload + CRC.pack(crc32c(head[2:] + payload))


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
