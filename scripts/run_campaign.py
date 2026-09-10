"""Validate attributable lockstep evidence; local candidates are never canonical."""
import argparse
import hashlib
import json
from pathlib import Path
import re
import struct
import sys

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
ARTIFACTS={'inputs_tvcrec':'inputs.tvcrec','control_tvcrec':'control.tvcrec',
           'sim_csv':'sim.csv','vehicle_csv':'vehicle.csv'}
CLAUSES=('termination','peak','settled','cadence','finiteness')
IDENTIFIERS={'model':'pitch-frozen-flight-v1','controller':'pid-v1','actuator':'ideal-angle-v1',
             'sensor':'ideal-v1','environment':'frozen-flight-v1','scenario_schema':'tvc-scenario-v1'}
SHA=re.compile(r'[0-9a-f]{64}')
PUBLISHED=re.compile(r'ghcr\.io/mamadou-wane/tvc-gold@sha256:[0-9a-f]{64}')
FIXED_SOURCES=('scripts/run_campaign.py','scripts/run_scenario.py','scripts/reconcile.py',
               'scripts/golden_csv.py','ground/wire.py','CMakeLists.txt','docker/Dockerfile.gold',
               'sim/scenarios/S2-gust.json')


def require(condition,message):
    if not condition: raise ValueError(message)


def hash_files(root,paths):
    root=Path(root).resolve();paths=list(paths)
    require(len(paths)==len(set(paths)),'duplicate source path')
    digest=hashlib.sha256()
    for name in sorted(paths,key=lambda x:x.encode('utf-8')):
        path=Path(name)
        require(not path.is_absolute() and '..' not in path.parts,'source path outside root')
        full=root/path
        require(not full.is_symlink() and full.is_file(),'missing or symlink source: '+name)
        data=full.read_bytes();encoded=name.encode('utf-8')
        digest.update(struct.pack('<Q',len(encoded)));digest.update(encoded)
        digest.update(struct.pack('<Q',len(data)));digest.update(data)
    return digest.hexdigest()


def implementation_source(root=ROOT):
    root=Path(root)
    names=[p.relative_to(root).as_posix() for pattern in ('src/*.cpp','src/*.hpp','sim/*.py') for p in root.glob(pattern)]
    return hash_files(root,names+list(FIXED_SOURCES))


def seed_range(value):
    require(isinstance(value,str) and re.fullmatch(r'[1-9][0-9]*(?:-[1-9][0-9]*)?',value),'invalid seeds')
    parts=[int(x) for x in value.split('-')];lo=parts[0];hi=parts[-1]
    require(1<=lo<=hi<=200,'seeds outside declared range 1..200')
    return list(range(lo,hi+1))


def valid_digest(value): return isinstance(value,str) and SHA.fullmatch(value) is not None


def check_toolchain(toolchain,canonical):
    require(isinstance(toolchain,dict),'missing toolchain')
    for key in ('platform','machine','gxx','python','cmake','libc','google_crc32c','environment_sha256','lane'):
        require(isinstance(toolchain.get(key),str) and toolchain[key], 'missing toolchain '+key)
    require(valid_digest(toolchain['environment_sha256']),'invalid environment digest')
    if canonical:
        require(toolchain['lane']=='canonical' and isinstance(toolchain.get('image'),str)
                and PUBLISHED.fullmatch(toolchain['image']) is not None,'published platform digest required')
        require(toolchain['platform']=='linux/amd64' and toolchain['machine']=='x86_64','canonical platform mismatch')
    else:
        require(toolchain['lane'] in ('development','local-candidate') and toolchain.get('image') is None,
                'candidate must not claim a published identity')
        if toolchain['lane']=='local-candidate':
            value=toolchain.get('candidate_image_id','')
            require(isinstance(value,str) and re.fullmatch(r'sha256:[0-9a-f]{64}',value),'missing candidate image ID')


def case_directory(root,seed,delay): return Path(root)/f'seed-{seed:03d}-D{delay}'


def validate_artifact_hashes(case,root,scenario):
    prefix=case_directory(root,case['seed'],case['delay_ticks'])/scenario
    require(set(case['digests'])==set(ARTIFACTS),'incomplete artifact inventory')
    for key,suffix in ARTIFACTS.items():
        path=Path(str(prefix)+'.'+suffix)
        require(path.is_file() and not path.is_symlink(),'missing artifact '+str(path))
        require(digest(path)==case['digests'][key],'changed artifact '+key)


def validate_manifest(doc,*,expected_source,expected_toolchain,artifact_root=None,
                      expected_scenario=None,require_full=False,canonical=True,require_pass=True):
    try:
        if expected_scenario is None:expected_scenario=digest(ROOT/'sim/scenarios/S2-gust.json')
        require(doc['format']==('tvc-campaign-1' if canonical else 'tvc-campaign-candidate-1'),'wrong manifest class')
        require(doc['implementation']=='cpp-lockstep','wrong implementation')
        require(doc['scenario']=='S2-gust' and doc['scenario_sha256']==expected_scenario,'wrong scenario identity')
        require(doc['identifiers']==IDENTIFIERS,'wrong model identifiers')
        require(doc['loss']=={'p_up':.30,'p_down':.30},'wrong loss configuration')
        seeds=seed_range(doc['seeds']);delays=doc['delay_ticks']
        require(isinstance(delays,list) and delays and all(type(d) is int and d in (0,1) for d in delays)
                and delays==sorted(set(delays)),'invalid or duplicate delays')
        if require_full:require(seeds==list(range(1,201)) and delays==[0,1],'full declared matrix required')
        identity=doc['run_identity'];check_toolchain(identity['toolchain'],canonical)
        require(identity['toolchain']==expected_toolchain,'toolchain mismatch')
        require(valid_digest(identity['implementation_source_sha256']) and identity['implementation_source_sha256']==expected_source,
                'implementation source mismatch')
        require(valid_digest(identity['vehicle_sha256']) and valid_digest(identity['sim_sha256']),'invalid implementation digest')
        require(isinstance(identity['command'],str) and identity['command'],'missing command')
        expected={(s,d) for s in seeds for d in delays};seen=set();passed=0
        require(isinstance(doc['cases'],list),'missing cases')
        for case in doc['cases']:
            pair=(case['seed'],case['delay_ticks'])
            require(type(pair[0]) is int and type(pair[1]) is int and pair in expected and pair not in seen,'missing, duplicate or unexpected case')
            seen.add(pair)
            require(type(case['eligible']) is bool,'invalid eligibility')
            if not case['eligible']:
                require(not require_pass,'ineligible case')
                require(isinstance(case['errors'],list) and case['errors'],'missing failure reason')
                continue
            clauses=case['clauses']
            require(isinstance(clauses,dict) and set(clauses)==set(CLAUSES) and all(type(x) is bool for x in clauses.values()),'invalid clauses')
            require(set(case['digests'])==set(ARTIFACTS) and all(valid_digest(v) for v in case['digests'].values()),'incomplete artifact digests')
            for key in ('peak_theta_bits','window_max_omega_bits'):
                require(isinstance(case[key],str) and re.fullmatch(r'0x[0-9a-f]{16}',case[key]),'invalid metric bits')
            require(type(case['sim_reason']) is int and type(case['vehicle_reason']) is int,'invalid reasons')
            success=all(clauses.values())
            if success:
                require(case['sim_reason']==1 and case['vehicle_reason']==1,'successful case has wrong terminal reasons')
            require(not require_pass or success,'failed clause')
            passed+=int(success)
            if artifact_root is not None:
                validate_artifact_hashes(case,artifact_root,doc['scenario'])
                actual=inspect_case(case_directory(artifact_root,*pair),doc['scenario'],*pair,.30,
                    expected_binary=identity['vehicle_sha256'],expected_sim=identity['sim_sha256'],
                    expected_toolchain=expected_toolchain)
                require(all(case.get(k)==v for k,v in actual.items()),'case facts differ from retained evidence')
        require(seen==expected,'missing case')
        require(type(doc['total']) is int and type(doc['passed']) is int and doc['total']==len(expected) and doc['passed']==passed,'wrong aggregate')
    except (KeyError,TypeError) as exc:
        raise ValueError('malformed/incomplete manifest: '+str(exc)) from exc


def read_json(path):
    def unique(pairs):
        value={}
        for key,item in pairs:
            require(key not in value,'duplicate JSON key '+key);value[key]=item
        return value
    def invalid(value): raise ValueError('nonfinite JSON value '+value)
    return json.loads(Path(path).read_text(),object_pairs_hook=unique,parse_constant=invalid)


def check_current(path,root=ROOT):
    doc=read_json(path);current=implementation_source(root)
    try: stored=doc['run_identity']['implementation_source_sha256']
    except (KeyError,TypeError): raise ValueError('missing source identity') from None
    require(stored==current,f'campaign evidence stale: {stored} != {current}')
    validate_manifest(doc,expected_source=current,expected_toolchain=doc['run_identity']['toolchain'],
                      expected_scenario=digest(Path(root)/'sim/scenarios/S2-gust.json'),require_full=True)
    return current


def toolchain_info(*,development=False,candidate_image_id=None):
    import importlib.metadata
    import os
    import platform
    import subprocess
    def line(*args):return subprocess.check_output(args,text=True).splitlines()[0]
    observed=dict(platform=platform.system().lower()+'/'+('amd64' if platform.machine()=='x86_64' else 'arm64'),
        machine=platform.machine(),gxx=line('g++','--version'),python=platform.python_version(),
        cmake=line('cmake','--version'),libc=line('ldd','--version'),
        google_crc32c=importlib.metadata.version('google-crc32c'))
    if development:
        observed.update(image=None,lane='development',environment_sha256=hashlib.sha256(
            json.dumps(observed,sort_keys=True).encode()).hexdigest())
        return observed
    root=Path('/opt/tvc-gold');payload=(root/'environment.json').read_bytes();pinned=read_json(root/'environment.json')
    require(all(observed[k]==pinned[k] for k in observed),'active tools differ from pinned environment')
    installed=subprocess.check_output(['dpkg-query','-W','-f=${binary:Package}=${Version}\n'],text=True)
    inventory=('\n'.join(sorted(installed.splitlines()))+'\n').encode()
    require(hashlib.sha256(inventory).hexdigest()==pinned['packages_sha256'],'package closure changed')
    revision=subprocess.check_output(['git','-C',str(root/'hdr_histogram'),'rev-parse','HEAD'],text=True).strip()
    require(revision==pinned['hdr_histogram'],'HdrHistogram revision changed')
    require(subprocess.run(['git','-C',str(root/'hdr_histogram'),'diff','--quiet']).returncode==0,'HdrHistogram source changed')
    observed.update(environment_sha256=hashlib.sha256(payload).hexdigest(),
                    packages_sha256=pinned['packages_sha256'],hdr_histogram=revision)
    if candidate_image_id:
        observed.update(image=None,lane='local-candidate',candidate_image_id=candidate_image_id)
        check_toolchain(observed,False)
    else:
        observed.update(image=os.environ.get('TVC_GOLD_IMAGE'),lane='canonical')
        check_toolchain(observed,True)
    return observed


def digest(path):return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def number(bits):
    require(isinstance(bits,str) and re.fullmatch(r'0x[0-9a-f]{16}',bits),'invalid binary64 word')
    return struct.unpack('<d',struct.pack('<Q',int(bits,16)))[0]


def bitword(value):return f'0x{struct.unpack("<Q",struct.pack("<d",value))[0]:016x}'


def inspect_case(directory,scenario,seed,delay,loss,*,expected_binary=None,expected_sim=None,expected_toolchain=None):
    from ground import wire
    from sim.episode import TerminalResult
    from sim.run_headless import run_headless
    from sim.scenario import load
    from sim.trace import EvidenceRow,evaluate_rows
    from scripts.golden_csv import sim_csv,vehicle_csv
    from scripts.run_scenario import recording
    from scripts.reconcile import reconcile
    prefix=Path(directory)/scenario
    summary=read_json(str(prefix)+'.summary.json');report=read_json(str(prefix)+'.sim-report.json')
    result=read_json(str(prefix)+'.result.json');replay=read_json(str(prefix)+'.replay.json')
    if expected_binary is not None:require(replay['vehicle_sha256']==expected_binary,'vehicle binary identity mismatch')
    if expected_sim is not None:require(replay['sim_sha256']==expected_sim,'simulator source identity mismatch')
    if expected_toolchain is not None:require(replay['toolchain']==expected_toolchain,'case toolchain mismatch')
    require(result['eligible'] is True and result['vehicle_exit']==0 and result['sim_exit']==0,'ineligible process result')
    sensors=recording(str(prefix)+'.inputs.tvcrec',4);controls=recording(str(prefix)+'.control.tvcrec',6)
    checked=reconcile(summary,report,'lockstep',sensors=sensors,controls=controls)
    require(checked['eligible'] and checked==read_json(str(prefix)+'.reconcile.json'),'incomplete reconciliation')
    require(Path(str(prefix)+'.sim.csv').read_text()==sim_csv(report['rows']),'sim CSV differs from owned rows')
    require(Path(str(prefix)+'.vehicle.csv').read_text()==vehicle_csv(controls),'vehicle CSV differs from recording')
    hashes={key:digest(str(prefix)+'.'+suffix) for key,suffix in ARTIFACTS.items()}
    require(hashes==replay['digests'],'artifact digest mismatch')
    spec=load(ROOT/'sim/scenarios'/(scenario+'.json'))
    if loss is not None:spec=spec._replace(loss_up=loss,loss_down=loss)
    require(replay['scenario_sha256']==digest(ROOT/'sim/scenarios'/(scenario+'.json')),'scenario bytes mismatch')
    require(replay['seed']==seed and replay['delay_ticks']==delay,'case identity mismatch')
    reference=run_headless(spec,seed=seed,delay_ticks=delay)
    require(checked['uplink']['modeled_sample_loss']==sum(r.up_drop for r in reference.rows),
            'modeled sample loss differs from reference')
    require(checked['downlink']['modeled_command_loss']==sum(r.down_drop for r in reference.rows),
            'modeled command loss differs from reference')
    require(reference.to_sim_csv()==Path(str(prefix)+'.sim.csv').read_text(),'Python/C++ truth or applied-state mismatch')
    require(len(reference.rows)==len(controls),'reference length mismatch')
    for record,row in zip(controls,reference.rows):
        require(record['tick']==row.tick and record['state']==row.episode.state.mode,'reference state mismatch')
        why=row.episode.state.terminal.reason if row.episode.state.terminal else 0
        require(record['reason']==why and record['staleness']==row.staleness,'reference policy mismatch')
        for key,value in [('cmd',row.episode.requested_delta),('i_state',row.episode.state.pid.i_state),('d_prev',row.episode.state.pid.d_prev)]:
            require(bitword(record[key])==bitword(value),'reference '+key+' mismatch')
    terminal=summary['episode'];rows=tuple(EvidenceRow(r['tick'],number(r['theta_bits']),number(r['omega_bits']),
        c['cmd'],c['i_state'],c['d_prev']) for r,c in zip(report['rows'],controls))
    clauses=evaluate_rows(rows,spec.ticks,report['sim_reason'],controls[-1]['state'],
                         TerminalResult(terminal['vehicle_reason'],terminal['reason_tick']))
    return dict(seed=seed,delay_ticks=delay,eligible=True,sim_reason=report['sim_reason'],
        sim_reason_name=report['sim_reason_name'],vehicle_reason=terminal['vehicle_reason'],
        vehicle_reason_name=terminal['vehicle_reason_name'],reason_tick=terminal['reason_tick'],
        consumed_ticks=summary['link']['admitted'],clauses=clauses._asdict(),digests=hashes,
        peak_theta_bits=bitword(max(abs(r.theta) for r in rows)),
        window_max_omega_bits=bitword(max(abs(r.omega) for r in rows[-1000:])),errors=[])


def run_matrix(*,binary,out,seeds,delays,toolchain):
    from scripts.run_scenario import run_case
    source=implementation_source();cases=[];binary_sha=digest(binary)
    sim_sha=hashlib.sha256(b''.join(p.read_bytes() for p in sorted((ROOT/'sim').glob('*.py')))).hexdigest()
    for seed in seeds:
        for delay in delays:
            directory=case_directory(out,seed,delay)
            try:
                result=run_case(binary=binary,scenario_path=ROOT/'sim/scenarios/S2-gust.json',
                    out=directory,label='S2-gust',seed=seed,delay_ticks=delay,loss=.30,toolchain=toolchain)
                require(result['eligible'],'process case failed: '+str(result))
                case=inspect_case(directory,'S2-gust',seed,delay,.30,expected_binary=binary_sha,expected_sim=sim_sha,expected_toolchain=toolchain)
            except (OSError,ValueError,KeyError,TypeError) as exc:
                case=dict(seed=seed,delay_ticks=delay,eligible=False,clauses=None,
                          sim_reason=None,vehicle_reason=None,errors=[str(exc)],
                          digests={key:(digest(directory/('S2-gust.'+suffix)) if (directory/('S2-gust.'+suffix)).is_file() else None)
                                   for key,suffix in ARTIFACTS.items()})
            cases.append(case)
    if implementation_source()!=source:
        for case in cases:case['eligible']=False;case['errors'].append('source changed during campaign')
    canonical=toolchain['lane']=='canonical'
    doc=dict(format='tvc-campaign-1' if canonical else 'tvc-campaign-candidate-1',implementation='cpp-lockstep',
        scenario='S2-gust',scenario_sha256=digest(ROOT/'sim/scenarios/S2-gust.json'),identifiers=IDENTIFIERS,
        loss=dict(p_up=.30,p_down=.30),seeds=f'{seeds[0]}-{seeds[-1]}',delay_ticks=delays,cases=cases,
        passed=sum(c['eligible'] and all(c['clauses'].values()) for c in cases),total=len(seeds)*len(delays),
        run_identity=dict(implementation_source_sha256=source,vehicle_sha256=binary_sha,sim_sha256=sim_sha,
                          toolchain=toolchain,command='python3 scripts/run_campaign.py --scenario S2-gust --loss 0.30 '
                          f"--seeds {seeds[0]}-{seeds[-1]} --delay-ticks {','.join(map(str,delays))} --check"))
    validate_manifest(doc,expected_source=source,expected_toolchain=toolchain,canonical=canonical,require_pass=False)
    return doc


GOLDEN_SCENARIOS=('S1-hold','S2-gust','S3-kick','S4-open','S5-overgust','S6-blackout','S7-abort','demo-loss30')
GOLDEN_DIGESTS={'sim_csv_sha256':'sim_csv','vehicle_csv_sha256':'vehicle_csv',
                'inputs_sha256':'inputs_tvcrec','control_sha256':'control_tvcrec'}
OUTCOMES={1:'stabilized',2:'diverged',3:'aborted',4:'sensor lost',7:'not settled'}


def golden_entry(directory,name,toolchain=None):
    seed=20260902 if name=='demo-loss30' else 1
    case=inspect_case(directory,name,seed,0,None,expected_toolchain=toolchain)
    return dict(scenario=name,scenario_sha256=digest(ROOT/'sim/scenarios'/(name+'.json')),
        seed=seed,delay_ticks=0,reason=case['vehicle_reason'],reason_tick=case['reason_tick'],
        outcome=OUTCOMES[case['vehicle_reason']],consumed_ticks=case['consumed_ticks'],
        **{key:case['digests'][artifact] for key,artifact in GOLDEN_DIGESTS.items()})


def validate_goldens(doc,*,expected_source,expected_toolchain,artifact_root=None,canonical=True):
    try:
        require(doc['format']==('tvc-lockstep-goldens-1' if canonical else 'tvc-lockstep-goldens-candidate-1'),'wrong golden class')
        check_toolchain(doc['toolchain'],canonical)
        require(doc['toolchain']==expected_toolchain,'golden toolchain mismatch')
        require(doc['implementation_source_sha256']==expected_source,'golden source mismatch')
        require(isinstance(doc['scenarios'],list),'missing golden scenarios')
        names=[]
        for entry in doc['scenarios']:
            name=entry['scenario'];names.append(name)
            require(name in GOLDEN_SCENARIOS,'unexpected golden scenario')
            require(entry['seed']==(20260902 if name=='demo-loss30' else 1) and entry['delay_ticks']==0,'wrong golden parameters')
            require(valid_digest(entry['scenario_sha256']),'missing scenario digest')
            require(all(valid_digest(entry[k]) for k in GOLDEN_DIGESTS),'incomplete golden digests')
            require(type(entry['reason']) is int and entry['reason'] in OUTCOMES and entry['outcome']==OUTCOMES[entry['reason']], 'invalid golden outcome')
            require(type(entry['reason_tick']) is int and entry['reason_tick']>=0 and type(entry['consumed_ticks']) is int and entry['consumed_ticks']>=0,'invalid golden counts')
            if artifact_root is not None:
                require(entry==golden_entry(Path(artifact_root)/name,name,expected_toolchain),'golden artifact or oracle mismatch: '+name)
        require(len(names)==len(GOLDEN_SCENARIOS) and set(names)==set(GOLDEN_SCENARIOS),'missing or duplicate golden scenario')
    except (KeyError,TypeError) as exc:raise ValueError('malformed golden manifest: '+str(exc)) from exc


def generate_goldens(*,binary,out,toolchain):
    from scripts.run_scenario import run_case
    out=Path(out);source=implementation_source();entries=[]
    for name in GOLDEN_SCENARIOS:
        seed=20260902 if name=='demo-loss30' else 1
        result=run_case(binary=binary,scenario_path=ROOT/'sim/scenarios'/(name+'.json'),
                        out=out/name,label=name,seed=seed,delay_ticks=0,toolchain=toolchain)
        require(result['eligible'],'golden run failed: '+name)
        entries.append(golden_entry(out/name,name,toolchain))
    # A real missing mid-run reply must change observed diagnostics, not these files.
    name='S2-gust';repeat=out/'repeat';retry=out/'retry'
    for target,args in ((repeat,()),(retry,('--test-drop-actuator=1500',))):
        result=run_case(binary=binary,scenario_path=ROOT/'sim/scenarios/S2-gust.json',
            out=target,label=name,seed=1,delay_ticks=0,sim_args=args,toolchain=toolchain)
        require(result['eligible'],'repeat/retry failed')
        inspect_case(target,name,1,0,None)
        for suffix in ARTIFACTS.values():
            require((out/name/(name+'.'+suffix)).read_bytes()==(target/(name+'.'+suffix)).read_bytes(),
                    'repeat/retry changed '+suffix)
    normal=read_json(out/name/(name+'.reconcile.json'))
    repeated=read_json(retry/(name+'.reconcile.json'))
    require(repeated['uplink']['transmitted']>normal['uplink']['transmitted'] and
            repeated['uplink']['discarded_duplicate']>normal['uplink']['discarded_duplicate'],'retry hook did not execute')
    diagnostics=out/'diagnostic-csv';diagnostics.mkdir()
    for name in ('S4-open','S6-blackout','S7-abort','S2-gust','S5-overgust'):
        for side in ('sim','vehicle'):
            lines=(out/name/(name+'.'+side+'.csv')).read_text().splitlines(True)
            prefix=name in ('S2-gust','S5-overgust')
            filename=name+('.head2000' if prefix else '')+'.'+side+'.csv'
            (diagnostics/filename).write_text(''.join(lines[:2001] if prefix else lines))
    require(implementation_source()==source,'source changed during golden generation')
    doc=dict(format='tvc-lockstep-goldens-1' if toolchain['lane']=='canonical' else 'tvc-lockstep-goldens-candidate-1',
             implementation_source_sha256=source,toolchain=toolchain,scenarios=entries)
    validate_goldens(doc,expected_source=source,expected_toolchain=toolchain,canonical=toolchain['lane']=='canonical')
    return doc


def write_manifest(path,doc):
    path=Path(path);path.parent.mkdir(parents=True,exist_ok=True)
    with path.open('x') as stream:stream.write(json.dumps(doc,sort_keys=True,indent=2,allow_nan=False)+'\n')


def check_destination(path,*,canonical,goldens,seeds=None,delays=None):
    protected=ROOT/'tests/golden/lockstep'
    path=Path(path).resolve()
    if path not in (protected/'manifest.json',protected/'campaign-v02b.json'):return
    require(canonical,'candidate cannot occupy either authoritative path')
    if path==protected/'manifest.json':require(goldens,'golden path requires golden evidence')
    else:
        require(not goldens and seeds==list(range(1,201)) and delays==[0,1],
                'campaign path requires full canonical matrix')


def main(argv=None):
    from scripts.run_scenario import Arguments
    parser=Arguments(description=__doc__)
    parser.add_argument('--check-current',action='store_true')
    parser.add_argument('--validate',action='store_true')
    parser.add_argument('--goldens',action='store_true')
    parser.add_argument('--manifest')
    parser.add_argument('--binary',default=str(ROOT/'build/tvc_harness'))
    parser.add_argument('--out');parser.add_argument('--scenario',choices=['S2-gust'],default='S2-gust')
    parser.add_argument('--loss',type=float,default=.30);parser.add_argument('--seeds')
    parser.add_argument('--delay-ticks',default='0,1');parser.add_argument('--check',action='store_true')
    mode=parser.add_mutually_exclusive_group();mode.add_argument('--development',action='store_true')
    mode.add_argument('--candidate-image-id')
    args=parser.parse_args(argv)
    try:
        if args.check_current:
            print('campaign evidence current: '+check_current(args.manifest or ROOT/'tests/golden/lockstep/campaign-v02b.json'));return 0
        toolchain=toolchain_info(development=args.development,candidate_image_id=args.candidate_image_id)
        canonical=toolchain['lane']=='canonical'
        if args.validate:
            require(args.manifest is not None and args.out is not None,'--manifest and --out artifact root required')
            doc=read_json(args.manifest)
            validator=validate_goldens if args.goldens else validate_manifest
            validator(doc,expected_source=implementation_source(),expected_toolchain=toolchain,
                      artifact_root=args.out,canonical=canonical)
            print('evidence validated ('+toolchain['lane']+')');return 0
        if args.goldens:
            require(args.out is not None and args.manifest is not None,'--out and --manifest required for goldens')
            require(not Path(args.manifest).exists(),'golden manifest already exists')
            check_destination(args.manifest,canonical=canonical,goldens=True)
            doc=generate_goldens(binary=args.binary,out=args.out,toolchain=toolchain)
            write_manifest(args.manifest,doc)
            print(toolchain['lane']+': eight scenarios matched Python; four-artifact repeat/retry passed')
            return 0
        require(args.out is not None and args.seeds is not None,'explicit --out and --seeds required')
        require(args.loss==.30,'campaign loss is fixed at 0.30 in both directions')
        seeds=seed_range(args.seeds);delays=[int(v) for v in args.delay_ticks.split(',')]
        require(delays and delays==sorted(set(delays)) and all(d in (0,1) for d in delays),'invalid delays')
        manifest=Path(args.manifest) if args.manifest else Path(args.out)/'campaign.json'
        check_destination(manifest,canonical=canonical,goldens=False,seeds=seeds,delays=delays)
        require(not manifest.exists(),'manifest already exists; generate separately and compare')
        doc=run_matrix(binary=args.binary,out=args.out,seeds=seeds,delays=delays,toolchain=toolchain)
        write_manifest(manifest,doc)
        print(f"{toolchain['lane']}: {doc['passed']}/{doc['total']} cases passed")
        return int(any(not c['eligible'] for c in doc['cases']) or (args.check and doc['passed']!=doc['total']))
    except (OSError,ValueError,KeyError,TypeError) as error:
        print('campaign: '+str(error),file=sys.stderr);return 1


if __name__=='__main__':raise SystemExit(main())
