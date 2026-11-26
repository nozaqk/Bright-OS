#!/bin/bash
# =============================================================================
# Bright OS baseline measurement runner (for in-guest / QEMU use).
#
# Called by bright-measure-boot.service 120 seconds after the system
# reaches multi-user.target. Runs all measurement tools and writes a
# combined JSON report to:
#   /var/log/bright-os/measurements/boot-<timestamp>-<hostname>.json
#
# In CI/QEMU runs the JSON is also printed to stdout (which goes to the
# serial console/journal) so the test harness can grep for it.
#
# This script is placed in /usr/share/bright-os/measure/ by the packaging
# hooks in a later sub-phase; in sub-phase 6.0 it is a template only.
# =============================================================================

set -eu

MEASURE_DIR="${BRIGHT_MEASURE_DIR:-/usr/share/bright-os/measure}"
OUT_DIR="${BRIGHT_MEASURE_OUT_DIR:-/var/log/bright-os/measurements}"
TAG="${BRIGHT_MEASURE_TAG:-post-boot}"

mkdir -p "$OUT_DIR"

TS="$(date -u +%Y%m%dT%H%M%SZ)"
HOST="$(hostname 2>/dev/null || echo unknown)"
OUT_FILE="$OUT_DIR/boot-${TS}-${HOST}.json"

PYTHON="${PYTHON:-python3}"

echo "[bright-measure] collecting measurements to $OUT_FILE ..." >&2

"$PYTHON" "$MEASURE_DIR/run_measurements.py" \
    --tag "$TAG" \
    --out "$OUT_FILE"

echo "[bright-measure] ===== BRIGHT-OS-MEASUREMENT-JSON-BEGIN =====" >&2
cat "$OUT_FILE" >&2
echo "[bright-measure] ===== BRIGHT-OS-MEASUREMENT-JSON-END =====" >&2

exit 0
