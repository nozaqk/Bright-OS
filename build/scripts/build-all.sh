#!/bin/bash
# =============================================================================
# Bright OS Build All Editions
# =============================================================================
# Builds all three Bright OS editions (Home, Developer, Lite) sequentially.
#
# Usage:
#   ./build/scripts/build-all.sh                     # Build all with default version
#   ./build/scripts/build-all.sh --version 0.1.0     # Set version string
#   ./build/scripts/build-all.sh --verbose           # Verbose output for all builds
#
# Output ISOs are saved to build/output/<edition>/
#
# Each edition builds in its own directory. A failure in one edition does not
# prevent other editions from building (but the script exits non-zero at the end
# if any edition failed).
# =============================================================================

set -u

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "${SCRIPT_DIR}/../.." && pwd)"
BUILD_SCRIPT="${SCRIPT_DIR}/build.sh"

RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m'

# Build order: Lite first (smallest, fastest to catch build errors early), then Home, then Developer
EDITIONS="lite home developer"
VERSION="0.1.0-alpha"
VERBOSE=""

# Parse arguments
while [[ $# -gt 0 ]]; do
    case "$1" in
        -h|--help)
            cat <<EOF
Bright OS Build All Editions

Usage: $0 [OPTIONS]

Options:
  -h, --help           Show this help
  -v, --version VER    Version string (default: ${VERSION})
  --verbose            Verbose build output
EOF
            exit 0
            ;;
        -v|--version)
            if [ $# -lt 2 ]; then echo "ERROR: --version requires argument"; exit 1; fi
            VERSION="$2"; shift 2 ;;
        --verbose)
            VERBOSE="--verbose"; shift ;;
        *)
            echo "ERROR: Unknown argument: $1"; exit 1 ;;
    esac
done

echo "========================================"
echo "  Bright OS - Build All Editions"
echo "  Version:  $VERSION"
echo "  Editions: $EDITIONS"
echo "========================================"
echo ""

if [ ! -x "$BUILD_SCRIPT" ]; then
    echo "ERROR: Build script not found or not executable: $BUILD_SCRIPT"
    exit 1
fi

SUCCESS_COUNT=0
FAIL_COUNT=0
FAILED_EDITIONS=""
BUILD_START=$(date +%s)

for edition in $EDITIONS; do
    echo ""
    echo "========================================"
    echo "  Building: ${edition}"
    echo "========================================"
    echo ""

    set +e
    "$BUILD_SCRIPT" "$edition" --version "$VERSION" $VERBOSE
    RC=$?
    set -e

    if [ $RC -eq 0 ]; then
        echo ""
        echo -e "${GREEN}[SUCCESS]${NC} ${edition} built and validated successfully"
        SUCCESS_COUNT=$((SUCCESS_COUNT+1))
    else
        echo ""
        echo -e "${RED}[FAILURE]${NC} ${edition} build or validation failed (exit code ${RC})"
        FAIL_COUNT=$((FAIL_COUNT+1))
        FAILED_EDITIONS="${FAILED_EDITIONS} ${edition}"
    fi
done

BUILD_END=$(date +%s)
ELAPSED=$((BUILD_END - BUILD_START))
ELAPSED_MIN=$((ELAPSED / 60))
ELAPSED_SEC=$((ELAPSED % 60))

echo ""
echo "========================================"
echo "  Build All Complete"
echo "  Duration: ${ELAPSED_MIN}m ${ELAPSED_SEC}s"
echo "  Successful: ${SUCCESS_COUNT}/3"
echo "  Failed:     ${FAIL_COUNT}/3"
echo "========================================"

if [ "$FAIL_COUNT" -gt 0 ]; then
    echo ""
    echo -e "${RED}The following editions failed:${FAILED_EDITIONS}${NC}"
    echo "Check the build logs in build/output/<edition>/build.log"
    exit 1
fi

echo ""
echo -e "${GREEN}All editions built successfully!${NC}"
echo ""
echo "Output ISOs:"
for edition in $EDITIONS; do
    ISO_PATH="${PROJECT_ROOT}/build/output/${edition}/bright-os-${VERSION}-${edition}-amd64.iso"
    if [ -f "$ISO_PATH" ]; then
        SIZE=$(du -h "$ISO_PATH" | cut -f1)
        echo "  ${edition}: ${ISO_PATH} (${SIZE})"
    fi
done
echo ""
echo "Each edition was automatically validated during build."
echo "To re-validate an ISO manually:"
for edition in $EDITIONS; do
    echo "  ${SCRIPT_DIR}/validate-iso.sh build/output/${edition}/bright-os-${VERSION}-${edition}-amd64.iso"
done
echo ""
echo "To publish a release (validates all ISOs again before publishing):"
echo "  ${SCRIPT_DIR}/publish-release.sh ${VERSION}"
echo ""
