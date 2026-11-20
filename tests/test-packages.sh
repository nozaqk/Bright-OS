#!/bin/bash
# =============================================================================
# Phase 11: Package List Consistency Tests
# Tests for duplicates, edition separation, and package name sanity.
# =============================================================================

set -eu

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"
cd "$PROJECT_ROOT"

PASS=0; FAIL=0; WARN=0
RED='\033[0;31m'; GREEN='\033[0;32m'; YELLOW='\033[1;33m'; NC='\033[0m'
pass() { echo -e "${GREEN}[PASS]${NC} $*"; PASS=$((PASS+1)); }
fail() { echo -e "${RED}[FAIL]${NC} $*"; FAIL=$((FAIL+1)); }
warn() { echo -e "${YELLOW}[WARN]${NC} $*"; WARN=$((WARN+1)); }

get_pkgs() {
    grep -v '^#' "$1" | grep -v '^$' | sed 's/[[:space:]]*#.*//' | sort -u
}

CORE=$(get_pkgs config/package-lists/core.list.chroot)
DESKTOP=$(get_pkgs config/package-lists/desktop.list.chroot)
DESKTOP_LITE=$(get_pkgs config/package-lists/desktop-lite.list.chroot)
HOME=$(get_pkgs editions/home/packages.list)
DEV=$(get_pkgs editions/developer/packages.list)
LITE=$(get_pkgs editions/lite/packages.list)

echo "============================================"
echo "  Package List Consistency Tests"
echo "============================================"

echo ""
echo "--- Package counts ---"
echo "  Core (all editions):     $(echo "$CORE" | wc -l)"
echo "  Desktop (Plasma):        $(echo "$DESKTOP" | wc -l)"
echo "  Desktop-lite (LXQt):     $(echo "$DESKTOP_LITE" | wc -l)"
echo "  Home additions:          $(echo "$HOME" | wc -l)"
echo "  Developer additions:     $(echo "$DEV" | wc -l)"
echo "  Lite additions:          $(echo "$LITE" | wc -l)"
echo ""
echo "  Total Home:     $(echo "$CORE $DESKTOP $HOME" | tr ' ' '\n' | sort -u | wc -l)"
echo "  Total Developer:$(echo "$CORE $DESKTOP $DEV" | tr ' ' '\n' | sort -u | wc -l)"
echo "  Total Lite:     $(echo "$CORE $DESKTOP_LITE $LITE" | tr ' ' '\n' | sort -u | wc -l)"
pass "Package counts computed"

# --- Check for duplicates within each list ---
echo ""
echo "--- Duplicate detection ---"
for name in core desktop desktop-lite home developer lite; do
    case "$name" in
        core) list="$CORE" ;;
        desktop) list="$DESKTOP" ;;
        desktop-lite) list="$DESKTOP_LITE" ;;
        home) list="$HOME" ;;
        developer) list="$DEV" ;;
        lite) list="$LITE" ;;
    esac
    dups=$(echo "$list" | sort | uniq -d)
    if [ -z "$dups" ]; then
        pass "${name}: no duplicates"
    else
        fail "${name}: has duplicates: $dups"
    fi
done

# --- Check that Plasma/KDE packages don't leak into Lite ---
echo ""
echo "--- Edition separation ---"
PLASMA_PKGS="plasma-desktop plasma-workspace plasma-nm plasma-pa bluedevil powerdevil print-manager kde-config-gtk-style plasma-discover sddm-theme-debian-breeze"
LEAKS=0
for pkg in $PLASMA_PKGS; do
    if echo "$CORE" | grep -qx "$pkg"; then
        fail "Plasma package '${pkg}' in CORE (would leak into Lite!)"
        LEAKS=$((LEAKS+1))
    elif echo "$DESKTOP_LITE" | grep -qx "$pkg"; then
        fail "Plasma package '${pkg}' in DESKTOP-LITE"
        LEAKS=$((LEAKS+1))
    elif echo "$DESKTOP" | grep -qx "$pkg"; then
        : # correctly in desktop
    fi
done
if [ $LEAKS -eq 0 ]; then
    pass "No Plasma packages leak into Lite edition"
fi

# Check Lite has LXQt
if echo "$DESKTOP_LITE" | grep -qx "lxqt-core"; then
    pass "Lite includes lxqt-core"
else
    fail "Lite missing lxqt-core"
fi

# Check Lite has a compositor (picom)
if echo "$DESKTOP_LITE" | grep -qx "picom"; then
    pass "Lite includes picom compositor"
else
    fail "Lite missing picom compositor"
fi

# Check Lite has a window manager (openbox)
if echo "$DESKTOP_LITE" | grep -qx "openbox"; then
    pass "Lite includes openbox window manager"
else
    fail "Lite missing openbox"
fi

# Check KWin is in core (needed by Bright Desktop)
if echo "$CORE" | grep -qx "kwin-wayland"; then
    pass "Core includes kwin-wayland (needed by Bright Desktop on all editions)"
else
    fail "Core missing kwin-wayland"
fi

# Check SDDM is in core (display manager needed by all)
if echo "$CORE" | grep -qx "sddm"; then
    pass "Core includes sddm (display manager)"
else
    fail "Core missing sddm"
fi

# --- Check for known-bad package names ---
echo ""
echo "--- Known problematic packages ---"
BAD_PKGS=0
check_bad() {
    local pkg="$1"; local why="$2"; local list="$3"
    if echo "$list" | grep -qx "$pkg"; then
        fail "Found problematic package '${pkg}': ${why}"
        BAD_PKGS=$((BAD_PKGS+1))
    fi
}

ALL_PKGS="$CORE $DESKTOP $DESKTOP_LITE $HOME $DEV $LITE"
check_bad "compton" "renamed to picom in Trixie" "$ALL_PKGS"
check_bad "code" "VS Code not in Debian repos" "$ALL_PKGS"
check_bad "perf-tools-unstable" "not in Debian" "$ALL_PKGS"
check_bad "polkitd" "incorrect name (should be policykit-1)" "$ALL_PKGS"
check_bad "snapd" "removed (unnecessary bloat)" "$ALL_PKGS"
check_bad "docker-compose" "renamed to docker-compose-v2 in Trixie" "$ALL_PKGS"
if [ $BAD_PKGS -eq 0 ]; then
    pass "No known-bad package names found"
fi

# --- Package name format check ---
echo ""
echo "--- Package name format validation ---"
BAD_FMT=0
for name in core desktop desktop-lite home developer lite; do
    case "$name" in
        core) list="$CORE" ;;
        desktop) list="$DESKTOP" ;;
        desktop-lite) list="$DESKTOP_LITE" ;;
        home) list="$HOME" ;;
        developer) list="$DEV" ;;
        lite) list="$LITE" ;;
    esac
    while IFS= read -r pkg; do
        [ -z "$pkg" ] && continue
        if ! echo "$pkg" | grep -qE '^[a-z0-9][a-z0-9.+-]*$'; then
            fail "Invalid package name in ${name}: '${pkg}'"
            BAD_FMT=$((BAD_FMT+1))
        fi
    done <<< "$list"
done
if [ $BAD_FMT -eq 0 ]; then
    pass "All package names have valid format"
fi

echo ""
echo "============================================"
echo "  Results: $PASS passed, $FAIL failed, $WARN warnings"
echo "============================================"
if [ "$FAIL" -eq 0 ]; then
    echo -e "${GREEN}All package list tests passed!${NC}"
    exit 0
else
    echo -e "${RED}$FAIL test(s) failed.${NC}"
    exit 1
fi
