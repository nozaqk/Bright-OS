# Phase 6 Baseline Measurements

This directory contains machine-readable baseline measurements captured at the
start of Phase 6. They are the reference point against which all subsequent
optimizations are compared.

## Files

- `phase6-0-baseline-static.json` — captured at the start of sub-phase 6.0
  (commit on branch `arena/phase6-0-ci-baseline`). This is a STATIC baseline:
  package counts, source file counts, and repository layout. Runtime numbers
  (RAM/boot) in this file were captured on the CI sandbox, not on a booted
  Bright OS system, and are labeled as such in the JSON.

## Static baseline numbers (source-of-truth)

These are the STATIC package-list counts that define the pre-optimization
starting point (excluding transitive apt dependencies):

| Package list                        | Packages |
|-------------------------------------|---------:|
| `config/package-lists/core.list.chroot` | 173 |
| `config/package-lists/desktop.list.chroot` (Plasma) | 34 |
| `config/package-lists/desktop-lite.list.chroot` (LXQt) | 29 |
| `config/package-lists/aura-core.list.chroot` | 18 |
| `config/package-lists/android.list.chroot` | 7 |
| `editions/home/packages.list`       | 25 |
| `editions/developer/packages.list`  | 111 |
| `editions/lite/packages.list`       | 13 |

| Composed edition (unique package names, union) | Packages |
|------------------------------------------------|---------:|
| Home (core + desktop + aura + home)            | 240 |
| Home + Android                                 | 246 |
| Developer (core + desktop + aura + dev)        | 325 |
| Developer + Android                            | 331 |
| Lite (core + desktop-lite + aura + lite)       | 221 |

| Repository metric | Count |
|-------------------|------:|
| Python source files (source tree) | 62 (see sync test) |
| Python packaged copies (config/includes.chroot) | 62 |
| Python test files (source) | 17 |
| Shell test suites | 15 (14 pre-existing + 1 added in 6.0 for measurement tools) |

## What is NOT yet baselined (pending ISO build)

The following metrics require a built ISO that boots Bright OS into the
graphical session; they will be captured in sub-phase 6.7 (automated ISO
build + QEMU) and added here:

- **Idle RAM (PSS/RSS/MemAvailable)** — target 250–350 MB, not yet measured.
- **Boot time (kernel + userspace + graphical.target)** — target <60 s,
  not yet measured.
- **ISO size** — target <2 GiB, not yet measured.
- **Minimum-RAM boot behavior** (1 GB target).

Sandbox self-test numbers (visible in the JSON under `summary.memory_used_after_reclaim_mb`)
are explicitly NOT Bright OS idle-RAM baselines. They prove the measurement
tools produce valid output but were collected on the developer/CI sandbox,
which runs different services and a different kernel.
