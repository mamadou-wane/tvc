"""CLI integration on short development records; no timing qualification."""
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

from scripts import sweep
from tests.functional.test_sweep import functional_plan

ROOT=Path(__file__).resolve().parents[2]
BIN=Path(os.environ['TVC_BIN'])


class EvidenceCli(unittest.TestCase):
    def test_functional_audit_stays_available_but_evidence_clis_refuse_dev_run(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d);plan=functional_plan()
            self.assertEqual(sweep.run_row(plan,BIN,root),0,plan)
            from scripts.latency import verify_recorded_statistics
            verify_recorded_statistics(root/'L8',sweep.read_json(root/'L8.summary.json'))
            (root/'sweep.json').write_text(json.dumps(dict(format='tvc-sweep-1',complete=True,runs=[plan])))
            commands=[('scripts/latency.py',[str(root/'L8')],0),
                      ('scripts/latency.py',['--results',d],1),
                      ('scripts/latency.py',['--results',d,'--calibration'],1),
                      ('scripts/compare_arms.py',['--results',d],1),
                      ('scripts/bench_gate.py',['--results',d,'--level','L8','--no-baseline'],1)]
            for script,args,expected in commands:
                result=subprocess.run([sys.executable,'-B',script,*args],cwd=ROOT,capture_output=True,text=True)
                self.assertEqual(result.returncode,expected,(script,result.stderr,result.stdout))
            result=subprocess.run([sys.executable,'-B','scripts/plot_jitter.py','--results',d,
                                   '--latency','--out',str(root/'diagnostic.svg')],cwd=ROOT,capture_output=True,text=True)
            self.assertEqual(result.returncode,0,result.stderr)
            self.assertIn('diagnostic',(root/'diagnostic.svg').read_text())
            self.assertTrue((root/'diagnostic.png').is_file())
            (root/'L8.control.tvcrec').write_bytes((root/'L8.control.tvcrec').read_bytes()[:-1])
            result=subprocess.run([sys.executable,'-B','scripts/latency.py',str(root/'L8')],cwd=ROOT,capture_output=True,text=True)
            self.assertEqual(result.returncode,1)

    def test_recorded_statistics_match_existing_cpp_histogram_and_json_semantics(self):
        from scripts.latency import recorded_statistics
        cases=[[],[0],[1,1023,1024,2047,2048,2049,4095,4096],
               [999423],[999424],[999999],[1000000],
               [1999999,2000000,2000001,3000000],[10000000000]]
        cases += [[1]*(count-1)+[3000000] for count in (499,500,501,1000)]
        cases += [[(1<<shift)-1,1<<shift,(1<<shift)+1] for shift in range(11,34)]
        command=[str(BIN.with_name('measurement_tests')),'--statistics-fixtures']
        result=subprocess.run(command,capture_output=True,text=True)
        self.assertEqual(result.returncode,0,result.stderr)
        expected=json.loads(result.stdout)
        self.assertEqual(len(expected),len(cases))
        for values,actual in zip(cases,expected):
            self.assertEqual(recorded_statistics(values),{key:actual[key] for key in ('p99.9','max')})
            self.assertEqual(actual['dropped'],0)
