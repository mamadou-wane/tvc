import copy
import unittest
from scripts import latency


def fixture(warmup=0):
    counts=dict.fromkeys(('received','consumed','discarded_old','discarded_superseded','discarded_nonfinite',
        'discarded_skew_excess','discarded_duplicate','discarded_tick_conflict','discarded_invalid','future_expired',
        'bad_sync','bad_version','bad_type','bad_length','bad_crc','fresh','coast','neutral','lost',
        'actuator_transmitted','actuator_tx_fail','served'),0)
    a=dict(tick=0,sensor_tick=0,staleness=0,flags=3,state=2,reason=0,drops=0,
        deadline_ns=1000,woke_ns=1100,rx_ns=1300,tx_ns=1700,done_ns=2000,sensor_send_ns=500,
        rx_count=1,discarded_old=0,discarded_superseded=0,discarded_other=0)
    b=dict(a,tick=1,staleness=1,flags=10,state=3,reason=7,rx_count=0,
        deadline_ns=2001000,woke_ns=2001100,rx_ns=2001300,tx_ns=2001700,done_ns=2002000)
    full=dict(counts,received=1,consumed=1,fresh=1,coast=1,actuator_transmitted=1,served=1)
    recorded=full.copy() if warmup==0 else dict(counts,coast=1) if warmup==1 else counts.copy()
    s=dict(mode='freerun',total_cycles=2,cycles=max(0,2-warmup),warmup=warmup,origin_ns=1000,period_us=2000,
        episode=dict(tick_base=0,reason_tick=1,vehicle_reason=7,sim_reason_seen=1),
        telemetry=dict(records=2,dropped=0),events=dict(episode_transitions=2,record_attempts=2,records_pushed=2),
        terminal=dict(cycle=1,first_tx_ok=True,up_received_raw=0,up_received_raw_recorded=0,down_attempts=12,down_transmitted=12,down_tx_fail=0),
        actuator=dict(generated=1,transmitted=1,tx_fail=0),link=full,link_recorded=recorded,
        future_parked_at_end=0,future_parked_at_warmup=0 if warmup<2 else None,
        dropped_samples=0,jitter_us=dict(count=max(0,2-warmup)),exec_us=dict(count=max(0,2-warmup)),
        latency_us=dict(count=int(warmup==0),sum_ns=1200 if warmup==0 else 0,dropped=0),
        discard_age_us=dict(count=0,sum_ns=0,dropped=0),
        uplink_wait_us=dict(count=int(warmup==0),sum_ns=800 if warmup==0 else 0,dropped=0),
        vehicle_compute_us=dict(count=int(warmup==0),sum_ns=400 if warmup==0 else 0,dropped=0))
    return s,[a,b]


class LatencyIdentity(unittest.TestCase):
    def test_literal_endpoints_and_windows(self):
        for warmup in (0,1,2,10):
            s,rows=fixture(warmup)
            result=latency.validate(s,rows)
            self.assertEqual(result['errors'],[])
            self.assertEqual(result['identities']['T4'],True if warmup<2 else None)
            self.assertEqual(result['served_ns'],[1200] if warmup==0 else [])
            self.assertEqual(result['observation_coverage'],.5 if warmup==0 else 0 if warmup==1 else None)

    def test_fresh_failure_in_both_network_partitions(self):
        for terminal in (False,True):
            s,rows=fixture()
            if terminal:
                rows=rows[:1]; rows[0].update(state=3,reason=2)
                s.update(total_cycles=1,cycles=1)
                s['jitter_us']['count']=1;s['exec_us']['count']=1
                s['episode'].update(reason_tick=0,vehicle_reason=2,sim_reason_seen=None)
                s['telemetry']['records']=1
                s['events']=dict(episode_transitions=1,record_attempts=1,records_pushed=1)
                s['actuator'].update(generated=0,transmitted=0)
                s['terminal'].update(down_transmitted=11,down_tx_fail=1,first_tx_ok=False)
                for c in (s['link'],s['link_recorded']): c.update(coast=0,actuator_transmitted=0)
            else:
                s['actuator'].update(transmitted=0,tx_fail=1)
                for c in (s['link'],s['link_recorded']): c.update(actuator_transmitted=0,actuator_tx_fail=1)
            rows[0]['flags'] &= ~2
            for c in (s['link'],s['link_recorded']): c['served']=0
            for key in ('latency_us','uplink_wait_us','vehicle_compute_us'): s[key].update(count=0,sum_ns=0)
            self.assertEqual(latency.validate(s,rows)['errors'],[])

    def test_each_tampered_population_is_rejected(self):
        paths=[('jitter_us','count'),('exec_us','count'),('cycles',),('total_cycles',),('link','consumed'),('link','received'),('link','fresh'),
            ('link','actuator_transmitted'),('link_recorded','discarded_invalid'),
            ('link_recorded','discarded_duplicate'),('link_recorded','discarded_tick_conflict'),
            ('future_parked_at_end',),('latency_us','count'),('latency_us','sum_ns'),
            ('discard_age_us','count'),('telemetry','dropped'),('telemetry','records'),
            ('terminal','down_attempts'),('uplink_wait_us','sum_ns'),('dropped_samples',)]
        for path in paths:
            s,rows=fixture();target=s
            for k in path[:-1]: target=target[k]
            target[path[-1]]+=1
            with self.subTest(path=path): self.assertTrue(latency.validate(s,rows)['errors'])
        s,rows=fixture(10);s['future_parked_at_warmup']=0
        self.assertTrue(latency.validate(s,rows)['errors'])
        for bad in ({},None,{'mode':'lockstep'}): self.assertTrue(latency.validate(bad,[])['errors'])

    def test_balanced_ladder_and_false_staleness_are_rejected(self):
        for kind in ('ladder','age','held_stamp'):
            s,rows=fixture()
            if kind=='ladder':
                s['link']['fresh']=0;s['link']['coast']=2
            elif kind=='age':rows[-1]['staleness']=2
            else:rows[-1]['sensor_send_ns']=501
            with self.subTest(kind=kind):self.assertFalse(latency.validate(s,rows)['valid'])

class RoundTripEvidence(unittest.TestCase):
    def test_literal_formula_and_eligibility_rejection(self):
        sample=dict(received_ns=4500,sensor_send_ns=1000,status=2)
        report=dict(roundtrip_samples=[sample],latency_roundtrip_ns=[3500],
                    latency_roundtrip_us=dict(count=1,sum_ns=3500,p50=3.5,**{'p99.9':3.5},max=3.5),
                    actuator_receipt=dict(received=1))
        self.assertEqual(latency.validate_roundtrip(report),[])
        for key,value in (('received_ns',4400),('sensor_send_ns',0),('status',259),('status',65538)):
            bad=copy.deepcopy(report);bad['roundtrip_samples'][0][key]=value
            with self.subTest(key=key,value=value):self.assertTrue(latency.validate_roundtrip(bad))
        bad=copy.deepcopy(report);bad['latency_roundtrip_us']['count']=2
        self.assertTrue(latency.validate_roundtrip(bad))
