import json
from pathlib import Path
import tempfile
import unittest

from sim import link,rng
from tests.functional.test_loss import EXPECTED,check_counts


class LossCounts(unittest.TestCase):
    def test_frozen_streams_match_independent_integer_counts(self):
        for seed,expected in EXPECTED.items():
            actual=[]
            for name in ('link.loss.up','link.loss.down'):
                stream=rng.SplitMix64(rng.stream_state(seed,name))
                actual.append(sum(link.draw_drop(stream,.30) for _ in range(10000)))
            self.assertEqual(tuple(actual),expected)

    def test_reconciliation_oracle_rejects_wrong_loss_and_incomplete_terminal(self):
        with tempfile.TemporaryDirectory() as d:
            path=Path(d)/'seed-001-D0/S2-gust.reconcile.json';path.parent.mkdir()
            original=dict(eligible=True,sim_reason=1,vehicle_reason=1,reason_tick=9999,
                          uplink=dict(modeled_sample_loss=3047),downlink=dict(modeled_command_loss=2943))
            path.write_text(json.dumps(original));check_counts(d,seeds=(1,))
            for key,value in [('uplink',dict(modeled_sample_loss=0)),
                              ('downlink',dict(modeled_command_loss=0)),('reason_tick',9998),('eligible',False)]:
                path.write_text(json.dumps(dict(original,**{key:value})))
                with self.subTest(key=key),self.assertRaises(AssertionError):check_counts(d,seeds=(1,))
