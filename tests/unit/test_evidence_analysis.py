"""Literal synthetic decisions, never a qualified measurement campaign."""
import copy
import contextlib
import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from scripts import latency, bench_gate, sweep
from tests.unit.test_discipline import good


def row(level='L8', repeat=1, phase=400, calibration=False, coverage=1.0, jitter=16.0):
    label=f'{level}.phase{phase}.r{repeat}' if calibration else f'{level}.r{repeat}'
    s=good('freerun' if level=='L8' else 'harness')
    s.update(label=label,cycles=300000,cycles_requested=300000,period_us=2000)
    s['jitter_us']['p99.9']=jitter
    if level=='L7':s['config']+=' telemetry record:control'
    if level=='L8':
        s.update(total_cycles=305000,warmup=5000,phase_us=phase,
                 link={k:0 for k in latency.BAD},
                 link_recorded=dict(served=round(coverage*300000),consumed=300000,actuator_tx_fail=0),
                 latency_us={'count':round(coverage*300000),'p99.9':1000.0,'max':2000.0})
    replay=dict(loss=dict(p_up=0.0,p_down=0.0))
    recon=dict(eligible=True,terminal_agreement=True,uplink=dict(unexplained_missing=0),
               downlink=dict(unexplained_missing=0),terminal=dict(required_legs_complete=True,causes=[],
                   up=dict(required=True,residual='zero'),down=dict(required=True,residual='unresolved')))
    plan=dict(label=label,level=level,repeat=repeat,phase_us=phase if level=='L8' else None,
              cycles=300000,warmup=5000,rate=500,complete=True)
    if level != 'L8':
        plan['vehicle_argv']=['/bin/tvc','--label='+label,'--out=/synthetic','--cycles=300000',
            '--warmup=5000','--rate=500','--abs-deadline','--mlock','--fifo=80','--cpu=7',
            '--no-naive-log','--alloc-guard=abort']
        if level=='L7':plan['vehicle_argv']+=['--telemetry','--record=control']
    return dict(prefix=Path('/synthetic')/label,summary=s,replay=replay,reconciliation=recon,run=plan,peer_cpu=None)


def calibration_rows(coverages=None):
    coverages=coverages or {200:[1,1,1],400:[1,1,1],800:[1,1,1]}
    return [row(repeat=r,phase=p,calibration=True,coverage=coverages[p][r-1])
            for r in range(1,4) for p in (200,400,800)]


def pairs(diffs=None):
    diffs=diffs or [0]*8
    return [row(level=level,repeat=r,jitter=16+(diffs[r-1] if level=='L8' else 0))
            for r in range(1,9) for level in ('L5','L7','L8')]


class LatencyPolicy(unittest.TestCase):
    def test_policy_exists_and_inclusive_thresholds_pass(self):
        self.assertTrue(hasattr(latency,'evidence_checks'))
        result=latency.evidence_checks(row(coverage=.99))
        self.assertEqual(result['problems'],[])
        self.assertEqual(result['served_coverage'],.99)
        self.assertEqual(result['observation_coverage'],1.0)

    def test_declared_peer_session_rule_is_inherited_not_reinterpreted(self):
        def item(level='L8',disabled=3,peer_cpu=11):
            it=row(level);it['peer_cpu']=peer_cpu
            for state in it['summary']['env']['cpuidle']['states']: state['disabled']=disabled
            return it
        self.assertEqual(latency.evidence_checks(item())['problems'],[])
        self.assertTrue(any('cpuidle' in p for p in latency.evidence_checks(item(peer_cpu=None))['problems']))
        self.assertTrue(any('cpuidle' in p for p in latency.evidence_checks(item(disabled=2))['problems']))
        for level in ('L7','L8'):
            self.assertEqual(latency.experiment_row(item(level),level,1,level+'.r1')['cpu'],'7')
            for it in (item(level,peer_cpu=None),item(level,disabled=2),item(level,disabled=4)):
                with self.subTest(level=level,peer=it['peer_cpu'],disabled=it['summary']['env']['cpuidle']['states'][0]['disabled']),self.assertRaises(ValueError):
                    latency.experiment_row(it,level,1,level+'.r1')
        it=item();del it['peer_cpu']
        with self.assertRaises(ValueError):latency.evidence_checks(it)

    def test_each_policy_clause_isolated(self):
        cases=[(('summary','mode'),'harness','freerun'),
               (('summary','env','epp'),'powersave','epp'),
               (('replay','loss','p_up'),.3,'loss'),
               (('summary','link_recorded','served'),296999,'coverage'),
               (('summary','link_recorded','actuator_tx_fail'),1,'actuator'),
               (('reconciliation','uplink','unexplained_missing'),1,'uplink'),
               (('reconciliation','downlink','unexplained_missing'),1,'downlink'),
               (('reconciliation','terminal_agreement'),False,'terminal'),
               (('reconciliation','terminal','up','residual'),'unexplained','terminal'),
               (('summary','link','bad_crc'),1,'malformed'),
               (('summary','latency_us','p99.9'),1000.001,'p99.9'),
               (('summary','latency_us','max'),2000.001,'max')]
        for path,value,word in cases:
            item=row(coverage=.99);target=item
            for key in path[:-1]:target=target[key]
            target[path[-1]]=value
            if path[-1]=='served':item['summary']['latency_us']['count']=value
            with self.subTest(path=path):self.assertIn(word,' '.join(latency.evidence_checks(item)['problems']))
        for value in (None,True,float('nan'),float('inf'),-1):
            item=row();item['summary']['latency_us']['max']=value
            with self.subTest(value=value),self.assertRaises(ValueError):latency.evidence_checks(item)
        item=row();del item['replay']['loss']
        with self.assertRaises(ValueError):latency.evidence_checks(item)
        item=row();item['reconciliation']['terminal']['down']['residual']='unresolved'
        self.assertEqual(latency.evidence_checks(item)['problems'],[])
        self.assertEqual(item['reconciliation']['terminal']['down']['residual'],'unresolved')


class Calibration(unittest.TestCase):
    def test_smallest_qualifying_offset_and_no_fallback(self):
        cases=[({200:[1]*3,400:[.98]*3,800:[.98]*3},200),
               ({200:[.994]*3,400:[.995]*3,800:[.98]*3},400),
               ({200:[.98]*3,400:[.98]*3,800:[.995]*3},800),
               ({200:[.995]*3,400:[1]*3,800:[1]*3},200),
               ({200:[.994]*3,400:[.994]*3,800:[.994]*3},None)]
        for cov,selected in cases:
            with self.subTest(selected=selected):
                result=latency.calibration(calibration_rows(cov))
                self.assertEqual(result['selected_phase_us'],selected)
                self.assertEqual(result['valid'],selected is not None)
        items=calibration_rows({200:[.99,.995,1],400:[1]*3,800:[1]*3})
        self.assertEqual(latency.calibration(items)['selected_phase_us'],200)
        items[0]['summary']['link_recorded']['served']=296999
        items[0]['summary']['latency_us']['count']=296999
        self.assertEqual(latency.calibration(items)['selected_phase_us'],400)

    def test_bad_populations_are_rejected_before_selection(self):
        for mutate in ('missing','duplicate','offset','loss','discipline','order','label','short','cpu'):
            items=calibration_rows()
            if mutate=='missing':items.pop()
            elif mutate=='duplicate':items[-1]=copy.deepcopy(items[0])
            elif mutate=='offset':items[0]['run']['phase_us']=300
            elif mutate=='loss':items[0]['replay']['loss']['p_down']=.3
            elif mutate=='discipline':items[0]['summary']['env']['ac_online']=False
            elif mutate=='order':items.reverse()
            elif mutate=='label':items[0]['summary']['label']='L8.r1'
            elif mutate=='cpu':
                items[0]['summary']['config']=items[0]['summary']['config'].replace('cpu:7','cpu:6')
                items[0]['summary']['env']['cpu_end']=6
            else:items[0]['run']['cycles']=1000
            with self.subTest(mutate=mutate),self.assertRaises(ValueError):latency.calibration(items)


class PairedRuns(unittest.TestCase):
    def test_comparator_present(self):
        self.assertTrue((Path(__file__).resolve().parents[2]/'scripts/compare_arms.py').exists())

    def test_practical_rule_and_supplemental_signs(self):
        from scripts import compare_arms
        for value,valid in ((2.0,True),(2.0001,False),(1.9999,True),(-1.0,True)):
            result=compare_arms.compare(pairs([value]*8))
            self.assertEqual(result['valid'],valid)
            self.assertAlmostEqual(result['median_difference_us'],value)
            self.assertEqual(result['positive'],8 if value>0 else 0)
            self.assertEqual(result['negative'],8 if value<0 else 0)
            self.assertAlmostEqual(result['sign_test_p'],.0078125)
        result=compare_arms.compare(pairs([0]*8))
        self.assertEqual((result['tied'],result['sign_test_p'],result['valid']),(8,1.0,True))
        result=compare_arms.compare(pairs([-1,0,0,1,1,1,1,1]))
        self.assertEqual((result['positive'],result['negative'],result['tied']),(5,1,2))
        self.assertEqual(result['sign_test_p'],.21875)
        self.assertEqual([p['repeat'] for p in result['pairs']],list(range(1,9)))
        self.assertEqual(compare_arms.compare(pairs()),compare_arms.compare(pairs()))

    def test_bad_pairs_and_configuration_are_not_silently_dropped(self):
        from scripts import compare_arms
        for kind in ('missing','duplicate','mode','label','order','phase','cpu','length','nan'):
            items=pairs()
            if kind=='missing':items.pop()
            elif kind=='duplicate':items[-1]=copy.deepcopy(items[2])
            elif kind=='mode':items[1]['summary']['mode']='freerun'
            elif kind=='label':items[1]['run']['label']='L7.r8'
            elif kind=='order':items.reverse()
            elif kind=='phase':items[-1]['summary']['phase_us']=800
            elif kind=='cpu':items[-1]['summary']['config']=items[-1]['summary']['config'].replace('cpu:7','cpu:6')
            elif kind=='length':items[-1]['run']['cycles']=1000
            else:items[-1]['summary']['jitter_us']['p99.9']=float('nan')
            with self.subTest(kind=kind),self.assertRaises(ValueError):compare_arms.compare(items)

class AnalysisCli(unittest.TestCase):
    def capture(self, function, args):
        stream=io.StringIO()
        with contextlib.redirect_stdout(stream),contextlib.redirect_stderr(stream):
            code=function(args)
        return code,stream.getvalue()

    def test_cli_verdicts_are_deterministic_and_no_baseline_keeps_budgets(self):
        from scripts import compare_arms
        # File/record admission is exercised independently by the process tests;
        # these fixed admitted-row fixtures isolate CLI policy and exit status.
        with patch.object(latency,'ordered_results',return_value=calibration_rows()):
            code,output=self.capture(latency.main,['--results','synthetic','--calibration'])
            self.assertEqual(code,0);self.assertEqual(json.loads(output)['selected_phase_us'],200)
        with patch.object(latency,'ordered_results',return_value=calibration_rows({p:[.994]*3 for p in (200,400,800)})):
            code,output=self.capture(latency.main,['--results','synthetic','--calibration'])
            self.assertEqual(code,1);self.assertEqual(json.loads(output)['message'],'no offset qualifies')
        with patch.object(latency,'ordered_results',return_value=pairs([2.1]*8)):
            a=self.capture(compare_arms.main,['--results','synthetic'])
            b=self.capture(compare_arms.main,['--results','synthetic'])
            self.assertEqual(a,b);self.assertEqual(a[0],1)
            self.assertIn('supplemental',json.loads(a[1])['sign_test_role'])
        item=row()
        with patch.object(bench_gate,'candidate_rows',return_value=[item]):
            self.assertEqual(self.capture(bench_gate.main,['--results','synthetic','--level','L8','--no-baseline'])[0],0)
            item['summary']['latency_us']['max']=2001
            self.assertEqual(self.capture(bench_gate.main,['--results','synthetic','--level','L8','--no-baseline'])[0],1)
            self.assertEqual(self.capture(latency.main,['--results','synthetic'])[0],1)
        for args in (['--level','L5','--no-baseline'],['--level','L8','--no-baseline','--served-coverage-min','.9'],
                     ['--level','L8','--no-baseline','--latency-max-us','2001'],
                     ['--level','L5','--latency-p999-max-us','1000']):
            self.assertEqual(self.capture(bench_gate.main,['--results','synthetic',*args])[0],1)

    def test_missing_roster_and_invalid_other_summary_refuse_all_consumers(self):
        from scripts import compare_arms
        with tempfile.TemporaryDirectory() as d:
            p=Path(d);(p/'L5.r1.summary.json').write_text(json.dumps(row('L5')['summary']))
            (p/'nested').mkdir()
            bad=row('L7')['summary'];bad['env']['timer_migration']=1
            (p/'nested/L7.r1.summary.json').write_text(json.dumps(bad))
            for tool,args in ((latency.main,[]),(latency.main,['--calibration']),(compare_arms.main,[])):
                code,text=self.capture(tool,['--results',d,*args])
                self.assertEqual(code,1);self.assertIn('nested/L7.r1.summary.json',text)
            (p/'nested/L7.r1.summary.json').unlink()
            for tool,args in ((latency.main,['--calibration']),(compare_arms.main,[])):
                self.assertEqual(self.capture(tool,['--results',d,*args])[0],1)

    def test_existing_samplewise_decomposition_and_terminal_membership(self):
        from tests.unit.test_latency import fixture
        summary,controls=fixture()
        result=latency.validate(summary,controls)
        self.assertTrue(result['valid'])
        self.assertEqual(result['served_ns'],[1200])
        self.assertEqual((summary['uplink_wait_us']['sum_ns'],summary['vehicle_compute_us']['sum_ns']),(800,400))
        self.assertEqual(summary['latency_us']['sum_ns'],1200)
        # The nonfresh terminal reply is not another served sample.
        self.assertEqual(summary['latency_us']['count'],1)

class ExactComparisonBoundary(unittest.TestCase):
    def test_decimal_p999_difference_at_margin_is_inclusive(self):
        from scripts import compare_arms
        items=pairs()
        for item in items:
            if item['run']['level']=='L7':item['summary']['jitter_us']['p99.9']=2.001
            if item['run']['level']=='L8':item['summary']['jitter_us']['p99.9']=4.001
        result=compare_arms.compare(items)
        self.assertTrue(result['valid'])
        self.assertEqual(result['median_difference_us'],2.0)

class ReportFailures(unittest.TestCase):
    def test_short_write_or_flush_failure_is_not_a_successful_analysis(self):
        from scripts import compare_arms
        class Output:
            def __init__(self, fail_flush):self.fail_flush=fail_flush
            def write(self,text):return len(text) if self.fail_flush else max(0,len(text)-1)
            def flush(self):
                if self.fail_flush:raise OSError('injected flush failure')
        for fail_flush in (False,True):
            with patch.object(bench_gate,'candidate_rows',return_value=[row()]),contextlib.redirect_stdout(Output(fail_flush)):
                self.assertEqual(latency.main(['--results','synthetic']),1)
            with patch.object(latency,'ordered_results',return_value=pairs()),contextlib.redirect_stdout(Output(fail_flush)):
                self.assertEqual(compare_arms.main(['--results','synthetic']),1)

class ReviewFindings(unittest.TestCase):
    def test_comparison_refuses_missing_or_wrong_harness_argv(self):
        from scripts import compare_arms
        for value in (None,[],['/bin/tvc','--warmup=0','--alloc-guard=off']):
            items=pairs()
            for item in items:
                if item['run']['level'] in ('L5','L7'):item['run']['vehicle_argv']=value
            with self.subTest(value=value),self.assertRaises(ValueError):compare_arms.compare(items)

    def test_recorded_latency_cannot_be_understated(self):
        self.assertTrue(hasattr(latency,'recorded_statistics'))
        self.assertEqual(latency.recorded_statistics([3000000]),{'p99.9':3000.32,'max':3000.32})
        with tempfile.TemporaryDirectory() as d:
            from ground import wire
            p=Path(d)/'L8';sample=dict(tick=0,deadline_ns=0,woke_ns=0,done_ns=3000001,
                sensor_send_ns=1,rx_ns=2,tx_ns=3000001,theta=0,omega=0,cmd=0,i_state=0,d_prev=0,
                sensor_tick=0,staleness=0,rx_count=1,ack_cmd_seq=0,drops=0,state=3,reason=1,
                flags=3,discarded_old=0,discarded_superseded=0,discarded_other=0,ack_status=0)
            frame=wire.encode_frame(6,0,wire.encode_payload(6,sample))
            header=wire.HEADER.pack(wire.MAGIC,1,0,wire.SCHEMA_HASHES[6],0,0)
            Path(str(p)+'.control.tvcrec').write_bytes(header+frame)
            s=dict(warmup=0,latency_us={'p99.9':1,'max':1})
            with self.assertRaisesRegex(ValueError,'recorded'):latency.verify_recorded_statistics(p,s)
            s['latency_us']=dict(latency.recorded_statistics([3000000]))
            latency.verify_recorded_statistics(p,s)
