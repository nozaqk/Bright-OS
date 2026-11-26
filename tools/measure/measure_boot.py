#!/usr/bin/env python3
"""Measure boot time metrics on a running Linux (systemd) system.

Captures:
  - /proc/uptime (seconds since kernel start).
  - systemd-analyze time (firmware, loader, kernel, userspace, total) if
    systemd is present and systemd-analyze is available.
  - Kernel command line (/proc/cmdline) to document boot parameters.
  - Reached-target breakdown from `systemctl list-jobs` / `systemd-analyze
    blame` top-N (if available).

When systemd is not present (e.g. running in a container), falls back to
/proc/uptime only and records that systemd data is unavailable.

Output is a single JSON document.
"""
from __future__ import annotations

import argparse
import datetime
import json
import os
import pathlib
import platform
import re
import shutil
import subprocess
import sys
from typing import Any


def _read(path: str) -> str:
    try:
        with open(path, "r", encoding="utf-8", errors="replace") as f:
            return f.read()
    except OSError:
        return ""


def _read_uptime() -> float:
    text = _read("/proc/uptime")
    try:
        return float(text.split()[0])
    except (IndexError, ValueError):
        return -1.0


def _parse_systemd_analyze_time(text: str) -> dict[str, Any]:
    """Parse the output of `systemd-analyze time`.

    Typical output:
        Startup finished in 3.456s (kernel) + 8.123s (userspace) = 11.579s
        graphical.target reached after 8.001s in userspace.
    Or with firmware/loader:
        Startup finished in 2.100s (firmware) + 500ms (loader) +
        2.345s (kernel) + 7.890s (userspace) = 12.835s
        graphical.target reached after 7.800s in userspace.
    Returns dict with float seconds for each component present.
    """
    out: dict[str, Any] = {"raw": text.strip()}
    # Match segments like "3.456s (kernel)" or "500ms (loader)"
    pattern = re.compile(
        r"([\d.]+)(ms|s|min)\s*\((firmware|loader|kernel|userspace|initrd)\)"
    )
    for m in pattern.finditer(text):
        val = float(m.group(1))
        unit = m.group(2)
        phase = m.group(3)
        if unit == "ms":
            seconds = val / 1000.0
        elif unit == "min":
            seconds = val * 60.0
        else:
            seconds = val
        out[f"{phase}_seconds"] = round(seconds, 3)
    # Total
    m = re.search(r"=\s*([\d.]+)(ms|s|min)", text)
    if m:
        val = float(m.group(1))
        unit = m.group(2)
        mult = {"ms": 0.001, "s": 1.0, "min": 60.0}[unit]
        out["total_seconds"] = round(val * mult, 3)
    # graphical.target line
    m = re.search(r"graphical\.target reached after ([\d.]+)(ms|s|min)", text)
    if m:
        val = float(m.group(1))
        unit = m.group(2)
        mult = {"ms": 0.001, "s": 1.0, "min": 60.0}[unit]
        out["graphical_target_seconds"] = round(val * mult, 3)
    return out


def _systemd_analyze_time() -> dict[str, Any] | None:
    if not shutil.which("systemd-analyze"):
        return None
    # In containers (no PID 1 systemd) systemd-analyze may fail; tolerate it.
    try:
        res = subprocess.run(
            ["systemd-analyze", "time"],
            capture_output=True, text=True, timeout=10, check=False,
        )
    except (OSError, subprocess.TimeoutExpired):
        return None
    # systemd-analyze prints its human output to stderr
    text = res.stderr if res.stderr.strip() else res.stdout
    if not text.strip():
        return None
    return _parse_systemd_analyze_time(text)


def _systemd_blame_top(n: int = 15) -> list[dict[str, Any]] | None:
    if not shutil.which("systemd-analyze"):
        return None
    try:
        res = subprocess.run(
            ["systemd-analyze", "blame"],
            capture_output=True, text=True, timeout=15, check=False,
        )
    except (OSError, subprocess.TimeoutExpired):
        return None
    if res.returncode != 0:
        return None
    entries: list[dict[str, Any]] = []
    for line in res.stdout.splitlines():
        line = line.strip()
        if not line:
            continue
        m = re.match(r"^([\d.]+)(ms|s|min)\s+(.+)$", line)
        if not m:
            continue
        val = float(m.group(1))
        unit = m.group(2)
        unit_name = m.group(3).strip()
        mult = {"ms": 0.001, "s": 1.0, "min": 60.0}[unit]
        entries.append({"unit": unit_name, "seconds": round(val * mult, 3)})
        if len(entries) >= n:
            break
    return entries


def _cmdline() -> str:
    return _read("/proc/cmdline").strip()


def _has_systemd() -> bool:
    return os.path.isdir("/run/systemd/system")


def collect() -> dict[str, Any]:
    uptime = _read_uptime()
    sd_time = _systemd_analyze_time() if _has_systemd() else None
    sd_blame = _systemd_blame_top() if _has_systemd() else None
    return {
        "timestamp_utc": datetime.datetime.utcnow().isoformat(timespec="seconds") + "Z",
        "hostname": platform.node(),
        "kernel": platform.release(),
        "uptime_seconds": round(uptime, 3),
        "kernel_cmdline": _cmdline(),
        "has_systemd": _has_systemd(),
        "systemd_analyze_time": sd_time,
        "systemd_blame_top": sd_blame,
        "notes": [
            "systemd time data is only meaningful on a system that booted via systemd (not a container).",
            "Boot time to desktop requires additional instrumentation (bright-session-ready marker); see sub-phase 6.3.",
        ],
    }


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--out", "-o", help="Write JSON to this path (default: stdout)")
    ap.add_argument("--pretty", action="store_true", help="Pretty-print JSON")
    args = ap.parse_args()
    report = collect()
    text = json.dumps(report, indent=2 if args.pretty else None, sort_keys=True)
    if args.out:
        pathlib.Path(args.out).write_text(text + "\n", encoding="utf-8")
        print(f"Wrote boot report to {args.out}", file=sys.stderr)
    else:
        print(text)
    return 0


if __name__ == "__main__":
    sys.exit(main())
