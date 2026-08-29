#!/usr/bin/env python3
"""osnoise_tail.py: match the late cycles of an L6 recording to the osnoise
events on the measurement CPU. Both sides are CLOCK_MONOTONIC once the trace
clock is 'mono'.

  python3 osnoise_tail.py <L6.telemetry.tvcrec> <osnoise-cpu7.txt> [threshold_us] [warmup_records]

warmup_records skips the recording's warmup cycles (sweep.py --warmup, 5000 by
default) so counts match the histogram in the summary. Run from the repo
root; it imports ground.wire."""
import bisect, collections, os, re, sys
sys.path.insert(0, os.getcwd())
from ground.wire import read_recording

rec_path, trace_path = sys.argv[1], sys.argv[2]
thresh_us = float(sys.argv[3]) if len(sys.argv) > 3 else 100.0
warmup = int(sys.argv[4]) if len(sys.argv) > 4 else 0
PERIOD_NS = 2_000_000  # 500 Hz
LOOP = ("thread_noise swapper", "thread_noise tvc_harness")  # idle time and the loop itself, not noise

header, records, ctr = read_recording(rec_path)
measured = records[warmup:]
late = [r for r in measured if r.woke_ns - r.deadline_ns > thresh_us * 1000]
print(f"records={len(records)} warmup_skipped={warmup} measured={len(measured)} "
      f"crc_errors={ctr['crc_errors']} late>{thresh_us:g}us={len(late)}")

line_re = re.compile(r"^\s*(?P<comm>.+?)-(?P<pid>\d+)\s+\[(?P<cpu>\d+)\]\s+\S+\s+"
                     r"(?P<ts>\d+\.\d+):\s+(?P<ev>\w+):\s*(?P<rest>.*)$")
dur_re = re.compile(r"duration (\d+) ns")
events = []  # (end_ns, start_ns, source, detail); a noise line is stamped at its end
details = collections.Counter()
with open(trace_path, errors="replace") as f:
    for line in f:
        m = line_re.match(line)
        if not m:
            continue
        end_ns = int(round(float(m["ts"]) * 1e9))
        d = dur_re.search(m["rest"])
        dur = int(d.group(1)) if d else 0
        ev, rest = m["ev"], m["rest"].strip()
        source = f"{ev} {rest.split(' start ')[0]}" if ev.endswith("_noise") else ev
        if not ev.endswith("_noise"):
            details[f"{ev}: {rest}"] += 1
        events.append((end_ns, end_ns - dur, source, rest))
events.sort()
print(f"trace events={len(events)}")

count, total, worst = collections.Counter(), collections.Counter(), {}
for end, start, src, _ in events:
    count[src] += 1
    total[src] += end - start
    worst[src] = max(worst.get(src, 0), end - start)
print("\nevents by source: count, total ms, worst us")
for src, n in count.most_common():
    print(f"  {src:<44} {n:>8} {total[src]/1e6:>10.1f} {worst[src]/1e3:>10.1f}")
if details:
    print("\nnon-noise events by detail:")
    for k, n in details.most_common():
        print(f"  {n:>6}  {k}")

noise = [e for e in events if not e[2].startswith(LOOP)]
ends = [e[0] for e in noise]
print("\n20 longest noise events (idle time and the loop's own run time excluded):")
for end, start, src, rest in sorted(noise, key=lambda e: e[0] - e[1], reverse=True)[:20]:
    print(f"  {(end-start)/1e3:>9.1f} us  start={start/1e9:.6f}  {src}")

print(f"\nper late cycle: noise events overlapping [deadline - period, wake]; "
      f"'covered' means noise duration in the window >= half the lateness")
covered = 0
for r in late:
    lo, hi = r.deadline_ns - PERIOD_NS, r.woke_ns
    lateness = r.woke_ns - r.deadline_ns
    i = bisect.bisect_left(ends, lo)
    hits, tot = [], 0
    while i < len(noise) and noise[i][0] <= hi + 1_000_000:
        end, start, src, rest = noise[i]
        if start <= hi and end >= lo:
            hits.append((end - start, start, src))
            tot += end - start
        i += 1
    flag = "covered" if tot >= 0.5 * lateness else "not covered"
    covered += flag == "covered"
    print(f"\ntick {r.tick}  late {lateness/1e3:.1f} us  deadline={r.deadline_ns/1e9:.6f}  "
          f"noise in window {tot/1e3:.1f} us  {flag}")
    for dur, start, src in sorted(hits, reverse=True)[:8]:
        print(f"    {dur/1e3:>9.1f} us  start={start/1e9:.6f}  {src}")
    if not hits:
        print("    (no noise event in window)")
print(f"\nlate cycles: {len(late)}; covered by kernel-visible noise: {covered}; not covered: {len(late) - covered}")
