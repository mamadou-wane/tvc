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
