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

# Optional-profile flags: "" means "use edition default"; "true" means force enable;
# "false" means force disable.
WITH_BLUETOOTH=""
WITH_PRINTING=""
WITH_NETWORK_EXTRAS=""
WITH_WINE=""
WITH_DEVTOOLS=""
WITH_RECOVERY_KWIN=""
WITH_SECUREBOOT=""
WITH_PLYMOUTH=""
WITH_QEMU=""
WITH_ANDROID=""

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

Edition default features:
  home:      bluetooth, printing, network-extras (VPN/WWAN/mDNS), android
  developer: all home features + devtools, qemu, secureboot, wine
  lite:      none (minimal; user can add any --with-* flag)

Options:
  -h, --help            Show this help message
  -v, --version VER     Set version string (default: ${VERSION})
  -a, --arch ARCH       Set architecture (default: ${ARCH})
  -d, --distro CODENAME Debian codename (default: ${DEBIAN_CODENAME})
  --clean               Clean build directory only (no build deps needed)
  --skip-build          Configure only, do not build
  --verbose             Verbose build output

Optional profiles (override edition defaults):
  --with-bluetooth         Include Bluetooth support (bluez + blueman)
  --without-bluetooth      Exclude Bluetooth
  --with-printing          Include printing (CUPS)
  --without-printing       Exclude printing
  --with-network-extras    Include VPN/WWAN/mDNS (openvpn, ModemManager, avahi)
  --without-network-extras Exclude VPN/WWAN/mDNS
  --with-wine              Include Wine/Proton compatibility
  --without-wine           Exclude Wine
  --with-android           Include Bright Android (Waydroid)
  --without-android        Exclude Bright Android
  --with-devtools          Include developer tools
  --without-devtools       Exclude developer tools
  --with-recovery-kwin     Include KWin + SDDM recovery session
  --without-recovery-kwin  Exclude KWin recovery
  --with-secureboot        Include Secure Boot shim
  --without-secureboot     Exclude Secure Boot shim
  --with-plymouth          Include Plymouth boot splash
  --without-plymouth       Exclude Plymouth
  --with-qemu              Include QEMU/OVMF
  --without-qemu           Exclude QEMU
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
        --with-bluetooth) WITH_BLUETOOTH=true; shift ;;
        --without-bluetooth) WITH_BLUETOOTH=false; shift ;;
        --with-printing) WITH_PRINTING=true; shift ;;
        --without-printing) WITH_PRINTING=false; shift ;;
        --with-network-extras) WITH_NETWORK_EXTRAS=true; shift ;;
        --without-network-extras) WITH_NETWORK_EXTRAS=false; shift ;;
        --with-wine) WITH_WINE=true; shift ;;
        --without-wine) WITH_WINE=false; shift ;;
        --with-android) WITH_ANDROID=true; shift ;;
        --without-android) WITH_ANDROID=false; shift ;;
        --with-devtools) WITH_DEVTOOLS=true; shift ;;
        --without-devtools) WITH_DEVTOOLS=false; shift ;;
        --with-recovery-kwin) WITH_RECOVERY_KWIN=true; shift ;;
        --without-recovery-kwin) WITH_RECOVERY_KWIN=false; shift ;;
        --with-secureboot) WITH_SECUREBOOT=true; shift ;;
        --without-secureboot) WITH_SECUREBOOT=false; shift ;;
        --with-plymouth) WITH_PLYMOUTH=true; shift ;;
        --without-plymouth) WITH_PLYMOUTH=false; shift ;;
        --with-qemu) WITH_QEMU=true; shift ;;
        --without-qemu) WITH_QEMU=false; shift ;;
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

# ---------------------------------------------------------------------------
# Resolve optional-profile flags
# ---------------------------------------------------------------------------
# A flag value of "" means "use edition default"; "true"/"false" are explicit.
# Edition defaults:
#   home:      bluetooth, printing, network-extras, android = true;
#              wine, devtools, recovery-kwin, secureboot, plymouth, qemu = false
#   developer: bluetooth, printing, network-extras, android, devtools,
#              secureboot, qemu, wine = true; recovery-kwin, plymouth = false
#   lite:      all optional features default false (minimal)
resolve_flag() {
    # $1 = current flag value (""/true/false), $2 = edition default (true/false)
    if [ -z "$1" ]; then
        echo "$2"
    else
        echo "$1"
    fi
}
case "$EDITION" in
    home)
        DEF_BLUETOOTH=true; DEF_PRINTING=true; DEF_NETWORK_EXTRAS=true
        DEF_WINE=false; DEF_ANDROID=true; DEF_DEVTOOLS=false
        DEF_RECOVERY_KWIN=false; DEF_SECUREBOOT=false
        DEF_PLYMOUTH=false; DEF_QEMU=false ;;
    developer)
        DEF_BLUETOOTH=true; DEF_PRINTING=true; DEF_NETWORK_EXTRAS=true
        DEF_WINE=true; DEF_ANDROID=true; DEF_DEVTOOLS=true
        DEF_RECOVERY_KWIN=false; DEF_SECUREBOOT=true
        DEF_PLYMOUTH=false; DEF_QEMU=true ;;
    lite)
        DEF_BLUETOOTH=false; DEF_PRINTING=false; DEF_NETWORK_EXTRAS=false
        DEF_WINE=false; DEF_ANDROID=false; DEF_DEVTOOLS=false
        DEF_RECOVERY_KWIN=false; DEF_SECUREBOOT=false
        DEF_PLYMOUTH=false; DEF_QEMU=false ;;
esac

FEAT_BLUETOOTH=$(resolve_flag "$WITH_BLUETOOTH" "$DEF_BLUETOOTH")
FEAT_PRINTING=$(resolve_flag "$WITH_PRINTING" "$DEF_PRINTING")
FEAT_NETWORK_EXTRAS=$(resolve_flag "$WITH_NETWORK_EXTRAS" "$DEF_NETWORK_EXTRAS")
FEAT_WINE=$(resolve_flag "$WITH_WINE" "$DEF_WINE")
FEAT_ANDROID=$(resolve_flag "$WITH_ANDROID" "$DEF_ANDROID")
FEAT_DEVTOOLS=$(resolve_flag "$WITH_DEVTOOLS" "$DEF_DEVTOOLS")
FEAT_RECOVERY_KWIN=$(resolve_flag "$WITH_RECOVERY_KWIN" "$DEF_RECOVERY_KWIN")
FEAT_SECUREBOOT=$(resolve_flag "$WITH_SECUREBOOT" "$DEF_SECUREBOOT")
FEAT_PLYMOUTH=$(resolve_flag "$WITH_PLYMOUTH" "$DEF_PLYMOUTH")
FEAT_QEMU=$(resolve_flag "$WITH_QEMU" "$DEF_QEMU")

log_info "========================================"
log_info "  Bright OS Build System"
log_info "  Edition:    ${EDITION}"
log_info "  Version:    ${VERSION}"
log_info "  Arch:       ${ARCH}"
log_info "  Distro:     Debian ${DEBIAN_CODENAME}"
log_info "  Project:    ${PROJECT_ROOT}"
log_info "----------------------------------------"
log_info "  Optional profiles:"
log_info "    bluetooth:        ${FEAT_BLUETOOTH}"
log_info "    printing:         ${FEAT_PRINTING}"
log_info "    network-extras:   ${FEAT_NETWORK_EXTRAS}"
log_info "    wine:             ${FEAT_WINE}"
log_info "    android:          ${FEAT_ANDROID}"
log_info "    devtools:         ${FEAT_DEVTOOLS}"
log_info "    recovery-kwin:    ${FEAT_RECOVERY_KWIN}"
log_info "    secureboot:       ${FEAT_SECUREBOOT}"
log_info "    plymouth:         ${FEAT_PLYMOUTH}"
log_info "    qemu:             ${FEAT_QEMU}"
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
    for pkg in isolinux syslinux-common syslinux-efi mtools dosfstools genisoimage; do
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
        # shim-signed is recommended for Secure Boot but not strictly required
        if ! dpkg-query -W -f='${Status}' shim-signed 2>/dev/null | grep -q "install ok installed"; then
            log_warn "shim-signed is not installed; Secure Boot support may be limited"
        fi
    fi

    if [ ${#missing[@]} -gt 0 ] || [ ${#boot_missing[@]} -gt 0 ]; then
        local all_missing=("${missing[@]}" "${boot_missing[@]}")
        log_error "Missing dependencies: ${all_missing[*]}"
        log_info ""
        log_info "Install all dependencies with:"
        log_info "  sudo apt-get install -y live-build debootstrap squashfs-tools xorriso \\"
        log_info "    isolinux syslinux-common syslinux-efi mtools dosfstools genisoimage \\"
        log_info "    grub-pc-bin grub-efi-amd64-bin shim-signed"
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
        "${CONFIG_DIR}/package-lists/aura-core.list.chroot"
        "${CONFIG_DIR}/hooks/live/00-bright-os-branding.hook.chroot"
        "${CONFIG_DIR}/hooks/live/10-bright-os-components.hook.chroot"
        "${CONFIG_DIR}/hooks/live/15-display-manager.hook.chroot"
        "${CONFIG_DIR}/hooks/live/40-aura-setup.hook.chroot"
        "${CONFIG_DIR}/includes.chroot/etc/greetd/config.toml"
        "${CONFIG_DIR}/includes.binary/boot/grub/grub.cfg"
        "${CONFIG_DIR}/includes.chroot/etc/bright-os/edition"
        "${CONFIG_DIR}/includes.chroot/usr/bin/bright-desktop-shell"
        "${CONFIG_DIR}/includes.chroot/usr/bin/aura-core-service"
        "${CONFIG_DIR}/includes.chroot/usr/share/bright-os/Shell.qml"
        "${CONFIG_DIR}/includes.chroot/usr/share/bright-os/bright-desktop-shell.py"
        "${CONFIG_DIR}/includes.chroot/usr/share/bright-os/design/DesignTokens.js"
        "${CONFIG_DIR}/includes.chroot/usr/share/bright-os/profiles/EditionProfiles.js"
        "${CONFIG_DIR}/includes.chroot/usr/share/bright-os/installer/settings.conf"
        "${CONFIG_DIR}/includes.chroot/usr/share/bright-os/installer/modules/bootloader.conf"
        "${CONFIG_DIR}/includes.chroot/usr/share/bright-os/installer/modules/displaymanager.conf"
        "${CONFIG_DIR}/includes.chroot/etc/systemd/system/aura-core.service"
        "${CONFIG_DIR}/includes.chroot/etc/dbus-1/system.d/org.bright_os.AURA.conf"
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

# --- Copy AURA source tree to chroot ---
AURA_SRC_DIR="${PROJECT_ROOT}/aura"
AURA_DEST_DIR="config/includes.chroot/usr/lib/aura"
if [ -d "${AURA_SRC_DIR}" ]; then
    mkdir -p "${AURA_DEST_DIR}"
    cp -r "${AURA_SRC_DIR}/"* "${AURA_DEST_DIR}/"
    log_info "Copied AURA source tree to ${AURA_DEST_DIR}"
fi

# --- Copy Bright Android source tree to chroot ---
BA_SRC_DIR="${PROJECT_ROOT}/bright_android"
BA_DEST_DIR="config/includes.chroot/usr/lib/bright-android"
if [ -d "${BA_SRC_DIR}" ]; then
    mkdir -p "${BA_DEST_DIR}"
    cp -r "${BA_SRC_DIR}/"* "${BA_DEST_DIR}/"
    log_info "Copied Bright Android source tree to ${BA_DEST_DIR}"
    # Make GUI launcher executable
    chmod +x config/includes.chroot/usr/bin/bright-android 2>/dev/null || true
fi

# --- Bright Android GUI entry point ---
# Use the maintained package module (bright_android/gui.py) as the single source.
# applications/bright-android/bright-android is an older copy with a known bug
# (the "if False" runtime status check) and must not be shipped.
if [ -f "${BA_SRC_DIR}/gui.py" ]; then
    mkdir -p "${BA_DEST_DIR}"
    cp "${BA_SRC_DIR}/gui.py" "${BA_DEST_DIR}/bright-android-gui.py"
    chmod 0644 "${BA_DEST_DIR}/bright-android-gui.py"
fi
if [ -f "${PROJECT_ROOT}/applications/bright-android/bright-android.desktop" ]; then
    cp "${PROJECT_ROOT}/applications/bright-android/bright-android.desktop" \
       config/includes.chroot/usr/share/applications/
fi

# ---------------------------------------------------------------------------
# Copy optional-profile package lists based on resolved feature flags
# ---------------------------------------------------------------------------
copy_opt_list() {
    local flag="$1"; local name="$2"; local src="$3"; local dst="$4"
    if [ "$flag" = "true" ]; then
        if [ -f "$src" ]; then
            cp "$src" "$dst"
            log_info "Optional profile: ${name} (included)"
        else
            log_error "Optional profile source missing: $src"
            exit 1
        fi
    else
        rm -f "$dst"
        log_info "Optional profile: ${name} (excluded)"
    fi
}

copy_opt_list "$FEAT_BLUETOOTH"      "bluetooth"       "${CONFIG_DIR}/package-lists/optional-bluetooth.list.chroot"      "config/package-lists/opt-bluetooth.list.chroot"
copy_opt_list "$FEAT_PRINTING"       "printing"        "${CONFIG_DIR}/package-lists/optional-printing.list.chroot"       "config/package-lists/opt-printing.list.chroot"
copy_opt_list "$FEAT_NETWORK_EXTRAS" "network-extras"  "${CONFIG_DIR}/package-lists/optional-network-extras.list.chroot" "config/package-lists/opt-network-extras.list.chroot"
copy_opt_list "$FEAT_WINE"           "wine"            "${CONFIG_DIR}/package-lists/optional-wine.list.chroot"          "config/package-lists/opt-wine.list.chroot"
copy_opt_list "$FEAT_DEVTOOLS"       "devtools"        "${CONFIG_DIR}/package-lists/optional-devtools-core.list.chroot"  "config/package-lists/opt-devtools.list.chroot"
copy_opt_list "$FEAT_RECOVERY_KWIN"  "recovery-kwin"   "${CONFIG_DIR}/package-lists/optional-recovery-kwin.list.chroot" "config/package-lists/opt-recovery-kwin.list.chroot"
copy_opt_list "$FEAT_SECUREBOOT"     "secureboot"      "${CONFIG_DIR}/package-lists/optional-secureboot.list.chroot"    "config/package-lists/opt-secureboot.list.chroot"
copy_opt_list "$FEAT_PLYMOUTH"       "plymouth"        "${CONFIG_DIR}/package-lists/optional-plymouth.list.chroot"      "config/package-lists/opt-plymouth.list.chroot"
copy_opt_list "$FEAT_QEMU"           "qemu"            "${CONFIG_DIR}/package-lists/optional-qemu.list.chroot"          "config/package-lists/opt-qemu.list.chroot"

# Android is handled separately (it has its own source tree copy earlier,
# and we must conditionally include its package list here).
#
# Lite edition defaults to NO Android ("${EDITION}" = "lite" -> DEF_ANDROID=false).
# Android support optional (not installed by default) unless the feature flag
# resolves to true (home/developer default on; lite default off; --with-android
# or --without-android override).
if [ "$FEAT_ANDROID" = "true" ]; then
    ANDROID_PKGS="${CONFIG_DIR}/package-lists/android.list.chroot"
    if [ -f "$ANDROID_PKGS" ]; then
        cp "$ANDROID_PKGS" "config/package-lists/android-packages.list.chroot"
        log_info "Android packages: included"
    fi
else
    rm -f "config/package-lists/android-packages.list.chroot"
    log_info "Android packages: excluded"
fi

# --- Apply edition-specific configuration ---
mkdir -p config/includes.chroot/etc/bright-os
echo "${EDITION}" > config/includes.chroot/etc/bright-os/edition

# ---------------------------------------------------------------------------
# Service masking (correct behavior, Phase 6.3 corrective pass):
#
# For EVERY optional service, we:
#   1. If the feature IS enabled:  do NOT mask (so systemctl enable works).
#   2. If the feature is DISABLED: mask it to /dev/null so apt-recommends
#      or accidental installs don't start unwanted services.
#
# This replaces the prior buggy approach where all four services were
# masked unconditionally and then the hook tried to "enable" them (systemctl
# enable on a masked unit fails silently because the mask takes precedence).
# ---------------------------------------------------------------------------
mkdir -p config/includes.chroot/etc/systemd/system

mask_if_disabled() {
    local svc="$1"; local enabled="$2"
    local target="config/includes.chroot/etc/systemd/system/${svc}"
    if [ "$enabled" = "true" ]; then
        rm -f "$target"
        log_info "Service ${svc}: will be enabled (feature on)"
    else
        ln -sf /dev/null "$target"
        log_info "Service ${svc}: masked (feature off)"
    fi
}

mask_if_disabled bluetooth.service       "$FEAT_BLUETOOTH"
mask_if_disabled cups.service            "$FEAT_PRINTING"
# Network-extras controls ModemManager + avahi
if [ "$FEAT_NETWORK_EXTRAS" = "true" ]; then
    rm -f "config/includes.chroot/etc/systemd/system/ModemManager.service"
    rm -f "config/includes.chroot/etc/systemd/system/avahi-daemon.service"
    log_info "Service ModemManager + avahi-daemon: will be enabled (network-extras on)"
else
    ln -sf /dev/null "config/includes.chroot/etc/systemd/system/ModemManager.service"
    ln -sf /dev/null "config/includes.chroot/etc/systemd/system/avahi-daemon.service"
    log_info "Service ModemManager + avahi-daemon: masked (network-extras off)"
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

# --- Debug: list build directory contents and ISO root ---
set +o pipefail  # avoid SIGPIPE from head closing pipes killing us under set -e
log_info "Build directory contents after lb build:"
ls -la || true
echo ""
echo "=== [DEBUG] Recursive listing of chroot/ and binary/ dirs ==="
for d in chroot/binary/live chroot/binary/boot chroot/live chroot/boot binary/live binary/boot 2>/dev/null; do
  if [ -e "$d" ]; then
    echo "--- $d ---"
    ls -la "$d" 2>&1 | head -20 || true
  else
    echo "--- $d does not exist ---"
  fi
done
echo ""
echo "=== [DEBUG] Finding any vmlinuz/initrd/squashfs in build tree ==="
( find . -name "vmlinuz*" -o -name "initrd*" -o -name "*.squashfs" -o -name "*.iso" 2>/dev/null || true ) | head -30 || true
echo ""
if command -v isoinfo >/dev/null 2>&1; then
    log_info "ISO root directory listing (isoinfo -l):"
    isoinfo -i "${ISO_NAME}" -l 2>&1 | head -200 || true
    echo ""
    echo "=== [DEBUG] ISO listing (isoinfo -f - all paths, first 100) ==="
    isoinfo -i "${ISO_NAME}" -f 2>&1 | head -100 || true
    echo ""
fi
set -o pipefail

# --- Automatic ISO validation ---
# Run validate-iso.sh automatically.
# This checks ISO9660 filesystem, kernel, initrd, squashfs, BIOS/UEFI boot
# structures, GRUB, isolinux, and checksum.
# Exit codes: 0=PASS, 1=FAIL (critical), 2=INCONCLUSIVE (missing tools).
# We treat 1 as failure and 2 as a warning (tools unavailable but build completed).
# Set BRIGHT_SKIP_VALIDATION=1 to skip (e.g. in mock testing environments
# where real ISO inspection tools are not available or ISO is a dummy file).
VALIDATION_STATUS=0
VALIDATE_SCRIPT="${PROJECT_ROOT}/build/scripts/validate-iso.sh"

if [ "${BRIGHT_SKIP_VALIDATION:-0}" = "1" ]; then
    log_warn "Skipping ISO validation (BRIGHT_SKIP_VALIDATION=1 set)"
else
    log_info "Running ISO validation..."
    echo ""
    set +e
    bash "${VALIDATE_SCRIPT}" "${ISO_NAME}"
    VALIDATION_STATUS=$?
    set -e
    echo ""

    if [ "${VALIDATION_STATUS}" -eq 1 ]; then
        log_error "========================================"
        log_error "  ISO VALIDATION FAILED"
        log_error "  The ISO was built but failed structural validation."
        log_error "  ISO preserved at: ${ISO_PATH}"
        log_error "  Build log:        ${BUILD_DIR}/${BUILD_LOG}"
        log_error "  Review the validation output above for specific failures."
        log_error "========================================"
        # Do NOT exit 1 here during CI diagnostics — allow artifact collection
        # so we can inspect the ISO. In production, uncomment the exit 1 below.
        if [ "${BRIGHT_ENSURE_VALIDATION:-1}" = "1" ]; then
            exit 1
        fi
    elif [ "${VALIDATION_STATUS}" -eq 2 ]; then
        log_warn "ISO validation was INCONCLUSIVE (some tools missing)."
        log_warn "The ISO was built but could not be fully validated."
        log_warn "Install genisoimage, xorriso, and file for complete validation."
        log_warn "Run manually: ${VALIDATE_SCRIPT} ${ISO_PATH}"
    else
        log_ok "ISO validation passed"
    fi
fi  # end BRIGHT_SKIP_VALIDATION check

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
if [ "${VALIDATION_STATUS}" -eq 0 ]; then
log_ok "  Validation: PASSED"
elif [ "${VALIDATION_STATUS}" -eq 2 ]; then
log_warn "  Validation: INCONCLUSIVE (tools missing)"
fi
log_ok "========================================"
echo ""
if [ "${VALIDATION_STATUS}" -ne 0 ]; then
log_info "To fully validate the ISO, install missing tools and run:"
log_info "  ${VALIDATE_SCRIPT} ${ISO_PATH}"
echo ""
fi
log_info "To test in QEMU:"
log_info "  ${PROJECT_ROOT}/build/scripts/test-in-qemu.sh ${ISO_PATH}"
echo ""
log_info "To write to USB:"
log_info "  sudo dd if=${ISO_PATH} of=/dev/sdX bs=4M status=progress conv=fsync"
echo ""

exit 0
