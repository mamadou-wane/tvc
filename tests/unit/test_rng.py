import struct
import unittest

from sim import rng


STREAM_NAMES = (
    "link.loss.up",
    "link.loss.down",
    "sensor.noise",
    "actuator.fault",
    "environment.disturbance",
    "parameter.sampling",
    "scenario",
)

DERIVED_STATES = {
    0: (
        0xE220A8397B1DCDAF,
        0x6E789E6AA1B965F4,
        0x06C45D188009454F,
        0xF88BB8A8724C81EC,
        0x1B39896A51A8749B,
        0x53CB9F0C747EA2EA,
        0x2C829ABE1F4532E1,
    ),
    1: (
        0x910A2DEC89025CC1,
        0xBEEB8DA1658EEC67,
        0xF893A2EEFB32555E,
        0x71C18690EE42C90B,
        0x71BB54D8D101B5B9,
        0xC34D0BFF90150280,
        0xE099EC6CD7363CA5,
    ),
    0xFFFFFFFFFFFFFFFF: (
        0xE4D971771B652C20,
        0xE99FF867DBF682C9,
        0x382FF84CB27281E9,
        0x6D1DB36CCBA982D2,
        0xB4A0472E578069AE,
        0xD31DADBDA438BB33,
        0xF14F2CF802083FA5,
    ),
}

U64_OUTPUTS = {
    "link.loss.up": (
        0x5E41AB087439611E,
        0xF18D6CE93D6CF1EE,
        0x0B95F66D327E8D78,
        0xC7061B1B93322BA9,
        0x3817EDDDF9257651,
        0xC63F062C5C30E3D4,
        0xA05302141A219F0B,
        0x3F391C8A76D960BB,
    ),
    "link.loss.down": (
        0x778B1AA9C29BC868,
        0x08C9EB4685B1DAD7,
        0x0BC4AE3918A0287A,
        0x904A6E8FF8C23A56,
        0x660830FF6EFA0A4D,
        0xCC9C143A25C28764,
        0x6AB7E22510676EEA,
        0x2717B1FFFDBFE528,
    ),
    "sensor.noise": (
        0xA6C7188E0551111E,
        0x6D5016879973635C,
        0xAA7E844961F494EE,
        0x0EE3BB459E9E297B,
        0xE8FA78EE2C98E692,
        0x3C4BEA2672B6EBDA,
        0xAFB3634AFFB384CC,
        0x78F5B242ABF88965,
    ),
    "actuator.fault": (
        0x3EDFFCDC1F877BE0,
        0xC03E6BAFC0DC0CB6,
        0x3472F3C073F95F11,
        0xDB7B2CA93DFC9064,
        0xD79F383CD29DFD7F,
        0x5EC77D1C13265128,
        0xBE3BF3BA1FA94F5B,
        0x65C4FC451CD6FF46,
    ),
    "environment.disturbance": (
        0x4000795F8E33B2A8,
        0x76CDCCB95A30B7DA,
        0xED43B585A649A675,
        0x8F330E2083EBD686,
        0x1DCED0BE199E3945,
        0xF607CB20D7B7F271,
        0x80BC064C8069D620,
        0xDA6AA9EA00763404,
    ),
    "parameter.sampling": (
        0xFE70AC4117EDC3C7,
        0x256AD9CD03BF0193,
        0xDB9DC0BF71C9CCFF,
        0x8577EC3F8DD99729,
        0x87E7CEED25207B27,
        0xF77471EFC6B5FD1E,
        0xF023E1B053C82B2D,
        0x9AFF6B3504CE07F1,
    ),
    "scenario": (
        0xF52105EB43095AF5,
        0x73E2BE9588887860,
        0x5082DF562158D20C,
        0xF8006E8A15981575,
        0xB0311B3D77E08935,
        0x3653DCAECFFC8DED,
        0x62EF5FC861DE5865,
        0x3448A5562FC1E98C,
    ),
}

DOUBLE_OUTPUTS = {
    "link.loss.up": (
        "0x1.7906ac21d0e58p-2",
        "0x1.e31ad9d27ad9ep-1",
        "0x1.72becda64fd10p-5",
        "0x1.8e0c363726645p-1",
        "0x1.c0bf6eefc92b8p-3",
        "0x1.8c7e0c58b861cp-1",
        "0x1.40a6042834433p-1",
        "0x1.f9c8e453b6cb0p-3",
    ),
    "link.loss.down": (
        "0x1.de2c6aa70a6f2p-2",
        "0x1.193d68d0b63b0p-5",
        "0x1.7895c72314050p-5",
        "0x1.2094dd1ff1847p-1",
        "0x1.9820c3fdbbe82p-2",
        "0x1.993828744b850p-1",
        "0x1.aadf8894419dap-2",
        "0x1.38bd8fffedff0p-3",
    ),
}


def double_bits(value):
    return struct.unpack("<Q", struct.pack("<d", value))[0]


def draw_prefix(master, name, count):
    stream = rng.SplitMix64(rng.stream_state(master, name))
    return tuple(stream.next_u64() for _ in range(count))


class RngKnownAnswerTests(unittest.TestCase):
    def test_stream_derivation_known_answers(self):
        for master, expected_states in DERIVED_STATES.items():
            with self.subTest(master=master):
                actual = tuple(rng.stream_state(master, name) for name in STREAM_NAMES)
                self.assertEqual(actual, expected_states)

    def test_seed_one_integer_output_prefixes(self):
        for name, expected in U64_OUTPUTS.items():
            with self.subTest(name=name):
                self.assertEqual(draw_prefix(1, name, 8), expected)

    def test_active_stream_double_output_prefixes_preserve_bits(self):
        for name, expected_hex in DOUBLE_OUTPUTS.items():
            stream = rng.SplitMix64(rng.stream_state(1, name))
            actual_bits = tuple(double_bits(stream.next_double()) for _ in range(8))
            expected_bits = tuple(double_bits(float.fromhex(value)) for value in expected_hex)
            with self.subTest(name=name):
                self.assertEqual(actual_bits, expected_bits)

    def test_state_addition_wrap_vectors(self):
        vectors = (
            (0x0000000000000000, 0x9E3779B97F4A7C15, 0xE220A8397B1DCDAF),
            (0xFFFFFFFFFFFFFFFF, 0x9E3779B97F4A7C14, 0xE4D971771B652C20),
            (0x61C8864680B583EB, 0x0000000000000000, 0x0000000000000000),
        )
        for initial, expected_state, expected_output in vectors:
            stream = rng.SplitMix64(initial)
            with self.subTest(initial=initial):
                self.assertEqual(stream.next_u64(), expected_output)
                self.assertEqual(stream.state, expected_state)

    def test_unknown_stream_name_raises_value_error(self):
        with self.assertRaises(ValueError):
            rng.stream_state(1, "link.loss.sideways")

    def test_adjacent_master_sequences_are_not_shifted_aliases(self):
        for name in STREAM_NAMES:
            for master in range(1, 9):
                current = draw_prefix(master, name, 9)
                following = draw_prefix(master + 1, name, 8)
                with self.subTest(name=name, master=master):
                    self.assertNotEqual(following, current[1:])

    def test_all_master_stream_prefixes_are_distinct(self):
        prefixes = {
            draw_prefix(master, name, 8)
            for master in range(1, 65)
            for name in STREAM_NAMES
        }
        self.assertEqual(len(prefixes), 448)

    def test_preparing_reserved_streams_does_not_shift_live_prefixes(self):
        def prepare(names):
            return {
                name: rng.SplitMix64(rng.stream_state(1, name))
                for name in names
            }

        first_four = prepare(STREAM_NAMES[:4])
        all_seven = prepare(STREAM_NAMES)
        for name in STREAM_NAMES[:4]:
            expected = tuple(first_four[name].next_u64() for _ in range(8))
            actual = tuple(all_seven[name].next_u64() for _ in range(8))
            with self.subTest(name=name):
                self.assertEqual(actual, expected)


if __name__ == "__main__":
    unittest.main()
