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

Disabling every idle state on every CPU, not only the isolated pair, is
what moved L5 p99.9 from 88.4 to 7.5 us; the mechanism and the audit gap
are in results.md. Known defect in the 2026-08-16 setup: the IRQ
affinity mask written was ffff3f, which carries bits for CPUs 16 to 23
on this 16-CPU machine; the kernel rejected it with EOVERFLOW, so IRQ
affinity was not applied for that campaign. The correct exclude-6,7
mask is ff3f.

## Pending measurements

- Per-run environment discipline: AC status, EPP setting, governor, and
  package temperature recorded alongside each summary.
- Per-CPU cpuidle state captured in each summary's environment block:
  the v0.2a campaign showed a 12x p99.9 shift invisible to the current
  fields.
- Optional: confirm the tick stops on the isolated pair under load
  (timer:tick_stop tracepoint).
