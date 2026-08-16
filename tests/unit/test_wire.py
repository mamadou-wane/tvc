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
