import importlib.util
from pathlib import Path
import unittest
from ground.wire import Record

ROOT = Path(__file__).resolve().parents[2]


class HarnessColumnsTests(unittest.TestCase):
    def test_fixed_columns_have_independent_exact_bit_representation(self):
        spec = importlib.util.spec_from_file_location('golden_csv', ROOT / 'scripts/golden_csv.py')
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        rows = [Record(7, 11, 12, 13, -0.0, 0.12, 0),
                Record(8, 21, 22, 23, 0.25, -0.5, 0)]
        self.assertEqual(module.harness_csv(rows),
                         'tick,theta,cmd\n7,0x8000000000000000,0x3fbeb851eb851eb8\n'
                         '8,0x3fd0000000000000,0xbfe0000000000000\n')


if __name__ == '__main__': unittest.main()
