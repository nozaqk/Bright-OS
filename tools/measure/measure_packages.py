#!/usr/bin/env python3
"""Measure installed package counts from live-build package-lists and editions.

This is a STATIC measurement: it parses the package-list files in the
repository (no network, no apt). It gives a deterministic baseline of the
configured package set per edition so future commits can detect package
count drift (trimming or bloat).

Counts are performed for:
  - config/package-lists/core.list.chroot          (all editions)
  - config/package-lists/desktop.list.chroot       (Home & Developer)
  - config/package-lists/desktop-lite.list.chroot  (Lite)
  - config/package-lists/aura-core.list.chroot     (all editions)
  - config/package-lists/android.list.chroot       (optional; installed with -android metapackage)
  - editions/home/packages.list
  - editions/developer/packages.list
  - editions/lite/packages.list

Union sizes (unique package count) are computed for each composed edition:
Home = core + desktop + aura-core + home additions
Developer = core + desktop + aura-core + developer additions
Lite = core + desktop-lite + aura-core + lite additions
(android is always optional.)
"""
from __future__ import annotations

import argparse
import datetime
import json
import pathlib
import platform
import re
import sys
from typing import Iterable


REPO_ROOT = pathlib.Path(__file__).resolve().parents[2]

LIST_FILES = {
    "core":           REPO_ROOT / "config/package-lists/core.list.chroot",
    "desktop":        REPO_ROOT / "config/package-lists/desktop.list.chroot",
    "desktop_lite":   REPO_ROOT / "config/package-lists/desktop-lite.list.chroot",
    "aura_core":      REPO_ROOT / "config/package-lists/aura-core.list.chroot",
    "android":        REPO_ROOT / "config/package-lists/android.list.chroot",
    "edition_home":   REPO_ROOT / "editions/home/packages.list",
    "edition_dev":    REPO_ROOT / "editions/developer/packages.list",
    "edition_lite":   REPO_ROOT / "editions/lite/packages.list",
}


def parse_package_list(path: pathlib.Path) -> set[str]:
    """Return the set of package names declared in a package-list file.

    Handles: blank lines, '#' comments (whole-line and trailing after
    whitespace), indented entries.
    """
    pkgs: set[str] = set()
    if not path.is_file():
        return pkgs
    for raw in path.read_text(encoding="utf-8", errors="replace").splitlines():
        # strip trailing comment
        line = re.sub(r"#.*$", "", raw).strip()
        if not line:
            continue
        # Some list formats may have conditional prefixes like "pkg:arch"
        # or "pkg/stretch"; for counting purposes we only take the first
        # whitespace/tab/operator-delimited token.
        token = re.split(r"[\s:=/]", line, maxsplit=1)[0]
        if token and re.match(r"^[a-z0-9][a-z0-9.+\-]*$", token):
            pkgs.add(token)
    return pkgs


def measure() -> dict:
    lists: dict[str, list[str]] = {}
    for key, path in LIST_FILES.items():
        lists[key] = sorted(parse_package_list(path))

    core = set(lists["core"])
    desktop = set(lists["desktop"])
    desktop_lite = set(lists["desktop_lite"])
    aura = set(lists["aura_core"])
    android = set(lists["android"])
    home = set(lists["edition_home"])
    dev = set(lists["edition_dev"])
    lite = set(lists["edition_lite"])

    home_union = core | desktop | aura | home
    dev_union = core | desktop | aura | dev
    lite_union = core | desktop_lite | aura | lite
    full_plus_android_home = home_union | android
    full_plus_android_dev = dev_union | android

    editions = {
        "home": {
            "components": ["core", "desktop", "aura_core", "edition_home"],
            "unique_packages": len(home_union),
            "with_android": len(full_plus_android_home),
        },
        "developer": {
            "components": ["core", "desktop", "aura_core", "edition_dev"],
            "unique_packages": len(dev_union),
            "with_android": len(full_plus_android_dev),
        },
        "lite": {
            "components": ["core", "desktop_lite", "aura_core", "edition_lite"],
            "unique_packages": len(lite_union),
        },
    }

    # Per-list counts
    per_list_counts = {key: len(pkgs) for key, pkgs in lists.items()}

    # Compute overlap between core/desktop/desktop_lite to detect cross-drag
    overlap_core_desktop = core & desktop
    overlap_core_desktop_lite = core & desktop_lite
    overlap_desktop_lite_vs_full = desktop & desktop_lite

    # Python source count (for completeness metric)
    py_files = list((REPO_ROOT / "aura").rglob("*.py")) + \
               list((REPO_ROOT / "bright_android").rglob("*.py")) + \
               list((REPO_ROOT / "applications").rglob("*.py")) + \
               list((REPO_ROOT / "desktop").rglob("*.py")) + \
               list((REPO_ROOT / "system").rglob("*.py"))
    py_in_config = list((REPO_ROOT / "config/includes.chroot").rglob("*.py"))

    # Shell test count
    shell_tests = sorted((REPO_ROOT / "tests").glob("test-*.sh"))

    # Python test files (source tree only; packaged copies are duplicates)
    py_tests = []
    for sub in ("aura", "bright_android", "applications", "system"):
        py_tests.extend((REPO_ROOT / sub).rglob("tests/test_*.py"))

    return {
        "timestamp_utc": datetime.datetime.utcnow().isoformat(timespec="seconds") + "Z",
        "repo_root": str(REPO_ROOT),
        "hostname": platform.node(),
        "package_lists": per_list_counts,
        "editions": editions,
        "overlap_analysis": {
            "core_intersect_desktop": sorted(overlap_core_desktop),
            "core_intersect_desktop_lite": sorted(overlap_core_desktop_lite),
            "desktop_intersect_desktop_lite": sorted(overlap_desktop_lite_vs_full),
        },
        "repository": {
            "python_source_files": len(py_files),
            "python_packaged_copies": len(py_in_config),
            "python_test_files_source": len(py_tests),
            "shell_test_suites": len(shell_tests),
            "shell_test_files": [p.name for p in shell_tests],
        },
        "notes": [
            "These are STATIC package-list counts. They do not reflect transitive apt dependencies.",
            "Installed-size estimation requires apt-cache resolve (performed in CI environment in later sub-phases).",
            "Actual ISO size is measured from a built ISO artifact; this tool cannot compute it from source.",
        ],
    }


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--out", "-o", help="Write JSON to this path (default: stdout)")
    ap.add_argument("--pretty", action="store_true", help="Pretty-print JSON")
    args = ap.parse_args()
    report = measure()
    text = json.dumps(report, indent=2 if args.pretty else None, sort_keys=True)
    if args.out:
        pathlib.Path(args.out).write_text(text + "\n", encoding="utf-8")
        print(f"Wrote package report to {args.out}", file=sys.stderr)
    else:
        print(text)
    return 0


if __name__ == "__main__":
    sys.exit(main())
