#!/usr/bin/env python3
"""Run all Phase 6 measurement tools and write a single combined JSON report.

Usage:
    python3 tools/measure/run_measurements.py [--out FILE] [--tag TAG] [--iso PATH]

Produces a JSON document with sections:
    meta      - timestamp, tag, hostname, tool versions
    packages  - static package-list counts (always available)
    memory    - runtime memory measurement (if /proc accessible; usually yes)
    boot      - boot-time measurement (if systemd is PID 1; best-effort)
    iso       - ISO size/validation (if an ISO exists)

Designed to be safe to run inside:
  - A developer workstation (useful for the package section).
  - A CI sandbox (memory/boot may show container environment, labeled as such).
  - A QEMU-booted Bright OS live/installed session (full measurements).
"""
from __future__ import annotations

import argparse
import datetime
import json
import os
import pathlib
import platform
import subprocess
import sys
import time
from typing import Any

TOOLS_DIR = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(TOOLS_DIR))

import measure_memory  # noqa: E402
import measure_packages  # noqa: E402
import measure_boot  # noqa: E402
import measure_iso  # noqa: E402


def _section(name: str, collector, *args, **kwargs) -> dict[str, Any]:
    """Run a collector and catch exceptions so one failure doesn't kill the report."""
    t0 = time.time()
    try:
        data = collector(*args, **kwargs)
        return {
            "ok": True,
            "duration_seconds": round(time.time() - t0, 3),
            "data": data,
        }
    except Exception as e:  # pragma: no cover - defensive
        return {
            "ok": False,
            "duration_seconds": round(time.time() - t0, 3),
            "error": f"{type(e).__name__}: {e}",
        }


def detect_environment() -> dict[str, Any]:
    """Best-effort label for where the measurement is running."""
    env: dict[str, Any] = {
        "kernel": platform.release(),
        "python": platform.python_version(),
        "pid1": "",
        "in_container": False,
        "is_bright_os": False,
        "has_systemd": os.path.isdir("/run/systemd/system"),
        "has_kvm": os.path.exists("/dev/kvm"),
        "has_docker_env": bool(os.environ.get("DOCKER_RUNNING") or os.path.exists("/.dockerenv")),
    }
    try:
        with open("/proc/1/comm", "r", errors="replace") as f:
            env["pid1"] = f.read().strip()
    except OSError:
        pass
    # Bright OS detection via os-release
    for p in ("/etc/os-release", "/usr/lib/os-release"):
        if os.path.isfile(p):
            try:
                txt = open(p, "r", errors="replace").read()
            except OSError:
                continue
            if "ID=bright" in txt or 'ID="bright"' in txt or "Bright OS" in txt:
                env["is_bright_os"] = True
    if env["has_docker_env"] or (env["pid1"] and env["pid1"] not in ("systemd", "init")):
        env["in_container"] = True
    return env


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--out", "-o", default=None, help="Output file (default: stdout)")
    ap.add_argument("--tag", default="manual",
                    help="Tag label for this measurement (e.g. 'baseline', 'post-labwc', 'ci-<pr#>')")
    ap.add_argument("--iso", default=None, help="Explicit ISO path for iso measurement")
    ap.add_argument("--pretty", action="store_true", help="Pretty-print JSON")
    args = ap.parse_args()

    iso_path = pathlib.Path(args.iso).resolve() if args.iso else None
    env = detect_environment()

    report: dict[str, Any] = {
        "meta": {
            "timestamp_utc": datetime.datetime.utcnow().isoformat(timespec="seconds") + "Z",
            "tag": args.tag,
            "hostname": platform.node(),
            "measurement_tools_dir": str(TOOLS_DIR),
            "environment": env,
            "caveats": [
                "memory/boot sections measured in a container or on a non-Bright-OS host are NOT Bright OS baseline numbers.",
                "RAM and boot targets (250-350 MB idle, <60 s boot) are NOT claimed until measured on a booted Bright OS in QEMU/hardware.",
            ] if not env["is_bright_os"] else [
                "Measurement collected on a booted Bright OS system.",
            ],
        },
        "packages": _section("packages", measure_packages.measure),
        "memory":   _section("memory",   measure_memory.collect_memory_report),
        "boot":     _section("boot",     measure_boot.collect),
        "iso":      _section("iso",      lambda: measure_iso.measure(iso_path)),
    }

    # Compute summary lines for easy log scanning
    mem_kb = None
    if report["memory"]["ok"]:
        mp = report["memory"]["data"].get("memory_perspective_kb", {})
        mem_kb = mp.get("used_after_reclaim_kb")
    pkg_lite = None
    if report["packages"]["ok"]:
        pkg_lite = report["packages"]["data"]["editions"]["lite"]["unique_packages"]
    iso_mib = None
    if report["iso"]["ok"] and report["iso"]["data"]["iso_found"]:
        iso_mib = report["iso"]["data"]["iso_size_mib"]
    report["summary"] = {
        "package_count_lite_static": pkg_lite,
        "memory_used_after_reclaim_kb": mem_kb,
        "memory_used_after_reclaim_mb": round(mem_kb / 1024, 1) if mem_kb else None,
        "iso_size_mib": iso_mib,
        "boot_uptime_seconds": (report["boot"]["data"].get("uptime_seconds")
                                if report["boot"]["ok"] else None),
    }

    text = json.dumps(report, indent=2 if args.pretty else None, sort_keys=True)
    if args.out:
        pathlib.Path(args.out).write_text(text + "\n", encoding="utf-8")
        # Write summary to stderr for quick log reading
        print(f"Wrote measurement report to {args.out}", file=sys.stderr)
        print(json.dumps(report["summary"], indent=2), file=sys.stderr)
    else:
        print(text)
    return 0


if __name__ == "__main__":
    sys.exit(main())
