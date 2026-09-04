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
TYPES = (1, 2, 3, 4, 5, 6)
MAX_PAYLOAD = 498
SCHEMA = ("telemetry_v1:tick:u64,deadline_ns:i64,woke_ns:i64,done_ns:i64,"
          "theta:f64,cmd:f64,drops:u64")
SCHEMA_HASH = 0xA871CD84

# Payload schemas are separate from generic stream framing.
SCHEMAS = {
    1: SCHEMA,
    2: "command_v1:cmd_seq:u32,opcode:u16,flags:u16,effective_tick:u64",
    3: "ack_v1:applied_tick:u64,cmd_seq:u32,status:u16,state:u8,reason:u8",
    4: ("sensor_v1:tick:u64,t_send_ns:i64,theta:f64,omega:f64,flags:u32,"
        "cmd_seq:u32,sim_reason:u32"),
    5: ("actuator_v1:tick:u64,veh_tick:u64,t_sensor_send_ns:i64,t_veh_send_ns:i64,"
        "delta:f64,status:u32,staleness:u32"),
    6: ("control_v1:tick:u64,deadline_ns:i64,woke_ns:i64,done_ns:i64,"
        "sensor_send_ns:i64,rx_ns:i64,tx_ns:i64,sensor_tick:u64,theta:f64,"
        "omega:f64,cmd:f64,i_state:f64,d_prev:f64,drops:u64,staleness:u32,"
        "ack_cmd_seq:u32,rx_count:u8,discarded_old:u8,discarded_superseded:u8,"
        "discarded_other:u8,state:u8,reason:u8,flags:u8,ack_status:u8"),
}
SCHEMA_HASHES = {
    1: SCHEMA_HASH, 2: 0x7F802902, 3: 0x3D42AF39,
    4: 0xD23A4196, 5: 0x25573656, 6: 0xADFA94C8,
}
PAYLOAD_SIZES = {1: 56, 2: 16, 3: 16, 4: 44, 5: 48, 6: 128}
# Each supported recording schema declares one type.
FILE_SCHEMAS = {SCHEMA_HASHES[1]: 1, SCHEMA_HASHES[4]: 4, SCHEMA_HASHES[6]: 6}

MAGIC = b"TVCRECRD"

HEADER = struct.Struct("<8sHHIqq")    # magic, version, reserved, schema_hash, mono, epoch
FRAME_HEAD = struct.Struct("<HBBHI")  # sync, version, type, length, seq
RECORD = struct.Struct("<QqqqddQ")
CRC = struct.Struct("<I")

Record = collections.namedtuple(
    "Record", "tick deadline_ns woke_ns done_ns theta cmd drops")


def crc32c(data: bytes) -> int:
    return google_crc32c.value(data)


_FIELD_WIDTHS = {"u8": 1, "u16": 2, "u32": 4, "u64": 8, "i64": 8, "f64": 8}
_PAYLOAD_FIELDS = {
    1: (("tick", 0, "u64"), ("deadline_ns", 8, "i64"), ("woke_ns", 16, "i64"),
        ("done_ns", 24, "i64"), ("theta", 32, "f64"), ("cmd", 40, "f64"), ("drops", 48, "u64")),
    2: (("cmd_seq", 0, "u32"), ("opcode", 4, "u16"), ("flags", 6, "u16"), ("effective_tick", 8, "u64")),
    3: (("applied_tick", 0, "u64"), ("cmd_seq", 8, "u32"), ("status", 12, "u16"),
        ("state", 14, "u8"), ("reason", 15, "u8")),
    4: (("tick", 0, "u64"), ("t_send_ns", 8, "i64"), ("theta", 16, "f64"), ("omega", 24, "f64"),
        ("flags", 32, "u32"), ("cmd_seq", 36, "u32"), ("sim_reason", 40, "u32")),
    5: (("tick", 0, "u64"), ("veh_tick", 8, "u64"), ("t_sensor_send_ns", 16, "i64"),
        ("t_veh_send_ns", 24, "i64"), ("delta", 32, "f64"), ("status", 40, "u32"), ("staleness", 44, "u32")),
    6: (("tick", 0, "u64"), ("deadline_ns", 8, "i64"), ("woke_ns", 16, "i64"), ("done_ns", 24, "i64"),
        ("sensor_send_ns", 32, "i64"), ("rx_ns", 40, "i64"), ("tx_ns", 48, "i64"), ("sensor_tick", 56, "u64"),
        ("theta", 64, "f64"), ("omega", 72, "f64"), ("cmd", 80, "f64"), ("i_state", 88, "f64"),
        ("d_prev", 96, "f64"), ("drops", 104, "u64"), ("staleness", 112, "u32"), ("ack_cmd_seq", 116, "u32"),
        ("rx_count", 120, "u8"), ("discarded_old", 121, "u8"), ("discarded_superseded", 122, "u8"),
        ("discarded_other", 123, "u8"), ("state", 124, "u8"), ("reason", 125, "u8"),
        ("flags", 126, "u8"), ("ack_status", 127, "u8")),
}


def _check_payload_counts(ftype, fields):
    if ftype == 6:
        # Python integers keep the sum wide even for byte values summing past 255.
        discarded = fields["discarded_old"] + fields["discarded_superseded"] + fields["discarded_other"]
        if fields["rx_count"] > 9 or discarded > fields["rx_count"]:
            raise ValueError("invalid control counts")


def encode_payload(ftype, fields):
    """Encode a field mapping at explicit offsets; no episode/enum evaluation."""
    if ftype not in _PAYLOAD_FIELDS:
        raise ValueError(f"bad payload type {ftype}")
    _check_payload_counts(ftype, fields)
    payload = bytearray(PAYLOAD_SIZES[ftype])
    for name, offset, kind in _PAYLOAD_FIELDS[ftype]:
        value = fields[name]
        if name == "flags" and ftype in (2, 4):
            value &= 0x0001 if ftype == 2 else 0x0000FF07
        width = _FIELD_WIDTHS[kind]
        scalar = (struct.pack("<d", value) if kind == "f64" else
                  value.to_bytes(width, "little", signed=kind == "i64"))
        payload[offset:offset + width] = scalar
    return bytes(payload)


def decode_payload(ftype, data):
    """Return decoded fields; reserved flag bits are tolerated, not interpreted."""
    if ftype not in _PAYLOAD_FIELDS:
        raise ValueError(f"bad payload type {ftype}")
    if len(data) != PAYLOAD_SIZES[ftype]:
        raise ValueError(f"type-{ftype} payload length {len(data)} != {PAYLOAD_SIZES[ftype]}")
    fields = {}
    for name, offset, kind in _PAYLOAD_FIELDS[ftype]:
        fields[name] = (struct.unpack_from("<d", data, offset)[0] if kind == "f64" else
                        int.from_bytes(data[offset:offset + _FIELD_WIDTHS[kind]], "little", signed=kind == "i64"))
    _check_payload_counts(ftype, fields)
    return fields


def decode_datagram(data, accepted_types):
    """Return one (type, seq, raw payload); typed decoding is a separate step."""
    if len(data) < FRAME_HEAD.size + CRC.size:
        raise ValueError("bad_length: truncated datagram")
    sync, version, ftype, length, seq = FRAME_HEAD.unpack_from(data)
    if sync != SYNC:
        raise ValueError("bad_sync")
    if version != VERSION:
        raise ValueError("bad_version")
    if ftype not in PAYLOAD_SIZES or ftype not in accepted_types:
        raise ValueError("bad_type")
    if length != PAYLOAD_SIZES[ftype] or len(data) != FRAME_HEAD.size + length + CRC.size:
        raise ValueError("bad_length")
    if CRC.unpack_from(data, len(data) - CRC.size)[0] != crc32c(bytes(data[2:-CRC.size])):
        raise ValueError("bad_crc")
    return ftype, seq, bytes(data[FRAME_HEAD.size:-CRC.size])


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


def read_typed_recording(path, *, expected_type):
    """Schema-valid recovered records, not a clean-recording/evidence verdict.

    Callers must check the returned recovery counters before using the records
    as evidence. The legacy telemetry diagnostic reader remains separate.
    """
    if expected_type not in (1, 4, 6):
        raise ValueError(f"unsupported expected_type {expected_type}")
    with open(path, "rb") as f:
        data = f.read()
    if len(data) < HEADER.size:
        raise ValueError("recording shorter than its header")
    magic, version, reserved, schema_hash, mono, epoch = HEADER.unpack_from(data)
    if magic != MAGIC:
        raise ValueError(f"bad magic {magic!r}")
    if version != VERSION:
        raise ValueError(f"unsupported recording version {version}")
    if reserved != 0:
        raise ValueError("nonzero reserved header word")
    if schema_hash not in FILE_SCHEMAS:
        raise ValueError(f"unknown file schema 0x{schema_hash:08x}")
    if FILE_SCHEMAS[schema_hash] != expected_type:
        raise ValueError(f"file schema does not match expected_type {expected_type}")
    header = {"magic": magic, "version": version, "schema_hash": schema_hash,
              "start_monotonic_ns": mono, "start_epoch_ns": epoch, "schema_known": True}
    frames, ctr = decode_stream(data[HEADER.size:])
    records = []
    for ftype, seq, payload in frames:
        if ftype != expected_type:
            raise ValueError(f"recovered type {ftype} at seq {seq} != declared type {expected_type}")
        records.append(decode_payload(ftype, payload))
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
