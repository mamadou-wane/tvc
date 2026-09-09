"""Tick-indexed reference orchestration over the frozen Python components."""

import math

from sim import actuator, control_ref, environment, episode, link, plant, rng, scenario, sensor
from sim.trace import Row, StreamResult, Trace
from sim.types import Observation


class _Delay:
    def __init__(self, depth: int):
        self.values = [None] * depth

    def push_pop(self, arriving: float | None) -> float | None:
        self.values.append(arriving)
        return self.values.pop(0)


def run_headless(spec: scenario.Scenario, *, seed: int, delay_ticks: int,
                 controller=control_ref) -> Trace:
    """Run a resolved scenario without IO; only the frozen reference is supported."""
    if type(seed) is not int or not 0 <= seed < 0x10000000000000000:
        raise ValueError('seed must be a u64 integer')
    if type(delay_ticks) is not int or delay_ticks not in (0, 1):
        raise ValueError('delay_ticks must be 0 or 1')
    if controller is not control_ref:
        raise ValueError('episode owns the frozen reference controller')
    if type(spec.ticks) is not int or spec.ticks <= 0:
        raise ValueError('scenario must have a positive tick count')

    names = ('link.loss.up', 'link.loss.down')
    starts = tuple(rng.stream_state(seed, name) for name in names)
    streams = tuple(rng.SplitMix64(start) for start in starts)
    delay = _Delay(delay_ticks)
    truth = spec.initial
    act = actuator.initial()
    state = episode.initial(auto_arm=spec.auto_arm)
    held = None
    pending_reason = None
    command_seq = 0
    rows = []
    env = environment.fixed()
    for tick in range(spec.ticks):
        raw_up = link.draw_drop(streams[0], spec.loss_up)
        raw_down = link.draw_drop(streams[1], spec.loss_down)
        override_up = scenario.forced_drop_at(spec, tick, direction='up')
        override_down = scenario.forced_drop_at(spec, tick, direction='down')
        up_drop = raw_up if override_up is None else override_up
        down_drop = raw_down if override_down is None else override_down
        disturbance = scenario.disturbance_at(spec, tick, env)
        observation = sensor.observe(tick, truth)
        if up_drop:
            observation = Observation(tick, 0.0, 0.0, False)
        fresh = (observation.valid and math.isfinite(observation.theta)
                 and math.isfinite(observation.omega))
        if fresh:
            held = observation
        age = min(tick - held.tick if held is not None else tick + 1, 0xffffffff)
        opcode = scenario.command_at(spec, tick)
        command = None
        if opcode is not None:
            command_seq = (command_seq + 1) & 0xffffffff
            command = episode.Command(command_seq, episode.Opcode[opcode], tick + 50)
        sim_reason = pending_reason
        if sim_reason is None and tick == spec.ticks - 1:
            sim_reason = episode.SimReason.SIM_HORIZON
        output = episode.step(state, episode.EpisodeInput(
            tick, held, fresh, age, command, False, sim_reason, None))
        state = output.state
        arriving = delay.push_pop(None if down_drop else output.requested_delta)
        act = actuator.step(act, arriving)
        rows.append(Row(tick, truth, observation, held, fresh, age, command,
                        output, arriving, act, up_drop, down_drop))
        if sim_reason is not None:
            break
        if state.terminal is not None:
            sim_reason = episode.SimReason.SIM_VEHICLE_TERMINAL
            break
        truth = plant.step(truth, act, env, disturbance, control_ref.DT)
        if not math.isfinite(truth.theta) or not math.isfinite(truth.omega):
            pending_reason = episode.SimReason.SIM_LOC_NONFINITE
        elif abs(truth.theta) > 0.30:
            pending_reason = episode.SimReason.SIM_LOC_ANGLE

    results = tuple(StreamResult(name, start, stream.state, len(rows))
                    for name, start, stream in zip(names, starts, streams))
    return Trace(spec.ticks, seed, delay_ticks, tuple(rows), results, sim_reason)


def main(argv=None):
    import argparse
    import json
    from pathlib import Path
    from sim.trace import evaluate

    parser = argparse.ArgumentParser(description='Run one headless deterministic scenario')
    parser.add_argument('--scenario', required=True)
    parser.add_argument('--seed', type=int, default=1)
    parser.add_argument('--delay-ticks', type=int, choices=(0, 1), default=0)
    parser.add_argument('--loss', type=float)
    parser.add_argument('--check', action='store_true')
    args = parser.parse_args(argv)
    path = Path(args.scenario)
    if not path.suffix:
        path = Path(__file__).with_name('scenarios') / (args.scenario + '.json')
    try:
        spec = scenario.load(path)
        if args.loss is not None:
            spec = spec._replace(loss_up=args.loss, loss_down=args.loss)
        trace = run_headless(spec, seed=args.seed, delay_ticks=args.delay_ticks)
    except (OSError, ValueError) as error:
        parser.error(str(error))
    clauses = evaluate(trace)
    print(json.dumps({'ticks': len(trace.rows),
                      'reason': trace.rows[-1].episode.state.terminal.reason.name,
                      'clauses': clauses._asdict()}, sort_keys=True))
    return 1 if args.check and not clauses.passed else 0


if __name__ == '__main__':
    raise SystemExit(main())
