#!/bin/bash
# =============================================================================
# Phase 6.1: labwc Proof-of-Concept Configuration Tests
#
# Static checks for the experimental labwc session. These tests verify file
# presence, shell/Python syntax, XML well-formedness, session desktop-file
# structure, and that the existing KWin session remains intact. They do NOT
# boot a real session -- QEMU/VM/metal tests are required for that and are
# documented as remaining work.
# =============================================================================

set -eu

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"
cd "$PROJECT_ROOT"

PASS=0; FAIL=0
RED='\033[0;31m'; GREEN='\033[0;32m'; YELLOW='\033[1;33m'; NC='\033[0m'
pass() { echo -e "${GREEN}[PASS]${NC} $*"; PASS=$((PASS+1)); }
fail() { echo -e "${RED}[FAIL]${NC} $*"; FAIL=$((FAIL+1)); }
warn() { echo -e "${YELLOW}[WARN]${NC} $*"; }

# Resolve the source tree path and packaged path for session assets.
SOURCE_LABWC_DIR="desktop/session/labwc"
# Source for session scripts: desktop/session/
SOURCE_SESSION_DIR="desktop/session"
# Shell source: desktop/shell/
SOURCE_SHELL_DIR="desktop/shell"
# Packaged (chroot) target
PKG_BRIGHT_OS_DIR="config/includes.chroot/usr/share/bright-os"
PKG_SESSIONS_DIR="config/includes.chroot/usr/share/wayland-sessions"

echo "============================================"
echo "  Phase 6.1 labwc PoC static tests"
echo "============================================"

require_python3() {
    if ! command -v python3 >/dev/null 2>&1; then
        echo "SKIP: python3 not available"
        exit 0
    fi
}
require_python3

# --- File presence -------------------------------------------------------
echo ""
echo "--- Required labwc session files exist ---"

for f in \
    "$SOURCE_LABWC_DIR/rc.xml" \
    "$SOURCE_LABWC_DIR/menu.xml" \
    "$SOURCE_LABWC_DIR/themerc" \
    "$SOURCE_LABWC_DIR/environment" \
    "$SOURCE_LABWC_DIR/autostart" \
    "$SOURCE_SESSION_DIR/bright-desktop-session-labwc.sh" \
    "$PKG_BRIGHT_OS_DIR/labwc/rc.xml" \
    "$PKG_BRIGHT_OS_DIR/labwc/menu.xml" \
    "$PKG_BRIGHT_OS_DIR/labwc/themerc" \
    "$PKG_BRIGHT_OS_DIR/labwc/environment" \
    "$PKG_BRIGHT_OS_DIR/labwc/autostart" \
    "$PKG_BRIGHT_OS_DIR/bright-desktop-session-labwc.sh" \
    "$PKG_SESSIONS_DIR/bright.desktop" \
    ; do
    if [ -f "$f" ]; then
        pass "File present: $f"
    else
        fail "File missing: $f"
    fi
done

# --- Scripts are executable ---------------------------------------------
echo ""
echo "--- Executable bits ---"
for f in \
    "$PKG_BRIGHT_OS_DIR/labwc/autostart" \
    "$PKG_BRIGHT_OS_DIR/bright-desktop-session-labwc.sh" \
    ; do
    if [ -x "$f" ]; then
        pass "Executable: $f"
    else
        fail "Not executable: $f"
    fi
done

# --- Shell syntax --------------------------------------------------------
echo ""
echo "--- Shell syntax ---"
for f in \
    "$PKG_BRIGHT_OS_DIR/labwc/autostart" \
    "$PKG_BRIGHT_OS_DIR/bright-desktop-session-labwc.sh" \
    "$SOURCE_SESSION_DIR/bright-desktop-session-labwc.sh" \
    ; do
    if bash -n "$f" 2>/tmp/err; then
        pass "bash -n: $(basename $f)"
    else
        fail "bash -n: $(basename $f): $(cat /tmp/err)"
    fi
done

# --- Python syntax for the modified shell -------------------------------
echo ""
echo "--- Python syntax ---"
for f in desktop/shell/bright-desktop-shell.py config/includes.chroot/usr/share/bright-os/bright-desktop-shell.py; do
    if python3 -c "import py_compile; py_compile.compile('$f', doraise=True)" 2>/tmp/err; then
        pass "py_compile: $f"
    else
        fail "py_compile: $f: $(cat /tmp/err)"
    fi
done

# --- XML well-formedness ------------------------------------------------
echo ""
echo "--- XML well-formedness ---"
for f in "$SOURCE_LABWC_DIR/rc.xml" "$SOURCE_LABWC_DIR/menu.xml" \
         "$PKG_BRIGHT_OS_DIR/labwc/rc.xml" "$PKG_BRIGHT_OS_DIR/labwc/menu.xml"; do
    if python3 -c "
import xml.etree.ElementTree as ET, sys
ET.parse('$f')" 2>/tmp/err; then
        pass "Valid XML: $f"
    else
        fail "Invalid XML: $f: $(cat /tmp/err)"
    fi
done

# --- rc.xml root element and key sections -------------------------------
echo ""
echo "--- rc.xml structure ---"
f="$PKG_BRIGHT_OS_DIR/labwc/rc.xml"
if python3 -c "
import xml.etree.ElementTree as ET, sys
root = ET.parse('$f').getroot()
assert root.tag == 'labwc_config', f'root tag is {root.tag}'
assert root.find('keyboard') is not None, 'missing <keyboard>'
assert root.find('mouse') is not None, 'missing <mouse>'
assert root.find('windowRules') is not None, 'missing <windowRules>'
assert root.find('theme') is not None, 'missing <theme>'
" 2>/tmp/err; then
    pass "rc.xml has <labwc_config>/keyboard/mouse/windowRules/theme"
else
    fail "rc.xml structure issue: $(cat /tmp/err)"
fi

# --- bright.desktop (labwc default) content ----------------------------
echo ""
echo "--- Default labwc session .desktop file validation ---"
DESKTOP="$PKG_SESSIONS_DIR/bright.desktop"
for key in "Name=Bright Desktop" "TryExec=labwc" \
           "Exec=/usr/share/bright-os/bright-desktop-session-labwc.sh" \
           "Type=Application" "DesktopNames=Bright"; do
    if grep -qF "$key" "$DESKTOP"; then
        pass "bright.desktop (labwc) contains: $key"
    else
        fail "bright.desktop (labwc) missing key: $key"
    fi
done

# --- KWin recovery session is NOT present by default (hook writes it if kwin exists) ---
echo ""
echo "--- KWin recovery session (bright-kwin.desktop) written by hook only when kwin_wayland present ---"
KWIN_DESKTOP="$PKG_SESSIONS_DIR/bright-kwin.desktop"
if [ -f "$KWIN_DESKTOP" ]; then
    warn "bright-kwin.desktop is pre-installed in includes (should be hook-generated only if kwin present)"
else
    pass "bright-kwin.desktop is not pre-installed (will be generated by 00-sessions hook when kwin_wayland exists)"
fi
# Verify the hook that writes bright-kwin.desktop exists and checks for kwin_wayland
KWIN_HOOK="config/hooks/live/00-bright-os-session-files.hook.chroot"
if [ -f "$KWIN_HOOK" ] && grep -q "kwin_wayland" "$KWIN_HOOK"; then
    pass "00-sessions hook conditionally generates bright-kwin.desktop when kwin_wayland present"
else
    fail "00-sessions hook missing or doesn't check for kwin_wayland"
fi

# --- KWin wrapper /usr/bin/bright-desktop-shell unchanged --------------
KWIN_WRAPPER="config/includes.chroot/usr/bin/bright-desktop-shell"
if grep -qF "kwin_wayland" "$KWIN_WRAPPER"; then
    pass "/usr/bin/bright-desktop-shell still contains kwin_wayland invocation"
else
    fail "/usr/bin/bright-desktop-shell no longer invokes kwin_wayland"
fi

# --- bright-desktop-session.sh (KWin path) unchanged -------------------
KWIN_SESSION="$PKG_BRIGHT_OS_DIR/bright-desktop-session.sh"
if grep -qF "kwin_wayland" "$KWIN_SESSION"; then
    pass "bright-desktop-session.sh still references kwin_wayland"
else
    fail "bright-desktop-session.sh no longer references kwin_wayland"
fi

# --- Phase 6.3: labwc is now the default compositor in core -------------
echo ""
echo "--- Core package list includes labwc (default compositor in Phase 6.3) ---"
if grep -q "^labwc$" config/package-lists/core.list.chroot; then
    pass "core.list.chroot includes labwc (default compositor)"
else
    fail "core.list.chroot missing labwc (default compositor)"
fi
if grep -q "^greetd$" config/package-lists/core.list.chroot; then
    pass "core.list.chroot includes greetd (lightweight display manager)"
else
    fail "core.list.chroot missing greetd"
fi

# --- Packaged copies in sync --------------------------------------------
echo ""
echo "--- Source / packaged copies are in sync ---"
check_sync() {
    local src="$1" pkg="$2" name="$3"
    if diff -q "$src" "$pkg" >/dev/null 2>&1; then
        pass "Source and packaged $name are identical"
    else
        fail "Source and packaged $name DIFFER (sync broken)"
        diff "$src" "$pkg" | head -20
    fi
}
check_sync desktop/shell/bright-desktop-shell.py \
           "$PKG_BRIGHT_OS_DIR/bright-desktop-shell.py" \
           "bright-desktop-shell.py"
check_sync desktop/session/bright-desktop-session-labwc.sh \
           "$PKG_BRIGHT_OS_DIR/bright-desktop-session-labwc.sh" \
           "bright-desktop-session-labwc.sh"
for f in rc.xml menu.xml themerc environment autostart; do
    check_sync "$SOURCE_LABWC_DIR/$f" "$PKG_BRIGHT_OS_DIR/labwc/$f" "labwc/$f"
done

# --- Python shell accepts --qml flag (PoC feature) ----------------------
echo ""
echo "--- Python shell CLI flags ---"
# We grep the source for the argparse --qml definition (PyQt6 may not be
# installed in the static-test environment, so we cannot execute --help).
if grep -qE 'add_argument\(.*"--qml"' "$SOURCE_SHELL_DIR/bright-desktop-shell.py"; then
    pass "bright-desktop-shell.py defines --qml CLI argument"
else
    fail "bright-desktop-shell.py does not define --qml CLI argument"
fi
# Also verify the BRIGHT_SHELL_COMPOSITOR env var is read
if grep -q "BRIGHT_SHELL_COMPOSITOR" "$SOURCE_SHELL_DIR/bright-desktop-shell.py"; then
    pass "bright-desktop-shell.py reads BRIGHT_SHELL_COMPOSITOR env var"
else
    fail "bright-desktop-shell.py does not read BRIGHT_SHELL_COMPOSITOR env var"
fi

# --- Environment file sets required variables --------------------------
echo ""
echo "--- labwc environment file ---"
for kv in "XDG_CURRENT_DESKTOP=Bright:labwc" \
          "XDG_SESSION_TYPE=wayland" \
          "QT_QPA_PLATFORM=wayland;xcb" \
          "BRIGHT_SHELL_COMPOSITOR=labwc"; do
    if grep -qF "$kv" "$PKG_BRIGHT_OS_DIR/labwc/environment"; then
        pass "environment contains: $kv"
    else
        fail "environment missing: $kv"
    fi
done

# --- Autostart execs the shell ------------------------------------------
echo ""
echo "--- labwc autostart ---"
if grep -q "bright-desktop-shell.py" "$PKG_BRIGHT_OS_DIR/labwc/autostart"; then
    pass "autostart invokes bright-desktop-shell.py"
else
    fail "autostart does not invoke bright-desktop-shell.py"
fi
if grep -q "polkit-gnome-authentication-agent-1\|lxpolkit\|lxqt-policykit-agent" "$PKG_BRIGHT_OS_DIR/labwc/autostart"; then
    pass "autostart starts a polkit authentication agent"
else
    fail "autostart does not start any polkit agent"
fi
if grep -q "pipewire" "$PKG_BRIGHT_OS_DIR/labwc/autostart"; then
    pass "autostart handles pipewire startup"
else
    fail "autostart does not reference pipewire"
fi

# --- Shell script runs labwc (not kwin_wayland) ------------------------
echo ""
echo "--- labwc session script ---"
if grep -q "exec labwc" "$PKG_BRIGHT_OS_DIR/bright-desktop-session-labwc.sh"; then
    pass "labwc session script execs labwc"
else
    fail "labwc session script does not exec labwc"
fi
if grep -qE 'LABWC_CONFIG_DIR=.*?/usr/share/bright-os/labwc' "$PKG_BRIGHT_OS_DIR/bright-desktop-session-labwc.sh"; then
    pass "labwc session script uses Bright OS config dir"
else
    fail "labwc session script does not set config dir"
fi
if grep -qE 'exec[[:space:]]+labwc.*--config-dir' "$PKG_BRIGHT_OS_DIR/bright-desktop-session-labwc.sh"; then
    pass "labwc session script passes --config-dir to labwc"
else
    fail "labwc session script does not pass --config-dir to labwc"
fi

# --- Phase 6.3: labwc is in core; verify labwc-related packages are present
echo ""
echo "--- Core list includes labwc support packages ---"
for pkg in labwc greetd cage gtkgreet layer-shell-qt qml6-module-org-kde-layershell \
           xdg-desktop-portal-wlr mako-notifier swaylock swayidle kanshi grim slurp; do
    if grep -q "^${pkg}$" config/package-lists/core.list.chroot; then
        pass "core.list.chroot includes $pkg"
    else
        fail "core.list.chroot missing $pkg"
    fi
done
# Recovery profile still provides KWin+SDDM fallback
if grep -q "^sddm$" config/package-lists/optional-recovery-kwin.list.chroot \
   && grep -q "^kwin-wayland$" config/package-lists/optional-recovery-kwin.list.chroot; then
    pass "optional-recovery-kwin includes sddm + kwin-wayland (recovery path)"
else
    fail "optional-recovery-kwin missing sddm or kwin-wayland"
fi

# --- Summary ------------------------------------------------------------
echo ""
echo "============================================"
echo "  Results: $PASS passed, $FAIL failed"
echo "============================================"
echo ""
echo "NOTE: These are static tests only. They verify files, syntax, and"
echo "fallback preservation. The following require a booted labwc session"
echo "(QEMU KVM / hardware) and are NOT validated here:"
echo "  - labwc starts successfully"
echo "  - Shell window appears under labwc"
echo "  - Panel/dock/launcher are usable"
echo "  - Wayland/XWayland apps launch"
echo "  - Window focus/move/resize/switching work"
echo "  - Screen lock / logout works"
echo "  - Polkit prompts appear"
echo "  - AURA D-Bus activation still functions"
echo "  - Bright Android session activation still functions"
echo "See docs/PHASE-6-ARCHITECTURE-PLAN.md §4 for PoC acceptance criteria."

if [ "$FAIL" -eq 0 ]; then
    echo -e "${GREEN}All labwc PoC static tests passed!${NC}"
    exit 0
else
    echo -e "${RED}Some labwc PoC tests failed.${NC}"
    exit 1
fi
