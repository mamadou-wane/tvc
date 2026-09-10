import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

ROOT=Path(__file__).resolve().parents[2]
BIN=os.environ['TVC_BIN']


class SmallCampaign(unittest.TestCase):
    def test_two_seeds_two_delays_repeat_without_freezing_qualification(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d)
            manifests=[]
            for label in ('a','b'):
                result=subprocess.run([sys.executable,'-B',str(ROOT/'scripts/run_campaign.py'),
                    '--scenario=S2-gust','--loss=0.30','--seeds=1-2','--delay-ticks=0,1',
                    '--binary='+BIN,'--out='+str(root/label),'--manifest='+str(root/(label+'.json')),
                    '--development','--check'],capture_output=True,text=True,timeout=90)
                self.assertEqual(result.returncode,0,result.stdout+result.stderr)
                manifests.append((root/(label+'.json')).read_bytes())
            self.assertEqual(manifests[0],manifests[1])
            doc=json.loads(manifests[0]);self.assertEqual(doc['passed'],4);self.assertEqual(doc['total'],4)
            self.assertEqual(doc['format'],'tvc-campaign-candidate-1')
            self.assertEqual(set(doc['cases'][0]['digests']),{'inputs_tvcrec','control_tvcrec','sim_csv','vehicle_csv'})
            from tests.functional.test_loss import check_counts
            check_counts(root/'a',seeds=(1,2),delays=(0,1))
            # Hashes alone cannot validate reported numerical clauses/metrics.
            doc['cases'][0]['peak_theta_bits']='0x0000000000000000'
            lied=root/'lied.json';lied.write_text(json.dumps(doc))
            result=subprocess.run([sys.executable,'-B',str(ROOT/'scripts/run_campaign.py'),
                '--validate','--development','--manifest='+str(lied),'--out='+str(root/'a')],
                capture_output=True,text=True,timeout=60)
            self.assertNotEqual(result.returncode,0)

            from scripts.run_campaign import validate_manifest
            with self.assertRaisesRegex(ValueError,'scenario identity'):
                validate_manifest(dict(json.loads(manifests[0]),scenario_sha256='0'*64),
                    expected_source=doc['run_identity']['implementation_source_sha256'],
                    expected_toolchain=doc['run_identity']['toolchain'],artifact_root=root/'a',canonical=False)
            # Contradictory physical reports cannot hide behind unchanged artifacts.
            from unittest.mock import patch
            from scripts import run_campaign
            real_read=run_campaign.read_json
            def changed(path):
                value=real_read(path)
                if str(path).endswith('.sim-report.json'):value['transmission']['modeled_sample_loss']=0
                if str(path).endswith('.reconcile.json'):value['uplink']['modeled_sample_loss']=0
                return value
            with patch.object(run_campaign,'read_json',side_effect=changed), \
                 self.assertRaisesRegex(ValueError,'modeled sample loss'):
                validate_manifest(json.loads(manifests[0]),
                    expected_source=doc['run_identity']['implementation_source_sha256'],
                    expected_toolchain=doc['run_identity']['toolchain'],artifact_root=root/'a',canonical=False)
