# Phase 6 Measurement Tools

Sub-phase 6.0 introduces a machine-readable measurement harness for Bright OS.
These tools produce JSON artifacts that CI (and local developers) use to track
package counts, idle RAM, boot time, and ISO size across commits — so we never
silently regress on the Phase 6 lightweight targets.

## Tools

| Tool | Purpose |
|------|---------|
| `measure_memory.py` | Per-process PSS/RSS, `/proc/meminfo`, kernel working set, MemAvailable perspective, per-systemd-slice breakdown, top-N processes. |
| `measure_packages.py` | Static counts from `config/package-lists/` and `editions/` package lists; unique-package totals per edition. |
| `measure_boot.py` | `/proc/uptime`, `systemd-analyze time` (kernel+userspace+graphical.target), `systemd-analyze blame` top-N, kernel cmdline. |
| `measure_iso.py` | ISO size in bytes/MiB, SHA-256, ISO-9660 volume label, check against 2 GiB target. |
| `run_measurements.py` | Orchestrator that runs all four tools and writes a single combined JSON report with environment labels + caveats. |
| `harvest_serial_log.py` | Extracts a measurement JSON block from a QEMU serial log (between `BRIGHT-OS-MEASUREMENT-JSON-BEGIN` / `-END` markers). |
| `run-baseline.sh` | Shell wrapper for in-guest/VM use; called by the systemd unit. |
| `bright-measure-boot.service` | Systemd unit that waits 120 s after graphical.target and runs the measurement. **Not enabled by default** — enabled only in CI/QEMU images. |

## Quick start

Run a local measurement on any Linux machine:

```bash
python3 tools/measure/run_measurements.py --tag manual --pretty
```

Write a report to a file:

```bash
python3 tools/measure/run_measurements.py --tag post-change \
    --out build/measurements/post-change.json --pretty
```

Measure an ISO (after it is built in sub-phase 6.7):

```bash
python3 tools/measure/measure_iso.py --iso build/output/lite/bright-os-*.iso --pretty
```

## JSON schema (top level)

```json
{
  "meta": {
    "timestamp_utc": "2026-11-26T16:00:00Z",
    "tag": "baseline",
    "hostname": "bright-os",
    "environment": { "is_bright_os": true, "in_container": false, "has_kvm": false, ... },
    "caveats": [ ... ]
  },
  "packages": { "ok": true, "data": { ... } },
  "memory":   { "ok": true, "data": { ... } },
  "boot":     { "ok": true, "data": { ... } },
  "iso":      { "ok": true, "data": { ... } },
  "summary": {
    "package_count_lite_static": 221,
    "memory_used_after_reclaim_kb": 312000,
    "memory_used_after_reclaim_mb": 304.7,
    "iso_size_mib": null,
    "boot_uptime_seconds": 145.0
  }
}
```

## Memory methodology (per §6.2 of the Phase 6 plan)

- **Per-process PSS** (`/proc/<pid>/smaps_rollup`): Proportional Set Size, which divides
  shared library memory across consumers. This is the primary "fair" accounting.
- **RSS** is also recorded for reference but double-counts shared libraries.
- **Kernel working set**: `SUnreclaim + PageTables + KernelStack` (Slab Reclaimable is
  reported separately as cache).
- **Reclaimable cache**: `Cached + Buffers + SReclaimable - Shmem` — memory the kernel
  can drop under pressure; reported separately so it is not counted against idle target.
- **Used from MemAvailable perspective**: `MemTotal - MemAvailable` — this is what a user
  sees as "used" in `free -h` and is the headline idle-RAM number.
- **Idle period**: when running inside a booted Bright OS via the systemd unit, we wait
  120 s after reaching multi-user.target before sampling to let the desktop settle.

## Important caveats

- Memory/boot numbers from a developer workstation or CI runner are labeled
  `is_bright_os: false` and are **not** Bright OS baseline numbers. They are useful only
  to verify the tools produce valid output.
- True Bright OS idle-RAM and boot-time baselines will be captured once the first
  bootable ISO is built in sub-phase 6.7 and booted under QEMU.
- Do not claim the 250–350 MB idle RAM or <2 GiB ISO targets until measured on actual
  booted Bright OS (QEMU/KVM or hardware).
