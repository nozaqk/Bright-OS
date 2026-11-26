#!/usr/bin/env python3
"""Measure system memory usage on a running Linux system.

Captures:
  - /proc/meminfo fields (MemTotal, MemFree, MemAvailable, Buffers, Cached,
    SReclaimable, Shmem, Slab, PageTables, KernelStack, SwapTotal, SwapFree).
  - Per-process PSS, RSS, Private_{Clean,Dirty}, Shared_{Clean,Dirty}, Swap
    from /proc/<pid>/smaps_rollup (falling back to statm if smaps_rollup
    is unavailable).
  - Process metadata (pid, comm, cmdline, uid, systemd slice if available).
  - Kernel working set (Slab_Unreclaim + PageTables + KernelStack +
    VmallocUsed - VmallocChunk where available).
  - Reclaimable cache (Cached + Buffers + SReclaimable - Shmem).
  - Aggregate "used from MemAvailable perspective" = MemTotal - MemAvailable.

Output is a single JSON document on stdout (or to --out file).

This script is designed to be runnable on any Linux system (including the
CI sandbox) without Bright OS-specific dependencies. When run inside a
Bright OS live/installed session it captures the true baseline; when run
elsewhere the numbers are labeled with the host identifier so they are
not confused with Bright OS measurements.
"""
from __future__ import annotations

import argparse
import datetime
import json
import os
import pathlib
import platform
import re
import sys
from typing import Any


def _read(path: str) -> str:
    with open(path, "r", encoding="utf-8", errors="replace") as f:
        return f.read()


def read_meminfo() -> dict[str, int]:
    """Parse /proc/meminfo into a dict of {name: value_in_kibibytes}."""
    data: dict[str, int] = {}
    for line in _read("/proc/meminfo").splitlines():
        m = re.match(r"^([A-Za-z0-9_()]+):\s+(\d+)(?:\s*kB)?\s*$", line)
        if m:
            data[m.group(1)] = int(m.group(2))
    return data


def _read_smaps_rollup(pid: int) -> dict[str, int] | None:
    """Parse /proc/<pid>/smaps_rollup; return None if unavailable."""
    path = f"/proc/{pid}/smaps_rollup"
    try:
        text = _read(path)
    except (OSError, PermissionError):
        return None
    fields: dict[str, int] = {}
    for line in text.splitlines():
        m = re.match(r"^([A-Za-z0-9_()]+):\s+(\d+)\s*kB\s*$", line)
        if m:
            fields[m.group(1)] = int(m.group(2))
    return fields or None


def _read_statm(pid: int) -> tuple[int, int] | None:
    """Fallback: parse /proc/<pid>/statm -> (VmSize_kB, VmRSS_kB). Pages -> kB via page size."""
    path = f"/proc/{pid}/statm"
    try:
        text = _read(path)
    except (OSError, PermissionError):
        return None
    parts = text.split()
    if len(parts) < 2:
        return None
    page_size_kb = os.sysconf("SC_PAGE_SIZE") // 1024
    # statm: size resident shared text lib data dt
    size_pg = int(parts[0])
    rss_pg = int(parts[1])
    return (size_pg * page_size_kb, rss_pg * page_size_kb)


def _read_proc_status(pid: int) -> dict[str, str]:
    """Parse /proc/<pid>/status into a dict of field -> raw value string."""
    out: dict[str, str] = {}
    try:
        text = _read(f"/proc/{pid}/status")
    except (OSError, PermissionError):
        return out
    for line in text.splitlines():
        if ":" in line:
            k, v = line.split(":", 1)
            out[k.strip()] = v.strip()
    return out


def _read_cmdline(pid: int) -> str:
    try:
        raw = _read(f"/proc/{pid}/cmdline")
    except (OSError, PermissionError):
        return ""
    # cmdline uses NUL separators between args
    parts = [p for p in raw.split("\x00") if p]
    return " ".join(parts) if parts else ""


def _detect_systemd_slice(pid: int, status: dict[str, str]) -> str:
    """Best-effort detection of the systemd slice a process belongs to.

    Tries /proc/<pid>/cgroup first (systemd-style entries name the slice);
    falls back to uid-based heuristic (uid 0 -> system.slice, uid >= 1000 ->
    user-<uid>.slice; others -> other.slice).
    """
    try:
        cg_text = _read(f"/proc/{pid}/cgroup")
    except (OSError, PermissionError):
        cg_text = ""
    # Systemd cgroup v2 unified line looks like "0::/user.slice/user-1000.slice/..."
    # cgroup v1: "10:devices:/user.slice/..."
    for line in cg_text.splitlines():
        parts = line.split(":", 2)
        if len(parts) == 3:
            path = parts[2]
            m = re.match(r"/((?:user|system|machine|init)\.slice)\b", path)
            if m:
                # return the top-level slice name
                return m.group(1)
            m = re.match(r"/(user-\d+\.slice)\b", path)
            if m:
                return m.group(1)
    # Heuristic via uid
    uid_str = status.get("Uid", "").split()
    if uid_str:
        try:
            uid = int(uid_str[0])
        except ValueError:
            uid = -1
        if uid == 0:
            return "system.slice"
        if uid >= 1000:
            return f"user-{uid}.slice"
    return "other"


def _read_uptime() -> float:
    try:
        text = _read("/proc/uptime")
        return float(text.split()[0])
    except (OSError, ValueError, IndexError):
        return -1.0


def collect_processes() -> list[dict[str, Any]]:
    """Enumerate /proc and collect per-process memory metrics."""
    procs: list[dict[str, Any]] = []
    for entry in os.listdir("/proc"):
        if not entry.isdigit():
            continue
        pid = int(entry)
        if pid == 0 or pid == 1 and os.getpid() == 1:
            pass
        status = _read_proc_status(pid)
        if not status:
            continue  # process vanished
        rollup = _read_smaps_rollup(pid)
        statm = _read_statm(pid)
        comm = status.get("Name", "")
        cmdline = _read_cmdline(pid)
        uid_parts = status.get("Uid", "").split()
        uid = int(uid_parts[0]) if uid_parts else -1

        proc: dict[str, Any] = {
            "pid": pid,
            "comm": comm,
            "cmdline": cmdline,
            "uid": uid,
            "slice": _detect_systemd_slice(pid, status),
        }
        if rollup is not None:
            proc.update({
                "pss_kb": rollup.get("Pss", 0),
                "rss_kb": rollup.get("Rss", 0),
                "private_clean_kb": rollup.get("Private_Clean", 0),
                "private_dirty_kb": rollup.get("Private_Dirty", 0),
                "shared_clean_kb": rollup.get("Shared_Clean", 0),
                "shared_dirty_kb": rollup.get("Shared_Dirty", 0),
                "swap_kb": rollup.get("Swap", 0),
                "source": "smaps_rollup",
            })
        elif statm is not None:
            proc.update({
                "pss_kb": None,  # can't compute PSS without smaps_rollup
                "rss_kb": statm[1],
                "private_clean_kb": None,
                "private_dirty_kb": None,
                "shared_clean_kb": None,
                "shared_dirty_kb": None,
                "swap_kb": None,
                "source": "statm",
            })
        else:
            continue
        procs.append(proc)
    return procs


def aggregate_by_slice(procs: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    """Sum PSS/RSS/Private/Shared per systemd slice."""
    slices: dict[str, dict[str, Any]] = {}
    for p in procs:
        s = p["slice"]
        agg = slices.setdefault(s, {
            "process_count": 0,
            "pss_kb": 0,
            "rss_kb": 0,
            "private_clean_kb": 0,
            "private_dirty_kb": 0,
            "shared_clean_kb": 0,
            "shared_dirty_kb": 0,
            "swap_kb": 0,
            "pss_available": True,
        })
        agg["process_count"] += 1
        agg["rss_kb"] += p.get("rss_kb") or 0
        if p.get("pss_kb") is not None:
            agg["pss_kb"] += p["pss_kb"]
            agg["private_clean_kb"] += p.get("private_clean_kb") or 0
            agg["private_dirty_kb"] += p.get("private_dirty_kb") or 0
            agg["shared_clean_kb"] += p.get("shared_clean_kb") or 0
            agg["shared_dirty_kb"] += p.get("shared_dirty_kb") or 0
            agg["swap_kb"] += p.get("swap_kb") or 0
        else:
            agg["pss_available"] = False
    return slices


def top_processes(procs: list[dict[str, Any]], n: int = 15, key: str = "pss_kb") -> list[dict[str, Any]]:
    """Return top-n processes by key (pss_kb default, falls back to rss_kb)."""
    def sort_key(p: dict[str, Any]) -> int:
        v = p.get(key)
        if v is None:
            v = p.get("rss_kb") or 0
        return v
    return sorted(procs, key=sort_key, reverse=True)[:n]


def compute_kernel_working_set(meminfo: dict[str, int]) -> dict[str, Any]:
    """Estimate kernel working set from meminfo.

    Kernel working set (resident, non-reclaimable kernel memory) is
    approximated as:
        Slab (unreclaimable portion) + PageTables + KernelStack
    SReclaimable is already counted in "reclaimable cache" and is excluded.
    """
    slab_total = meminfo.get("Slab", 0)
    s_reclaim = meminfo.get("SReclaimable", 0)
    slab_unreclaim = max(slab_total - s_reclaim, 0)
    page_tables = meminfo.get("PageTables", 0)
    kernel_stack = meminfo.get("KernelStack", 0)
    vmalloc_used = meminfo.get("VmallocUsed", 0)
    return {
        "slab_unreclaimable_kb": slab_unreclaim,
        "slab_reclaimable_kb": s_reclaim,
        "page_tables_kb": page_tables,
        "kernel_stack_kb": kernel_stack,
        "vmalloc_used_kb": vmalloc_used,
        "kernel_working_set_kb": slab_unreclaim + page_tables + kernel_stack,
    }


def compute_used_perspective(meminfo: dict[str, int]) -> dict[str, Any]:
    """Compute the 'used from user perspective' numbers.

    MemAvailable is the kernel's best estimate of how much memory is
    available for starting new applications without swapping.
    Reclaimable cache is Cached + Buffers + SReclaimable - Shmem
    (Shmem is memory used by tmpfs/shared mem and is not easily reclaimed).
    """
    mem_total = meminfo.get("MemTotal", 0)
    mem_available = meminfo.get("MemAvailable", 0)
    mem_free = meminfo.get("MemFree", 0)
    buffers = meminfo.get("Buffers", 0)
    cached = meminfo.get("Cached", 0)
    s_reclaim = meminfo.get("SReclaimable", 0)
    shmem = meminfo.get("Shmem", 0)
    reclaimable = cached + buffers + s_reclaim - shmem
    return {
        "mem_total_kb": mem_total,
        "mem_free_kb": mem_free,
        "mem_available_kb": mem_available,
        "used_total_kb": mem_total - mem_free,
        "used_after_reclaim_kb": mem_total - mem_available,  # i.e. MemAvailable view
        "reclaimable_cache_kb": max(reclaimable, 0),
        "buffers_kb": buffers,
        "cached_kb": cached,
        "shmem_kb": shmem,
    }


def collect_memory_report() -> dict[str, Any]:
    meminfo = read_meminfo()
    procs = collect_processes()
    slices = aggregate_by_slice(procs)
    top_pss = top_processes(procs, n=20, key="pss_kb")
    # Stripped process info for top list (avoid huge JSON)
    def _stripped(p: dict[str, Any]) -> dict[str, Any]:
        return {k: p.get(k) for k in (
            "pid", "comm", "cmdline", "uid", "slice",
            "pss_kb", "rss_kb", "private_dirty_kb", "swap_kb", "source",
        )}
    # Totals (sum over all procs with PSS available; note shared libs are
    # divided across consumers via PSS, so PSS sum approximates total user-
    # space memory fairly, while RSS sum double-counts shared memory.)
    pss_total = sum((p.get("pss_kb") or 0) for p in procs if p.get("pss_kb") is not None)
    rss_total = sum((p.get("rss_kb") or 0) for p in procs)
    # Detect mode: are we running under systemd?
    has_systemd = os.path.isdir("/run/systemd/system")
    return {
        "timestamp_utc": datetime.datetime.utcnow().isoformat(timespec="seconds") + "Z",
        "hostname": platform.node(),
        "kernel": platform.release(),
        "uptime_seconds": _read_uptime(),
        "has_systemd": has_systemd,
        "meminfo_kb": meminfo,
        "memory_perspective_kb": compute_used_perspective(meminfo),
        "kernel_working_set_kb": compute_kernel_working_set(meminfo),
        "processes_total": len(procs),
        "totals_kb": {
            "pss_sum": pss_total,
            "rss_sum": rss_total,
            "note": "rss_sum double-counts shared libraries; pss_sum divides shared pages across consumers",
        },
        "slices": slices,
        "top_processes_by_pss": [_stripped(p) for p in top_pss],
        "swap": {
            "swap_total_kb": meminfo.get("SwapTotal", 0),
            "swap_free_kb": meminfo.get("SwapFree", 0),
            "swap_used_kb": meminfo.get("SwapTotal", 0) - meminfo.get("SwapFree", 0),
        },
    }


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--out", "-o", help="Write JSON to this path (default: stdout)")
    ap.add_argument("--pretty", action="store_true", help="Pretty-print JSON")
    args = ap.parse_args()

    report = collect_memory_report()
    text = json.dumps(report, indent=2 if args.pretty else None, sort_keys=True)
    if args.out:
        pathlib.Path(args.out).write_text(text + "\n", encoding="utf-8")
        print(f"Wrote memory report to {args.out}", file=sys.stderr)
    else:
        print(text)
    return 0


if __name__ == "__main__":
    sys.exit(main())
