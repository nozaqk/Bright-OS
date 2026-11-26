#!/usr/bin/env python3
# =============================================================================
# Extract package manifest from a Bright OS squashfs root (dpkg status file).
# Writes manifest/packages.txt (one "pkg=version" per line, sorted) to the
# current directory, and prints a summary to stdout.
#
# Usage: extract_manifest.py <path-to-dpkg-status-file> <output-dir>
# =============================================================================
import re
import sys
import pathlib


def main() -> int:
    if len(sys.argv) < 2:
        print("usage: extract_manifest.py <dpkg-status-file> [output-dir]", file=sys.stderr)
        return 2
    status_path = pathlib.Path(sys.argv[1])
    out_dir = pathlib.Path(sys.argv[2]) if len(sys.argv) > 2 else pathlib.Path("manifest")
    if not status_path.exists():
        print(f"No dpkg status at {status_path}; skipping manifest.", file=sys.stderr)
        return 0
    text = status_path.read_text(errors="replace")
    # Match Package/Status/Version triplets across blocks (non-greedy)
    pkgs = re.findall(
        r"^Package:\s*(\S+).*?^Status:\s*(.*?)$.*?^Version:\s*(\S+)",
        text,
        re.MULTILINE | re.DOTALL,
    )
    installed = [(n, v) for (n, s, v) in pkgs if "installed" in s]
    installed.sort()
    total = len(installed)
    print(f"Total installed packages in ISO: {total}")
    key_pkgs = [
        "sddm", "kwin-wayland", "plasma-desktop", "calamares", "aura-core-service",
        "waydroid", "labwc", "linux-image-amd64", "firefox-esr",
        "policykit-1", "xdg-desktop-portal", "pipewire", "grub-pc",
    ]
    key_index = {n: v for (n, v) in installed}
    for k in key_pkgs:
        v = key_index.get(k, "(not installed)")
        print(f"  {k}: {v}")
    out_dir.mkdir(parents=True, exist_ok=True)
    out_file = out_dir / "packages.txt"
    with out_file.open("w") as f:
        for n, v in installed:
            f.write(f"{n}={v}\n")
    print(f"Wrote {out_file} ({total} entries)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
