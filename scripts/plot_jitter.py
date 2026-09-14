#!/usr/bin/env python3
"""
plot_jitter.py: draw the figure the project is judged on.

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

ROOT = pathlib.Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
from scripts import sweep

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


def y_floor(counts, default=5e-6):
    """Lower y limit: half the reciprocal of the largest series, so the last
    real point stays on the axis."""
    if not counts:
        return default
    return 0.5 / max(counts)


def series_label(filename):
    """Filename minus its known jitter-CSV suffix. `L3.jitter.csv` -> `L3`,
    `L3.r2.jitter.csv` -> `L3.r2` (--repeat runs keep their .rN)."""
    for suffix in (".jitter_naive.csv", ".jitter.csv"):
        if filename.endswith(suffix):
            return filename[: -len(suffix)]
    return filename.split(".")[0]


LATENCY_POPULATIONS = (
    ('latency', 'served sensor-to-actuator latency'),
    ('uplink_wait', 'uplink wait (served observations)'),
    ('vehicle_compute', 'vehicle compute (served observations)'),
    ('discard_age', 'discard age (unserved observations)'),
)


def latency_series(directory):
    import math
    rows = []
    for meta in sorted(pathlib.Path(directory).glob('*.summary.json')):
        summary = sweep.read_json(meta)
        mode, _ = sweep.summary_mode(summary)
        if mode in ('harness', 'lockstep'):
            continue
        name = meta.name[:-len('.summary.json')]
        served_counts = []
        for population, title in LATENCY_POPULATIONS:
            distribution = summary.get(population+'_us')
            if distribution is None and population == 'discard_age':
                continue
            if not isinstance(distribution, dict) or type(distribution.get('count')) is not int or distribution['count'] < 0:
                raise ValueError(str(meta)+': invalid '+population+' population')
            count = distribution['count']
            if population != 'discard_age':
                served_counts.append(count)
            if not count:
                continue
            p999 = distribution.get('p99.9')
            if type(p999) not in (int,float) or not math.isfinite(p999) or p999 < 0:
                raise ValueError(str(meta)+': invalid '+population+' percentile')
            path = meta.with_name(name+'.'+population+'.csv')
            xs, ys = [], []
            last_value, last_percentile, last_count = -1, -1, 0
            with path.open(newline='') as stream:
                reader = csv.DictReader(stream)
                if not {'Value','Percentile','TotalCount'} <= set(reader.fieldnames or []):
                    raise ValueError(str(path)+': invalid histogram columns')
                for point in reader:
                    if (point.get('Value') or '').startswith('#'):
                        continue
                    value = float(point['Value']); percentile = float(point['Percentile']); total = int(point['TotalCount'])
                    if (not math.isfinite(value) or not math.isfinite(percentile)
                            or value < last_value or value < 0 or not last_percentile <= percentile <= 1
                            or percentile < 0 or not last_count <= total <= count):
                        raise ValueError(str(path)+': invalid histogram ordering/population')
                    last_value, last_percentile, last_count = value, percentile, total
                    if percentile < 1:
                        xs.append(value); ys.append(1-percentile)
            if last_count != count or last_percentile != 1 or not xs:
                raise ValueError(str(path)+': incomplete histogram population')
            mode_label = mode or 'mode unknown'
            rows.append(dict(population=population,count=count,p999_us=p999,xs=xs,ys=ys,
                             title=title,label=f'{name} ({mode_label}, diagnostic)'))
        if len(set(served_counts)) > 1:
            raise ValueError(str(meta)+': served component populations differ')
    if not rows:
        raise ValueError('no latency populations to plot')
    return rows


def plot_latency(directory, output=None):
    rows = latency_series(directory)
    fig, axes = plt.subplots(2,2,figsize=(12,8))
    try:
        for ax,(population,title) in zip(axes.flat,LATENCY_POPULATIONS):
            selected = [r for r in rows if r['population']==population]
            for r in selected:
                ax.plot(r['xs'],r['ys'],label=f"{r['label']}; n={r['count']}; p99.9 observed {r['p999_us']:g} us")
            ax.set_title(title); ax.set_xlabel('microseconds'); ax.set_ylabel('fraction worse')
            ax.set_yscale('log')
            if selected:
                ax.set_ylim(y_floor([r['count'] for r in selected]),1.1)
                ax.legend(fontsize=7)
            else:
                ax.text(.1,.5,'no recorded population',transform=ax.transAxes)
            ax.grid(True,alpha=.3)
        fig.suptitle('Latency populations: diagnostic rendering, qualification must be checked separately')
        fig.tight_layout()
        out = pathlib.Path(output) if output else pathlib.Path(directory)/'latency.svg'
        out.parent.mkdir(parents=True,exist_ok=True)
        fig.savefig(out,bbox_inches='tight')
        fig.savefig(out.with_suffix('.png'),dpi=170,bbox_inches='tight')
        print(f'wrote {out} and {out.with_suffix(".png")} (diagnostic)')
        return 0
    finally:
        plt.close(fig)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--results", default="results")
    ap.add_argument("--out", default=None, help="default: <results>/jitter.svg")
    ap.add_argument("--naive", action="store_true",
                    help="plot the self-referenced naive-measurement series (CO demo)")
    ap.add_argument("--target-us", type=float, default=100.0,
                    help="p99.9 deadline target marker (default: 100)")
    ap.add_argument('--latency',action='store_true',help='plot served s2a, components and discard age')
    args = ap.parse_args(argv)
    if args.latency and args.naive:
        ap.error('--latency and --naive are distinct populations')
    if args.latency:
        try:
            return plot_latency(args.results,args.out)
        except (OSError,ValueError,TypeError,KeyError) as error:
            print(error,file=sys.stderr)
            return 1

    rdir = pathlib.Path(args.results)
    series = "jitter_naive" if args.naive else "jitter"
    files = sorted(rdir.glob(f"*.{series}.csv"))
    if not files:
        return print(f"no *.{series}.csv in {rdir}: run scripts/sweep.py first") or 1

    fig, ax = plt.subplots(figsize=(10, 5.6))
    fig.patch.set_facecolor("white")

    lo, hi = 1e9, 0.0
    counts = []
    for i, path in enumerate(files):
        label = series_label(path.name)

        meta = rdir / f"{label}.summary.json"
        if not meta.exists():
            print(f"skipping {label}: no summary.json to verify config against")
            continue
        d = json.loads(meta.read_text())
        mode, mode_problem = sweep.summary_mode(d)
        problem = sweep.row_problem(d) if mode_problem is None else None
        if problem:
            print(f"skipping {label}: {problem}")
            continue

        xs, ys = read_cdf(path)
        if not xs:
            continue
        lo, hi = min(lo, min(xs)), max(hi, max(xs))

        p999 = d["jitter_us"]["p99.9_naive" if args.naive else "p99.9"]
        legend = f"{label}  ·  p99.9 {p999:,.0f} µs  ·  {d['config']}" + (
            " · mode unknown, diagnostic" if mode_problem else "")
        counts.append(d.get("cycles", 0))

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
    if hi <= 0:
        return print(f"no plottable data in {rdir}") or 1
    ax.set_xlim(max(lo * 0.8, 0.05), hi * 1.4)
    ax.set_ylim(y_floor(counts), 1.4)
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
