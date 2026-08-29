#!/usr/bin/env python3
"""irq_delta.py: per-IRQ counts that landed on CPUs 6 and 7 between two
/proc/interrupts snapshots.

  python3 irq_delta.py <interrupts.before> <interrupts.after> [irq,irq,...]

The optional list names IRQs to print even when their delta is zero."""
import sys

def load(path):
    rows = {}
    for line in open(path):
        parts = line.split()
        if not parts or not parts[0].endswith(":"):
            continue
        counts = []
        for tok in parts[1:]:
            if not tok.isdigit():
                break
            counts.append(int(tok))
        rows[parts[0][:-1]] = (counts, " ".join(parts[1 + len(counts):]))
    return rows

before, after = load(sys.argv[1]), load(sys.argv[2])
always = set(sys.argv[3].split(",")) if len(sys.argv) > 3 else set()
print(f"{'irq':>6} {'cpu6':>8} {'cpu7':>8}  source")
for irq, (cb, desc) in after.items():
    ca = before.get(irq, ([0] * len(cb), desc))[0]
    if len(cb) < 8 or len(ca) < 8:
        continue
    d6, d7 = cb[6] - ca[6], cb[7] - ca[7]
    if d6 or d7 or irq in always:
        print(f"{irq:>6} {d6:>8} {d7:>8}  {desc}")
