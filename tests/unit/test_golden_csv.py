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

    def test_vehicle_and_sim_columns_have_independent_literals(self):
        spec = importlib.util.spec_from_file_location('golden_csv', ROOT / 'scripts/golden_csv.py')
        module = importlib.util.module_from_spec(spec); spec.loader.exec_module(module)
        record = dict(tick=7,state=2,reason=0,sensor_tick=6,staleness=1,flags=10,
                      theta=-0.0,omega=0.25,cmd=0.12,i_state=0.0,d_prev=-0.5)
        self.assertEqual(module.vehicle_csv([record]),
            'tick,state,reason,sensor_tick,staleness,ladder,theta_bits,omega_bits,cmd_bits,i_state_bits,d_prev_bits\n'
            '7,2,0,6,1,8,0x8000000000000000,0x3fd0000000000000,0x3fbeb851eb851eb8,0x0000000000000000,0xbfe0000000000000\n')
        row=dict(tick=0,has_sample=0,applied=0,theta_bits='0x8000000000000000',
                 omega_bits='0x3fd0000000000000',cmd_applied_bits='0x3fbeb851eb851eb8')
        self.assertEqual(module.sim_csv([row]),
            'tick,has_sample,applied,theta_bits,omega_bits,cmd_applied_bits\n'
            '0,0,0,0x8000000000000000,0x3fd0000000000000,0x3fbeb851eb851eb8\n')


if __name__ == '__main__': unittest.main()
