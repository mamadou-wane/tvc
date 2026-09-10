import importlib
from pathlib import Path
import tempfile
import unittest


class SourceIdentity(unittest.TestCase):
    def setUp(self): self.module=importlib.import_module('scripts.run_campaign')

    def test_length_prefixed_source_identity_matches_independent_literal(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d)
            values={'src/a.cpp':b'A\n','sim/b.py':b'\x00B','CMakeLists.txt':b'project(tvc)\n'}
            for path,data in values.items():
                p=root/path;p.parent.mkdir(parents=True,exist_ok=True);p.write_bytes(data)
            self.assertEqual(self.module.hash_files(root,list(values)),
                             '7481c95e97ad74756c6e285e3d7d33ef475a2ac737f1a7e814a24d9d0062082d')
            self.assertEqual(self.module.hash_files(root,list(reversed(values))),
                             self.module.hash_files(root,list(values)))
            (root/'sim/b.py').write_bytes(b'\x00C')
            self.assertNotEqual(self.module.hash_files(root,list(values)),
                                '7481c95e97ad74756c6e285e3d7d33ef475a2ac737f1a7e814a24d9d0062082d')

    def test_duplicate_outside_missing_and_symlink_inputs_are_rejected(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d);(root/'x').write_text('x');(root/'link').symlink_to(root/'x')
            for paths in (['x','x'],['../x'],['missing'],['link']):
                with self.subTest(paths=paths),self.assertRaises((ValueError,OSError)):
                    self.module.hash_files(root,paths)

    def test_currentness_rejects_changed_source_without_running_cases(self):
        import copy,json
        from tests.unit.test_campaign_manifest import fixture
        with tempfile.TemporaryDirectory() as d:
            root=Path(d)
            for name in list(self.module.FIXED_SOURCES)+['src/x.cpp','src/x.hpp','sim/x.py']:
                path=root/name;path.parent.mkdir(parents=True,exist_ok=True);path.write_text('fixture\n')
            doc=fixture();template=doc['cases'][0];doc['seeds']='1-200'
            doc['cases']=[dict(copy.deepcopy(template),seed=seed,delay_ticks=delay)
                          for seed in range(1,201) for delay in (0,1)]
            doc.update(passed=400,total=400)
            expected=self.module.implementation_source(root)
            doc['run_identity']['implementation_source_sha256']=expected
            doc['scenario_sha256']=self.module.digest(root/'sim/scenarios/S2-gust.json')
            manifest=root/'synthetic-manifest.json';manifest.write_text(json.dumps(doc))
            self.assertEqual(self.module.check_current(manifest,root),expected)
            (root/'src/x.cpp').write_text('changed\n')
            with self.assertRaisesRegex(ValueError,'campaign evidence stale'):
                self.module.check_current(manifest,root)
