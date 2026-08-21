// env_probe.hpp: environment discipline fields, read post-loop only: never
// on the record path. Every one of these is best-effort and absent in the
// CI container, so each falls back to a sentinel rather than failing the
// run.

#pragma once
#include <string>

namespace env_probe {

std::string read_sysfs_line(const std::string& path);
std::string sysfs_or_unknown(const std::string& path);

// cpuidle driver, CPU count, and per-state name/latency_us/disabled under
// cpu_root (trailing slash). No exceptions beyond allocation failure escape;
// missing files are sentinels. Absent tree yields { "driver": "unknown",
// "cpus": 0, "states": [] }. "disabled" counts USER disables only: the
// kernel masks out driver-imposed disables, so a driver-disabled state
// reads 0.
std::string cpuidle_json(
    const std::string& cpu_root = "/sys/devices/system/cpu/");

}  // namespace env_probe
