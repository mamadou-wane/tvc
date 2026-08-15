#!/usr/bin/env python3
"""
bench_gate.py: the jitter regression gate.

Runs only on the measurement machine. Compares a fresh campaign directory
against the committed baselines and fails when the gated level's p99.9
median regresses beyond tolerance. Hosted CI never produces or judges a
timing number; that boundary is deliberate (see docs/results.md).

    python3 scripts/bench_gate.py --results results/2026-09-01-campaign
"""

import argparse
import glob
import json
import pathlib
import statistics
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
import sweep  # row_problem gates rows here exactly as in the campaign table


def verified_p999s(directory, level):
    """p99.9 values of the level's runs that pass the integrity gate."""
    values = []
    pattern = str(pathlib.Path(directory) / f"{level}*.summary.json")
    for path in sorted(glob.glob(pattern)):
        with open(path) as f:
            s = json.load(f)
        if sweep.row_problem(s) is None:
            values.append(s["jitter_us"]["p99.9"])
    return values


def gate(new_values, base_values, tolerance_pct):
    """(ok, message). Fails when the new median exceeds the baseline median
    plus tolerance, or when either side has no verified runs."""
    if not new_values:
        return False, "no verified runs in the results directory"
    if not base_values:
        return False, "no verified runs in the baseline directory"
    new_med = statistics.median(new_values)
    base_med = statistics.median(base_values)
    limit = base_med * (1 + tolerance_pct / 100.0)
    ok = new_med <= limit
    verdict = "pass" if ok else "REGRESSION"
    return ok, (f"{verdict}: new p99.9 median {new_med:.1f} us vs baseline "
                f"{base_med:.1f} us (limit {limit:.1f} at +{tolerance_pct:g}%)")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--results", required=True, help="fresh campaign directory")
    ap.add_argument("--baseline", default="baselines/2026-08-15-campaign-2")
    ap.add_argument("--level", default="L5")
    ap.add_argument("--tolerance-pct", type=float, default=25.0)
    args = ap.parse_args()

    ok, msg = gate(verified_p999s(args.results, args.level),
                   verified_p999s(args.baseline, args.level),
                   args.tolerance_pct)
    print(f"bench gate [{args.level}] {msg}")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
