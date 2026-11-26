#!/usr/bin/env python3
# =============================================================================
# Record an ISO build measurement JSON file.
# Usage: record_build_measurement.py <iso-path> <sha256> <out-json> [--key=value ...]
#
# Reads the manifest/packages.txt next to the ISO (if present) for package count
# and records runner/environment metadata.
# =============================================================================
import argparse
import datetime
import json
import os
import pathlib
import socket
import subprocess
import sys


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("iso_path")
    p.add_argument("sha256")
    p.add_argument("out_json")
    p.add_argument("--tag", default="")
    p.add_argument("--version", default="")
    p.add_argument("--edition", default="home")
    p.add_argument("--codename", default="trixie")
    p.add_argument("--event", default="")
    p.add_argument("--run-id", default="")
    p.add_argument("--workflow", default="")
    p.add_argument("--extra-caveat", action="append", default=[])
    args = p.parse_args()

    iso_path = pathlib.Path(args.iso_path)
    if not iso_path.exists():
        print(f"ISO not found: {iso_path}", file=sys.stderr)
        return 1

    size = iso_path.stat().st_size
    try:
        size_human = subprocess.run(
            ["numfmt", "--to=iec-i", "--suffix=B", str(size)],
            capture_output=True, text=True, check=True,
        ).stdout.strip()
    except Exception:
        size_human = f"{size} bytes"

    pkgs_file = iso_path.parent / "manifest" / "packages.txt"
    pkg_count = 0
    if pkgs_file.exists():
        with pkgs_file.open() as f:
            pkg_count = sum(1 for _ in f)

    caveats = [
        "Build ran on a CI runner (not on Bright OS itself); idle-RAM and boot-time are not measured.",
        "KVM is not available on GitHub-hosted runners; QEMU smoke test uses TCG software emulation.",
        "Real-hardware boot and installation testing is required before declaring stable readiness.",
    ] + list(args.extra_caveat)

    data = {
        "schema_version": 1,
        "tag": args.tag or f"ci-build-{args.run_id or 'manual'}",
        "timestamp": datetime.datetime.utcnow().isoformat() + "Z",
        "meta": {
            "environment": {
                "runner": os.environ.get("RUNNER_OS", "unknown"),
                "runner_name": socket.gethostname(),
                "kernel": os.uname().release,
                "arch": os.uname().machine,
                "distro": args.codename,
                "edition": args.edition,
                "version": args.version,
                "has_kvm": os.path.exists("/dev/kvm"),
                "ci": True,
            },
            "caveats": caveats,
        },
        "measurements": {
            "iso": {
                "filename": iso_path.name,
                "size_bytes": size,
                "size_human": size_human,
                "sha256": args.sha256,
                "installed_packages": pkg_count,
            },
            "build": {
                "workflow": args.workflow,
                "run_id": args.run_id,
                "event": args.event,
            },
        },
    }
    out = pathlib.Path(args.out_json)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(data, indent=2))
    print(f"Wrote {out}")
    print(json.dumps(data["measurements"], indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
