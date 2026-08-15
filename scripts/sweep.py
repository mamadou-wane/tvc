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


def plan_levels(levels, cpu):
    """Cumulative prefix of levels that can run. Once any level is skipped,
    everything after it is invalid (it would differ from its predecessor by
    more than one change), so the campaign stops there."""
    runnable = []
    for label, desc, add in levels:
        if any("{cpu}" in f for f in add) and cpu is None:
            return runnable, f"{label} needs --cpu; campaign stops here"
        runnable.append((label, desc, add))
    return runnable, None


def row_ok(summary):
    """A row enters the table only if every requested mitigation was applied
    and the run completed its full requested cycle count (an interrupted or
    short run cannot enter the table)."""
    applied = summary.get("applied")
    if not isinstance(applied, dict):
        return False
    if summary.get("cycles") != summary.get("cycles_requested"):
        return False
    return all(applied.values())


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--bin", default="build/tvc_harness")
    ap.add_argument("--out", default="results")
    ap.add_argument("--cpu", type=int, default=None,
                    help="isolated core for L4+; without it the campaign stops after L3")
    ap.add_argument("--rate", type=float, default=500.0)
    ap.add_argument("--cycles", type=int, default=300_000)
    ap.add_argument("--warmup", type=int, default=5_000)
    ap.add_argument("--only", nargs="*", metavar="LABEL",
                    help="run just these levels")
    ap.add_argument("--repeat", type=int, default=1,
                    help="runs per level; table reports median and spread")
    args = ap.parse_args()

    binary = pathlib.Path(args.bin)
    if not binary.exists():
        print(f"no binary at {binary} — build first:", file=sys.stderr)
        print("  cmake -S . -B build && cmake --build build -j", file=sys.stderr)
        return 1

    outdir = pathlib.Path(args.out)
    outdir.mkdir(parents=True, exist_ok=True)

    runnable, stopped = plan_levels(LEVELS, args.cpu)
    if stopped:
        print(f"note: {stopped}", file=sys.stderr)

    flags: list[str] = []
    ran: list[str] = []
    for label, desc, add in runnable:
        flags += [f.format(cpu=args.cpu) for f in add]
        if args.only and label not in args.only:
            continue
        for r in range(1, args.repeat + 1):
            run_label = label if args.repeat == 1 else f"{label}.r{r}"
            print(f"\n{'=' * 72}\n{run_label}  {desc}\n{'=' * 72}")
            cmd = [str(binary), f"--label={run_label}", f"--out={outdir}",
                   f"--rate={args.rate}", f"--cycles={args.cycles}",
                   f"--warmup={args.warmup}", *flags]
            print("  " + " ".join(cmd) + "\n")
            rc = subprocess.run(cmd).returncode
            if rc != 0:
                print(f"\n{run_label} exited {rc}.", file=sys.stderr)
                if rc == 2:
                    print("A requested mitigation was not applied; this run "
                          "will not enter the table.", file=sys.stderr)
                if label == "L5":
                    print("If the allocation guard aborted, that is the harness "
                          "working: something in the cycle still allocates. "
                          "Re-run with --alloc-guard=count.", file=sys.stderr)
                return rc
        ran.append(label)

    # ---- comparison table ----
    import statistics
    rows, excluded = [], []
    for label in ran:
        pattern = f"{label}.summary.json" if args.repeat == 1 else f"{label}.r*.summary.json"
        summaries = [json.loads(p.read_text()) for p in sorted(outdir.glob(pattern))]
        good = [s for s in summaries if row_ok(s)]
        excluded += [s["label"] for s in summaries if not row_ok(s)]
        if not good:
            continue
        p999s = [s["jitter_us"]["p99.9"] for s in good]
        base = dict(good[0])
        base["label"] = label
        base["jitter_us"] = dict(good[0]["jitter_us"])
        base["jitter_us"]["p99.9"] = statistics.median(p999s)
        base["p999_spread"] = (min(p999s), max(p999s)) if len(p999s) > 1 else None
        rows.append(base)
    if excluded:
        print(f"\nexcluded (mitigation not applied): {', '.join(excluded)}",
              file=sys.stderr)

    if rows:
        w = shutil.get_terminal_size((100, 20)).columns
        print("\n" + "=" * min(w, 96))
        print("CAMPAIGN SUMMARY — wakeup jitter, microseconds")
        print("=" * min(w, 96))
        print(f"{'':4} {'p50':>9} {'p99':>9} {'p99.9':>16} {'p99.9 nv':>10} "
              f"{'max':>10} {'missed':>7} {'drop':>6}   config")
        base = None
        for r in rows:
            j = r["jitter_us"]
            spread = r.get("p999_spread")
            sp = f" ({spread[0]:.0f}-{spread[1]:.0f})" if spread else ""
            p999_cell = f"{j['p99.9']:.1f}{sp}"
            print(f"{r['label']:4} {j['p50']:9.1f} {j['p99']:9.1f} {p999_cell:>16} "
                  f"{j['p99.9_naive']:10.1f} {j['max']:10.1f} "
                  f"{r['missed_deadlines']:7d} {r['dropped_samples']:6d}   {r['config']}")
            if base is None:
                base = j["p99.9"]
        if base and len(rows) > 1 and rows[-1]["jitter_us"]["p99.9"] > 0:
            factor = base / rows[-1]["jitter_us"]["p99.9"]
            print(f"\np99.9 improved {factor:.1f}x from {rows[0]['label']} "
                  f"to {rows[-1]['label']}.")
        print(f"\nPlot it:  ./scripts/plot_jitter.py --results {outdir}")
    return 1 if excluded else 0


if __name__ == "__main__":
    sys.exit(main())
