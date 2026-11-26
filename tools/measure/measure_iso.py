#!/usr/bin/env python3
"""Measure ISO file size and basic validity when an ISO artifact exists.

This tool is a shim that reports the size of any *.iso file found at a
path you specify (default: build/ output directories). It is designed to
run in CI after a build step; if no ISO exists it reports that clearly
rather than failing.

Also computes SHA-256 for artifact integrity, and reads the ISO's primary
volume descriptor (offset 32769 = 0x8001) to extract the volume label if
the ISO is a valid ISO-9660 image.
"""
from __future__ import annotations

import argparse
import datetime
import hashlib
import json
import os
import pathlib
import platform
import struct
import sys
from typing import Any


REPO_ROOT = pathlib.Path(__file__).resolve().parents[2]
DEFAULT_SEARCH_DIRS = [
    REPO_ROOT / "build" / "output",
    REPO_ROOT / "build" / "live-build",
    REPO_ROOT,
]


def sha256_of(path: pathlib.Path, buf: int = 1 << 20) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        while True:
            chunk = f.read(buf)
            if not chunk:
                break
            h.update(chunk)
    return h.hexdigest()


def read_iso_label(path: pathlib.Path) -> str | None:
    """Try to read ISO-9660 primary volume descriptor volume ID."""
    try:
        with open(path, "rb") as f:
            f.seek(32769)  # sector 16, offset of PVD
            pvd = f.read(2048)
    except OSError:
        return None
    if len(pvd) < 2048 or pvd[0] != 1:
        return None  # not a PVD
    # Volume ID is bytes 40..72 (32 bytes, padded with spaces)
    vol_id = pvd[40:72].decode("ascii", errors="replace").rstrip(" ")
    return vol_id or None


def find_isos(search_dirs: list[pathlib.Path]) -> list[pathlib.Path]:
    found: list[pathlib.Path] = []
    for d in search_dirs:
        if not d.is_dir():
            continue
        for p in sorted(d.rglob("*.iso")):
            if p.is_file() and p not in found:
                found.append(p)
    return found


def human_size(n_bytes: int) -> str:
    units = ["B", "KiB", "MiB", "GiB"]
    v = float(n_bytes)
    for u in units:
        if v < 1024 or u == units[-1]:
            return f"{v:.2f} {u}"
        v /= 1024.0
    return f"{n_bytes} B"


def measure(iso_path: pathlib.Path | None) -> dict[str, Any]:
    out: dict[str, Any] = {
        "timestamp_utc": datetime.datetime.utcnow().isoformat(timespec="seconds") + "Z",
        "hostname": platform.node(),
        "iso_found": False,
        "iso_size_bytes": None,
        "iso_size_human": None,
        "iso_size_mib": None,
        "iso_path": None,
        "sha256": None,
        "volume_label": None,
        "target_max_bytes": 2 * 1024 * 1024 * 1024,  # 2 GiB
        "within_target": None,
        "notes": [],
    }
    if iso_path is None:
        out["notes"].append(
            "No ISO artifact found. This is expected in sub-phase 6.0 before the build pipeline produces ISOs."
        )
        out["notes"].append(
            "ISO size target (<2 GiB / 2147483648 bytes) will be checked once artifacts exist in sub-phase 6.7."
        )
        return out
    if not iso_path.is_file():
        out["notes"].append(f"Specified ISO path does not exist: {iso_path}")
        return out
    size = iso_path.stat().st_size
    out.update({
        "iso_found": True,
        "iso_path": str(iso_path),
        "iso_size_bytes": size,
        "iso_size_human": human_size(size),
        "iso_size_mib": round(size / (1024 * 1024), 2),
        "sha256": sha256_of(iso_path),
        "volume_label": read_iso_label(iso_path),
        "within_target": size <= out["target_max_bytes"],
    })
    if out["within_target"]:
        out["notes"].append(
            f"ISO is under the 2 GiB target (headroom {human_size(out['target_max_bytes'] - size)})."
        )
    else:
        out["notes"].append(
            f"ISO EXCEEDS the 2 GiB target by {human_size(size - out['target_max_bytes'])}."
        )
    return out


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--iso", help="Path to ISO file (default: auto-search build/ output dirs)")
    ap.add_argument("--out", "-o", help="Write JSON to this path (default: stdout)")
    ap.add_argument("--pretty", action="store_true", help="Pretty-print JSON")
    args = ap.parse_args()

    iso = pathlib.Path(args.iso).resolve() if args.iso else None
    if iso is None:
        found = find_isos(DEFAULT_SEARCH_DIRS)
        iso = found[0] if found else None
    report = measure(iso)
    text = json.dumps(report, indent=2 if args.pretty else None, sort_keys=True)
    if args.out:
        pathlib.Path(args.out).write_text(text + "\n", encoding="utf-8")
        print(f"Wrote ISO report to {args.out}", file=sys.stderr)
    else:
        print(text)
    return 0


if __name__ == "__main__":
    sys.exit(main())
