import copy
import importlib
import unittest
from tests.unit.test_campaign_manifest import SOURCE,TOOLCHAIN

NAMES=('S1-hold','S2-gust','S3-kick','S4-open','S5-overgust','S6-blackout','S7-abort','demo-loss30')


def fixture():
    return dict(format='tvc-lockstep-goldens-1',implementation_source_sha256=SOURCE,
        toolchain=copy.deepcopy(TOOLCHAIN),scenarios=[dict(scenario=name,scenario_sha256='c'*64,
            seed=20260902 if name=='demo-loss30' else 1,delay_ticks=0,
            sim_csv_sha256='d'*64,vehicle_csv_sha256='e'*64,inputs_sha256='f'*64,control_sha256='1'*64,
            reason=1,reason_tick=9999,outcome='stabilized',consumed_ticks=10000)
            for name in NAMES])


class GoldenValidation(unittest.TestCase):
    def setUp(self):self.module=importlib.import_module('scripts.run_campaign')

    def test_exact_membership_and_four_artifact_inventory(self):
        doc=fixture();self.module.validate_goldens(doc,expected_source=SOURCE,expected_toolchain=TOOLCHAIN)
        for kind in ('missing','duplicate','digest','source','image'):
            doc=fixture()
            if kind=='missing':doc['scenarios'].pop()
            elif kind=='duplicate':doc['scenarios'][1]=doc['scenarios'][0]
            elif kind=='digest':doc['scenarios'][0].pop('control_sha256')
            elif kind=='source':doc['implementation_source_sha256']='a'*64
            else:doc['toolchain']['image']=None
            with self.subTest(kind=kind),self.assertRaises(ValueError):
                self.module.validate_goldens(doc,expected_source=SOURCE,expected_toolchain=TOOLCHAIN)
