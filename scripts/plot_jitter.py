#!/usr/bin/env python3
"""
plot_jitter.py — draw the figure the project is judged on.

Produces a complementary CDF: x is wakeup jitter, y is the fraction of cycles
worse than that value, on a log scale so the tail occupies real estate
proportional to how much it matters. A linear-y CDF squashes everything
interesting into the top two percent of the plot, which is why latency work
uses this form.

    ./scripts/plot_jitter.py --results results
    ./scripts/plot_jitter.py --results results --naive
    ./scripts/plot_jitter.py --results results --out docs/jitter.svg

--naive plots what a self-referencing measurement (previous wakeup + period)
would have reported. The primary series is coordinated-omission-free by
construction; the naive series exists to demonstrate what CO hides.
"""

import argparse
import csv
import json
import pathlib
import sys

try:
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    from matplotlib.ticker import LogLocator
except ImportError:
    sys.exit("needs matplotlib:  pip install matplotlib")

INK, GRID, FAINT = "#14212A", "#CDD8DD", "#8B9DA7"
# Ordered worst to best, so the legend reads in campaign order.
SERIES_COLORS = ["#AF2E22", "#C4632A", "#B8912B", "#5F8A3A", "#2A7A57", "#1A4FA0"]


def read_cdf(path):
    """HdrHistogram CSV -> (values, fraction-worse). Drops the 1.0 row, whose
    reciprocal is infinite."""
    xs, ys = [], []
    with open(path, newline="") as f:
        for row in csv.DictReader(f):
            try:
                v, p = float(row["Value"]), float(row["Percentile"])
            except (KeyError, ValueError):
                continue
            if p >= 1.0:
                continue
            xs.append(v)
            ys.append(1.0 - p)
    return xs, ys


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--results", default="results")
    ap.add_argument("--out", default=None, help="default: <results>/jitter.svg")
    ap.add_argument("--naive", action="store_true",
                    help="plot the self-referenced naive-measurement series (CO demo)")
    ap.add_argument("--target-us", type=float, default=100.0,
                    help="p99.9 deadline target marker (default: 100)")
    args = ap.parse_args()

    rdir = pathlib.Path(args.results)
    series = "jitter_naive" if args.naive else "jitter"
    files = sorted(rdir.glob(f"*.{series}.csv"))
    if not files:
        return print(f"no *.{series}.csv in {rdir} — run scripts/sweep.py first") or 1

    fig, ax = plt.subplots(figsize=(10, 5.6))
    fig.patch.set_facecolor("white")

    lo, hi = 1e9, 0.0
    for i, path in enumerate(files):
        label = path.name.split(".")[0]
        xs, ys = read_cdf(path)
        if not xs:
            continue
        lo, hi = min(lo, min(xs)), max(hi, max(xs))

        meta = rdir / f"{label}.summary.json"
        if meta.exists():
            d = json.loads(meta.read_text())
            p999 = d["jitter_us"]["p99.9_naive" if args.naive else "p99.9"]
            legend = f"{label}  ·  p99.9 {p999:,.0f} µs  ·  {d['config']}"
        else:
            legend = label

        ax.plot(xs, ys, lw=1.9, color=SERIES_COLORS[i % len(SERIES_COLORS)],
                label=legend, solid_joinstyle="round")

    ax.axvline(args.target_us, color="#2A7A57", ls="--", lw=1.1, zorder=1)
    ax.text(args.target_us, 1.25, f"  p99.9 target {args.target_us:.0f} µs",
            color="#2A7A57", fontsize=8.5, va="top", family="monospace")

    # Percentile guide lines, labelled inside the right edge so they never
    # collide with the y-axis ticks.
    blend = matplotlib.transforms.blended_transform_factory(ax.transAxes, ax.transData)
    for frac, name in ((1e-2, "p99"), (1e-3, "p99.9"), (1e-4, "p99.99")):
        ax.axhline(frac, color=GRID, lw=0.9, zorder=0)
        ax.text(0.995, frac, name, color=FAINT, fontsize=8.5, va="bottom",
                ha="right", family="monospace", transform=blend, zorder=3)

    ax.set_xscale("log")
    ax.set_yscale("log")
    ax.set_xlim(lo * 0.8, hi * 1.4)
    ax.set_ylim(5e-6, 1.4)
    ax.xaxis.set_major_locator(LogLocator(base=10))

    ax.set_xlabel("wakeup jitter, microseconds", fontsize=10, color=INK)
    ax.set_ylabel("fraction of cycles worse", fontsize=10, color=INK)
    ax.set_title(
        "Control-loop wakeup jitter"
        + ("  ·  naive self-referenced measurement" if args.naive else ""),
        fontsize=12.5, color=INK, loc="left", pad=14)

    ax.grid(True, which="major", color=GRID, lw=0.7)
    ax.grid(True, which="minor", color=GRID, lw=0.35, alpha=0.6)
    for side in ("top", "right"):
        ax.spines[side].set_visible(False)
    for side in ("left", "bottom"):
        ax.spines[side].set_color(FAINT)
    ax.tick_params(colors=FAINT, labelsize=9)

    leg = ax.legend(loc="lower left", fontsize=8.5, frameon=True, framealpha=0.95,
                    edgecolor=GRID, prop={"family": "monospace", "size": 8.5})
    leg.get_frame().set_linewidth(0.8)

    out = pathlib.Path(args.out) if args.out else rdir / (
        "jitter_naive.svg" if args.naive else "jitter.svg")
    out.parent.mkdir(parents=True, exist_ok=True)
    fig.tight_layout()
    fig.savefig(out, bbox_inches="tight")
    fig.savefig(out.with_suffix(".png"), dpi=170, bbox_inches="tight")
    print(f"wrote {out} and {out.with_suffix('.png')}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
