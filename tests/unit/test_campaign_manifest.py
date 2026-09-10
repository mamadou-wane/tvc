import copy
import hashlib
import importlib
from pathlib import Path
import tempfile
import unittest

SOURCE='1'*64
TOOLCHAIN=dict(image='ghcr.io/mamadou-wane/tvc-gold@sha256:'+'a'*64,
               platform='linux/amd64',machine='x86_64',gxx='fixture-g++',python='fixture-python',
               cmake='fixture-cmake',libc='fixture-libc',google_crc32c='fixture-crc',
               environment_sha256='b'*64,lane='canonical')
CLAUSES=('termination','peak','settled','cadence','finiteness')
ARTIFACTS={'inputs_tvcrec':'inputs.tvcrec','control_tvcrec':'control.tvcrec',
           'sim_csv':'sim.csv','vehicle_csv':'vehicle.csv'}


def fixture():
    cases=[]
    for seed in (1,2):
        for delay in (0,1):
            cases.append(dict(seed=seed,delay_ticks=delay,eligible=True,sim_reason=1,
                sim_reason_name='SIM_HORIZON',vehicle_reason=1,vehicle_reason_name='STABILIZED',
                clauses=dict.fromkeys(CLAUSES,True),digests={k:hashlib.sha256(k.encode()).hexdigest() for k in ARTIFACTS},
                peak_theta_bits='0x0000000000000000',window_max_omega_bits='0x0000000000000000',errors=[]))
    return dict(format='tvc-campaign-1',implementation='cpp-lockstep',scenario='S2-gust',
        scenario_sha256='c'*64,loss=dict(p_up=.30,p_down=.30),seeds='1-2',delay_ticks=[0,1],
        identifiers={'model':'pitch-frozen-flight-v1','controller':'pid-v1','sensor':'ideal-v1',
                     'actuator':'ideal-angle-v1','environment':'frozen-flight-v1','scenario_schema':'tvc-scenario-v1'},
        run_identity=dict(implementation_source_sha256=SOURCE,vehicle_sha256='d'*64,sim_sha256='e'*64,
                          toolchain=copy.deepcopy(TOOLCHAIN),command='fixture command'),
        cases=cases,passed=4,total=4)


class ManifestValidation(unittest.TestCase):
    def setUp(self): self.module=importlib.import_module('scripts.run_campaign')

    def validate(self,doc,**kwargs):
        return self.module.validate_manifest(doc,expected_source=SOURCE,expected_toolchain=TOOLCHAIN,
                                             expected_scenario='c'*64,**kwargs)

    def test_scenario_hash_is_bound_to_expected_bytes(self):
        doc=fixture();doc['scenario_sha256']='0'*64
        with self.assertRaisesRegex(ValueError,'scenario identity'):self.validate(doc)

    def test_candidate_writers_cannot_use_either_authoritative_path(self):
        from unittest.mock import patch
        candidate=dict(TOOLCHAIN,image=None,lane='development')
        for goldens in (False,True):
            for filename in ('manifest.json','campaign-v02b.json'):
                args=['--development','--out=/unused','--seeds=1-2',
                      '--manifest='+str(self.module.ROOT/'tests/golden/lockstep'/filename)]
                if goldens:args.append('--goldens')
                with self.subTest(goldens=goldens,filename=filename), \
                     patch.object(self.module,'toolchain_info',return_value=candidate), \
                     patch.object(self.module,'generate_goldens') as generate, \
                     patch.object(self.module,'run_matrix',return_value=fixture()) as matrix, \
                     patch.object(self.module,'write_manifest') as write:
                    self.assertEqual(self.module.main(args),1)
                    generate.assert_not_called();matrix.assert_not_called();write.assert_not_called()

    def test_complete_small_matrix_passes_but_is_not_full_qualification(self):
        self.validate(fixture())
        with self.assertRaises(ValueError):self.validate(fixture(),require_full=True)

    def test_missing_duplicate_failed_clause_wrong_identity_and_malformed_fail(self):
        for kind in ('missing','duplicate','clause','implementation','source','digest','stale','malformed','aggregate','schema'):
            doc=fixture()
            if kind=='missing':doc['cases'].pop()
            elif kind=='duplicate':doc['cases'][1]=copy.deepcopy(doc['cases'][0])
            elif kind=='clause':doc['cases'][0]['clauses']['peak']=False;doc['passed']=3
            elif kind=='implementation':doc['implementation']='python'
            elif kind=='source':doc['run_identity']['implementation_source_sha256']='0'*64
            elif kind=='digest':doc['cases'][0]['digests'].pop('control_tvcrec')
            elif kind=='stale':doc['run_identity']['toolchain']['image']='ghcr.io/mamadou-wane/tvc-gold@sha256:'+'0'*64
            elif kind=='malformed':doc['cases'][0]['clauses']['termination']=1
            elif kind=='aggregate':doc['passed']=400
            else:doc['scenario']='S5-overgust'
            with self.subTest(kind=kind),self.assertRaises(ValueError):self.validate(doc)

    def test_changed_artifact_bytes_or_digest_are_rejected(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d);doc=fixture()
            for case in doc['cases']:
                directory=root/f"seed-{case['seed']:03d}-D{case['delay_ticks']}";directory.mkdir()
                for key,suffix in ARTIFACTS.items():(directory/('S2-gust.'+suffix)).write_bytes(key.encode())
            for case in doc['cases']:self.module.validate_artifact_hashes(case,root,'S2-gust')
            (root/'seed-001-D0/S2-gust.control.tvcrec').write_bytes(b'changed')
            with self.assertRaises(ValueError):self.module.validate_artifact_hashes(doc['cases'][0],root,'S2-gust')

    def test_candidate_never_passes_as_published_identity(self):
        doc=fixture();doc['format']='tvc-campaign-candidate-1'
        doc['run_identity']['toolchain'].update(image=None,lane='local-candidate',candidate_image_id='sha256:'+'f'*64)
        with self.assertRaises(ValueError):self.validate(doc)

    def test_ineligible_case_is_retained_and_cannot_pass(self):
        doc=fixture();doc['cases'][0].update(eligible=False,clauses=None,errors=['missing recording'])
        doc['cases'][0]['digests']={k:None for k in ARTIFACTS};doc['passed']=3
        with self.assertRaises(ValueError):self.validate(doc)
