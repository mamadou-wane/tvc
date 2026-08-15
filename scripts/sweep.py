#!/usr/bin/env python3
"""
sweep.py — run the determinism campaign.

Each level adds exactly one mitigation to the one before it, so the difference
between two adjacent runs is attributable to a single change. That property is
the entire value of the exercise; resist the urge to batch them.

    ./scripts/sweep.py --cpu 3
    ./scripts/sweep.py --cpu 3 --cycles 600000     # 20 min per level at 500 Hz
    ./scripts/sweep.py --only L0 L1                # re-run two levels

Levels above L2 need privileges. Without them the run still completes and the
harness reports the failure, which is a legitimate data point but not the one
you want in the writeup — check the FAIL lines before trusting a plot.
"""

import argparse
import json
import pathlib
import shutil
import subprocess
import sys

# (label, description, extra flags). Cumulative by construction.
LEVELS = [
    ("L0", "baseline: sleep_for, allocating telemetry path", []),
    ("L1", "absolute deadlines (clock_nanosleep TIMER_ABSTIME)", ["--abs-deadline"]),
    ("L2", "+ mlockall and pre-faulted stack and heap", ["--mlock"]),
    ("L3", "+ SCHED_FIFO priority 80", ["--fifo=80"]),
    ("L4", "+ pinned to an isolated core", ["--cpu={cpu}"]),
    ("L5", "+ allocation-free hot path", ["--no-naive-log", "--alloc-guard=abort"]),
]


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--bin", default="build/tvc_harness")
    ap.add_argument("--out", default="results")
    ap.add_argument("--cpu", type=int, default=None,
                    help="isolated core for L4 and above; L4/L5 are skipped without it")
    ap.add_argument("--rate", type=float, default=500.0)
    ap.add_argument("--cycles", type=int, default=300_000)
    ap.add_argument("--warmup", type=int, default=5_000)
    ap.add_argument("--only", nargs="*", metavar="LABEL",
                    help="run just these levels")
    args = ap.parse_args()

    binary = pathlib.Path(args.bin)
    if not binary.exists():
        print(f"no binary at {binary} — build first:", file=sys.stderr)
        print("  cmake -S . -B build && cmake --build build -j", file=sys.stderr)
        return 1

    outdir = pathlib.Path(args.out)
    outdir.mkdir(parents=True, exist_ok=True)

    flags: list[str] = []
    ran: list[str] = []

    for label, desc, add in LEVELS:
        if any("{cpu}" in f for f in add) and args.cpu is None:
            print(f"\n{label}  skipped — needs --cpu")
            continue
        flags += [f.format(cpu=args.cpu) for f in add]
        if args.only and label not in args.only:
            continue

        print(f"\n{'=' * 72}\n{label}  {desc}\n{'=' * 72}")
        cmd = [str(binary), f"--label={label}", f"--out={outdir}",
               f"--rate={args.rate}", f"--cycles={args.cycles}",
               f"--warmup={args.warmup}", *flags]
        print("  " + " ".join(cmd) + "\n")
        rc = subprocess.run(cmd).returncode
        if rc != 0:
            print(f"\n{label} exited {rc}.", file=sys.stderr)
            if label == "L5":
                print("If the allocation guard aborted, that is the harness working: "
                      "something in the cycle still allocates. Re-run this level with "
                      "--alloc-guard=count to see how many and how big.", file=sys.stderr)
            return rc
        ran.append(label)

    # ---- comparison table ----
    rows = []
    for label in ran:
        p = outdir / f"{label}.summary.json"
        if p.exists():
            rows.append(json.loads(p.read_text()))

    if rows:
        w = shutil.get_terminal_size((100, 20)).columns
        print("\n" + "=" * min(w, 96))
        print("CAMPAIGN SUMMARY — wakeup jitter, microseconds")
        print("=" * min(w, 96))
        print(f"{'':4} {'p50':>9} {'p99':>9} {'p99.9':>10} {'p99.9 CO':>10} "
              f"{'max':>10} {'missed':>7}   config")
        base = None
        for r in rows:
            j = r["jitter_us"]
            print(f"{r['label']:4} {j['p50']:9.1f} {j['p99']:9.1f} {j['p99.9']:10.1f} "
                  f"{j['p99.9_corrected']:10.1f} {j['max']:10.1f} "
                  f"{r['missed_deadlines']:7d}   {r['config']}")
            if base is None:
                base = j["p99.9"]
        if base and len(rows) > 1 and rows[-1]["jitter_us"]["p99.9"] > 0:
            factor = base / rows[-1]["jitter_us"]["p99.9"]
            print(f"\np99.9 improved {factor:.1f}x from {rows[0]['label']} "
                  f"to {rows[-1]['label']}.")
        print(f"\nPlot it:  ./scripts/plot_jitter.py --results {outdir}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
