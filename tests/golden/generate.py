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
