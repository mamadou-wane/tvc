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

## Pending measurements

- One hour of hwlatdetect at idle (firmware stall qualification).
- SMI counter via turbostat, logged per benchmark run.
- Per-run environment discipline: AC status, EPP setting, governor, and
  package temperature recorded alongside each summary.
- Confirmation after reboot that the isolated pair shows in
  /sys/devices/system/cpu/isolated and the tick actually stops
  (timer:tick_stop tracepoint).
