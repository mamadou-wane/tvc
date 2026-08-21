#!/usr/bin/env python3
"""
sweep.py: run the determinism campaign.

Each level adds exactly one mitigation to the one before it, so the difference
between two adjacent runs is attributable to a single change. That property is
the entire value of the exercise; resist the urge to batch them.

    ./scripts/sweep.py --cpu 3
    ./scripts/sweep.py --cpu 3 --cycles 600000     # 20 min per level at 500 Hz
    ./scripts/sweep.py --only L0 L1                # re-run two levels

Levels above L2 need privileges. Without them the harness exits nonzero, the
sweep stops at that level, and any summary whose requested config was not
applied is excluded from the table automatically.
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
    ("L6", "+ telemetry ring + drain thread", ["--telemetry"]),
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


def row_problem(summary):
    """None if the row is good enough for the table, else a short reason it
    was excluded: either the requested mitigation was not applied, or the
    run is short or interrupted (or predates the cycles_requested field)."""
    applied = summary.get("applied")
    if not isinstance(applied, dict) or not all(applied.values()):
        return "config was not applied"
    if summary.get("cycles") != summary.get("cycles_requested"):
        return "incomplete run or pre-integrity summary format"
    return None


def row_ok(summary):
    """A row enters the table only if every requested mitigation was applied
    and the run completed its full requested cycle count (an interrupted or
    short run cannot enter the table)."""
    return row_problem(summary) is None


def aggregate_row(label, good):
    """One table row from the good repeats of a level: percentiles take
    the median across repeats, counters sum, max is the worst repeat."""
    import statistics
    row = dict(good[0])
    row["label"] = label
    row["jitter_us"] = dict(good[0]["jitter_us"])
    percentile_keys = ["p50", "p99", "p99.9", "p99.9_naive", "p99.99"]
    for key in percentile_keys:
        row["jitter_us"][key] = statistics.median(
            summary["jitter_us"][key] for summary in good)
    row["jitter_us"]["max"] = max(
        summary["jitter_us"]["max"] for summary in good)
    row["dropped_samples"] = sum(summary["dropped_samples"] for summary in good)
    row["missed_deadlines"] = sum(summary["missed_deadlines"] for summary in good)
    p999s = [summary["jitter_us"]["p99.9"] for summary in good]
    p9999s = [summary["jitter_us"]["p99.99"] for summary in good]
    row["p999_spread"] = (min(p999s), max(p999s)) if len(good) > 1 else None
    row["p9999_spread"] = (min(p9999s), max(p9999s)) if len(good) > 1 else None
    return row


def binary_is_stale(bin_path, source_paths):
    """True when the binary predates any source it was built from."""
    import os
    try:
        bin_mtime = os.path.getmtime(bin_path)
    except OSError:
        return False
    newest = 0.0
    for p in source_paths:
        try:
            newest = max(newest, os.path.getmtime(p))
        except OSError:
            continue
    return newest > bin_mtime


def parse_cpu_list(text):
    """sysfs CPU-list syntax ('6-7', '0,2-5,8', '') to a set of ints;
    blank input is the empty set."""
    cpus = set()
    for part in text.split(","):
        part = part.strip()
        if not part:
            continue
        if "-" in part:
            lo, hi = (int(value) for value in part.split("-", 1))
            cpus.update(range(lo, hi + 1))
        else:
            cpus.add(int(part))
    return cpus


def read_online_isolated(sysfs="/sys/devices/system/cpu"):
    """(online, isolated) CPU sets. Missing or unreadable files fall
    back to range(os.cpu_count()) for online and the empty set for
    isolated, so containers and non-Linux sandboxes keep working."""
    import os
    try:
        with open(os.path.join(sysfs, "online")) as f:
            online = parse_cpu_list(f.read())
    except OSError:
        online = set(range(os.cpu_count() or 1))
    try:
        with open(os.path.join(sysfs, "isolated")) as f:
            isolated = parse_cpu_list(f.read())
    except OSError:
        isolated = set()
    return online, isolated


def affinity_problem(affinity, online, isolated):
    """None when the inherited mask is unrestricted, else a short
    reason string, in the style of row_problem."""
    missing = online - affinity
    if not missing:
        return None
    reason = (f"inherited CPU affinity {sorted(affinity)} is missing online CPUs "
              f"{sorted(missing)} (launched under taskset or in a cpuset?)")
    if not (affinity - isolated):
        reason += ("; every allowed CPU is isolated, so unpinned levels and the "
                   "telemetry drain thread would run on the measurement core")
    return reason


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
    ap.add_argument("--allow-stale", action="store_true",
                    help="run even if the binary predates its sources")
    ap.add_argument("--allow-restricted-affinity", action="store_true",
                    help="run even if the inherited CPU mask is restricted "
                         "(taskset, cpuset)")
    args = ap.parse_args()

    binary = pathlib.Path(args.bin)
    if not binary.exists():
        print(f"no binary at {binary}, build first:", file=sys.stderr)
        print("  cmake -S . -B build && cmake --build build -j", file=sys.stderr)
        return 1

    repo_root = pathlib.Path(__file__).resolve().parents[1]
    sources = sorted(
        list(repo_root.glob("src/*.cpp"))
        + list(repo_root.glob("src/*.hpp"))
        + [repo_root / "CMakeLists.txt"]
    )
    if binary_is_stale(binary, sources):
        if args.allow_stale:
            print(f"warning: {binary} is older than the sources; running anyway "
                  "(--allow-stale)", file=sys.stderr)
        else:
            print("binary is older than the sources; rebuild first: "
                  "cmake --build build -j", file=sys.stderr)
            return 1

    import os
    if hasattr(os, "sched_getaffinity"):
        affinity = set(os.sched_getaffinity(0))
        online, isolated = read_online_isolated()
        problem = affinity_problem(affinity, online, isolated)
        if problem:
            if args.allow_restricted_affinity:
                print(f"warning: {problem}; running anyway "
                      "(--allow-restricted-affinity)", file=sys.stderr)
            else:
                print(problem, file=sys.stderr)
                print("re-launch with a full CPU mask or pass "
                      "--allow-restricted-affinity", file=sys.stderr)
                return 1
        if args.cpu is not None and isolated and args.cpu not in isolated:
            print(f"note: --cpu {args.cpu} is not in the isolated set "
                  f"{sorted(isolated)}", file=sys.stderr)

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
    rows, excluded = [], []
    for label in ran:
        pattern = f"{label}.summary.json" if args.repeat == 1 else f"{label}.r*.summary.json"
        summaries = [json.loads(p.read_text()) for p in sorted(outdir.glob(pattern))]
        good = [s for s in summaries if row_ok(s)]
        excluded += [(s["label"], row_problem(s)) for s in summaries if not row_ok(s)]
        if not good:
            continue
        rows.append(aggregate_row(label, good))
    if excluded:
        print(file=sys.stderr)
        for label, reason in excluded:
            print(f"excluded {label}: {reason}", file=sys.stderr)

    if rows:
        w = shutil.get_terminal_size((100, 20)).columns
        print("\n" + "=" * min(w, 96))
        print("CAMPAIGN SUMMARY: wakeup jitter, microseconds")
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
        spreads = [(r["label"], r["jitter_us"]["p99.99"], r["p9999_spread"])
                   for r in rows if r.get("p9999_spread")]
        if spreads:
            print("\np99.99 median (min-max) across repeats:")
            for label, med, (lo, hi) in spreads:
                print(f"  {label:4} {med:10.1f} ({lo:.1f}-{hi:.1f})")
        print(f"\nPlot it:  ./scripts/plot_jitter.py --results {outdir}")
    return 1 if excluded else 0


if __name__ == "__main__":
    sys.exit(main())
