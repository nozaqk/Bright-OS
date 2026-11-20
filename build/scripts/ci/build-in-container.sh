#!/bin/bash
# =============================================================================
# CI helper: Build a Bright OS edition inside a Debian Trixie Docker container
#
# Usage: build-in-container.sh <edition> <version> <arch>
#
# This script is called from the GitHub Actions workflow. It handles:
#   - Docker container setup with all build dependencies
#   - Running build.sh inside the container
#   - Fixing file permissions after build
#
# Designed to avoid nested quoting/escaping issues in YAML.
# =============================================================================

set -euo pipefail

EDITION="${1:?Usage: $0 <edition> <version> <arch>}"
VERSION="${2:?Usage: $0 <edition> <version> <arch>}"
ARCH="${3:?Usage: $0 <edition> <version> <arch>}"

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "${SCRIPT_DIR}/../../.." && pwd)"
cd "$PROJECT_ROOT"

ISO_NAME="bright-os-${VERSION}-${EDITION}-${ARCH}.iso"
BUILD_DIR="build/output/${EDITION}"

echo "============================================================"
echo "  CI Build: Bright OS ${VERSION} - ${EDITION} edition"
echo "  Architecture: ${ARCH}"
echo "  Container:    debian:trixie (privileged for chroot/mount)"
echo "  Expected ISO: ${ISO_NAME}"
echo "  Project root: ${PROJECT_ROOT}"
echo "============================================================"
echo ""

# Print diagnostic info
echo "--- Runner diagnostics ---"
echo "Docker version: $(docker --version)"
echo "Debian version (host): $(cat /etc/os-release 2>/dev/null | head -2 || echo 'unknown')"
echo "Available disk space:"
df -h "$PROJECT_ROOT" | tail -1
echo ""

# Pull the latest Debian Trixie image
echo "--- Pulling Debian Trixie image ---"
docker pull debian:trixie
echo ""

# Create a temporary build script to run inside the container
# This avoids nested quoting issues
CONTAINER_SCRIPT=$(mktemp /tmp/bright-ci-build-XXXXXX.sh)
trap 'rm -f "$CONTAINER_SCRIPT"' EXIT

cat > "$CONTAINER_SCRIPT" << 'CONTAINER_EOF'
#!/bin/bash
set -euo pipefail

echo "--- [Container] Setting up APT sources ---"
cat > /etc/apt/sources.list << 'APT_SOURCES'
deb http://deb.debian.org/debian trixie main contrib non-free non-free-firmware
deb http://deb.debian.org/debian trixie-updates main contrib non-free non-free-firmware
deb http://security.debian.org/debian-security trixie-security main contrib non-free non-free-firmware
APT_SOURCES

echo "--- [Container] Updating package lists ---"
apt-get update -qq

echo "--- [Container] Installing build dependencies ---"
apt-get install -y --no-install-recommends \
    eatmydata \
    live-build \
    debootstrap \
    squashfs-tools \
    xorriso \
    isolinux \
    syslinux-common \
    syslinux-efi \
    grub-pc-bin \
    grub-efi-amd64-bin \
    grub-efi-amd64-signed \
    shim-signed \
    mtools \
    dosfstools \
    genisoimage \
    cpio \
    gzip \
    xz-utils \
    bzip2 \
    coreutils \
    util-linux \
    mount \
    udev \
    binutils \
    findutils \
    sed \
    gawk \
    grep \
    tar \
    wget \
    ca-certificates \
    file \
    dpkg-dev

echo "--- [Container] Installed dependency versions ---"
echo "live-build: $(dpkg-query -W -f='${Version}' live-build 2>/dev/null || echo 'unknown')"
echo "debootstrap: $(dpkg-query -W -f='${Version}' debootstrap 2>/dev/null || echo 'unknown')"
echo "grub-pc-bin: $(dpkg-query -W -f='${Version}' grub-pc-bin 2>/dev/null || echo 'unknown')"
echo "grub-efi-amd64-bin: $(dpkg-query -W -f='${Version}' grub-efi-amd64-bin 2>/dev/null || echo 'unknown')"
echo "xorriso: $(dpkg-query -W -f='${Version}' xorriso 2>/dev/null || echo 'unknown')"

echo "--- [Container] Checking disk space ---"
df -h /workspace

echo "--- [Container] Running build ---"
export BRIGHT_EDITION EDITION VERSION ARCH
cd /workspace
eatmydata bash build/scripts/build.sh "${EDITION}" --version "${VERSION}" --verbose
echo "--- [Container] Build script finished ---"
CONTAINER_EOF

chmod +x "$CONTAINER_SCRIPT"

echo "--- Running build in Docker container ---"
echo "Container script:"
cat "$CONTAINER_SCRIPT"
echo ""

docker run --rm \
    --privileged \
    -v "$PROJECT_ROOT":/workspace \
    -v "$CONTAINER_SCRIPT":/tmp/ci-build.sh:ro \
    -w /workspace \
    -e "BRIGHT_EDITION=${EDITION}" \
    -e "EDITION=${EDITION}" \
    -e "BRIGHT_VERSION=${VERSION}" \
    -e "VERSION=${VERSION}" \
    -e "BRIGHT_ARCH=${ARCH}" \
    -e "ARCH=${ARCH}" \
    -e "DEBIAN_FRONTEND=noninteractive" \
    -e "LC_ALL=C" \
    debian:trixie \
    bash /tmp/ci-build.sh

echo ""
echo "=== Build container exited successfully ==="

# Make output files readable by the runner user (owned by root from Docker)
echo "--- Fixing file permissions ---"
sudo chmod -R a+rX "${BUILD_DIR}" 2>/dev/null || true
if command -v sudo &>/dev/null; then
    sudo chown -R "$(id -u):$(id -g)" "${BUILD_DIR}" 2>/dev/null || true
fi

echo ""
echo "--- Build output directory ---"
ls -la "${BUILD_DIR}/"

if [ ! -f "${BUILD_DIR}/${ISO_NAME}" ]; then
    echo "ERROR: Expected ISO not found at ${BUILD_DIR}/${ISO_NAME}"
    echo "Contents of ${BUILD_DIR}:"
    ls -la "${BUILD_DIR}/"
    exit 1
fi

echo ""
echo "ISO found: ${BUILD_DIR}/${ISO_NAME}"
stat "${BUILD_DIR}/${ISO_NAME}"

ISO_SIZE=$(stat -c%s "${BUILD_DIR}/${ISO_NAME}")
ISO_SIZE_MB=$((ISO_SIZE / 1024 / 1024))
echo "ISO size: ${ISO_SIZE_MB} MB (${ISO_SIZE} bytes)"
echo ""
echo "=== BUILD STEP COMPLETE ==="
