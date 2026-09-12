import unittest
from sim import episode, rng, scenario
from sim.freerun import Model
from sim.types import TruthState
from ground import wire


def spec(**kw):
    args = dict(id='unit', ticks=20, initial=TruthState(0,0), gusts=(),
        loss_up=0.0, loss_down=0.0, loss_start_tick=0, blackout_up=None,
        blackout_down=None, commands=(), auto_arm=True)
    args.update(kw)
    return scenario.Scenario(**args)


def reply(tick, terminal=False):
    return wire.encode_frame(5,tick,wire.encode_payload(5,dict(tick=tick,veh_tick=tick,
        t_sensor_send_ns=1,t_veh_send_ns=2,delta=0.12,
        status=259 if terminal else 2,staleness=0)))


class FreeModel(unittest.TestCase):
    def test_runtime_minimum_leaves_shared_scenario_contract_alone(self):
        from sim.freerun import execute
        from unittest.mock import patch
        for ticks in (0,1):
            with self.subTest(ticks=ticks):
                with self.assertRaisesRegex(ValueError,'ticks'):
                    Model(spec(ticks=ticks),1,0)
                with patch('sim.freerun.socket.socket') as socket_factory:
                    with self.assertRaisesRegex(ValueError,'ticks'):
                        execute(spec(ticks=ticks),seed=1,delay_ticks=0,peer=('127.0.0.1',9),
                                bind_port=0,prefix='/unused/one')
                    socket_factory.assert_not_called()

    def test_overrides_bind_to_frame_up_and_body_down(self):
        model = Model(spec(blackout_up=(10,12),blackout_down=(10,12)),1,0)
        self.assertEqual(model.loss('up',11),(False,True))
        self.assertIsNone(model.receive([reply(1),reply(19)],10))
        self.assertEqual(model.draws,[1,2])
        self.assertEqual(model.down['last_received_tick'],19)
        self.assertEqual(model.down['intentionally_lost'],2)
        self.assertEqual(model.receive([reply(1)],12),0.12)
        self.assertEqual(model.draws,[1,3])

    def test_terminal_copies_ignore_blackout_and_pre_loss_keep(self):
        model = Model(spec(blackout_up=(0,20),blackout_down=(0,20)),1,0)
        self.assertEqual(model.loss('up',10,terminal=True),(False,False))
        model.receive([reply(10,True)],10)
        self.assertEqual(model.term['down_survived'],1)
        self.assertEqual(model.vehicle_seen,1)
        lossy = Model(spec(loss_up=1,loss_down=1,loss_start_tick=20),1,0)
        self.assertEqual(lossy.loss('up',0,prologue=True),(True,False))
        self.assertEqual(lossy.loss('up',1),(True,False))
        self.assertEqual(lossy.loss('up',1,terminal=True),(True,True))
        lossy.receive([reply(10,True)],10)
        self.assertEqual(lossy.term['down_intentionally_lost'],1)
        self.assertIsNone(lossy.vehicle_seen)

    def test_one_draw_per_accepted_packet_in_receive_order(self):
        model = Model(spec(loss_down=0.3),12,1)
        reference = rng.SplitMix64(rng.stream_state(12,'link.loss.down'))
        drops = [reference.next_double() < .3 for _ in range(3)]
        model.receive([reply(3), b'bad', reply(1), reply(2)],0)
        self.assertEqual(model.draws[1],3)
        self.assertEqual(model.streams[1].state,reference.state)
        self.assertEqual(model.down['intentionally_lost'],sum(drops))
        self.assertEqual(model.down['malformed'],1)

    def test_delay_and_terminal_stop_do_not_advance_again(self):
        for delay, expected in ((0,0.12),(1,0.0)):
            m = Model(spec(),1,delay)
            m.advance(0,0.12)
            self.assertEqual(m.act.applied,expected)
            m.receive([reply(1,True)],1)
            self.assertEqual(m.reason,episode.SimReason.SIM_VEHICLE_TERMINAL)
            with self.assertRaisesRegex(ValueError,'after termination'): m.advance(1,None)
            self.assertEqual(m.events['plant_steps'],1)
            self.assertEqual(m.events['fifo_advances'],1)

    def test_dropped_payload_cannot_supply_a_command(self):
        value=dict(tick=0,veh_tick=0,t_sensor_send_ns=1,t_veh_send_ns=2,
                   delta=float('nan'),status=2,staleness=0)
        packet=wire.encode_frame(5,0,wire.encode_payload(5,value))
        dropped=Model(spec(loss_down=1),1,0)
        self.assertIsNone(dropped.receive([packet],0))
        self.assertEqual(dropped.down['intentionally_lost'],1)
        self.assertEqual(dropped.draws[1],1)
        with self.assertRaisesRegex(ValueError,'nonfinite'):
            Model(spec(),1,0).receive([packet],0)
        value['status']=259
        terminal=Model(spec(),1,0)
        terminal.receive([wire.encode_frame(5,0,wire.encode_payload(5,value))],0)
        self.assertEqual(terminal.vehicle_seen,1)

class RoundTrip(unittest.TestCase):
    def test_literal_simulator_clock_endpoint_and_exclusions(self):
        from sim.freerun import roundtrip_ns
        def packet(status=2,echo=1000,delta=0):
            return wire.encode_frame(5,0,wire.encode_payload(5,dict(tick=0,veh_tick=0,
                t_sensor_send_ns=echo,t_veh_send_ns=999999999,delta=delta,status=status,staleness=0)))
        self.assertEqual(roundtrip_ns(packet(),4500),3500)
        for frame in (b'bad',packet(status=259),packet(status=2+(1<<16)),packet(echo=0)):
            self.assertIsNone(roundtrip_ns(frame,4500))
        m=Model(spec(loss_down=1),1,0)
        frame=packet()
        self.assertEqual(roundtrip_ns(frame,4500),3500)
        m.receive([frame],0)
        self.assertEqual(m.down['intentionally_lost'],1)

    def test_terminal_send_lifetime_encloses_delayed_syscall(self):
        import socket
        import tempfile
        import time
        import json
        from pathlib import Path
        from unittest.mock import patch
        from sim.freerun import execute
        original=socket.socket; completed=[]
        class Delayed:
            def __init__(self,*args,**kwargs):self.inner=original(*args,**kwargs)
            def __getattr__(self,name):return getattr(self.inner,name)
            def send(self,data,flags):
                _,_,payload=wire.decode_datagram(data,{4})
                terminal=bool(wire.decode_payload(4,payload)['flags']&2)
                if terminal:time.sleep(.02)
                result=self.inner.send(data,flags)
                if terminal:completed.append(time.monotonic_ns())
                return result
        with original(socket.AF_INET,socket.SOCK_DGRAM) as peer,tempfile.TemporaryDirectory() as directory:
            peer.bind(('127.0.0.1',0));prefix=Path(directory)/'run'
            with patch('sim.freerun.socket.socket',Delayed):
                self.assertEqual(execute(spec(ticks=2),seed=1,delay_ticks=0,peer=peer.getsockname(),
                                         bind_port=0,prefix=prefix,terminal_copies=1),3)
            report=json.loads(Path(str(prefix)+'.sim-report.json').read_text())
            self.assertEqual(len(completed),1)
            self.assertGreaterEqual(report['terminal_send_last_ns'],completed[0])
