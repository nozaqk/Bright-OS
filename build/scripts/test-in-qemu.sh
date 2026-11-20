#!/bin/bash
# =============================================================================
# Bright OS QEMU Boot Test Script
# Boots the ISO in QEMU for testing. Supports BIOS/UEFI, KVM/TCG, graphical/serial.
#
# NOTE: This script launches QEMU but does NOT programmatically verify that the
# OS boots successfully — boot success must be confirmed visually (graphical)
# or via serial console output (--serial).
# =============================================================================

set -euo pipefail

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
CPUS=2
MIN_MEMORY=512
MAX_MEMORY=32768
DISPLAY_MODE="gtk"
SERIAL_LOG=""
DISK_SIZE=""
DISK_FILE=""
DRY_RUN=false

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
  --display MODE   Display: gtk, sdl, curses, none, serial (default: ${DISPLAY_MODE})
                   'serial' implies -nographic with serial to stdio
                   'none' uses -display none (headless, useful with --serial-log)
  --serial-log FILE  Log serial console output to FILE (also adds serial to stdio if display=none)
  --disk SIZE_GB   Create and attach a virtual disk of SIZE_GB (for installation testing)
  --disk-file FILE Use existing disk image instead of creating one
  --dry-run        Print QEMU command but don't execute

Examples:
  # Graphical boot with KVM
  $0 build/output/lite/bright-os-0.1.0-alpha-lite-amd64.iso

  # UEFI graphical boot
  $0 --uefi -m 4096 my.iso

  # Headless serial boot (capture logs to file)
  $0 --display serial --serial-log /tmp/bright-serial.log -m 2048 my.iso

  # Boot with 20GB virtual disk for installation testing
  $0 --disk 20 -m 4096 my.iso

  # Software emulation (no KVM, slower)
  $0 -m 2048 -c 2 --display serial my.iso
EOF
    exit "${1:-0}"
}

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
            if [ $# -lt 2 ]; then echo "ERROR: --memory requires an argument"; exit 1; fi
            MEMORY="$2"; shift 2 ;;
        -c|--cpus)
            if [ $# -lt 2 ]; then echo "ERROR: --cpus requires an argument"; exit 1; fi
            CPUS="$2"; shift 2 ;;
        --display)
            if [ $# -lt 2 ]; then echo "ERROR: --display requires an argument"; exit 1; fi
            DISPLAY_MODE="$2"; shift 2 ;;
        --serial-log)
            if [ $# -lt 2 ]; then echo "ERROR: --serial-log requires an argument"; exit 1; fi
            SERIAL_LOG="$2"; shift 2 ;;
        --disk)
            if [ $# -lt 2 ]; then echo "ERROR: --disk requires size in GB"; exit 1; fi
            DISK_SIZE="$2"; shift 2 ;;
        --disk-file)
            if [ $# -lt 2 ]; then echo "ERROR: --disk-file requires a path"; exit 1; fi
            DISK_FILE="$2"; shift 2 ;;
        --dry-run)
            DRY_RUN=true; shift ;;
        --*)
            echo "ERROR: Unknown option: $1"; usage 1 ;;
        -*)
            echo "ERROR: Unknown short option: $1"; usage 1 ;;
        *)
            if [ -n "$ISO_CANDIDATE" ]; then
                echo "ERROR: Multiple ISO paths specified: '${ISO_CANDIDATE}' and '$1'"
                exit 1
            fi
            ISO_CANDIDATE="$1"; shift ;;
    esac
done

# Validate memory
if ! [[ "$MEMORY" =~ ^[0-9]+$ ]]; then
    echo "ERROR: Memory must be a positive integer (got '${MEMORY}')"; exit 1
fi
if [ "$MEMORY" -lt "$MIN_MEMORY" ]; then
    echo "ERROR: Memory too small: ${MEMORY} MB (minimum ${MIN_MEMORY} MB)"; exit 1
fi
if [ "$MEMORY" -gt "$MAX_MEMORY" ]; then
    echo "ERROR: Memory too large: ${MEMORY} MB (maximum ${MAX_MEMORY} MB)"; exit 1
fi

# Validate CPUs
if ! [[ "$CPUS" =~ ^[0-9]+$ ]] || [ "$CPUS" -lt 1 ] || [ "$CPUS" -gt 64 ]; then
    echo "ERROR: CPUs must be an integer between 1 and 64 (got '${CPUS}')"; exit 1
fi

# Resolve ISO path
if [ -n "$ISO_CANDIDATE" ]; then
    if [ ! -f "$ISO_CANDIDATE" ]; then
        echo "ERROR: ISO file not found: ${ISO_CANDIDATE}"; exit 1
    fi
    ISO_PATH="$(cd "$(dirname "$ISO_CANDIDATE")" && pwd)/$(basename "$ISO_CANDIDATE")"
else
    shopt -s nullglob
    candidates=(
        "${PROJECT_ROOT}/build/output/lite/bright-os-"*"-lite-amd64.iso"
        "${PROJECT_ROOT}/build/output/home/bright-os-"*"-home-amd64.iso"
        "${PROJECT_ROOT}/build/output/developer/bright-os-"*"-developer-amd64.iso"
    )
    shopt -u nullglob
    if [ ${#candidates[@]} -eq 0 ]; then
        echo "ERROR: No ISO file found and none specified on command line."
        echo ""
        echo "Build an ISO first:"
        echo "  ${PROJECT_ROOT}/build/scripts/build.sh lite"
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
    echo "ERROR: ISO file is not readable: ${ISO_PATH}"; exit 1
fi

# Check QEMU is available
if ! command -v qemu-system-x86_64 &>/dev/null; then
    echo "ERROR: qemu-system-x86_64 not found."
    echo "Install with: sudo apt-get install -y qemu-system-x86 qemu-utils"
    exit 1
fi

# Create virtual disk if requested
CREATED_DISK=""
if [ -n "$DISK_SIZE" ]; then
    if [ -z "$DISK_FILE" ]; then
        CREATED_DISK=$(mktemp /tmp/bright-disk-XXXXXX.qcow2)
        DISK_FILE="$CREATED_DISK"
        echo "Creating ${DISK_SIZE}GB virtual disk: ${DISK_FILE}"
        qemu-img create -f qcow2 "$DISK_FILE" "${DISK_SIZE}G" >/dev/null 2>&1 || {
            echo "ERROR: Failed to create virtual disk"; exit 1
        }
    fi
elif [ -n "$DISK_FILE" ]; then
    if [ ! -f "$DISK_FILE" ]; then
        echo "ERROR: Disk file not found: ${DISK_FILE}"; exit 1
    fi
fi

# Clean up created disk on exit
cleanup() {
    if [ -n "$CREATED_DISK" ] && [ -f "$CREATED_DISK" ]; then
        echo ""
        echo "Cleaning up temporary disk: ${CREATED_DISK}"
        rm -f "$CREATED_DISK"
    fi
}
trap cleanup EXIT

echo "=== Bright OS QEMU Boot Test ==="
echo "ISO:      ${ISO_PATH}"
echo "Mode:     ${BOOT_MODE}"
echo "Memory:   ${MEMORY} MB"
echo "CPUs:     ${CPUS}"
echo "Display:  ${DISPLAY_MODE}"
if [ -n "$DISK_FILE" ]; then
    echo "Disk:     ${DISK_FILE} (${DISK_SIZE:-existing} GB)"
fi
if [ -n "$SERIAL_LOG" ]; then
    echo "Serial log: ${SERIAL_LOG}"
fi
echo ""

# Build QEMU arguments
QEMU_ARGS=()

# Machine/CPU
QEMU_ARGS+=(-m "${MEMORY}" -smp "${CPUS}")

# Boot from CD-ROM
QEMU_ARGS+=(-cdrom "${ISO_PATH}" -boot d)

# Display configuration
case "$DISPLAY_MODE" in
    gtk)
        QEMU_ARGS+=(-vga virtio -display gtk)
        ;;
    sdl)
        QEMU_ARGS+=(-vga virtio -display sdl)
        ;;
    curses)
        QEMU_ARGS+=(-display curses)
        ;;
    none)
        QEMU_ARGS+=(-display none -vga std)
        ;;
    serial)
        QEMU_ARGS+=(-nographic -vga none)
        ;;
    *)
        echo "ERROR: Unknown display mode: ${DISPLAY_MODE}"; exit 1 ;;
esac

# USB input
if [ "$DISPLAY_MODE" != "serial" ] && [ "$DISPLAY_MODE" != "none" ]; then
    QEMU_ARGS+=(-usb -device usb-ehci -device usb-tablet)
fi

# Network
QEMU_ARGS+=(-netdev user,id=net0 -device e1000,netdev=net0)

# KVM acceleration (optional)
if [ -r /dev/kvm ] && [ -w /dev/kvm ]; then
    echo "KVM:      enabled (hardware acceleration)"
    QEMU_ARGS+=(-enable-kvm -cpu host)
else
    echo "KVM:      not available (TCG software emulation — boot will be slow)"
    QEMU_ARGS+=(-cpu qemu64)
fi

# UEFI firmware
if [ "$BOOT_MODE" = "uefi" ]; then
    OVMF_PATH=""
    OVMF_VARS=""
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
    TMP_VARS=$(mktemp /tmp/bright-ovmf-vars-XXXXXX.fd)
    trap 'rm -f "$TMP_VARS"; cleanup' EXIT
    if [ -n "$OVMF_VARS" ]; then
        cp "$OVMF_VARS" "$TMP_VARS"
        QEMU_ARGS+=(-drive "if=pflash,format=raw,unit=0,readonly=on,file=${OVMF_PATH}")
        QEMU_ARGS+=(-drive "if=pflash,format=raw,unit=1,file=${TMP_VARS}")
    else
        echo "WARNING: OVMF vars template not found; using -bios fallback"
        QEMU_ARGS+=(-bios "${OVMF_PATH}")
    fi
fi

# Virtual disk attachment
if [ -n "$DISK_FILE" ]; then
    QEMU_ARGS+=(-drive "file=${DISK_FILE},format=qcow2,if=virtio,cache=unsafe")
fi

# Serial console
if [ "$DISPLAY_MODE" = "serial" ] || [ "$DISPLAY_MODE" = "none" ] || [ -n "$SERIAL_LOG" ]; then
    if [ "$DISPLAY_MODE" = "serial" ]; then
        # Serial to stdio (nographic mode)
        QEMU_ARGS+=(-serial mon:stdio)
    elif [ -n "$SERIAL_LOG" ]; then
        QEMU_ARGS+=(-serial "file:${SERIAL_LOG}")
    fi
    # Add kernel console=ttyS0 by modifying boot options? No, that requires editing the ISO.
    # Instead, add serial device but note that GRUB/kernel need console=ttyS0 for output.
fi

echo ""
if [ "$DRY_RUN" = true ]; then
    echo "QEMU command that would be executed:"
    echo "qemu-system-x86_64 ${QEMU_ARGS[*]}"
    exit 0
fi

echo "Starting QEMU..."
echo "(Close the QEMU window or press Ctrl+C to stop)"
echo "For serial mode: press Ctrl+A then X to exit"
echo ""

exec qemu-system-x86_64 "${QEMU_ARGS[@]}"
