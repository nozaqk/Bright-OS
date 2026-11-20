#!/bin/bash
# =============================================================================
# Bright OS ISO Build Script
# =============================================================================
# Builds a bootable Bright OS ISO using Debian live-build.
#
# Usage:
#   ./build.sh [OPTIONS] [EDITION]
#
# Editions: home (default), developer, lite
# =============================================================================

# Do NOT use -o pipefail globally; we need careful pipefail control around
# the build pipeline to reliably capture ./auto/build exit status through tee.
set -eu

# Determine script location and project root
# Script is at: <root>/build/scripts/build.sh
# So PROJECT_ROOT is two levels up from the script directory.
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "${SCRIPT_DIR}/../.." && pwd)"
LIVE_BUILD_DIR="${PROJECT_ROOT}/build/live-build"
CONFIG_DIR="${PROJECT_ROOT}/config"
EDITIONS_DIR="${PROJECT_ROOT}/editions"

# Validate that PROJECT_ROOT looks correct
if [ ! -f "${PROJECT_ROOT}/README.md" ] || [ ! -d "${CONFIG_DIR}" ]; then
    echo "[ERROR] PROJECT_ROOT calculation failed."
    echo "  SCRIPT_DIR=${SCRIPT_DIR}"
    echo "  PROJECT_ROOT=${PROJECT_ROOT}"
    echo "  Could not find README.md or config/ at project root."
    exit 1
fi

# Defaults
EDITION=""
ARCH="amd64"
VERSION="0.1.0-alpha"
SKIP_BUILD=false
CLEAN_ONLY=false
VERBOSE=false
DEBIAN_CODENAME="${BRIGHT_DEBIAN_CODENAME:-trixie}"
EDITION_SET=false

# Valid values
VALID_EDITIONS="home developer lite"
VALID_ARCHS="amd64"
VALID_CODENAMES="bookworm trixie forky"
REQUIRED_DISK_GB=20
VERSION_PATTERN='^[a-zA-Z0-9][a-zA-Z0-9._-]*$'

# Color output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m'

log_info()  { echo -e "${BLUE}[INFO]${NC} $*"; }
log_ok()    { echo -e "${GREEN}[OK]${NC} $*"; }
log_warn()  { echo -e "${YELLOW}[WARN]${NC} $*"; }
log_error() { echo -e "${RED}[ERROR]${NC} $*" >&2; }

usage() {
    local ec="${1:-0}"
    cat <<EOF
Bright OS Build Script

Usage: $0 [OPTIONS] [EDITION]

Editions:
  home        Bright OS Home edition (default)
  developer   Bright OS Developer edition
  lite        Bright OS Lite edition

Options:
  -h, --help            Show this help message
  -v, --version VER     Set version string (default: ${VERSION})
  -a, --arch ARCH       Set architecture (default: ${ARCH})
  -d, --distro CODENAME Debian codename (default: ${DEBIAN_CODENAME})
  --clean               Clean build directory only (no build deps needed)
  --skip-build          Configure only, do not build
  --verbose             Verbose build output
EOF
    exit "$ec"
}

# Parse arguments
while [[ $# -gt 0 ]]; do
    case "$1" in
        home|developer|lite)
            if [ "$EDITION_SET" = true ]; then
                log_error "Duplicate edition: '$1' conflicts with previously set edition '${EDITION}'"
                exit 1
            fi
            EDITION="$1"
            EDITION_SET=true
            shift
            ;;
        -h|--help)
            usage 0
            ;;
        -v|--version)
            if [ $# -lt 2 ]; then
                log_error "--version requires an argument"
                exit 1
            fi
            VERSION="$2"
            shift 2
            ;;
        -a|--arch)
            if [ $# -lt 2 ]; then
                log_error "--arch requires an argument"
                exit 1
            fi
            ARCH="$2"
            shift 2
            ;;
        -d|--distro)
            if [ $# -lt 2 ]; then
                log_error "--distro requires an argument"
                exit 1
            fi
            DEBIAN_CODENAME="$2"
            shift 2
            ;;
        --clean)
            CLEAN_ONLY=true
            shift
            ;;
        --skip-build)
            SKIP_BUILD=true
            shift
            ;;
        --verbose)
            VERBOSE=true
            shift
            ;;
        --*)
            log_error "Unknown option: $1"
            usage 1
            ;;
        -*)
            log_error "Unknown short option: $1"
            usage 1
            ;;
        *)
            log_error "Unknown argument: $1"
            usage 1
            ;;
    esac
done

# Default edition if none specified
if [ -z "$EDITION" ]; then
    EDITION="home"
fi

# Validate edition
case " ${VALID_EDITIONS} " in
    *" ${EDITION} "*) ;;
    *) log_error "Invalid edition '${EDITION}'. Valid: ${VALID_EDITIONS}"; exit 1 ;;
esac

# Validate architecture
case " ${VALID_ARCHS} " in
    *" ${ARCH} "*) ;;
    *) log_error "Invalid architecture '${ARCH}'. Valid for Alpha 0.1: ${VALID_ARCHS}"; exit 1 ;;
esac

# Validate codename
case " ${VALID_CODENAMES} " in
    *" ${DEBIAN_CODENAME} "*) ;;
    *) log_error "Invalid Debian codename '${DEBIAN_CODENAME}'. Valid: ${VALID_CODENAMES}"; exit 1 ;;
esac

# Validate version string (safe for filenames)
if ! echo "$VERSION" | grep -qE "$VERSION_PATTERN"; then
    log_error "Invalid version string '${VERSION}'. Use only letters, digits, dots, hyphens, underscores."
    exit 1
fi

log_info "========================================"
log_info "  Bright OS Build System"
log_info "  Edition:    ${EDITION}"
log_info "  Version:    ${VERSION}"
log_info "  Arch:       ${ARCH}"
log_info "  Distro:     Debian ${DEBIAN_CODENAME}"
log_info "  Project:    ${PROJECT_ROOT}"
log_info "========================================"

# --- Set up build directory (needed early for clean) ---
BUILD_DIR="${PROJECT_ROOT}/build/output/${EDITION}"

# Safety: ensure BUILD_DIR is inside PROJECT_ROOT/build/output/
case "$BUILD_DIR" in
    "${PROJECT_ROOT}/build/output/"*) ;;  # Safe
    *)
        log_error "BUILD_DIR (${BUILD_DIR}) is outside project build output directory."
        exit 1 ;;
esac

# Create the build directory
mkdir -p "$BUILD_DIR"

# --- CLEAN MODE: minimal checks, no dependencies needed ---
if [ "$CLEAN_ONLY" = true ]; then
    log_info "Cleaning build directory: ${BUILD_DIR}"
    cd "$BUILD_DIR"
    # Only clean known build artifacts, not ISO outputs
    if command -v lb &>/dev/null; then
        lb clean --purge 2>/dev/null || true
    fi
    # Remove build artifacts (not .iso or .sha256)
    rm -rf -- config/ local/ .build/ chroot/ binary/ cache/
    # Clean auto scripts copied from our setup
    rm -rf -- auto/
    # Clean build log
    rm -f -- build.log
    log_ok "Clean complete (ISO files preserved)"
    exit 0
fi

# --- Check build dependencies (only for actual build/configure) ---
check_dependencies() {
    log_info "Checking build dependencies..."
    local missing=()
    local deps="lb debootstrap mksquashfs xorriso"
    for dep in $deps; do
        if ! command -v "$dep" &>/dev/null; then
            missing+=("$dep")
        fi
    done

    local boot_missing=()
    for pkg in isolinux mtools dosfstools; do
        if ! dpkg-query -W -f='${Status}' "$pkg" 2>/dev/null | grep -q "install ok installed"; then
            boot_missing+=("$pkg")
        fi
    done
    # grub packages differ by arch; for amd64 we need both BIOS and EFI
    if [ "$ARCH" = "amd64" ]; then
        for pkg in grub-pc-bin grub-efi-amd64-bin; do
            if ! dpkg-query -W -f='${Status}' "$pkg" 2>/dev/null | grep -q "install ok installed"; then
                boot_missing+=("$pkg")
            fi
        done
    fi

    if [ ${#missing[@]} -gt 0 ] || [ ${#boot_missing[@]} -gt 0 ]; then
        local all_missing=("${missing[@]}" "${boot_missing[@]}")
        log_error "Missing dependencies: ${all_missing[*]}"
        log_info ""
        log_info "Install all dependencies with:"
        log_info "  sudo apt-get install -y live-build debootstrap squashfs-tools xorriso \\"
        log_info "    isolinux syslinux-common mtools dosfstools \\"
        log_info "    grub-pc-bin grub-efi-amd64-bin"
        exit 1
    fi
    log_ok "All required build tools found"
}

check_dependencies

# --- Check required source files ---
check_source_files() {
    log_info "Checking source files..."
    local required_files=(
        "${LIVE_BUILD_DIR}/auto/config"
        "${LIVE_BUILD_DIR}/auto/build"
        "${LIVE_BUILD_DIR}/auto/clean"
        "${CONFIG_DIR}/package-lists/core.list.chroot"
        "${CONFIG_DIR}/package-lists/desktop.list.chroot"
        "${CONFIG_DIR}/hooks/live/00-bright-os-branding.hook.chroot"
        "${CONFIG_DIR}/hooks/live/10-bright-os-components.hook.chroot"
        "${CONFIG_DIR}/includes.binary/boot/grub/grub.cfg"
        "${CONFIG_DIR}/includes.chroot/etc/bright-os/edition"
        "${CONFIG_DIR}/includes.chroot/usr/bin/bright-desktop-shell"
        "${CONFIG_DIR}/includes.chroot/usr/share/bright-os/Shell.qml"
        "${CONFIG_DIR}/includes.chroot/usr/share/bright-os/bright-desktop-shell.py"
        "${EDITIONS_DIR}/${EDITION}/packages.list"
    )
    local missing=0
    for f in "${required_files[@]}"; do
        if [ ! -f "$f" ]; then
            log_error "Missing required file: $f"
            missing=$((missing+1))
        fi
    done
    if [ $missing -gt 0 ]; then
        log_error "${missing} required source file(s) missing. Cannot continue."
        exit 1
    fi
    log_ok "All required source files present"
}

check_source_files

# --- Check disk space ---
AVAIL_KB=$(df --output=avail "${PROJECT_ROOT}" | tail -1 | tr -d ' ')
AVAIL_GB=$((AVAIL_KB / 1024 / 1024))
if [ "$AVAIL_GB" -lt "$REQUIRED_DISK_GB" ]; then
    log_error "Insufficient disk space: ${AVAIL_GB} GB available, ${REQUIRED_DISK_GB} GB required."
    exit 1
fi
log_ok "Disk space: ${AVAIL_GB} GB available (${REQUIRED_DISK_GB} GB required)"

# --- Enter build directory ---
cd "$BUILD_DIR"

# --- Copy live-build auto scripts ---
log_info "Setting up live-build configuration..."
rm -rf auto
mkdir -p auto
shopt -s nullglob
auto_copied=0
for f in "${LIVE_BUILD_DIR}/auto/"*; do
    cp "$f" "auto/"
    chmod +x "auto/$(basename "$f")"
    auto_copied=$((auto_copied+1))
done
shopt -u nullglob

if [ $auto_copied -eq 0 ]; then
    log_error "No auto scripts found in ${LIVE_BUILD_DIR}/auto/"
    exit 1
fi
if [ ! -x auto/config ] || [ ! -x auto/build ]; then
    log_error "Failed to copy auto/config or auto/build"
    exit 1
fi

# --- Copy config tree ---
rm -rf config
cp -r "${CONFIG_DIR}" ./config

# --- Select desktop environment package list ---
# Home and Developer use full KDE Plasma; Lite uses lightweight LXQt/Openbox
DESKTOP_PKGS="${CONFIG_DIR}/package-lists/desktop.list.chroot"
if [ "${EDITION}" = "lite" ]; then
    DESKTOP_PKGS="${CONFIG_DIR}/package-lists/desktop-lite.list.chroot"
fi
if [ ! -f "${DESKTOP_PKGS}" ]; then
    log_error "Desktop package list not found: ${DESKTOP_PKGS}"
    exit 1
fi
cp "${DESKTOP_PKGS}" "config/package-lists/desktop-packages.list.chroot"
log_info "Desktop packages: $(basename "${DESKTOP_PKGS}")"

# --- Write edition marker ---
mkdir -p config/includes.chroot/etc/bright-os
echo "${EDITION}" > "config/includes.chroot/etc/bright-os/edition"

# --- Copy edition-specific package list ---
EDITION_PKGS="${EDITIONS_DIR}/${EDITION}/packages.list"
if [ -f "${EDITION_PKGS}" ]; then
    cp "${EDITION_PKGS}" "config/package-lists/edition-packages.list.chroot"
    log_info "Edition packages: ${EDITION_PKGS}"
else
    log_error "Edition package list missing: ${EDITION_PKGS}"
    exit 1
fi

# --- Copy edition-specific hooks if present ---
EDITION_HOOKS_DIR="${EDITIONS_DIR}/${EDITION}/hooks"
if [ -d "${EDITION_HOOKS_DIR}" ]; then
    shopt -s nullglob
    hook_count=0
    for h in "${EDITION_HOOKS_DIR}/"*; do
        [ -f "$h" ] || continue
        cp "$h" config/hooks/live/
        chmod +x "config/hooks/live/$(basename "$h")"
        hook_count=$((hook_count+1))
    done
    shopt -u nullglob
    if [ $hook_count -gt 0 ]; then
        log_info "Copied ${hook_count} edition-specific hook(s)"
    fi
fi

# --- Apply Lite edition specific configuration ---
if [ "${EDITION}" = "lite" ]; then
    mkdir -p config/includes.chroot/etc/systemd/system
    # Mask heavy services not needed in Lite
    for svc in bluetooth.service cups.service ModemManager.service; do
        ln -sf /dev/null "config/includes.chroot/etc/systemd/system/${svc}" 2>/dev/null || true
    done
    log_info "Lite edition: masking bluetooth, cups, ModemManager"
fi

# --- Export environment for auto/config ---
export BRIGHT_EDITION="$EDITION"
export BRIGHT_ARCH="$ARCH"
export BRIGHT_VERSION="$VERSION"
export BRIGHT_DEBIAN_CODENAME="$DEBIAN_CODENAME"

# --- Run auto/config ---
log_info "Configuring live-build for Debian ${DEBIAN_CODENAME}..."
set +e
./auto/config
CONFIG_STATUS=$?
set -e
if [ $CONFIG_STATUS -ne 0 ]; then
    log_error "live-build configuration failed (exit code ${CONFIG_STATUS})"
    exit $CONFIG_STATUS
fi
log_ok "live-build configuration complete"

if [ "$SKIP_BUILD" = true ]; then
    log_ok "Configuration complete. Skipping build (--skip-build)."
    log_info "Build directory: ${BUILD_DIR}"
    exit 0
fi

# =========================================================================
# BUILD PIPELINE — with reliable exit status capture
# =========================================================================
#
# Method: Run the pipeline, then capture PIPESTATUS[0] IMMEDIATELY into an
# array BEFORE any other command runs. This gives the exact exit code of
# ./auto/build regardless of what tee or grep do.
#
# Key rules:
#  - Do NOT use set -o pipefail (grep returning 1 for "no match" must not kill
#    the pipeline or be treated as a build failure)
#  - Do NOT use || true after the pipeline (it destroys PIPESTATUS)
#  - Capture PIPESTATUS into an array as the VERY NEXT command after the pipeline
#  - grep's exit code (0=match, 1=no match) is ignored — only build exit matters
# =========================================================================

log_info "Starting ISO build (this will take 30-90 minutes)..."
BUILD_LOG="build.log"
rm -f "$BUILD_LOG"

# Disable pipefail and set -e for the pipeline section so we can capture
# exit codes precisely.
set +e
set +o pipefail

if [ "$VERBOSE" = true ]; then
    # Verbose mode: show all build output on screen
    ./auto/build 2>&1 | tee "$BUILD_LOG"
    _pipestatus=(${PIPESTATUS[@]})
    BUILD_STATUS=${_pipestatus[0]}
else
    # Normal mode: full output saved to build.log; key progress lines on screen
    # grep returns 0 on match, 1 on no match — both are fine; only BUILD_STATUS matters
    ./auto/build 2>&1 | tee "$BUILD_LOG" | grep -E --line-buffered \
        '^P:|^E:|^I:|^W:|BUILD SUCCESS|BUILD FAILED|mksquashfs|genisoimage|xorriso|^\[|=====|lb build|Building|building|^Setting up|^Created|^Calculating|^Unpacking|^dpkg'
    _pipestatus=(${PIPESTATUS[@]})
    BUILD_STATUS=${_pipestatus[0]}
fi

# Restore strict mode immediately after capturing status
set -e
set -o pipefail

# Validate BUILD_STATUS is a valid integer
if ! [[ "$BUILD_STATUS" =~ ^[0-9]+$ ]]; then
    log_error "Could not determine build exit code (got '${BUILD_STATUS}'); assuming failure"
    BUILD_STATUS=1
fi

if [ "$BUILD_STATUS" -ne 0 ]; then
    log_error "Build failed with exit code ${BUILD_STATUS}!"
    if [ -f "$BUILD_LOG" ]; then
        log_error "Last 30 lines of build.log:"
        tail -30 "$BUILD_LOG" >&2 || true
        log_error ""
        log_error "Full log: ${BUILD_DIR}/${BUILD_LOG}"
    fi
    exit "$BUILD_STATUS"
fi

# --- Locate ISO ---
# Collect ISO candidates, deduplicating (hybrid.iso also matches *.iso)
shopt -s nullglob
ISO_CANDIDATES=()
declare -A _seen_isos
for pattern in live-image-*.hybrid.iso live-image-*.iso; do
    for f in $pattern; do
        if [ -z "${_seen_isos[$f]:-}" ]; then
            ISO_CANDIDATES+=("$f")
            _seen_isos[$f]=1
        fi
    done
done
unset _seen_isos
shopt -u nullglob

ISO_NAME="bright-os-${VERSION}-${EDITION}-${ARCH}.iso"
ISO_PATH="${BUILD_DIR}/${ISO_NAME}"

if [ ${#ISO_CANDIDATES[@]} -eq 0 ]; then
    log_error "Build completed with exit 0 but no ISO image found in ${BUILD_DIR}"
    log_error "This likely means lb build completed but did not produce an ISO."
    log_error "Build directory contents:"
    ls -la >&2 || true
    exit 1
fi

if [ ${#ISO_CANDIDATES[@]} -gt 1 ]; then
    log_error "Ambiguous build output: found ${#ISO_CANDIDATES[@]} ISO files:"
    for c in "${ISO_CANDIDATES[@]}"; do
        log_error "  - $c"
    done
    log_error "Remove old ISOs from the build directory and rebuild."
    exit 1
fi

GENERATED_ISO="${ISO_CANDIDATES[0]}"

# Verify the generated ISO is a real file with non-zero size
if [ ! -s "${GENERATED_ISO}" ]; then
    log_error "Generated ISO ${GENERATED_ISO} is empty or missing"
    exit 1
fi

# Protect against overwriting an existing output ISO
if [ -e "${ISO_NAME}" ]; then
    log_error "Output file ${ISO_NAME} already exists."
    log_error "Remove it manually (e.g. with '${PROJECT_ROOT}/build/scripts/build.sh --clean ${EDITION}')"
    log_error "or use a different version string with --version."
    exit 1
fi

mv "${GENERATED_ISO}" "${ISO_NAME}"

# --- Verify final ISO before generating checksums ---
if [ ! -s "${ISO_NAME}" ]; then
    log_error "ISO rename produced empty file"
    exit 1
fi

# --- Generate checksums ONLY after successful build and rename ---
log_info "Generating SHA256 checksum..."
sha256sum "${ISO_NAME}" > "${ISO_NAME}.sha256"

# --- Report ---
ISO_SIZE=$(du -h "${ISO_NAME}" | cut -f1)
SHA256=$(cut -d' ' -f1 "${ISO_NAME}.sha256")

echo ""
log_ok "========================================"
log_ok "  BUILD SUCCESSFUL"
log_ok "  Edition:   ${EDITION}"
log_ok "  ISO:       ${ISO_PATH}"
log_ok "  Size:      ${ISO_SIZE}"
log_ok "  SHA256:    ${SHA256}"
log_ok "  Log:       ${BUILD_DIR}/${BUILD_LOG}"
log_ok "========================================"
echo ""
log_info "To validate the ISO:"
log_info "  ${PROJECT_ROOT}/build/scripts/validate-iso.sh ${ISO_PATH}"
echo ""
log_info "To test in QEMU:"
log_info "  ${PROJECT_ROOT}/build/scripts/test-in-qemu.sh ${ISO_PATH}"
echo ""
log_info "To write to USB:"
log_info "  sudo dd if=${ISO_PATH} of=/dev/sdX bs=4M status=progress conv=fsync"
echo ""
