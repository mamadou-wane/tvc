# Platform qualification

The measured record of the machine every published number comes from.
Nothing in this file is assumed: each section is command output captured on
the box, and the pending section lists what has not been measured yet.

## Machine

HP ProBook 465 G11 (product A1RM8UT#ABA), AMD Ryzen 7 7735U, 16 GB DDR5.
Ubuntu 26.04 LTS, captured 2026-08-14.

## Kernel

```
$ uname -r
7.0.0-29-generic

$ grep -E 'CONFIG_NO_HZ_FULL|CONFIG_RCU_NOCB_CPU' /boot/config-$(uname -r)
CONFIG_NO_HZ_FULL=y
CONFIG_RCU_NOCB_CPU=y
# CONFIG_RCU_NOCB_CPU_DEFAULT_ALL is not set
```

2026-08-29: an apt upgrade replaced both 7.0.0-29 images with 7.0.0-30
(generic and realtime) and removed the old ones, and GRUB_DEFAULT=0
then booted the realtime image, which sorts first. The default now
names the generic entry by id
(GRUB_DEFAULT="gnulinux-advanced-<uuid>>gnulinux-7.0.0-30-generic-advanced-<uuid>");
every number from that date on is 7.0.0-30-generic. Both images carry
CONFIG_OSNOISE_TRACER=y.

The isolation boot parameters (isolcpus, nohz_full, rcu_nocbs) engage on
this kernel. The realtime comparison kernel is in the archive,
version-matched to generic:

```
$ apt-cache search linux-image | grep -i realtime
linux-image-7.0.0-29-realtime - Signed kernel image realtime
linux-image-realtime - Linux kernel image for real-time systems.
...
```

## Topology

Eight homogeneous cores, SMT siblings in adjacent pairs, one shared L3,
uniform 4.82 GHz max across all threads. No heterogeneous core types.

```
$ cat /sys/devices/system/cpu/cpu*/topology/thread_siblings_list | sort -u
0-1
2-3
4-5
6-7
8-9
10-11
12-13
14-15
```

```
$ lscpu --all --extended
CPU NODE SOCKET CORE L1d:L1i:L2:L3 ONLINE    MAXMHZ   MINMHZ       MHZ
  0    0      0    0 0:0:0:0          yes 4821.1401 406.6030 1103.6350
  1    0      0    0 0:0:0:0          yes 4821.1401 406.6030 1439.0720
  2    0      0    1 1:1:1:0          yes 4821.1401 406.6030 2245.4519
  3    0      0    1 1:1:1:0          yes 4821.1401 406.6030 1533.1541
  4    0      0    2 2:2:2:0          yes 4821.1401 406.6030 1837.9810
  5    0      0    2 2:2:2:0          yes 4821.1401 406.6030 1103.6350
  6    0      0    3 3:3:3:0          yes 4821.1401 406.6030 1343.1960
  7    0      0    3 3:3:3:0          yes 4821.1401 406.6030 1387.0940
  8    0      0    4 4:4:4:0          yes 4821.1401 406.6030 1281.5070
  9    0      0    4 4:4:4:0          yes 4821.1401 406.6030 1282.2650
 10    0      0    5 5:5:5:0          yes 4821.1401 406.6030 1281.8760
 11    0      0    5 5:5:5:0          yes 4821.1401 406.6030 1103.6350
 12    0      0    6 6:6:6:0          yes 4821.1401 406.6030 2245.8279
 13    0      0    6 6:6:6:0          yes 4821.1401 406.6030 1103.6350
 14    0      0    7 7:7:7:0          yes 4821.1401 406.6030 1812.5400
 15    0      0    7 7:7:7:0          yes 4821.1401 406.6030 1103.6350
```

## Chosen isolation

Core 3 (CPUs 6 and 7): both siblings isolated, loop pinned to CPU 7,
CPU 6 left idle. Core 0 avoided because it carries default housekeeping
and IRQ load. Recipe and rationale: methodology.md, host preparation.

## Isolation verified after reboot

```
$ cat /sys/devices/system/cpu/isolated
6-7

$ cat /proc/cmdline
BOOT_IMAGE=/boot/vmlinuz-7.0.0-29-generic root=UUID=... ro quiet splash
isolcpus=6,7 nohz_full=6,7 rcu_nocbs=6,7 crashkernel=...
```

## Firmware stall qualification

One hour of hwlatdetect at idle, 10 us threshold, all CPUs sampled,
captured 2026-08-15:

```
$ sudo hwlatdetect --duration=3600 --threshold=10
test finished
Max Latency: 129us
Samples recorded: 2
Samples exceeding threshold: 2
ts: 1786805006.080003491, inner:0, outer:11, cpu:0
ts: 1786807428.990884859, inner:129, outer:92, cpu:3
```

Verdict: qualified. Two events in an hour, neither on the isolated pair.
At that rate a ten-minute campaign run expects roughly 0.3 events; one
sample in 300,000 sits at p99.9997, so a stall of this size can appear in
a run's max or p99.99 and cannot move the p99.9 headline. The 129 us
event is the number to publish next to any run whose max looks
inexplicable.

Note on SMI counters: the turbostat SMI column reads an Intel-only MSR
and does not exist on this AMD part. hwlatdetect is the firmware-stall
instrument for this machine; rerun it if the max of a campaign run ever
exceeds the qualified 129 us.

## Realtime kernel

linux-image-realtime 7.0.0-29 (version-matched to generic) was booted
one-shot via grub-reboot for the comparison campaign on 2026-08-15, with
the runtime discipline re-applied after boot; every summary in
baselines/2026-08-15-rt-campaign records kernel 7.0.0-29-realtime with
performance governor and EPP on AC. The machine returns to the generic
kernel, the configuration of record, on the next reboot.

## Power discipline (captured 2026-08-16, v0.2a campaign)

Applied at runtime before the campaign; resets on reboot and must be
reapplied before any gated run.

```
$ sudo cpupower frequency-set -g performance
$ echo performance | sudo tee /sys/devices/system/cpu/cpu*/cpufreq/energy_performance_preference
$ sudo cpupower idle-set -D 0
$ cpupower idle-info
CPUidle driver: acpi_idle
POLL (DISABLED) ... C1 (DISABLED) Latency: 1 ... C2 (DISABLED) Latency: 18 ... C3 (DISABLED) Latency: 350
```

Disabling every idle state on every CPU is what moved L5 p99.9 from
88.4 to 7.5 us; the mechanism and the audit gap are in results.md. Known defect in the 2026-08-16 setup: the IRQ
affinity mask written was ffff3f, which carries bits for CPUs 16 to 23
on this 16-CPU machine; the kernel rejected it with EOVERFLOW, so IRQ
affinity was not applied for that campaign. The correct exclude-6,7
mask is ff3f.

## Session discipline, 2026-08-29 (the pinned-timer discipline)

Not yet the discipline of record; that is decided with the next full
campaign (results.md, what this changes). The machine-wide idle-set
above makes every idle CPU busy-poll on 7.0.0-30: turbostat read
Busy% 100 on all cores at 4,211 MHz and 24.96 W package power, and
k10temp read 92 C once during the session (captures in
baselines/2026-08-29-timer-migration/session-observations.txt). What
it was compensating for is nohz_full timer migration (results.md, the
far tail), and this discipline goes at the source:

```
$ sudo cpupower frequency-set -g performance
$ echo performance | sudo tee /sys/devices/system/cpu/cpu*/cpufreq/energy_performance_preference
$ echo ff3f | sudo tee /proc/irq/default_smp_affinity
$ for f in /proc/irq/[0-9]*/smp_affinity; do echo ff3f | sudo tee "$f" > /dev/null 2>&1 || echo "refused: $f"; done
$ sudo cpupower -c 6,7 idle-set -D 0
$ echo 0 | sudo tee /proc/sys/kernel/timer_migration
```

Verified state before osnoise-C-mig0:

```
$ cat /sys/devices/system/cpu/cpu*/cpuidle/state*/disable | sort | uniq -c
     56 0
      8 1
$ cat /proc/sys/kernel/timer_migration
0
```

All of it resets on reboot. With only the pair polling the package
read 68 C at the start and 69 C at the end of the ten-minute
osnoise-C-mig0 run (its run.log), and 67 to 69 C in the env blocks of
all pair-only runs.

Where the wakeup timer lives, sampled from /proc/timer_list during an
L5 run with timer_migration=1 (six samples 0.5 s apart; three carried
a hrtimer_wakeup entry expiring within 2.5 ms, two carried stale
entries from other processes, one carried none; all six in
session-observations.txt):

```
hrtimer_wakeup on cpu 4, expires in 1218 us
hrtimer_wakeup on cpu 4, expires in 2198 us
hrtimer_wakeup on cpu 7, expires in 1444 us
```

With timer_migration=0, LOC for CPU 7 in /proc/interrupts climbs two
per cycle during a run (607,732 over 300,000 cycles in osnoise-C-mig0,
31,893 over 16,000 in timerdiag-mig0). With it at 1 the count depends
on where the timer went: 93 over 60,000 cycles in osnoise-B-all, 69,490
over 15,000 in osnoise-A-pair (results.md explains the difference). The
LOC count alone does not prove the timer is pinned; /proc/timer_list
does.

## IRQ affinity (applied 2026-08-29)

First campaign with the mask in force. 26 IRQs refuse the write
(session-observations.txt has the list): irq 0 (timer), irq 2, six
ACPI events, the power button, the touchpad, and the sixteen NVMe
queues, which are kernel-managed. Two of those land on the isolated
pair:

```
irq 55  nvme0q3  effective_affinity 0040   (CPU 6)
irq 56  nvme0q4  effective_affinity 0080   (CPU 7)
```

Neither fired during any traced run: each irq-delta.txt prints their
rows, zero on both CPUs. Per-IRQ deltas on CPUs 6 and 7 over the
ten-minute run: LOC 205 and 607,732, CAL 258 and 258, IWI, RES, and
MCP in single digits, nothing else. Keeping managed IRQs off the pair
needs isolcpus=domain,managed_irq,6,7 at the next reboot; the domain
flag must be written explicitly, because a flag list replaces the
implicit domain isolation of a bare CPU list and the pair would rejoin
the scheduler domains.

## Tick on the isolated pair (measured 2026-08-29)

tick_stop events on CPU 7 across the three traced runs (tick-stop.txt
per run): five in osnoise-A-pair, two successful stops and three held
by RCU; none in osnoise-B-all; two in osnoise-C-mig0, both held by
RCU. /proc/timer_list for CPU 7 read .tick_stopped: 1 while idle after
osnoise-A-pair; that read is the only direct evidence of a stopped
tick during the session. The local-timer handler on CPU 7 runs 0.87 us
at the median and 40 us at worst (osnoise-A-pair), so the tick is not a
far-tail candidate either way.

## Pending

- isolcpus=domain,managed_irq,6,7 in GRUB_CMDLINE_LINUX_DEFAULT, a
  reboot, and a re-check of the two NVMe queues above.
- timer_migration recorded in each summary's env block.
- A full L0 to L6 campaign under the pinned-timer discipline to replace
  the gate baselines.
