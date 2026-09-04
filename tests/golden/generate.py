#!/usr/bin/env python3
# tests/golden/generate.py: regenerate the golden corpus. Byte-stable:
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
    "frame_sensor.bin": "canonical type-4 sensor frame",
    "frame_actuator.bin": "canonical type-5 actuator frame",
    "frame_command.bin": "canonical type-2 command frame",
    "frame_ack.bin": "canonical type-3 acknowledgment frame",
    "frame_control.bin": "canonical type-6 control frame",
    "recording_control_mini.tvcrec":
        "header + six control frames, seq-2 frame corrupted, proving resync",
}
ROUNDTRIP = {
    "frame_record.bin": True, "frame_empty.bin": True, "frame_max.bin": True,
    "frames_seqwrap.bin": True, "frame_badcrc.bin": False,
    "frame_truncated.bin": False, "recording_mini.tvcrec": False,
    "frame_sensor.bin": True, "frame_actuator.bin": True, "frame_command.bin": True,
    "frame_ack.bin": True, "frame_control.bin": True, "recording_control_mini.tvcrec": False,
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

    # Synthetic wire vectors, not a physical or episode trajectory.
    control = dict(tick=1, deadline_ns=-2, woke_ns=3, done_ns=4, sensor_send_ns=5,
                   rx_ns=6, tx_ns=7, sensor_tick=8, theta=1.25, omega=-2.5, cmd=-0.0,
                   i_state=3.75, d_prev=-4.5, drops=14, staleness=15, ack_cmd_seq=16,
                   rx_count=9, discarded_old=1, discarded_superseded=2, discarded_other=3,
                   state=4, reason=5, flags=0x76, ack_status=7)
    payloads = {
        2: wire.encode_payload(2, dict(cmd_seq=0x01020304, opcode=3, flags=1,
                                      effective_tick=0x1112131415161718)),
        3: wire.encode_payload(3, dict(applied_tick=0x2122232425262728, cmd_seq=0x31323334,
                                      status=2, state=1, reason=7)),
        4: wire.encode_payload(4, dict(tick=0x0102030405060708, t_send_ns=-2,
                                      theta=1.25, omega=-2.5, flags=0x0307,
                                      cmd_seq=0x21222324, sim_reason=2)),
        5: wire.encode_payload(5, dict(tick=0x0102030405060708, veh_tick=0x1112131415161718,
                                      t_sensor_send_ns=-3, t_veh_send_ns=0x2122232425262728,
                                      delta=-0.125, status=0x84030201, staleness=0x31323334)),
        6: wire.encode_payload(6, control),
    }
    for name, ftype, seq in (("frame_sensor.bin", 4, 0), ("frame_actuator.bin", 5, 1),
                             ("frame_command.bin", 2, 2), ("frame_ack.bin", 3, 3),
                             ("frame_control.bin", 6, 4)):
        files[name] = wire.encode_frame(ftype, seq, payloads[ftype])
    frames = [wire.encode_frame(6, n, wire.encode_payload(6, dict(control, tick=n)))
              for n in range(6)]
    frames[2] = corrupt_last(frames[2])
    header = wire.HEADER.pack(wire.MAGIC, wire.VERSION, 0, wire.SCHEMA_HASHES[6],
                              1_000_000_000, 1_755_000_000_000_000_000)
    files["recording_control_mini.tvcrec"] = header + b"".join(frames)
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
    doc = {"schema_hash": "0xA871CD84", "files": entries,
           "file_schemas": {f"0x{digest:08X}": ftype for digest, ftype in wire.FILE_SCHEMAS.items()}}
    (out / "manifest.json").write_text(
        json.dumps(doc, indent=2, sort_keys=True) + "\n")


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else None)
