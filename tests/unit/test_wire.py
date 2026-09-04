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


class PayloadMetadata(unittest.TestCase):
    def test_schema_strings_and_hashes(self):
        self.assertTrue(hasattr(wire, "SCHEMAS"), "payload schemas not implemented")
        self.assertTrue(hasattr(wire, "SCHEMA_HASHES"), "payload hashes not implemented")
        expected = {
            1: ("telemetry_v1:tick:u64,deadline_ns:i64,woke_ns:i64,done_ns:i64,"
                "theta:f64,cmd:f64,drops:u64", 0xA871CD84),
            2: ("command_v1:cmd_seq:u32,opcode:u16,flags:u16,effective_tick:u64", 0x7F802902),
            3: ("ack_v1:applied_tick:u64,cmd_seq:u32,status:u16,state:u8,reason:u8", 0x3D42AF39),
            4: ("sensor_v1:tick:u64,t_send_ns:i64,theta:f64,omega:f64,"
                "flags:u32,cmd_seq:u32,sim_reason:u32", 0xD23A4196),
            5: ("actuator_v1:tick:u64,veh_tick:u64,t_sensor_send_ns:i64,"
                "t_veh_send_ns:i64,delta:f64,status:u32,staleness:u32", 0x25573656),
            6: ("control_v1:tick:u64,deadline_ns:i64,woke_ns:i64,done_ns:i64,"
                "sensor_send_ns:i64,rx_ns:i64,tx_ns:i64,sensor_tick:u64,theta:f64,"
                "omega:f64,cmd:f64,i_state:f64,d_prev:f64,drops:u64,staleness:u32,"
                "ack_cmd_seq:u32,rx_count:u8,discarded_old:u8,discarded_superseded:u8,"
                "discarded_other:u8,state:u8,reason:u8,flags:u8,ack_status:u8", 0xADFA94C8),
        }
        self.assertEqual(set(wire.SCHEMAS), set(expected))
        self.assertEqual(set(wire.SCHEMA_HASHES), set(expected))
        for ftype, (schema, digest) in expected.items():
            with self.subTest(ftype=ftype):
                self.assertEqual(wire.SCHEMAS[ftype], schema)
                self.assertEqual(wire.SCHEMA_HASHES[ftype], digest)
                self.assertEqual(wire.crc32c(wire.SCHEMAS[ftype].encode("ascii")), digest)
        self.assertEqual(wire.SCHEMA, wire.SCHEMAS[1])
        self.assertEqual(wire.SCHEMA_HASH, wire.SCHEMA_HASHES[1])

    def test_payload_sizes(self):
        self.assertTrue(hasattr(wire, "PAYLOAD_SIZES"), "payload sizes not implemented")
        self.assertEqual(wire.PAYLOAD_SIZES, {1: 56, 2: 16, 3: 16, 4: 44, 5: 48, 6: 128})
        self.assertEqual(wire.PAYLOAD_SIZES[1], wire.RECORD.size)

    def test_single_type_file_schema_metadata(self):
        self.assertTrue(hasattr(wire, "FILE_SCHEMAS"), "file schema metadata not implemented")
        self.assertEqual(wire.FILE_SCHEMAS, {0xA871CD84: 1, 0xD23A4196: 4, 0xADFA94C8: 6})
        for digest, ftype in wire.FILE_SCHEMAS.items():
            self.assertEqual(wire.crc32c(wire.SCHEMAS[ftype].encode("ascii")), digest)


if __name__ == "__main__":
    unittest.main()


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
        for t in (0, 7, 255):
            with self.assertRaises(ValueError):
                wire.encode_frame(t, 0, b"")


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
            def regular_names(directory):
                return {p.name for p in directory.iterdir()
                        if p.is_file() and p.name != "generate.py"
                        and p.suffix not in {".pyc", ".pyo"}}
            expected = {entry["file"] for entry in self.manifest["files"]} | {"manifest.json"}
            self.assertEqual(regular_names(pathlib.Path(d)), expected)
            self.assertEqual(regular_names(GOLDEN), expected)
            for name in sorted(expected):
                self.assertEqual((pathlib.Path(d) / name).read_bytes(),
                                 (GOLDEN / name).read_bytes(), name)


# Literal payloads are independent of candidate codecs and the corpus generator.
PAYLOAD_EXAMPLES = {
    1: (dict(tick=0x0102030405060708, deadline_ns=-2, woke_ns=0x1112131415161718,
             done_ns=0x2122232425262728, theta=1.25, cmd=-2.5, drops=0x3132333435363738),
        bytes.fromhex("08 07 06 05 04 03 02 01 fe ff ff ff ff ff ff ff "
                      "18 17 16 15 14 13 12 11 28 27 26 25 24 23 22 21 "
                      "00 00 00 00 00 00 f4 3f 00 00 00 00 00 00 04 c0 "
                      "38 37 36 35 34 33 32 31")),
    2: (dict(cmd_seq=0x01020304, opcode=3, flags=1, effective_tick=0x1112131415161718),
        bytes.fromhex("04 03 02 01 03 00 01 00 18 17 16 15 14 13 12 11")),
    3: (dict(applied_tick=0x2122232425262728, cmd_seq=0x31323334, status=2, state=1, reason=7),
        bytes.fromhex("28 27 26 25 24 23 22 21 34 33 32 31 02 00 01 07")),
    4: (dict(tick=0x0102030405060708, t_send_ns=-2, theta=1.25, omega=-2.5,
             flags=0x0307, cmd_seq=0x21222324, sim_reason=2),
        bytes.fromhex("08 07 06 05 04 03 02 01 fe ff ff ff ff ff ff ff "
                      "00 00 00 00 00 00 f4 3f 00 00 00 00 00 00 04 c0 "
                      "07 03 00 00 24 23 22 21 02 00 00 00")),
    5: (dict(tick=0x0102030405060708, veh_tick=0x1112131415161718, t_sensor_send_ns=-3,
             t_veh_send_ns=0x2122232425262728, delta=-0.125, status=0x84030201,
             staleness=0x31323334),
        bytes.fromhex("08 07 06 05 04 03 02 01 18 17 16 15 14 13 12 11 "
                      "fd ff ff ff ff ff ff ff 28 27 26 25 24 23 22 21 "
                      "00 00 00 00 00 00 c0 bf 01 02 03 84 34 33 32 31")),
    6: (dict(tick=1, deadline_ns=-2, woke_ns=3, done_ns=4, sensor_send_ns=5, rx_ns=6,
             tx_ns=7, sensor_tick=8, theta=1.25, omega=-2.5, cmd=-0.0, i_state=3.75,
             d_prev=-4.5, drops=14, staleness=15, ack_cmd_seq=16, rx_count=9,
             discarded_old=1, discarded_superseded=2, discarded_other=3,
             state=4, reason=5, flags=0x76, ack_status=7),
        bytes.fromhex("01 00 00 00 00 00 00 00 fe ff ff ff ff ff ff ff "
                      "03 00 00 00 00 00 00 00 04 00 00 00 00 00 00 00 "
                      "05 00 00 00 00 00 00 00 06 00 00 00 00 00 00 00 "
                      "07 00 00 00 00 00 00 00 08 00 00 00 00 00 00 00 "
                      "00 00 00 00 00 00 f4 3f 00 00 00 00 00 00 04 c0 "
                      "00 00 00 00 00 00 00 80 00 00 00 00 00 00 0e 40 "
                      "00 00 00 00 00 00 12 c0 0e 00 00 00 00 00 00 00 "
                      "0f 00 00 00 10 00 00 00 09 01 02 03 04 05 76 07")),
}


def framed(ftype, payload, seq=7):
    # Valid CRC even for deliberately malformed typed payloads or foreign types.
    import struct
    head = struct.pack("<HBBHI", 0xEB90, 1, ftype, len(payload), seq)
    return head + payload + wire.crc32c(head[2:] + payload).to_bytes(4, "little")


class TypedPayloads(unittest.TestCase):
    def setUp(self):
        self.assertTrue(hasattr(wire, "encode_payload"), "typed payload encoder missing")
        self.assertTrue(hasattr(wire, "decode_payload"), "typed payload decoder missing")

    def test_literal_payloads(self):
        import struct
        for ftype, (fields, literal) in PAYLOAD_EXAMPLES.items():
            with self.subTest(ftype=ftype):
                self.assertEqual(wire.encode_payload(ftype, fields), literal)
                decoded = wire.decode_payload(ftype, literal)
                self.assertEqual(set(decoded), set(fields))
                for name, value in fields.items():
                    if isinstance(value, float):
                        self.assertEqual(struct.pack("<d", decoded[name]), struct.pack("<d", value))
                    else:
                        self.assertEqual(decoded[name], value)

    def test_exact_lengths_and_unknown_types(self):
        for ftype, (_, literal) in PAYLOAD_EXAMPLES.items():
            for cut in range(len(literal)):
                with self.assertRaisesRegex(ValueError, "length"):
                    wire.decode_payload(ftype, literal[:cut])
            with self.assertRaisesRegex(ValueError, "length"):
                wire.decode_payload(ftype, literal + b"\0")
        for ftype in (0, 7, 255):
            with self.assertRaisesRegex(ValueError, "type"):
                wire.encode_payload(ftype, {})
            with self.assertRaisesRegex(ValueError, "type"):
                wire.decode_payload(ftype, b"")

    def test_reserved_flags_zero_on_encode_tolerated_on_decode(self):
        for ftype, offset, width, mask in ((2, 6, 2, 1), (4, 32, 4, 0xFF07)):
            fields, literal = PAYLOAD_EXAMPLES[ftype]
            all_bits = (1 << (width * 8)) - 1
            encoded = wire.encode_payload(ftype, dict(fields, flags=all_bits))
            self.assertEqual(int.from_bytes(encoded[offset:offset + width], "little"), mask)
            incoming = bytearray(literal)
            incoming[offset:offset + width] = all_bits.to_bytes(width, "little")
            self.assertEqual(wire.decode_payload(ftype, incoming)["flags"], all_bits)

    def test_no_episode_enum_restrictions(self):
        for ftype, overrides in ((2, dict(opcode=65535)), (3, dict(status=65535, state=255, reason=255)),
                                 (4, dict(sim_reason=0xFFFFFFFF)), (5, dict(status=0xFFFFFFFF)),
                                 (6, dict(state=255, reason=255, ack_status=255))):
            fields = dict(PAYLOAD_EXAMPLES[ftype][0], **overrides)
            decoded = wire.decode_payload(ftype, wire.encode_payload(ftype, fields))
            for name, value in overrides.items():
                self.assertEqual(decoded[name], value)

    def test_binary64_payload_bits(self):
        import struct
        patterns = ("00 00 00 00 00 00 00 80", "34 12 00 00 00 00 f8 7f",
                    "ef be ad de 00 00 f8 ff", "42 00 00 00 00 00 f0 7f",
                    "42 00 00 00 00 00 f0 ff", "00 00 00 00 00 00 f0 7f")
        locations = {1: (("theta", 32), ("cmd", 40)), 4: (("theta", 16), ("omega", 24)),
                     5: (("delta", 32),), 6: (("theta", 64), ("omega", 72), ("cmd", 80),
                                            ("i_state", 88), ("d_prev", 96))}
        for ftype, fields_at in locations.items():
            fields, literal = PAYLOAD_EXAMPLES[ftype]
            for name, offset in fields_at:
                for pattern in patterns:
                    bits = bytes.fromhex(pattern)
                    expected = literal[:offset] + bits + literal[offset + 8:]
                    value = struct.unpack("<d", bits)[0]
                    self.assertEqual(wire.encode_payload(ftype, dict(fields, **{name: value})), expected)
                    decoded = wire.decode_payload(ftype, expected)
                    self.assertEqual(struct.pack("<d", decoded[name]), bits)

    def test_control_counts_use_a_wide_sum(self):
        fields, literal = PAYLOAD_EXAMPLES[6]
        names = ("rx_count", "discarded_old", "discarded_superseded", "discarded_other")
        for values in ((10, 0, 0, 0), (9, 4, 3, 3), (9, 255, 1, 0), (9, 250, 250, 20)):
            with self.assertRaisesRegex(ValueError, "count"):
                wire.encode_payload(6, dict(fields, **dict(zip(names, values))))
            bad = literal[:120] + bytes(values) + literal[124:]
            with self.assertRaisesRegex(ValueError, "count"):
                wire.decode_payload(6, bad)
        for values in ((0, 0, 0, 0), (9, 3, 3, 3), (9, 9, 0, 0)):
            good = literal[:120] + bytes(values) + literal[124:]
            decoded = wire.decode_payload(6, good)
            self.assertEqual(tuple(decoded[n] for n in names), values)


class StrictDatagrams(unittest.TestCase):
    def setUp(self):
        self.assertTrue(hasattr(wire, "decode_datagram"), "strict datagram decoder missing")

    def test_accepts_one_frame_with_an_allowed_type(self):
        for ftype, (_, payload) in PAYLOAD_EXAMPLES.items():
            self.assertEqual(wire.decode_datagram(framed(ftype, payload), {ftype}), (ftype, 7, payload))
        self.assertEqual(wire.decode_datagram(framed(4, PAYLOAD_EXAMPLES[4][1]), {4, 5})[0], 4)

    def test_truncation_trailing_concatenation_and_no_resync(self):
        frame = framed(4, PAYLOAD_EXAMPLES[4][1])
        for cut in range(len(frame)):
            with self.assertRaisesRegex(ValueError, "bad_length"):
                wire.decode_datagram(frame[:cut], {4})
        for bad in (frame + b"x", frame + frame):
            with self.assertRaisesRegex(ValueError, "bad_length"):
                wire.decode_datagram(bad, {4})
        with self.assertRaisesRegex(ValueError, "bad_sync"):
            wire.decode_datagram(b"junk" + frame, {4})

    def test_crc_valid_wrong_type_and_payload_size(self):
        for accepted in ({2}, {3}, {5}, {6}, set()):
            with self.assertRaisesRegex(ValueError, "bad_type"):
                wire.decode_datagram(framed(4, PAYLOAD_EXAMPLES[4][1]), accepted)
        with self.assertRaisesRegex(ValueError, "bad_type"):
            wire.decode_datagram(framed(7, b""), {7})
        for ftype, (_, payload) in PAYLOAD_EXAMPLES.items():
            for bad in (payload[:-1], payload + b"\0"):
                with self.assertRaisesRegex(ValueError, "bad_length"):
                    wire.decode_datagram(framed(ftype, bad), {ftype})

    def test_sync_version_and_crc(self):
        frame = framed(4, PAYLOAD_EXAMPLES[4][1])
        for offset, reason in ((0, "bad_sync"), (2, "bad_version"), (-1, "bad_crc")):
            bad = bytearray(frame)
            bad[offset] ^= 0xFF
            with self.assertRaisesRegex(ValueError, reason):
                wire.decode_datagram(bytes(bad), {4})


class ExpandedFraming(unittest.TestCase):
    def test_new_types_are_generic_frames(self):
        for ftype in (4, 5, 6):
            frame = wire.encode_frame(ftype, 7, b"arbitrary framing payload")
            self.assertEqual(wire.decode_stream(frame),
                             ([(ftype, 7, b"arbitrary framing payload")], counters(frames_ok=1)))


class TypedRecordings(unittest.TestCase):
    def setUp(self):
        self.assertTrue(hasattr(wire, "read_typed_recording"), "typed recording reader missing")

    def read(self, body, expected_type, header=None, legacy=False):
        import tempfile
        if header is None:
            header = wire.HEADER.pack(b"TVCRECRD", 1, 0, wire.SCHEMA_HASHES[expected_type], 11, 22)
        with tempfile.TemporaryDirectory() as directory:
            path = pathlib.Path(directory) / "recording.tvcrec"
            path.write_bytes(header + body)
            return (wire.read_recording(path) if legacy else
                    wire.read_typed_recording(path, expected_type=expected_type))

    def test_valid_single_type_recordings(self):
        for ftype in (1, 4, 6):
            fields, literal = PAYLOAD_EXAMPLES[ftype]
            header, records, ctr = self.read(framed(ftype, literal), ftype)
            self.assertEqual(header, dict(magic=b"TVCRECRD", version=1,
                                         schema_hash=wire.SCHEMA_HASHES[ftype],
                                         start_monotonic_ns=11, start_epoch_ns=22, schema_known=True))
            self.assertEqual(records, [fields])
            self.assertEqual(ctr, counters(frames_ok=1))

    def test_required_and_supported_expected_type(self):
        with self.assertRaises(TypeError):
            wire.read_typed_recording("unused")
        for expected_type in (0, 2, 3, 5, 7, 255):
            with self.assertRaisesRegex(ValueError, "expected_type"):
                self.read(b"", expected_type, header=bytes(32))

    def test_header_contract(self):
        good = wire.HEADER.pack(b"TVCRECRD", 1, 0, 0xA871CD84, 0, 0)
        for cut in range(32):
            with self.assertRaisesRegex(ValueError, "header"):
                self.read(b"", 1, header=good[:cut])
        for header, reason in ((wire.HEADER.pack(b"NOTMAGIC", 1, 0, 0xA871CD84, 0, 0), "magic"),
                               (wire.HEADER.pack(b"TVCRECRD", 9, 0, 0xA871CD84, 0, 0), "version"),
                               (wire.HEADER.pack(b"TVCRECRD", 1, 1, 0xA871CD84, 0, 0), "reserved"),
                               (wire.HEADER.pack(b"TVCRECRD", 1, 0, 0xDEAD, 0, 0), "schema")):
            with self.assertRaisesRegex(ValueError, reason):
                self.read(b"", 1, header=header)

    def test_known_schema_mismatch(self):
        for declared in (1, 4, 6):
            for expected in (1, 4, 6):
                if declared == expected:
                    continue
                header = wire.HEADER.pack(b"TVCRECRD", 1, 0, wire.SCHEMA_HASHES[declared], 0, 0)
                with self.assertRaisesRegex(ValueError, "schema"):
                    self.read(b"", expected, header=header)

    def test_crc_valid_recovered_foreign_types(self):
        for declared, foreign in ((1, 4), (4, 6), (6, 1)):
            with self.assertRaisesRegex(ValueError, "type"):
                self.read(framed(foreign, PAYLOAD_EXAMPLES[foreign][1]), declared)

    def test_crc_valid_recovered_bad_lengths_and_counts(self):
        for ftype in (1, 4, 6):
            payload = PAYLOAD_EXAMPLES[ftype][1]
            for bad in (payload[:-1], payload + b"\0"):
                with self.assertRaisesRegex(ValueError, "length"):
                    self.read(framed(ftype, bad), ftype)
        payload = PAYLOAD_EXAMPLES[6][1]
        for counts_bytes in (bytes((10, 0, 0, 0)), bytes((9, 255, 1, 0))):
            bad = payload[:120] + counts_bytes + payload[124:]
            with self.assertRaisesRegex(ValueError, "count"):
                self.read(framed(6, bad), 6)

    def test_corrupted_control_recording_recovers_with_counters(self):
        fields, payload = PAYLOAD_EXAMPLES[6]
        frames = [framed(6, payload, n) for n in range(6)]
        frames[2] = frames[2][:-1] + bytes([frames[2][-1] ^ 0xFF])
        _, records, ctr = self.read(b"".join(frames), 6)
        self.assertEqual(records, [fields] * 5)
        self.assertEqual(ctr, counters(frames_ok=5, crc_errors=1, resyncs=1, lost=1, skipped_bytes=142))

    def test_legacy_reader_remains_diagnostic(self):
        header = wire.HEADER.pack(b"TVCRECRD", 1, 99, 0xDEAD, 11, 22)
        body = framed(1, PAYLOAD_EXAMPLES[1][1], 0) + framed(4, PAYLOAD_EXAMPLES[4][1], 1)
        result, records, ctr = self.read(body, 1, header=header, legacy=True)
        self.assertFalse(result["schema_known"])
        self.assertEqual(records, [wire.Record(**PAYLOAD_EXAMPLES[1][0])])
        self.assertEqual(ctr, counters(frames_ok=2))


# Header/CRC literals were calculated independently of generate.py and wire.py.
CORPUS_FRAMES = (
    ("frame_sensor.bin", 4, 0, 58, "90 eb 01 04 2c 00 00 00 00 00", "7e f2 a5 b9"),
    ("frame_actuator.bin", 5, 1, 62, "90 eb 01 05 30 00 01 00 00 00", "38 24 08 11"),
    ("frame_command.bin", 2, 2, 30, "90 eb 01 02 10 00 02 00 00 00", "db b1 97 4d"),
    ("frame_ack.bin", 3, 3, 30, "90 eb 01 03 10 00 03 00 00 00", "a5 91 56 41"),
    ("frame_control.bin", 6, 4, 142, "90 eb 01 06 80 00 04 00 00 00", "42 e1 99 de"),
)


class ExtendedGoldenCorpus(unittest.TestCase):
    def test_exact_manifest_contract(self):
        manifest = json.loads((GOLDEN / "manifest.json").read_text())
        self.assertEqual(set(manifest), {"schema_hash", "file_schemas", "files"})
        self.assertEqual(manifest["schema_hash"], "0xA871CD84")
        schemas = {"0xA871CD84": 1, "0xADFA94C8": 6, "0xD23A4196": 4}
        self.assertEqual(manifest["file_schemas"], schemas)
        self.assertTrue(all(type(t) is int for t in manifest["file_schemas"].values()))
        self.assertEqual({int(h, 16): t for h, t in schemas.items()}, wire.FILE_SCHEMAS)
        for digest, ftype in schemas.items():
            self.assertEqual(wire.crc32c(wire.SCHEMAS[ftype].encode("ascii")), int(digest, 16))
        descriptions = {
            "frame_sensor.bin": "canonical type-4 sensor frame",
            "frame_actuator.bin": "canonical type-5 actuator frame",
            "frame_command.bin": "canonical type-2 command frame",
            "frame_ack.bin": "canonical type-3 acknowledgment frame",
            "frame_control.bin": "canonical type-6 control frame",
            "recording_control_mini.tvcrec":
                "header + six control frames, seq-2 frame corrupted, proving resync",
        }
        historical = {"frame_badcrc.bin", "frame_empty.bin", "frame_max.bin", "frame_record.bin",
                      "frame_truncated.bin", "frames_seqwrap.bin", "recording_mini.tvcrec"}
        names = [entry["file"] for entry in manifest["files"]]
        self.assertEqual(names, sorted(historical | set(descriptions)))
        entries = {entry["file"]: entry for entry in manifest["files"]}
        for name, description in descriptions.items():
            recording = name.endswith(".tvcrec")
            expected = (counters(frames_ok=5, crc_errors=1, resyncs=1, lost=1, skipped_bytes=142)
                        if recording else counters(frames_ok=1))
            self.assertEqual(entries[name], dict(file=name, description=description,
                                                roundtrip=not recording, expect=expected))

    def assert_fields(self, actual, expected):
        import struct
        self.assertEqual(set(actual), set(expected))
        for name, value in expected.items():
            if isinstance(value, float):
                self.assertEqual(struct.pack("<d", actual[name]), struct.pack("<d", value), name)
            else:
                self.assertEqual(actual[name], value, name)

    def test_standalone_literal_bytes_and_fields(self):
        for name, ftype, seq, size, head, crc in CORPUS_FRAMES:
            with self.subTest(file=name):
                self.assertTrue((GOLDEN / name).is_file(), name)
                data = (GOLDEN / name).read_bytes()
                fields, payload = PAYLOAD_EXAMPLES[ftype]
                self.assertEqual(len(data), size)
                self.assertEqual(data, bytes.fromhex(head) + payload + bytes.fromhex(crc))
                self.assertEqual(wire.decode_datagram(data, {ftype}), (ftype, seq, payload))
                self.assertEqual(wire.decode_stream(data), ([(ftype, seq, payload)], counters(frames_ok=1)))
                self.assert_fields(wire.decode_payload(ftype, data[10:-4]), fields)

    def test_control_recording_whole_file_literal(self):
        path = GOLDEN / "recording_control_mini.tvcrec"
        self.assertTrue(path.is_file(), path.name)
        # Includes the corrupt frame's payload and CRC, not merely recovered records.
        expected = bytes.fromhex("54 56 43 52 45 43 52 44 01 00 00 00 c8 94 fa ad "
                                 "00 ca 9a 3b 00 00 00 00 00 80 cf 9c 33 03 5b 18")
        crcs = ("05 90 39 27", "e2 ec dc 2b", "cb 69 f3 c1",
                "2c 15 16 32", "99 63 ac 14", "7e 1f 49 18")
        for n, crc in enumerate(crcs):
            expected += (bytes.fromhex("90 eb 01 06 80 00") + bytes((n, 0, 0, 0)) +
                         bytes((n,)) + PAYLOAD_EXAMPLES[6][1][1:] + bytes.fromhex(crc))
        self.assertEqual(len(expected), 884)
        self.assertEqual(path.read_bytes(), expected)

    def test_control_recording_typed_recovery(self):
        path = GOLDEN / "recording_control_mini.tvcrec"
        self.assertTrue(path.is_file(), path.name)
        header, records, ctr = wire.read_typed_recording(path, expected_type=6)
        self.assertEqual(header, dict(magic=b"TVCRECRD", version=1, schema_hash=0xADFA94C8,
                                     start_monotonic_ns=1_000_000_000,
                                     start_epoch_ns=1_755_000_000_000_000_000, schema_known=True))
        expected_counters = counters(frames_ok=5, crc_errors=1, resyncs=1, lost=1, skipped_bytes=142)
        self.assertEqual(ctr, expected_counters)
        ticks = [0, 1, 3, 4, 5]
        self.assertEqual([record["tick"] for record in records], ticks)
        for record, tick in zip(records, ticks):
            self.assert_fields(record, dict(PAYLOAD_EXAMPLES[6][0], tick=tick))
        frames, framing_counters = wire.decode_stream(path.read_bytes()[32:])
        self.assertEqual([(t, seq) for t, seq, _ in frames], [(6, n) for n in ticks])
        self.assertEqual(framing_counters, expected_counters)
        for (_, seq, payload), tick in zip(frames, ticks):
            self.assertEqual(payload, bytes((tick,)) + PAYLOAD_EXAMPLES[6][1][1:])
