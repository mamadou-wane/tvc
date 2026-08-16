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
