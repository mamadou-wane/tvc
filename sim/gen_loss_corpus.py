import argparse
import json
from pathlib import Path

from sim import link, rng, scenario


_P30 = "0x1.3333333333333p-2"
_CASES = (
    ("S2-gust", 1, _P30, _P30, 2000),
    ("S2-gust", 1, _P30, _P30, 3000),
    ("S2-gust", 1, _P30, _P30, 5000),
    ("S2-gust", 1, _P30, _P30, 10000),
    ("S1-hold", 1, "0x0.0p+0", "0x1.0000000000000p+0", 32),
    ("S1-hold", 1, "0x1.7906ac21d0e58p-2", "0x1.de2c6aa70a6f2p-2", 32),
    ("S6-blackout", 1, _P30, _P30, 2000),
    ("demo-loss30", 20260902, _P30, _P30, 3000),
)


def main() -> None:
    parser = argparse.ArgumentParser(description="Generate the fixed logical loss corpus.")
    parser.add_argument("output_directory", type=Path)
    output = parser.parse_args().output_directory
    if not output.is_dir():
        parser.error("output_directory must be an existing directory")

    scenario_directory = Path(__file__).resolve().parent / "scenarios"
    cases = []
    for name, seed, p_up, p_down, ticks in _CASES:
        spec = scenario.load(scenario_directory / (name + ".json"))
        up = rng.SplitMix64(rng.stream_state(seed, "link.loss.up"))
        down = rng.SplitMix64(rng.stream_state(seed, "link.loss.down"))
        streams = (("up", up, float.fromhex(p_up)), ("down", down, float.fromhex(p_down)))
        counts = {"up": 0, "down": 0}
        prefixes = {"up": "", "down": ""}
        for tick in range(ticks):
            for direction, stream, probability in streams:
                raw = link.draw_drop(stream, probability)
                forced = scenario.forced_drop_at(spec, tick, direction=direction)
                effective = raw if forced is None else forced
                counts[direction] += int(effective)
                if tick < 32:
                    prefixes[direction] += "1" if raw else "0"
        cases.append({
            "scenario": name, "seed": seed, "p_up": p_up, "p_down": p_down, "ticks": ticks,
            "intentionally_lost_up": counts["up"],
            "intentionally_lost_down": counts["down"],
            "draw_drop_prefix_up": prefixes["up"],
            "draw_drop_prefix_down": prefixes["down"],
            "final_state_up": f"0x{up.state:016x}",
            "final_state_down": f"0x{down.state:016x}",
        })

    document = {"cases": cases}
    text = json.dumps(document, indent=2, sort_keys=True, ensure_ascii=True, allow_nan=False) + "\n"
    (output / "loss_counts.json").write_bytes(text.encode("utf-8"))


if __name__ == "__main__":
    main()
