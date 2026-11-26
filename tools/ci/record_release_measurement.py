#!/usr/bin/env python3
# =============================================================================
# Record release metadata JSON (same schema as build measurement, plus release
# tag and release caveats). Called by the release workflow after build.
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
    p.add_argument("--tag", required=True)
    p.add_argument("--version", required=True)
    p.add_argument("--edition", default="home")
    p.add_argument("--codename", default="trixie")
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

    data = {
        "tag": args.tag,
        "version": args.version,
        "edition": args.edition,
        "codename": args.codename,
        "built_at": datetime.datetime.utcnow().isoformat() + "Z",
        "runner": socket.gethostname(),
        "iso": {
            "filename": iso_path.name,
            "size_bytes": size,
            "size_human": size_human,
            "sha256": args.sha256,
            "installed_packages": pkg_count,
        },
        "caveats": [
            "Experimental alpha build — use for testing, not production.",
            "KWin is the default compositor; labwc is optional/experimental.",
            "See docs/labwc-poc-notes.md for current labwc limitations.",
            "Idle-RAM and runtime performance have not been measured on booted hardware.",
            "Test in a VM (QEMU/KVM, VirtualBox) before installing on real hardware.",
        ],
    }
    out = pathlib.Path(args.out_json)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(data, indent=2))
    print(f"Wrote {out}")
    print(json.dumps(data, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
