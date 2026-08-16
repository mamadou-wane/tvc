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
