import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest

ROOT=Path(__file__).resolve().parents[2]


class CanonicalEntrypoint(unittest.TestCase):
    def test_clean_checkout_has_mountpoint_before_read_only_container(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d);repo=root/'checkout';(repo/'scripts').mkdir(parents=True)
            script=repo/'scripts/check_canonical.sh'
            shutil.copyfile(ROOT/'scripts/check_canonical.sh',script)
            command=root/'docker'
            command.write_text('''#!/usr/bin/env python3
import pathlib,sys
args=sys.argv[1:]
if args[:2]==['image','inspect']:
    print('amd64')
elif args[0]=='run':
    source=next(v[:-6] for v in args if v.endswith(':/w:ro'))
    assert (pathlib.Path(source)/'build').is_dir(), 'missing read-only mountpoint'
    assert '--network=none' in args and '/w/build:rw,exec' in args
else:
    raise AssertionError(args)
''')
            command.chmod(0o755)
            self.assertFalse((repo/'build').exists())
            result=subprocess.run(['bash',str(script),'--candidate','sha256:'+'a'*64,str(root/'out')],
                env={**os.environ,'PATH':str(root)+os.pathsep+os.environ['PATH']},
                capture_output=True,text=True)
            self.assertEqual(result.returncode,0,result.stderr)
