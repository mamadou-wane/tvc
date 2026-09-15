"""Synthetic qualification fixtures; no measured timing evidence."""
import contextlib
import io
import json
from pathlib import Path
import tempfile
import unittest

from scripts import bench_gate, sweep


def good(mode='harness'):
    s = dict(label='L5', mode=mode, config='abs-deadline mlock fifo:80 cpu:7 no-alloc',
             applied=dict(mlock=True, fifo=True, cpu=True, telemetry=True),
             cycles=100, cycles_requested=100, jitter_us={'p99.9':16.543},
             env=dict(kernel='7.0.0-30-generic', cpu_end=7, timer_migration=0,
                      governor='performance', epp='performance', ac_online=True,
                      cpuidle=dict(driver='acpi_idle', cpus=16, states=[
                          dict(name='POLL', latency_us=0, disabled=2),
                          dict(name='C1', latency_us=1, disabled=2)])))
    if mode == 'freerun':
        s.update(label='L8', config='mode:freerun abs-deadline mlock fifo:80 cpu:7 telemetry record:control',
                 total_cycles=110, warmup=10, ground=dict(requested=False,send_errors=0))
        s['applied'].update(link=True, ground=False)
    return s


class Discipline(unittest.TestCase):
    def test_valid_workload_and_pair_population(self):
        self.assertTrue(hasattr(bench_gate, 'discipline_problem'), 'discipline predicate absent')
        for mode in ('harness','freerun'):
            self.assertIsNone(bench_gate.discipline_problem(good(mode)))

    def test_each_clause_is_independently_required(self):
        mutations = [
            ('mode', None, 'mode'), ('mode','unknown','mode'), ('mode','lockstep','lockstep'),
            ('cycles',99,'cycle'), ('applied.mlock',False,'applied'),
            ('env.kernel','7.0.0-other','kernel'), ('env.timer_migration',1,'timer_migration'),
            ('env.governor','powersave','governor'), ('env.epp','balance_performance','epp'),
            ('env.ac_online',False,'ac_online'), ('env.cpu_end',6,'cpu'),
            ('env.cpuidle',None,'cpuidle'), ('env.cpuidle.states',[],'cpuidle'),
            ('env.cpuidle.cpus',1,'cpuidle'), ('cycles_requested',True,'cycle'),
            ('env.timer_migration',False,'timer_migration')]
        for key,value,reason in mutations:
            with self.subTest(key=key,value=value):
                s=good();target=s;parts=key.split('.')
                for part in parts[:-1]: target=target[part]
                target[parts[-1]]=value
                self.assertIn(reason,bench_gate.discipline_problem(s))
        for value in (0,1,3,16,True,None):
            s=good();s['env']['cpuidle']['states'][0]['disabled']=value
            self.assertIn('cpuidle',bench_gate.discipline_problem(s))
        for key in good()['env']:
            s=good();del s['env'][key]
            self.assertIsNotNone(bench_gate.discipline_problem(s),key)
        s=good();del s['mode']
        self.assertEqual(bench_gate.discipline_problem(s),'summary has no mode field')

    def test_declared_peer_session_expects_the_pair_plus_the_peer(self):
        def disabled(count, mode='harness'):
            s=good(mode)
            for state in s['env']['cpuidle']['states']: state['disabled']=count
            return s
        for mode in ('harness','freerun'):
            with self.subTest(mode=mode):
                self.assertIsNone(bench_gate.discipline_problem(disabled(2,mode)))
                self.assertIsNone(bench_gate.discipline_problem(disabled(2,mode),None))
                self.assertIn('cpuidle',bench_gate.discipline_problem(disabled(3,mode)))
                self.assertIsNone(bench_gate.discipline_problem(disabled(3,mode),11))
                self.assertIn('cpuidle',bench_gate.discipline_problem(disabled(2,mode),11))
                self.assertIn('cpuidle',bench_gate.discipline_problem(disabled(4,mode),11))
        s=disabled(3);s['env']['cpuidle']['states'][1]['disabled']=2
        self.assertIn('cpuidle',bench_gate.discipline_problem(s,11))
        for bad in (-1,True,'11',11.0):
            with self.subTest(peer=bad):
                self.assertIsNotNone(bench_gate.discipline_problem(disabled(3),bad))

    def test_optional_ground_is_not_a_mitigation_or_an_unconditional_exemption(self):
        for requested,applied,valid in ((False,False,True),(True,True,True),
                                         (True,False,False),(False,True,False)):
            for errors in (0,12):
                s=good('freerun');s['ground'].update(requested=requested,send_errors=errors)
                s['applied']['ground']=applied
                self.assertEqual(bench_gate.discipline_problem(s) is None,valid)
                self.assertEqual(sweep.row_problem(s) is None,valid)
        for field in ('ground','applied'):
            s=good('freerun');s[field].pop('requested' if field=='ground' else 'ground')
            self.assertIsNotNone(bench_gate.discipline_problem(s))

    def test_freerun_requires_profile_and_actual_window(self):
        for token in ('mlock','fifo:80','cpu:7','abs-deadline','telemetry','record:control'):
            s=good('freerun');s['config']=s['config'].replace(token,'')
            self.assertIsNotNone(bench_gate.discipline_problem(s),token)
        s=good('freerun');s['total_cycles']=109
        self.assertIn('cycle',bench_gate.discipline_problem(s))
        s=good();s['config']='sleep_for naive-log';s['env']['cpu_end']=3
        self.assertIsNone(bench_gate.discipline_problem(s))


class DirectoryGate(unittest.TestCase):
    def invoke(self, directory, level='L5', extra=()):
        stdout,stderr=io.StringIO(),io.StringIO()
        with contextlib.redirect_stdout(stdout),contextlib.redirect_stderr(stderr):
            rc=bench_gate.main(['--results',str(directory),'--level',level,*extra])
        return rc,stdout.getvalue()+stderr.getvalue()

    def test_l5_baseline_and_refused_bypass(self):
        with tempfile.TemporaryDirectory() as d:
            p=Path(d);(p/'L5.r1.summary.json').write_text(json.dumps(good()))
            self.assertEqual(self.invoke(p)[0],0)
            s=good();s['jitter_us']['p99.9']=25
            (p/'L5.r1.summary.json').write_text(json.dumps(s))
            self.assertEqual(self.invoke(p)[0],1)
            rc,msg=self.invoke(p,extra=['--no-baseline'])
            self.assertEqual(rc,1);self.assertIn('--no-baseline is not permitted for level L5',msg)
        self.assertEqual(bench_gate.verified_p999s('baselines/2026-08-29-pinned-timer-campaign','L5',baseline=True),[16.351,16.543,16.831])

    def test_other_level_nested_failure_cannot_hide(self):
        with tempfile.TemporaryDirectory() as d:
            p=Path(d);(p/'L5.summary.json').write_text(json.dumps(good()))
            (p/'nested').mkdir();s=good();s['env']['epp']='powersave'
            (p/'nested/L7.summary.json').write_text(json.dumps(s))
            rc,msg=self.invoke(p)
            self.assertEqual(rc,1);self.assertIn('nested/L7.summary.json',msg);self.assertIn('epp',msg)

    def test_no_baseline_retains_discipline_and_integrity(self):
        self.assertEqual(bench_gate.NO_BASELINE_LEVELS,('L7','L8'))
        with tempfile.TemporaryDirectory() as d:
            p=Path(d);s=good();s['label']='L7';s['config']+=' telemetry record:control'
            (p/'L7.summary.json').write_text(json.dumps(s))
            self.assertEqual(self.invoke(p,'L7',['--no-baseline'])[0],0)
            self.assertEqual(self.invoke(p,'L7')[0],1)
            s['env']['timer_migration']=1
            (p/'L7.summary.json').write_text(json.dumps(s))
            self.assertEqual(self.invoke(p,'L7',['--no-baseline'])[0],1)
            (p/'L7.summary.json').unlink()
            (p/'L8.summary.json').write_text(json.dumps(good('freerun')))
            rc,msg=self.invoke(p,'L8',['--no-baseline'])
            self.assertEqual(rc,1);self.assertIn('L8',msg)  # no owned artifacts

    def test_wrong_modes_and_malformed_inputs_never_enter_gate(self):
        for level,mode in (('L5','freerun'),('L7','freerun'),('L8','harness')):
            with tempfile.TemporaryDirectory() as d:
                (Path(d)/(level+'.summary.json')).write_text(json.dumps(good(mode)))
                rc,msg=self.invoke(d,level,['--no-baseline'] if level!='L5' else [])
                self.assertEqual(rc,1);self.assertIn('mode',msg)
        for text in ('{}','[]','{broken','{"mode": "harness", "mode": "freerun"}'):
            with tempfile.TemporaryDirectory() as d:
                (Path(d)/'L5.summary.json').write_text(text)
                self.assertEqual(self.invoke(d)[0],1)

class ProfileRefusal(unittest.TestCase):
    def test_l5_cannot_substitute_telemetry_or_naive_workload(self):
        with tempfile.TemporaryDirectory() as d:
            p=Path(d)/'L5.summary.json'
            for config in ('sleep_for naive-log','abs-deadline mlock fifo:80 cpu:7 no-alloc telemetry',
                           'abs-deadline mlock fifo:80 no-alloc'):
                s=good();s['config']=config;p.write_text(json.dumps(s))
                with contextlib.redirect_stdout(io.StringIO()),contextlib.redirect_stderr(io.StringIO()):
                    self.assertEqual(bench_gate.main(['--results',d]),1)

class RosterMetadata(unittest.TestCase):
    def fixture(self, p):
        summary=good('freerun');summary.update(cycles=1000,cycles_requested=1000,total_cycles=1010,
                                             phase_us=400,period_us=2000)
        vehicle=['/bin/tvc','--mode=freerun','--auto-arm','--abs-deadline','--mlock','--fifo=80',
                 '--cpu=7','--telemetry','--record=control','--alloc-guard=abort',
                 '--cycles=1000','--warmup=10','--rate=500','--sensor-port=0','--phase-us=400',
                 '--skew-max-ticks=4','--terminal-copies=12','--label=L8','--out=/fixture']
        peer=['/bin/python3','-B','-m','sim.run_sim','--mode=freerun','--scenario=/fixture/S1-hold.json',
              '--seed=1','--loss=0.0','--delay-ticks=1','--ticks=1043','--vehicle=127.0.0.1:12345',
              '--bind-port=0','--terminal-copies=12','--label=L8','--out=/fixture']
        row=dict(level='L8',label='L8',repeat=1,phase_us=400,cycles=1000,warmup=10,rate=500,
                 complete=True,vehicle_exit=0,sim_exit=0,vehicle_argv=vehicle,sim_argv=peer,
                 ready=dict(mode='freerun',command_port='0',sensor_port='12345',consts='0xe77201ca'),
                 peer_cpu=None,peer=None)
        replay=dict(vehicle_argv=vehicle,sim_argv=peer,seed=1,delay_ticks=1,ticks=1043,
                    ticks_declared=10000,ticks_resolved=1043,scenario='S1-hold',rate_hz=500,
                    period_ns=2000000,loss=dict(p_up=0.0,p_down=0.0),peer_cpu=None,peer=None)
        return summary,row,replay

    def write(self,p,s,row,replay):
        for suffix,value in (('.summary.json',s),('.result.json',row),('.replay.json',replay)):
            (p/('L8'+suffix)).write_text(json.dumps(value))
        (p/'sweep.json').write_text(json.dumps(dict(format='tvc-sweep-1',complete=True,runs=[row])))

    def test_required_metadata_cannot_be_stripped_or_mismatched(self):
        with tempfile.TemporaryDirectory() as d:
            p=Path(d);s,row,replay=self.fixture(p);self.write(p,s,row,replay)
            self.assertEqual(sweep.roster_row(p/'L8'),row)
            for key in ('vehicle_argv','sim_argv','level','repeat','phase_us','cycles','warmup','rate','ready','peer_cpu','peer'):
                s,row,replay=self.fixture(p);row.pop(key);replay.pop(key,None)
                self.write(p,s,row,replay)
                with self.subTest(missing=key),self.assertRaises(ValueError):sweep.roster_row(p/'L8')
            for key,value in (('level','L7'),('cycles',999),('warmup',11),('phase_us',200),('repeat',2)):
                s,row,replay=self.fixture(p);row[key]=value;self.write(p,s,row,replay)
                with self.subTest(key=key),self.assertRaises(ValueError):sweep.roster_row(p/'L8')
            for which,old,new in (('vehicle_argv','--auto-arm',None),
                                   ('vehicle_argv','--alloc-guard=abort','--alloc-guard=off'),
                                   ('sim_argv','--seed=1','--seed=2'),
                                   ('sim_argv','--ticks=1043','--ticks=10000'),
                                   ('sim_argv','--vehicle=127.0.0.1:12345','--vehicle=127.0.0.1:0')):
                s,row,replay=self.fixture(p);argv=row[which]
                if new is None:argv.remove(old)
                else:argv[argv.index(old)]=new
                self.write(p,s,row,replay)
                with self.subTest(old=old),self.assertRaises(ValueError):sweep.roster_row(p/'L8')
