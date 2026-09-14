"""Produce and check the fixed demo's artifacts before any visualization."""
import argparse
from collections import Counter
import csv
import json
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
from scripts import golden_csv, run_campaign, run_scenario
from scripts.reconcile import reconcile
from sim.scenario import load

NAME = 'demo-loss30'
SCENARIO = ROOT / 'sim/scenarios/demo-loss30.json'
MANIFEST = ROOT / 'tests/golden/lockstep/manifest.json'


def manifest_document():
    return run_campaign.read_json(MANIFEST)


def manifest_entry(document):
    entries = [row for row in document['scenarios'] if row['scenario'] == NAME]
    if len(entries) != 1:
        raise ValueError('demo must have one canonical manifest entry')
    entry = entries[0]
    if (entry['seed'],entry['delay_ticks'],entry['reason'],entry['reason_tick']) != (20260902,0,1,2999):
        raise ValueError('canonical demo configuration changed')
    return entry


def checked_scenario(expected):
    if run_campaign.digest(SCENARIO) != expected['scenario_sha256']:
        raise ValueError('demo scenario differs from canonical input')
    spec = load(SCENARIO)
    if spec.ticks != 3000:
        raise ValueError('demo scenario horizon changed')
    return spec


def verify_data(prefix, *, canonical=True):
    prefix = Path(prefix)
    path = lambda suffix: Path(str(prefix)+suffix)
    try:
        document = manifest_document(); expected = manifest_entry(document)
        result = run_campaign.read_json(path('.result.json'))
        if (result['eligible'] is not True or any(type(result[k]) is not int or result[k] != 0
                for k in ('code','vehicle_exit','sim_exit'))):
            raise ValueError('demo owner process failed or incomplete')
        summary = run_campaign.read_json(path('.summary.json'))
        report = run_campaign.read_json(path('.sim-report.json'))
        replay = run_campaign.read_json(path('.replay.json'))
        if summary['mode'] != 'lockstep' or summary['timing_valid'] is not False or report['mode'] != 'lockstep':
            raise ValueError('demo requires non-timing lockstep artifacts')
        if canonical and replay['toolchain'] != document['toolchain']:
            raise ValueError('demo toolchain differs from canonical manifest')
        checked_scenario(expected)
        if (replay['scenario'],replay['seed'],replay['delay_ticks'],replay['ticks_resolved']) != (NAME,20260902,0,3000):
            raise ValueError('demo resolved configuration mismatch')
        if replay['scenario_sha256'] != expected['scenario_sha256']:
            raise ValueError('demo scenario identity mismatch')
        controls = run_scenario.recording(path('.control.tvcrec'),6)
        sensors = run_scenario.recording(path('.inputs.tvcrec'),4)
        if len(controls) != 3000 or len(sensors) != 3000:
            raise ValueError('incomplete demo recording')
        checked = reconcile(summary,report,'lockstep',sensors=sensors,controls=controls)
        if checked['eligible'] is not True or checked != run_campaign.read_json(path('.reconcile.json')):
            raise ValueError('demo reconciliation failed or changed')
        if path('.vehicle.csv').read_text() != golden_csv.vehicle_csv(controls):
            raise ValueError('vehicle CSV differs from recording')
        if path('.sim.csv').read_text() != golden_csv.sim_csv(report['rows']):
            raise ValueError('sim CSV differs from owned rows')
        hashes = {key:run_campaign.digest(path('.'+suffix)) for key,suffix in run_campaign.ARTIFACTS.items()}
        if hashes != replay['digests']:
            raise ValueError('demo replay artifact digest mismatch')
        if canonical:
            for key,artifact in run_campaign.GOLDEN_DIGESTS.items():
                if hashes[artifact] != expected[key]:
                    raise ValueError('canonical '+key+' mismatch')
        terminal = summary['episode']
        if (terminal['vehicle_reason'],terminal['reason_tick'],terminal['state']) != (1,2999,3):
            raise ValueError('demo terminal outcome mismatch')
        if any(r['tick'] != tick for tick,r in enumerate(controls)) or controls[-1]['reason'] != 1:
            raise ValueError('demo control tick/state mismatch')
        with path('.sim.csv').open(newline='') as stream:
            rows = list(csv.DictReader(stream))
        if len(rows) != 3000 or any(int(row['tick']) != k for k,row in enumerate(rows)):
            raise ValueError('demo simulator tick mismatch')
        up_lost = [k for k,r in enumerate(rows) if r['has_sample']=='0']
        down_lost = [k for k,r in enumerate(rows) if r['applied']=='0']
        if (len(up_lost) != checked['uplink']['modeled_sample_loss'] or
                len(down_lost) != checked['downlink']['modeled_command_loss']):
            raise ValueError('demo CSV loss markers disagree with owner counters')
        facts = dict(outcome='stabilized',reason=1,terminal_tick=2999,seed=20260902,
            delay_ticks=0,records=len(controls),decode='CRC/sequence clean; zero clock anchors',
            ladder=dict(fresh=sum(bool(r['flags']&1) for r in controls),
                        coast=sum(bool(r['flags']&8) for r in controls),
                        neutral=sum(bool(r['flags']&16) for r in controls),
                        lost=sum(r['staleness']>=21 for r in controls)),
            modeled_loss=dict(up=len(up_lost),down=len(down_lost)),
            staleness=dict(sorted(Counter(r['staleness'] for r in controls).items())),
            vehicle_csv_sha256=hashes['vehicle_csv'],canonical_identity_verified=canonical,
            evidence='deterministic synthetic data; no timing or reliability claim')
        return dict(facts=facts,controls=controls,theta=[run_campaign.number(r['theta_bits']) for r in rows],
                    up_lost=up_lost,down_lost=down_lost)
    except (KeyError,TypeError,IndexError) as error:
        raise ValueError('incomplete demo artifacts: '+str(error)) from error


def run_demo(out, *, binary=None, canonical=True, data_only=False, gif=None):
    document = manifest_document(); expected = manifest_entry(document)
    checked_scenario(expected)
    toolchain = run_campaign.toolchain_info(development=not canonical)
    if canonical and toolchain != document['toolchain']:
        raise ValueError('active demo toolchain differs from canonical manifest')
    out = Path(out).resolve()
    if any(out.glob(NAME+'.*')):
        raise ValueError('demo output already exists; choose a new --out directory')
    if binary is None:
        subprocess.run(['cmake','-S',str(ROOT),'-B',str(ROOT/'build'),'-DCMAKE_BUILD_TYPE=RelWithDebInfo'],check=True)
        subprocess.run(['cmake','--build',str(ROOT/'build'),'--target','tvc_harness','-j'],check=True)
        binary = ROOT/'build/tvc_harness'
    result = run_scenario.run_case(binary=binary,scenario_path=SCENARIO,out=out,label=NAME,
        seed=expected['seed'],delay_ticks=expected['delay_ticks'],toolchain=toolchain)
    if result['eligible'] is not True:
        raise ValueError('demo run failed: '+str(result))
    data = verify_data(out/NAME,canonical=canonical)
    text = json.dumps(data['facts'],sort_keys=True,allow_nan=False)+'\n'
    if sys.stdout.write(text) != len(text):
        raise OSError('short demo report write')
    sys.stdout.flush()
    if not data_only:
        from scripts.render_demo import render
        render(out/NAME,Path(gif) if gif else ROOT/'docs/demo.gif',canonical=canonical)
    return data['facts']


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__,allow_abbrev=False)
    parser.add_argument('--out',type=Path,default=ROOT/'results/demo')
    parser.add_argument('--binary',type=Path)
    parser.add_argument('--gif',type=Path,default=ROOT/'docs/demo.gif')
    parser.add_argument('--data-only',action='store_true')
    args = parser.parse_args(argv)
    try:
        run_demo(args.out,binary=args.binary,gif=args.gif,data_only=args.data_only)
        return 0
    except (OSError,ValueError,subprocess.SubprocessError) as error:
        print('demo: '+str(error),file=sys.stderr)
        return 1


if __name__=='__main__':
    raise SystemExit(main())
