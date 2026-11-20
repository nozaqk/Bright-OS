#!/bin/bash
# =============================================================================
# Bright OS First ISO Build Script
# =============================================================================
# Builds the Bright OS Lite edition (smallest, fastest) for the first ISO test.
#
# Workflow:
#   1. Verify we're in a Bright OS repository
#   2. Run build doctor (fail if critical issues)
#   3. Run all automated tests
#   4. Build Lite edition
#   5. Validate ISO structure
#   6. Verify SHA256 checksum
#   7. Report results
#
# Usage:
#   ./build/scripts/build-first-iso.sh [--version VER] [--skip-tests] [--force]
# =============================================================================

set -u

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "${SCRIPT_DIR}/../.." && pwd)"

RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
BOLD='\033[1m'
NC='\033[0m'

log_info()  { echo -e "${BLUE}[INFO]${NC} $*"; }
log_ok()    { echo -e "${GREEN}[OK]${NC} $*"; }
log_warn()  { echo -e "${YELLOW}[WARN]${NC} $*"; }
log_error() { echo -e "${RED}[ERROR]${NC} $*" >&2; }
log_step()  { echo -e "\n${BOLD}${BLUE}=== $* ===${NC}"; }

VERSION="0.1.0-alpha"
SKIP_TESTS=false
FORCE=false

while [[ $# -gt 0 ]]; do
    case "$1" in
        -h|--help)
            cat <<EOF
Bright OS First ISO Build Script

Builds the Lite edition (first target for genuine ISO validation).

Usage: $0 [OPTIONS]

Options:
  -h, --help       Show this help
  -v, --version V  Set version string (default: ${VERSION})
  --skip-tests     Skip automated tests before building (not recommended)
  --force          Overwrite existing ISO if present
EOF
            exit 0
            ;;
        -v|--version)
            if [ $# -lt 2 ]; then log_error "--version requires an argument"; exit 1; fi
            VERSION="$2"; shift 2 ;;
        --skip-tests)
            SKIP_TESTS=true; shift ;;
        --force)
            FORCE=true; shift ;;
        *)
            log_error "Unknown argument: $1"; exit 1 ;;
    esac
done

EDITION="lite"
BUILD_SCRIPT="${SCRIPT_DIR}/build.sh"
VALIDATE_SCRIPT="${SCRIPT_DIR}/validate-iso.sh"
DOCTOR_SCRIPT="${SCRIPT_DIR}/bright-build-doctor.sh"
BUILD_DIR="${PROJECT_ROOT}/build/output/${EDITION}"
ISO_NAME="bright-os-${VERSION}-${EDITION}-amd64.iso"
ISO_PATH="${BUILD_DIR}/${ISO_NAME}"
SHA_PATH="${ISO_PATH}.sha256"
BUILD_LOG="${BUILD_DIR}/build-first-iso.log"
BUILD_START=$(date +%s)

echo "============================================================"
echo "  Bright OS First ISO Build"
echo "  Edition:  ${EDITION}"
echo "  Version:  ${VERSION}"
echo "  Output:   ${ISO_PATH}"
echo "============================================================"

# ============================================================
log_step "Step 1: Verify repository"
# ============================================================

if [ ! -f "${PROJECT_ROOT}/README.md" ]; then
    log_error "Not in a Bright OS repository (README.md not found)."
    log_error "Run this script from the root of a Bright OS git clone."
    exit 1
fi

if [ ! -x "$BUILD_SCRIPT" ]; then
    log_error "Build script not found or not executable: ${BUILD_SCRIPT}"
    exit 1
fi

if [ ! -f "${PROJECT_ROOT}/editions/lite/packages.list" ]; then
    log_error "Lite edition package list not found."
    exit 1
fi

log_ok "Bright OS repository found at ${PROJECT_ROOT}"

# Check we're not in a detached HEAD state (warn but don't fail)
if git -C "$PROJECT_ROOT" rev-parse --abbrev-ref HEAD 2>/dev/null | grep -q "HEAD"; then
    log_warn "Git is in detached HEAD state."
fi

# ============================================================
log_step "Step 2: Run Build Doctor"
# ============================================================

echo ""
# Run build doctor and capture exit code IMMEDIATELY (do NOT use 'if ! cmd' — that
# inverts the exit code and $? inside the then-block is always 0)
"$DOCTOR_SCRIPT"
DOCTOR_EXIT=$?
echo ""

case "$DOCTOR_EXIT" in
    0)
        log_ok "Build doctor: all checks passed"
        ;;
    1)
        log_error "Build doctor found CRITICAL issues (exit code ${DOCTOR_EXIT})."
        log_error "Fix the issues above and run this script again."
        echo ""
        echo "To install missing dependencies on Debian:"
        echo "  sudo apt-get update"
        echo "  sudo apt-get install -y live-build debootstrap squashfs-tools xorriso \\"
        echo "    isolinux syslinux-common syslinux-efi mtools dosfstools genisoimage \\"
        echo "    grub-pc-bin grub-efi-amd64-bin shim-signed grub-efi-amd64-signed \\"
        echo "    qemu-system-x86 qemu-utils ovmf file"
        echo ""
        echo "  Or run: ./build/scripts/setup-build-env.sh"
        echo ""
        exit 1
        ;;
    2)
        if [ "$FORCE" != "true" ]; then
            log_warn "Build doctor found warnings but no critical failures (exit code ${DOCTOR_EXIT})."
            echo ""
            echo "Do you want to continue? [y/N]"
            read -r CONTINUE
            case "$CONTINUE" in
                y|Y|yes|YES) ;;
                *) log_error "Aborted by user."; exit 1 ;;
            esac
        else
            log_warn "Build doctor found warnings; continuing due to --force"
        fi
        ;;
    *)
        log_error "Build doctor exited with unexpected code ${DOCTOR_EXIT} (possible crash)."
        log_error "Please report this as a bug."
        exit 1
        ;;
esac

# ============================================================
log_step "Step 3: Check for existing ISO"
# ============================================================

if [ -f "$ISO_PATH" ]; then
    EXISTING_SIZE=$(du -h "$ISO_PATH" | cut -f1)
    if [ "$FORCE" != "true" ]; then
        log_error "Existing ISO found: ${ISO_PATH} (${EXISTING_SIZE})"
        log_error "Refusing to overwrite without --force flag."
        log_error "Move or remove the existing ISO, or use --force to overwrite."
        exit 1
    else
        log_warn "Overwriting existing ISO: ${ISO_PATH} (${EXISTING_SIZE})"
        rm -f "$ISO_PATH" "$SHA_PATH"
    fi
else
    log_ok "No existing Lite ISO at ${ISO_PATH}"
fi

# ============================================================
log_step "Step 4: Run automated tests"
# ============================================================

if [ "$SKIP_TESTS" = "true" ]; then
    log_warn "Skipping automated tests (--skip-tests)"
else
    echo ""
    TEST_PASS=0
    TEST_FAIL=0
    TEST_SUITES=0
    FAILED_SUITES=""

    for test in "${PROJECT_ROOT}"/tests/test-*.sh; do
        [ -f "$test" ] || continue
        TEST_SUITES=$((TEST_SUITES+1))
        SUITE_NAME=$(basename "$test")
        echo -n "  Running ${SUITE_NAME}... "
        RESULT=$(bash "$test" 2>&1)
        PASS=$(echo "$RESULT" | grep -oP '\d+(?= passed)' | tail -1 || echo 0)
        FAIL=$(echo "$RESULT" | grep -oP '\d+(?= failed)' | tail -1 || echo 0)
        if [ "$FAIL" -gt 0 ]; then
            echo -e "${RED}${FAIL} FAILED${NC}"
            echo "$RESULT" | grep "FAIL" | sed 's/^/    /'
            TEST_FAIL=$((TEST_FAIL+FAIL))
            FAILED_SUITES="$FAILED_SUITES $SUITE_NAME"
        else
            echo -e "${GREEN}${PASS} passed${NC}"
        fi
        TEST_PASS=$((TEST_PASS+PASS))
    done

    echo ""
    if [ "$TEST_FAIL" -gt 0 ]; then
        log_error "${TEST_FAIL} test(s) failed in:${FAILED_SUITES}"
        if [ "$FORCE" != "true" ]; then
            log_error "Fix failing tests before building, or use --force to bypass."
            exit 1
        else
            log_warn "Continuing despite test failures (--force)"
        fi
    else
        log_ok "All ${TEST_PASS} tests passed across ${TEST_SUITES} suites"
    fi
fi

# ============================================================
log_step "Step 5: Build Lite edition"
# ============================================================

mkdir -p "$BUILD_DIR"

echo ""
log_info "Building Bright OS Lite ${VERSION}..."
log_info "Build log: ${BUILD_LOG}"
log_info "This typically takes 30-90 minutes depending on network speed and hardware."
echo ""

# Clean stale build state if any (but preserve old ISO)
log_info "Cleaning stale build artifacts..."
"${BUILD_SCRIPT}" --clean "$EDITION" >> "$BUILD_LOG" 2>&1 || true

# Run the actual build
BUILD_EXIT=0
set +e
"${BUILD_SCRIPT}" "$EDITION" --version "$VERSION" 2>&1 | tee "$BUILD_LOG"
BUILD_EXIT=${PIPESTATUS[0]}
set -e

BUILD_END=$(date +%s)
BUILD_ELAPSED=$((BUILD_END - BUILD_START))
BUILD_MIN=$((BUILD_ELAPSED / 60))
BUILD_SEC=$((BUILD_ELAPSED % 60))

echo ""
if [ "$BUILD_EXIT" -ne 0 ]; then
    log_error "Build FAILED with exit code ${BUILD_EXIT} after ${BUILD_MIN}m ${BUILD_SEC}s"
    log_error "Build log preserved at: ${BUILD_LOG}"
    log_error "Last 30 lines of build log:"
    echo ""
    tail -30 "$BUILD_LOG" >&2
    echo ""
    exit 1
fi

log_ok "Build completed in ${BUILD_MIN}m ${BUILD_SEC}s"

# ============================================================
log_step "Step 6: Verify ISO exists"
# ============================================================

if [ ! -f "$ISO_PATH" ]; then
    log_error "Build reported success but ISO not found at: ${ISO_PATH}"
    log_error "Check ${BUILD_DIR} for ISO files."
    ls -la "$BUILD_DIR"/*.iso 2>/dev/null >&2 || true
    exit 1
fi

ISO_SIZE=$(du -h "$ISO_PATH" | cut -f1)
ISO_SIZE_BYTES=$(stat -c%s "$ISO_PATH" 2>/dev/null || echo 0)
ISO_SIZE_MB=$((ISO_SIZE_BYTES / 1024 / 1024))

if [ "$ISO_SIZE_BYTES" -lt 100000000 ]; then
    log_error "ISO is suspiciously small: ${ISO_SIZE_MB} MB (expected > 100 MB)"
    exit 1
fi

log_ok "ISO produced: ${ISO_PATH}"
log_ok "Size: ${ISO_SIZE} (${ISO_SIZE_MB} MB)"

# ============================================================
log_step "Step 7: Run ISO validation"
# ============================================================

echo ""
if [ -x "$VALIDATE_SCRIPT" ]; then
    VALIDATE_EXIT=0
    set +e
    "$VALIDATE_SCRIPT" "$ISO_PATH" 2>&1 | tee -a "$BUILD_LOG"
    VALIDATE_EXIT=${PIPESTATUS[0]}
    set -e
    echo ""
    if [ "$VALIDATE_EXIT" -eq 0 ]; then
        log_ok "ISO validation PASSED"
    elif [ "$VALIDATE_EXIT" -eq 2 ]; then
        log_warn "ISO validation was INCONCLUSIVE (some tools missing)"
        log_warn "Install genisoimage, xorriso, and file for complete validation."
    else
        log_error "ISO validation FAILED (exit code ${VALIDATE_EXIT})"
        exit 1
    fi
else
    log_warn "validate-iso.sh not found; skipping validation"
fi

# ============================================================
log_step "Step 8: Verify SHA256 checksum"
# ============================================================

if [ -f "$SHA_PATH" ]; then
    echo ""
    if (cd "$BUILD_DIR" && sha256sum -c "$(basename "$SHA_PATH")"); then
        log_ok "SHA256 checksum verified"
    else
        log_error "SHA256 checksum mismatch!"
        exit 1
    fi
    SHA256=$(cut -d' ' -f1 "$SHA_PATH")
else
    log_warn "SHA256 file not found; generating now"
    (cd "$BUILD_DIR" && sha256sum "$(basename "$ISO_PATH")" > "$(basename "$ISO_NAME").sha256")
    SHA256=$(cut -d' ' -f1 "$SHA_PATH")
    log_ok "SHA256 generated: ${SHA256}"
fi

# ============================================================
log_step "Step 9: Record build metadata"
# ============================================================

METADATA="${BUILD_DIR}/BUILD-INFO.txt"
cat > "$METADATA" <<EOF
============================================================
Bright OS Build Information
============================================================
Edition:      ${EDITION}
Version:      ${VERSION}
Build date:   $(date -u +"%Y-%m-%d %H:%M:%S UTC")
Build host:   $(hostname 2>/dev/null || echo "unknown")
Kernel:       $(uname -r 2>/dev/null || echo "unknown")
Build time:   ${BUILD_MIN}m ${BUILD_SEC}s

ISO file:     ${ISO_PATH}
Size:         ${ISO_SIZE} (${ISO_SIZE_BYTES} bytes)
SHA256:       ${SHA256}

Git branch:   $(git -C "$PROJECT_ROOT" rev-parse --abbrev-ref HEAD 2>/dev/null || echo "unknown")
Git commit:   $(git -C "$PROJECT_ROOT" rev-parse HEAD 2>/dev/null || echo "unknown")
============================================================
EOF

log_ok "Build metadata saved to: ${METADATA}"

# ============================================================
# Final Report
# ============================================================

echo ""
echo "============================================================"
echo -e "  ${GREEN}${BOLD}FIRST ISO BUILD SUCCESSFUL${NC}"
echo "============================================================"
echo ""
echo "  Edition:     Bright OS ${EDITION^}"
echo "  Version:     ${VERSION}"
echo "  ISO:         ${ISO_PATH}"
echo "  Size:        ${ISO_SIZE} (${ISO_SIZE_MB} MB)"
echo "  SHA256:      ${SHA256}"
echo "  Build time:  ${BUILD_MIN}m ${BUILD_SEC}s"
echo "  Log:         ${BUILD_LOG}"
echo "  Metadata:    ${METADATA}"
echo ""
echo "  Next steps:"
echo "    1. Test BIOS boot:"
echo "       ${SCRIPT_DIR}/test-in-qemu.sh --bios ${ISO_PATH}"
echo ""
echo "    2. Test UEFI boot:"
echo "       ${SCRIPT_DIR}/test-in-qemu.sh --uefi ${ISO_PATH}"
echo ""
echo "    3. Test installation (20 GB virtual disk):"
echo "       ${SCRIPT_DIR}/test-in-qemu.sh --disk 20 -m 4096 ${ISO_PATH}"
echo ""
echo "    4. Write to USB:"
echo "       sudo dd if=${ISO_PATH} of=/dev/sdX bs=4M status=progress conv=fsync"
echo ""
echo "============================================================"
exit 0
