import json
import math
from pathlib import Path
from typing import NamedTuple

from sim.types import Disturbance, Environment, TruthState


class Scenario(NamedTuple):
    id: str
    ticks: int
    initial: TruthState
    gusts: tuple[tuple[int, int, float], ...]
    loss_up: float
    loss_down: float
    loss_start_tick: int
    blackout_up: tuple[int, int] | None
    blackout_down: tuple[int, int] | None
    commands: tuple[tuple[int, str], ...]
    auto_arm: bool


_KEYS = {
    "ticks", "theta0", "omega0", "gusts", "loss_up", "loss_down",
    "loss_start_tick", "blackout_up", "blackout_down", "commands", "auto_arm",
}


def _unique_object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError(f"duplicate JSON key: {key}")
        result[key] = value
    return result


def _integer(value, name):
    if isinstance(value, bool) or not isinstance(value, int):
        raise ValueError(f"{name} must be an integer")
    return value


def _number(value, name):
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f"{name} must be a finite number")
    try:
        number = float(value)
    except OverflowError:
        raise ValueError(f"{name} must be a finite binary64 number") from None
    if not math.isfinite(number):
        raise ValueError(f"{name} must be a finite number")
    return number


def _probability(value, name):
    number = _number(value, name)
    if not 0.0 <= number <= 1.0:
        raise ValueError(f"{name} must be in [0, 1]")
    return number


def _interval(value, ticks, name):
    if not isinstance(value, list) or len(value) != 2:
        raise ValueError(f"{name} must be a two-element interval")
    start = _integer(value[0], f"{name} start")
    end = _integer(value[1], f"{name} end")
    if not 0 <= start < end <= ticks:
        raise ValueError(f"{name} must satisfy 0 <= start < end <= ticks")
    return start, end


def _check_tick(tick, ticks):
    _integer(tick, "tick")
    if not 0 <= tick < ticks:
        raise ValueError("tick must satisfy 0 <= tick < scenario.ticks")


def load(path: str | Path) -> Scenario:
    path = Path(path)
    with path.open(encoding="utf-8") as source:
        data = json.load(source, object_pairs_hook=_unique_object)
    if not isinstance(data, dict):
        raise ValueError("scenario must be a JSON object")
    if data.keys() != _KEYS:
        raise ValueError(
            f"scenario keys: missing {sorted(_KEYS - data.keys())}; "
            f"unknown {sorted(data.keys() - _KEYS)}"
        )
    ticks = _integer(data["ticks"], "ticks")
    if ticks <= 0:
        raise ValueError("ticks must be positive")
    loss_start = _integer(data["loss_start_tick"], "loss_start_tick")
    if not 0 <= loss_start <= ticks:
        raise ValueError("loss_start_tick must be in [0, ticks]")
    if not isinstance(data["auto_arm"], bool):
        raise ValueError("auto_arm must be boolean")

    if not isinstance(data["gusts"], list):
        raise ValueError("gusts must be a list")
    gusts = []
    previous_end = 0
    for index, gust in enumerate(data["gusts"]):
        if not isinstance(gust, list) or len(gust) != 3:
            raise ValueError(f"gust {index} must contain start, end and angle")
        start, end = _interval(gust[:2], ticks, f"gust {index}")
        if start < previous_end:
            raise ValueError("gusts must be ordered and nonoverlapping")
        gusts.append((start, end, _number(gust[2], f"gust {index} angle")))
        previous_end = end

    blackouts = []
    for name in ("blackout_up", "blackout_down"):
        value = data[name]
        blackouts.append(None if value is None else _interval(value, ticks, name))

    if not isinstance(data["commands"], list):
        raise ValueError("commands must be a list")
    commands = []
    previous_tick = -1
    for command in data["commands"]:
        if not isinstance(command, dict) or command.keys() != {"tick", "opcode"}:
            raise ValueError("command must contain exactly tick and opcode")
        tick = command["tick"]
        _check_tick(tick, ticks)
        if tick <= previous_tick:
            raise ValueError("command request ticks must be strictly increasing")
        opcode = command["opcode"]
        if not isinstance(opcode, str) or opcode not in ("ARM", "LAUNCH", "ABORT"):
            raise ValueError("command opcode must be ARM, LAUNCH or ABORT")
        commands.append((tick, opcode))
        previous_tick = tick

    return Scenario(
        id=path.stem,
        ticks=ticks,
        initial=TruthState(_number(data["theta0"], "theta0"), _number(data["omega0"], "omega0")),
        gusts=tuple(gusts),
        loss_up=_probability(data["loss_up"], "loss_up"),
        loss_down=_probability(data["loss_down"], "loss_down"),
        loss_start_tick=loss_start,
        blackout_up=blackouts[0],
        blackout_down=blackouts[1],
        commands=tuple(commands),
        auto_arm=data["auto_arm"],
    )


def disturbance_at(scenario: Scenario, tick: int, environment: Environment) -> Disturbance:
    _check_tick(tick, scenario.ticks)
    for start, end, alpha_g in scenario.gusts:
        if start <= tick < end:
            return Disturbance(tau_d=environment.k_a * alpha_g)
    return Disturbance(tau_d=0.0)


def command_at(scenario: Scenario, tick: int) -> str | None:
    _check_tick(tick, scenario.ticks)
    for request_tick, opcode in scenario.commands:
        if tick == request_tick:
            return opcode
    return None


def forced_drop_at(scenario: Scenario, tick: int, *, direction: str) -> bool | None:
    _check_tick(tick, scenario.ticks)
    if direction not in ("up", "down"):
        raise ValueError("direction must be up or down")
    blackout = scenario.blackout_up if direction == "up" else scenario.blackout_down
    if blackout is not None and blackout[0] <= tick < blackout[1]:
        return True
    if tick < scenario.loss_start_tick:
        return False
    return None
