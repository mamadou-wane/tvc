import json
import os
from pathlib import Path
import subprocess
import tempfile
import unittest

ROOT=Path(__file__).resolve().parents[2]


class LauncherPaths(unittest.TestCase):
    def run_launcher(self,*args):
        with tempfile.TemporaryDirectory() as d:
            fake=Path(d)/'docker'
            fake.write_text('#!/usr/bin/env python3\nimport json,sys\nprint(json.dumps(sys.argv[1:]))\n')
            fake.chmod(0o755)
            env=dict(os.environ,PATH=d+os.pathsep+os.environ['PATH'])
            env.pop('TVC_GOLD_IMAGE',None)
            return subprocess.run(['bash',str(ROOT/'scripts/demo.sh'),*args],cwd=ROOT,
                                  env=env,capture_output=True,text=True)

    def test_host_paths_are_mapped_and_explicit_binary_is_visible(self):
        result=self.run_launcher('--out',str(ROOT/'results/demo with spaces'),
                                 '--gif='+str(ROOT/'docs/demo.gif'),
                                 '--binary',str(ROOT/'build/tvc_harness'),'--data-only')
        self.assertEqual(result.returncode,0,result.stderr)
        argv=json.loads(result.stdout)
        self.assertIn('/w/results/demo with spaces',argv)
        self.assertIn('--gif=/w/docs/demo.gif',argv)
        self.assertIn('/w/build/tvc_harness',argv)
        self.assertNotIn('--tmpfs',argv)
        expected=json.loads((ROOT/'tests/golden/lockstep/manifest.json').read_text())['toolchain']['image']
        self.assertIn(expected,argv)

    def test_external_paths_are_refused_and_default_build_is_isolated(self):
        result=self.run_launcher('--out','/outside-checkout/demo')
        self.assertNotEqual(result.returncode,0)
        self.assertIn('checkout',result.stderr)
        result=self.run_launcher('--out','results/demo-again')
        self.assertEqual(result.returncode,0,result.stderr)
        argv=json.loads(result.stdout)
        self.assertIn('/w/results/demo-again',argv)
        self.assertIn('/w/build:rw,exec',argv)

    def test_outputs_cannot_disappear_in_temporary_build_mount(self):
        for option,value in (('--out','build/demo'),('--gif','build/demo.gif')):
            result=self.run_launcher(option,value)
            self.assertNotEqual(result.returncode,0)
            self.assertIn('temporary build',result.stderr)

    def test_abbreviated_options_are_not_an_unmapped_path_escape(self):
        import contextlib
        import io
        from scripts import demo
        with contextlib.redirect_stderr(io.StringIO()),self.assertRaises(SystemExit) as result:
            demo.main(['--o=/unmapped'])
        self.assertEqual(result.exception.code,2)
