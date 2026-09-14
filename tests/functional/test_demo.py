"""Development artifact checks; canonical identity is exercised in its own image."""
import contextlib
import importlib
import io
import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest
from unittest.mock import patch

ROOT=Path(__file__).resolve().parents[2]
BIN=Path(os.environ['TVC_BIN'])
CANONICAL=bool(os.environ.get('TVC_GOLD_IMAGE'))


class Demo(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.demo=importlib.import_module('scripts.demo')
        cls.temp=tempfile.TemporaryDirectory();cls.addClassCleanup(cls.temp.cleanup)
        cls.out=Path(cls.temp.name)/'run'
        cls.facts=cls.demo.run_demo(cls.out,binary=BIN,canonical=CANONICAL,data_only=True)

    def clone(self):
        temp=tempfile.TemporaryDirectory();self.addCleanup(temp.cleanup)
        out=Path(temp.name)/'case';shutil.copytree(self.out,out)
        return out/'demo-loss30'

    def test_data_facts_and_fixed_invocation(self):
        f=self.facts
        self.assertEqual((f['outcome'],f['reason'],f['terminal_tick']),('stabilized',1,2999))
        self.assertEqual(f['records'],3000)
        self.assertEqual(f['ladder'],dict(fresh=2168,coast=832,neutral=0,lost=0))
        self.assertEqual(f['modeled_loss'],dict(up=832,down=838))
        replay=json.loads((self.out/'demo-loss30.replay.json').read_text())
        self.assertIn('--seed=20260902',replay['sim_argv'])
        self.assertIn('--delay-ticks=0',replay['sim_argv'])
        self.assertFalse(any(a.startswith('--loss=') or a.startswith('--ticks=') for a in replay['sim_argv']))
        self.assertEqual(f['canonical_identity_verified'],CANONICAL)
        if CANONICAL:
            manifest=json.loads((ROOT/'tests/golden/lockstep/manifest.json').read_text())
            expected=next(r for r in manifest['scenarios'] if r['scenario']=='demo-loss30')
            self.assertEqual(f['vehicle_csv_sha256'],expected['vehicle_csv_sha256'])

    def test_corruption_and_failed_outcomes_are_refused(self):
        for suffix in ('.control.tvcrec','.inputs.tvcrec','.sim.csv','.vehicle.csv',
                       '.reconcile.json','.result.json','.summary.json'):
            prefix=self.clone();path=Path(str(prefix)+suffix);raw=path.read_bytes()
            path.write_bytes(raw[:len(raw)//2] if suffix.endswith('.json') else raw[:-1])
            with self.subTest(suffix=suffix),self.assertRaises((ValueError,OSError)):
                self.demo.verify_data(prefix,canonical=CANONICAL)
        prefix=self.clone();path=Path(str(prefix)+'.result.json');result=json.loads(path.read_text())
        result['vehicle_exit']=1;path.write_text(json.dumps(result))
        with self.assertRaises(ValueError):self.demo.verify_data(prefix,canonical=CANONICAL)

    def test_digest_mismatch_and_toolchain_refusal_are_explicit(self):
        prefix=self.clone()
        if CANONICAL:
            manifest=json.loads((ROOT/'tests/golden/lockstep/manifest.json').read_text())
            expected=next(r for r in manifest['scenarios'] if r['scenario']=='demo-loss30')
            expected['vehicle_csv_sha256']='0'*64
            with patch.object(self.demo,'manifest_document',return_value=manifest):
                with self.assertRaisesRegex(ValueError,'vehicle_csv'):self.demo.verify_data(prefix)
        else:
            with self.assertRaisesRegex(ValueError,'toolchain'):self.demo.verify_data(prefix)

    def test_data_failure_never_renders(self):
        renderer=importlib.import_module('scripts.render_demo')
        with tempfile.TemporaryDirectory() as d,patch.object(renderer,'render') as render:
            with self.assertRaises((ValueError,OSError)):
                self.demo.run_demo(Path(d)/'bad',binary=Path('/bin/false'),canonical=CANONICAL)
            render.assert_not_called()

    def test_artifact_markers_and_gif_properties(self):
        from PIL import Image
        renderer=importlib.import_module('scripts.render_demo')
        prefix=self.clone();data=renderer.load_data(prefix,canonical=CANONICAL)
        self.assertEqual((len(data['up_lost']),len(data['down_lost'])),(832,838))
        self.assertEqual([data['controls'][k]['state'] for k in (0,49,50,109,110,2999)],
                         [0,0,1,1,2,3])
        self.assertTrue(all(k>=200 for k in data['up_lost']+data['down_lost']))
        output=prefix.parent/'demo.gif'
        renderer.render(prefix,output,canonical=CANONICAL)
        self.assertLess(output.stat().st_size,1572864)
        with Image.open(output) as gif:
            self.assertEqual(gif.size,(640,360));self.assertEqual(gif.n_frames,150)
            for i in range(gif.n_frames):gif.seek(i);self.assertEqual(gif.info['duration'],40)
        Path(str(prefix)+'.sim.csv').write_text('broken')
        before=output.read_bytes()
        with self.assertRaises((ValueError,OSError)):renderer.render(prefix,output,canonical=CANONICAL)
        self.assertEqual(output.read_bytes(),before)

    def test_render_failure_fails_command_after_data_proof(self):
        renderer=importlib.import_module('scripts.render_demo')
        with tempfile.TemporaryDirectory() as d,patch.object(renderer,'render',side_effect=OSError('injected renderer failure')):
            with self.assertRaisesRegex(OSError,'renderer failure'):
                self.demo.run_demo(Path(d)/'run',binary=BIN,canonical=CANONICAL)
            self.assertTrue((Path(d)/'run/demo-loss30.vehicle.csv').is_file())

    def test_data_only_and_output_reuse_refusal(self):
        with tempfile.TemporaryDirectory() as d:
            out=Path(d)/'data'
            if CANONICAL:
                command=['bash','scripts/demo.sh','--out',str(out),'--binary',str(BIN),'--data-only']
                run=subprocess.run(command,cwd=ROOT,capture_output=True,text=True)
                self.assertEqual(run.returncode,0,run.stderr)
                self.assertIn('"canonical_identity_verified": true',run.stdout)
                self.assertNotEqual(subprocess.run(command,cwd=ROOT,capture_output=True).returncode,0)
            else:
                self.demo.run_demo(out,binary=BIN,canonical=False,data_only=True)
                with self.assertRaisesRegex(ValueError,'already exists'):
                    self.demo.run_demo(out,binary=BIN,canonical=False,data_only=True)
            self.assertFalse((out/'demo.gif').exists())
