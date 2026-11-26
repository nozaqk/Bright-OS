#!/bin/bash
# =============================================================================
# Phase 6.0: Measurement tools test suite
# Verifies that the memory / boot / packages / ISO measurement tools produce
# valid JSON, accept expected arguments, and fail gracefully.
# =============================================================================

set -eu

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"
cd "$PROJECT_ROOT"

PASS=0; FAIL=0
RED='\033[0;31m'; GREEN='\033[0;32m'; NC='\033[0m'
pass() { echo -e "${GREEN}[PASS]${NC} $*"; PASS=$((PASS+1)); }
fail() { echo -e "${RED}[FAIL]${NC} $*"; FAIL=$((FAIL+1)); }

MEASURE_DIR="tools/measure"
TMPDIR=$(mktemp -d)
trap 'rm -rf "$TMPDIR"' EXIT

require_python3() {
    if ! command -v python3 >/dev/null 2>&1; then
        echo "SKIP: python3 not available"
        exit 0
    fi
}

echo "============================================"
echo "  Phase 6.0 Measurement Tools Tests"
echo "============================================"

require_python3

# --- Syntax checks --------------------------------------------------------
echo ""
echo "--- Syntax checks ---"
for f in "$MEASURE_DIR"/*.py; do
    if python3 tools/support/py_syntax_check.py 2>/dev/null || [ -f tools/support/py_syntax_check.py ]; then
        :
    fi
    if python3 -c "import py_compile; py_compile.compile('$f', doraise=True)" 2>"$TMPDIR/err"; then
        pass "Python syntax: $(basename "$f")"
    else
        fail "Python syntax: $(basename "$f"): $(cat "$TMPDIR/err")"
    fi
done

if [ -x "$MEASURE_DIR/run-baseline.sh" ]; then
    if bash -n "$MEASURE_DIR/run-baseline.sh" 2>"$TMPDIR/err"; then
        pass "Shell syntax: run-baseline.sh"
    else
        fail "Shell syntax: run-baseline.sh: $(cat "$TMPDIR/err")"
    fi
fi

# --- JSON output validity ------------------------------------------------
echo ""
echo "--- JSON output validity ---"
for tool in measure_memory.py measure_packages.py measure_boot.py measure_iso.py run_measurements.py; do
    out="$TMPDIR/$tool.out"
    if python3 "$MEASURE_DIR/$tool" >"$out" 2>"$TMPDIR/$tool.err"; then
        if python3 -c "import json,sys; json.load(open('$out'))" 2>"$TMPDIR/$tool.jerr"; then
            pass "Valid JSON from $tool"
        else
            fail "$tool produced invalid JSON: $(cat "$TMPDIR/$tool.jerr")"
        fi
    else
        fail "$tool exited non-zero: $(cat "$TMPDIR/$tool.err")"
    fi
done

# --- --pretty flag produces parseable JSON ------------------------------
echo ""
echo "--- --pretty flag ---"
out="$TMPDIR/pretty.out"
python3 "$MEASURE_DIR/run_measurements.py" --pretty >"$out"
if python3 -c "import json; json.load(open('$out'))"; then
    pass "--pretty output is valid JSON"
else
    fail "--pretty output is not valid JSON"
fi

# --- --out flag writes file --------------------------------------------
echo ""
echo "--- --out flag ---"
out="$TMPDIR/out.json"
python3 "$MEASURE_DIR/run_measurements.py" --out "$out" >/dev/null 2>&1
if [ -s "$out" ] && python3 -c "import json; json.load(open('$out'))"; then
    pass "--out writes valid JSON file"
else
    fail "--out did not produce a valid JSON file"
fi

# --- package baseline sanity --------------------------------------------
echo ""
echo "--- Package baseline sanity ---"
out="$TMPDIR/pkg.json"
python3 "$MEASURE_DIR/measure_packages.py" --out "$out" >/dev/null 2>&1
# Core list should contain >150 packages (baseline established during audit)
core_count=$(python3 -c "import json; d=json.load(open('$out')); print(d['package_lists']['core'])")
if [ "$core_count" -ge 150 ]; then
    pass "core.list.chroot has $core_count packages (baseline intact)"
else
    fail "core.list.chroot has $core_count packages (expected >=150, possible regression)"
fi
# Lite edition union should be present and between 150 and 400 packages
lite_count=$(python3 -c "import json; d=json.load(open('$out')); print(d['editions']['lite']['unique_packages'])")
if [ "$lite_count" -ge 150 ] && [ "$lite_count" -le 400 ]; then
    pass "Lite static unique package count $lite_count is within expected range"
else
    fail "Lite static count $lite_count outside expected range [150,400]"
fi

# --- memory output contains required fields -----------------------------
echo ""
echo "--- Memory output schema ---"
out="$TMPDIR/mem.json"
python3 "$MEASURE_DIR/measure_memory.py" --out "$out" >/dev/null 2>&1
for key in meminfo_kb memory_perspective_kb kernel_working_set_kb processes_total totals_kb slices top_processes_by_pss; do
    if python3 -c "import json,sys; d=json.load(open('$out')); sys.exit(0 if '$key' in d else 1)"; then
        pass "Memory report contains key: $key"
    else
        fail "Memory report missing key: $key"
    fi
done
# MemAvailable must be present
if python3 -c "import json; d=json.load(open('$out')); assert 'MemAvailable' in d['meminfo_kb']"; then
    pass "MemAvailable present in meminfo"
else
    fail "MemAvailable missing from meminfo"
fi

# --- boot output contains uptime ---------------------------------------
echo ""
echo "--- Boot output schema ---"
out="$TMPDIR/boot.json"
python3 "$MEASURE_DIR/measure_boot.py" --out "$out" >/dev/null 2>&1
if python3 -c "import json; d=json.load(open('$out')); assert 'uptime_seconds' in d and d['uptime_seconds'] > 0"; then
    pass "boot report contains positive uptime_seconds"
else
    fail "boot report missing/invalid uptime_seconds"
fi
if python3 -c "import json; d=json.load(open('$out')); assert 'kernel_cmdline' in d"; then
    pass "boot report contains kernel_cmdline"
else
    fail "boot report missing kernel_cmdline"
fi

# --- iso report graceful when no ISO present ---------------------------
echo ""
echo "--- ISO report without ISO ---"
out="$TMPDIR/iso.json"
python3 "$MEASURE_DIR/measure_iso.py" --out "$out" >/dev/null 2>&1
if python3 -c "import json; d=json.load(open('$out')); assert d['iso_found'] is False and d['within_target'] is None"; then
    pass "iso report correctly reports 'no ISO' when none present"
else
    fail "iso report did not correctly handle missing ISO"
fi

# --- Combined report has summary section -------------------------------
echo ""
echo "--- Combined report summary ---"
out="$TMPDIR/all.json"
python3 "$MEASURE_DIR/run_measurements.py" --tag ci-test --out "$out" >/dev/null 2>&1
for section in meta packages memory boot iso summary; do
    if python3 -c "import json,sys; d=json.load(open('$out')); sys.exit(0 if '$section' in d else 1)"; then
        pass "Combined report contains section: $section"
    else
        fail "Combined report missing section: $section"
    fi
done

# --- systemd unit file existence ----------------------------------------
echo ""
echo "--- Packaging assets ---"
if [ -f "$MEASURE_DIR/bright-measure-boot.service" ]; then
    pass "bright-measure-boot.service is present"
else
    fail "bright-measure-boot.service missing"
fi
if grep -q "ExecStart=.*run-baseline.sh" "$MEASURE_DIR/bright-measure-boot.service"; then
    pass "service unit references run-baseline.sh"
else
    fail "service unit does not reference run-baseline.sh"
fi

# --- Clean exit ---------------------------------------------------------
echo ""
echo "============================================"
echo "  Results: $PASS passed, $FAIL failed"
echo "============================================"
if [ "$FAIL" -eq 0 ]; then
    echo -e "${GREEN}All measurement-tools tests passed!${NC}"
    exit 0
else
    echo -e "${RED}Some measurement-tools tests failed.${NC}"
    exit 1
fi
