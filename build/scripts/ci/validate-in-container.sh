#!/bin/bash
# =============================================================================
# CI helper: Validate a Bright OS ISO inside a Debian Trixie Docker container
#
# Usage: validate-in-container.sh <edition> <version> <arch>
#
# Runs validate-iso.sh and checksum verification with proper tools available.
# =============================================================================

set -euo pipefail

EDITION="${1:?Usage: $0 <edition> <version> <arch>}"
VERSION="${2:?Usage: $0 <edition> <version> <arch>}"
ARCH="${3:?Usage: $0 <edition> <version> <arch>}"

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "${SCRIPT_DIR}/../../.." && pwd)"
cd "$PROJECT_ROOT"

ISO_NAME="bright-os-${VERSION}-${EDITION}-${ARCH}.iso"
ISO_PATH="${PROJECT_ROOT}/build/output/${EDITION}/${ISO_NAME}"

echo "=== Validating ISO: ${ISO_PATH} ==="
echo ""

# 1. File existence and size
if [ ! -f "${ISO_PATH}" ]; then
    echo "ERROR: ISO not found at ${ISO_PATH}"
    exit 1
fi
if [ ! -s "${ISO_PATH}" ]; then
    echo "ERROR: ISO file is empty"
    exit 1
fi

ISO_SIZE=$(stat -c%s "${ISO_PATH}")
ISO_SIZE_MB=$((ISO_SIZE / 1024 / 1024))
echo "ISO size: ${ISO_SIZE_MB} MB (${ISO_SIZE} bytes)"

if [ "${ISO_SIZE_MB}" -lt 100 ]; then
    echo "ERROR: ISO is too small (${ISO_SIZE_MB} MB < 100 MB minimum)"
    exit 1
fi

# 2. GitHub Release asset size limit is 2 GiB
GITHUB_LIMIT_BYTES=2147483648
if [ "${ISO_SIZE}" -gt "${GITHUB_LIMIT_BYTES}" ]; then
    echo "ERROR: ISO size (${ISO_SIZE_MB} MB) exceeds GitHub release asset limit of 2048 MB (2 GiB)"
    echo ""
    echo "The ISO must be reduced in size before it can be uploaded to GitHub Releases."
    exit 1
fi
echo "Size within GitHub limit (2 GiB): OK"

# 3. Run project validation script inside Debian Trixie container
echo ""
echo "--- Running validate-iso.sh inside Debian Trixie container ---"
docker run --rm \
    --privileged \
    -v "${PROJECT_ROOT}":/workspace \
    -w /workspace \
    debian:trixie \
    bash -c "
      set -euo pipefail
      cat > /etc/apt/sources.list << 'APT_SOURCES'
deb http://deb.debian.org/debian trixie main contrib non-free non-free-firmware
deb http://security.debian.org/debian-security trixie-security main contrib non-free non-free-firmware
APT_SOURCES
      apt-get update -qq
      apt-get install -y --no-install-recommends genisoimage xorriso file coreutils sharutils xxd
      bash build/scripts/validate-iso.sh '${ISO_PATH}'
    "

# 4. Verify checksum
echo ""
echo "--- Verifying SHA256 checksum ---"
(cd "$(dirname "${ISO_PATH}")" && sha256sum -c "$(basename "${ISO_PATH}").sha256")
echo "Checksum valid."

# Fix perms again after container access
sudo chmod -R a+rX "$(dirname "${ISO_PATH}")" 2>/dev/null || true

echo ""
echo "============================================================"
echo "  VALIDATION PASSED: ${EDITION} edition"
echo "  ISO:  ${ISO_PATH}"
echo "  Size: ${ISO_SIZE_MB} MB"
echo "============================================================"
