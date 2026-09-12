import copy
import unittest
from scripts.reconcile import terminal_residual, reconcile
from tests.unit.test_latency import fixture


class TerminalResidual(unittest.TestCase):
    def test_literal_lifetimes(self):
        for sent,received,closed,expected in ((3,3,20,'zero'),(3,1,20,'unresolved'),
                                             (3,0,5,'trailing'),(3,0,40,'unexplained')):
            with self.subTest(expected=expected):
                r=terminal_residual(sent,received,10,30,0,closed,True)
                self.assertEqual(r['residual'],expected)
                self.assertEqual(r['unobserved'],sent-received)
        self.assertEqual(terminal_residual(3,1,10,30,0,40,True,answered=True)['residual'],'unresolved')
        self.assertEqual(terminal_residual(3,0,10,30,0,20,False)['residual'],'not_evaluated')
        with self.assertRaises(ValueError): terminal_residual(1,2,10,30,0,40,True)


def pair():
    s,rows=fixture()
    s['last_received_tick']=0
    s.update(clock_domain='linux-monotonic:test:time',termination_before_ns=1999900,termination_ns=2000000,termination_source='simulator')
    rows[-1]['rx_count']=1
    s['terminal'].update(up_received_raw=1,up_received_raw_recorded=1,up_tick_conflict=0,up_illegal_reason=0,up_future_expired=0,
        up_skew_excess=0,send_first_ns=2000000,send_last_ns=24000000,
        receive_open_ns=0,receive_closed_ns=2002000)
    s['terminal_copies']=12
    p=dict(clock_domain='linux-monotonic:test:time',termination_before_ns=1499900,termination_ns=1500000,termination_source='local',mode='freerun',sim_reason=1,vehicle_reason_seen=7,terminal_handshake='answered',
        transmission=dict(generated=1,intentionally_lost=0,transmitted=1,sensor_tx_fail=0),
        actuator_receipt=dict(received=1,actuator_selected=1,intentionally_lost=0,superseded=0,
                              malformed=0,invalid=0,last_received_tick=0),
        terminal=dict(up_attempts=2,up_intentionally_lost=0,up_tx_fail=0,up_transmitted=2,
                      down_received_raw=1,down_intentionally_lost=0,down_survived=1),
        terminal_send_first_ns=1500000,terminal_send_last_ns=3500000,
        receive_open_ns=0,receive_closed_ns=4000000)
    p.update(roundtrip_samples=[],latency_roundtrip_ns=[],latency_roundtrip_us=dict(count=0,sum_ns=0,p50=0,**{'p99.9':0},max=0))
    sensors=[dict(tick=0,flags=1),dict(tick=1,flags=3)]
    return s,p,sensors,rows


class FreeReconcile(unittest.TestCase):
    def test_answered_paths_and_unresolved_residuals(self):
        s,p,sensors,rows=pair()
        r=reconcile(s,p,'freerun',sensors=sensors,controls=rows)
        self.assertEqual(r['errors'],[])
        self.assertEqual(r['terminal']['path'],'sim_first_up_delivered')
        self.assertEqual(r['terminal']['up']['residual'],'unresolved')
        self.assertEqual(r['terminal']['down']['residual'],'unresolved')
        self.assertTrue(r['terminal']['required_legs_complete'])
        self.assertEqual(r['terminal']['causes'],[])
        s['termination_source']='local';p['termination_source']='vehicle';p['termination_ns']=4000000
        p['sim_reason']=4;p['terminal'].update(up_attempts=0,up_transmitted=0)
        s['episode']['sim_reason_seen']=None;s['terminal']['up_received_raw']=0;s['terminal']['up_received_raw_recorded']=0;rows[-1]['rx_count']=0;sensors=sensors[:1]
        r=reconcile(s,p,'freerun',sensors=sensors,controls=rows)
        self.assertEqual(r['errors'],[])
        self.assertEqual(r['terminal']['path'],'vehicle_first')
        self.assertEqual(r['terminal']['up']['residual'],'not_evaluated')

    def test_negative_identities_and_missing_owner_evidence(self):
        for side,path in [('sim',('transmission','transmitted')),('sim',('actuator_receipt','received')),
             ('sim',('terminal','down_survived')),('vehicle',('terminal','up_received_raw')),
             ('vehicle',('last_received_tick',)),('vehicle',('terminal','up_tick_conflict'))]:
            s,p,sensors,rows=pair();target=p if side=='sim' else s
            for k in path[:-1]: target=target[k]
            target[path[-1]]+=2
            with self.subTest(path=path):
                self.assertTrue(reconcile(s,p,'freerun',sensors=sensors,controls=rows)['errors'])
        s,p,sensors,rows=pair()
        del p['receive_closed_ns']
        self.assertTrue(reconcile(s,p,'freerun',sensors=sensors,controls=rows)['errors'])

class Chronology(unittest.TestCase):
    def test_order_requires_causality_or_shared_clock(self):
        from scripts.reconcile import terminal_order
        a=dict(clock_domain='linux:boot:time',termination_before_ns=90,termination_ns=100,termination_source='local')
        b=dict(clock_domain='linux:boot:time',termination_before_ns=190,termination_ns=200,termination_source='local')
        self.assertEqual(terminal_order(a,b),'vehicle_first')
        self.assertEqual(terminal_order(b,a),'sim_first')
        a['termination_before_ns']=50;b['termination_before_ns']=80
        self.assertIsNone(terminal_order(a,b))
        a.pop('termination_before_ns');b.pop('termination_before_ns')
        self.assertIsNone(terminal_order(a,b))
        b['clock_domain']='another host'
        self.assertIsNone(terminal_order(a,b))
        b['termination_source']='vehicle'
        self.assertEqual(terminal_order(a,b),'vehicle_first')
        b['termination_source']='local';a['termination_source']='simulator'
        self.assertEqual(terminal_order(a,b),'sim_first')

    def test_symmetric_causes_and_completed_leg_diagnostics(self):
        from scripts.reconcile import terminal_causes
        def leg(**kw):
            v=dict(required=True,complete=False,tx_fail=0,opportunities=12,budget=12,
                   intentionally_lost=0,residual='zero');v.update(kw);return v
        for direction in ('up','down'):
            legs={direction:leg(tx_fail=1), 'other':leg(required=False)}
            self.assertEqual(terminal_causes(legs),['send_failure'])
            legs[direction]['complete']=True
            self.assertEqual(terminal_causes(legs),[])
        self.assertEqual(set(terminal_causes({'up':leg(tx_fail=1,opportunities=10,residual='unexplained')})),
                         {'send_failure','opportunity_shortfall','unexplained_transport_loss'})
        self.assertEqual(terminal_causes({'down':leg(intentionally_lost=12)}),['impairment_model'])

class ReviewNegatives(unittest.TestCase):
    def test_first_terminal_send_and_unaccounted_ingress(self):
        for corruption in ('terminal_send','extra_receipt'):
            s,p,sensors,rows=pair()
            if corruption=='terminal_send': rows[-1]['flags'] &= ~2
            else: rows[0]['rx_count']=9
            with self.subTest(corruption=corruption):
                self.assertFalse(reconcile(s,p,'freerun',sensors=sensors,controls=rows)['eligible'])

    def test_non_evidence_terminal_reason_is_not_compared(self):
        s,p,sensors,rows=pair()
        s['episode']['vehicle_reason']=6;rows[-1]['reason']=6;p['vehicle_reason_seen']=6
        r=reconcile(s,p,'freerun',sensors=sensors,controls=rows)
        self.assertIsNone(r['terminal_agreement'])
        self.assertFalse(r['eligible'])

    def test_unknown_order_preserves_unknown_required_legs(self):
        s,p,sensors,rows=pair()
        s['termination_source']='local';s.pop('termination_before_ns')
        r=reconcile(s,p,'freerun',sensors=sensors,controls=rows)
        self.assertIsNone(r['terminal']['path'])
        self.assertIsNone(r['terminal']['up']['required'])
        self.assertIsNone(r['terminal']['down']['required'])
        self.assertFalse(r['eligible'])
