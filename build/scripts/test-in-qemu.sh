#!/bin/bash
# =============================================================================
# Bright OS QEMU Boot Test Script
# Boots the ISO in QEMU for testing. Exits QEMU with the same exit status.
# NOTE: This script launches QEMU but does NOT verify that the OS actually
# boots successfully — it only starts the virtual machine. Boot success
# must be confirmed visually or via automated QEMU tests.
# =============================================================================

set -euo pipefail

# Script is at <root>/build/scripts/test-in-qemu.sh
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "${SCRIPT_DIR}/../.." && pwd)"

if [ ! -f "${PROJECT_ROOT}/README.md" ]; then
    echo "ERROR: Cannot determine project root from SCRIPT_DIR=${SCRIPT_DIR}"
    exit 1
fi

# Defaults
ISO_PATH=""
BOOT_MODE="bios"
MEMORY=4096
CPUS=4
MIN_MEMORY=512
MAX_MEMORY=32768

usage() {
    cat <<EOF
Bright OS QEMU Test Script

Usage: $0 [OPTIONS] [ISO_PATH]

Options:
  -h, --help       Show this help
  --bios           BIOS boot mode (default)
  --uefi           UEFI boot mode (requires ovmf package)
  -m, --memory MB  Memory in MB (default: ${MEMORY}, range: ${MIN_MEMORY}-${MAX_MEMORY})
  -c, --cpus N     Number of CPUs (default: ${CPUS})

Examples:
  $0 build/output/home/bright-os-0.1.0-alpha-home-amd64.iso
  $0 --uefi -m 8192
  $0 my.iso --bios
EOF
    exit "${1:-0}"
}

# Parse arguments
ISO_CANDIDATE=""
while [[ $# -gt 0 ]]; do
    case "$1" in
        -h|--help)
            usage 0 ;;
        --bios)
            BOOT_MODE="bios"
            shift ;;
        --uefi)
            BOOT_MODE="uefi"
            shift ;;
        -m|--memory)
            if [ $# -lt 2 ]; then
                echo "ERROR: --memory requires an argument"
                exit 1
            fi
            MEMORY="$2"
            shift 2 ;;
        -c|--cpus)
            if [ $# -lt 2 ]; then
                echo "ERROR: --cpus requires an argument"
                exit 1
            fi
            CPUS="$2"
            shift 2 ;;
        --*)
            echo "ERROR: Unknown option: $1"
            usage 1 ;;
        -*)
            echo "ERROR: Unknown short option: $1"
            usage 1 ;;
        *)
            # Positional argument: ISO path (accept only one)
            if [ -n "$ISO_CANDIDATE" ]; then
                echo "ERROR: Multiple ISO paths specified: '${ISO_CANDIDATE}' and '$1'"
                exit 1
            fi
            ISO_CANDIDATE="$1"
            shift ;;
    esac
done

# Validate memory is a positive integer within range
if ! [[ "$MEMORY" =~ ^[0-9]+$ ]]; then
    echo "ERROR: Memory must be a positive integer (got '${MEMORY}')"
    exit 1
fi
if [ "$MEMORY" -lt "$MIN_MEMORY" ]; then
    echo "ERROR: Memory too small: ${MEMORY} MB (minimum ${MIN_MEMORY} MB)"
    exit 1
fi
if [ "$MEMORY" -gt "$MAX_MEMORY" ]; then
    echo "ERROR: Memory too large: ${MEMORY} MB (maximum ${MAX_MEMORY} MB)"
    exit 1
fi

# Validate CPUs
if ! [[ "$CPUS" =~ ^[0-9]+$ ]] || [ "$CPUS" -lt 1 ] || [ "$CPUS" -gt 64 ]; then
    echo "ERROR: CPUs must be an integer between 1 and 64 (got '${CPUS}')"
    exit 1
fi

# Resolve ISO path
if [ -n "$ISO_CANDIDATE" ]; then
    if [ ! -f "$ISO_CANDIDATE" ]; then
        echo "ERROR: ISO file not found: ${ISO_CANDIDATE}"
        exit 1
    fi
    # Convert to absolute path
    ISO_PATH="$(cd "$(dirname "$ISO_CANDIDATE")" && pwd)/$(basename "$ISO_CANDIDATE")"
else
    # Auto-detect built ISOs
    shopt -s nullglob
    candidates=(
        "${PROJECT_ROOT}/build/output/home/bright-os-"*"-home-amd64.iso"
        "${PROJECT_ROOT}/build/output/developer/bright-os-"*"-developer-amd64.iso"
        "${PROJECT_ROOT}/build/output/lite/bright-os-"*"-lite-amd64.iso"
    )
    shopt -u nullglob
    if [ ${#candidates[@]} -eq 0 ]; then
        echo "ERROR: No ISO file found and none specified on command line."
        echo ""
        echo "Build an ISO first:"
        echo "  ${PROJECT_ROOT}/build/scripts/build.sh home"
        echo ""
        echo "Or specify a path:"
        echo "  $0 /path/to/bright-os.iso"
        exit 1
    fi
    if [ ${#candidates[@]} -gt 1 ]; then
        echo "WARNING: Multiple ISOs found; using first: ${candidates[0]}"
    fi
    ISO_PATH="${candidates[0]}"
fi

if [ ! -r "$ISO_PATH" ]; then
    echo "ERROR: ISO file is not readable: ${ISO_PATH}"
    exit 1
fi

# Check QEMU is available
if ! command -v qemu-system-x86_64 &>/dev/null; then
    echo "ERROR: qemu-system-x86_64 not found."
    echo "Install with: sudo apt-get install -y qemu-system-x86 qemu-utils"
    exit 1
fi

echo "=== Bright OS QEMU Boot Test ==="
echo "ISO:      ${ISO_PATH}"
echo "Mode:     ${BOOT_MODE}"
echo "Memory:   ${MEMORY} MB"
echo "CPUs:     ${CPUS}"
echo ""
echo "NOTE: This launches QEMU but does NOT verify the OS boots."
echo "      Close the QEMU window (or press Ctrl+A then X) to stop."
echo ""

# Build QEMU arguments as an array for safe passing
QEMU_ARGS=(
    -m "${MEMORY}"
    -smp "${CPUS}"
    -cdrom "${ISO_PATH}"
    -boot d
    -vga virtio
    -display gtk
    -usb
    -device usb-ehci
    -device usb-tablet
    -netdev user,id=net0
    -device e1000,netdev=net0
)

# KVM acceleration (optional, auto-detected)
if [ -r /dev/kvm ] && [ -w /dev/kvm ]; then
    echo "KVM:      enabled (hardware acceleration)"
    QEMU_ARGS+=( -enable-kvm -cpu host )
else
    echo "KVM:      not available (software emulation — much slower)"
fi

# UEFI firmware
if [ "$BOOT_MODE" = "uefi" ]; then
    OVMF_PATH=""
    OVMF_VARS=""
    # Search common OVMF locations
    for ovmf_code in \
        /usr/share/OVMF/OVMF_CODE_4M.fd \
        /usr/share/OVMF/OVMF_CODE.fd \
        /usr/share/edk2/x64/OVMF_CODE.fd \
        /usr/share/edk2-ovmf/x64/OVMF_CODE.fd \
        /usr/share/qemu/OVMF_CODE.fd; do
        if [ -r "$ovmf_code" ]; then
            OVMF_PATH="$ovmf_code"
            break
        fi
    done
    # Find matching vars template for writable NVRAM
    if [ -n "$OVMF_PATH" ]; then
        for ovmf_vars_candidate in \
            "${OVMF_PATH%CODE_4M.fd}OVMF_VARS_4M.fd" \
            "${OVMF_PATH%CODE.fd}VARS.fd" \
            /usr/share/OVMF/OVMF_VARS_4M.fd \
            /usr/share/OVMF/OVMF_VARS.fd; do
            if [ -r "$ovmf_vars_candidate" ]; then
                OVMF_VARS="$ovmf_vars_candidate"
                break
            fi
        done
    fi
    if [ -z "$OVMF_PATH" ]; then
        echo "ERROR: UEFI firmware (OVMF) not found."
        echo "Install with: sudo apt-get install -y ovmf"
        echo "Or use --bios for BIOS boot testing."
        exit 1
    fi
    echo "UEFI:     ${OVMF_PATH}"
    # Create a temporary writable copy of the vars template
    TMP_VARS=$(mktemp /tmp/bright-ovmf-vars-XXXXXX.fd)
    if [ -n "$OVMF_VARS" ]; then
        cp "$OVMF_VARS" "$TMP_VARS"
        QEMU_ARGS+=( -drive "if=pflash,format=raw,readonly=on,file=${OVMF_PATH}" )
        QEMU_ARGS+=( -drive "if=pflash,format=raw,file=${TMP_VARS}" )
    else
        # Fallback: use -bios (older method, no writable vars)
        echo "WARNING: OVMF vars template not found; using -bios fallback"
        QEMU_ARGS+=( -bios "${OVMF_PATH}" )
    fi
    # Clean up temp vars on exit
    trap 'rm -f "$TMP_VARS"' EXIT
fi

echo ""
echo "Starting QEMU..."
echo ""

exec qemu-system-x86_64 "${QEMU_ARGS[@]}"
