#!/bin/bash
# =============================================================================
# Phase 6.3 tests: lightweight core architecture
#
# Verifies that:
#   - labwc is the default compositor (in core.list.chroot)
#   - greetd is the default display manager
#   - Heavy KDE/Plasma packages are NOT in core
#   - Optional profiles exist for bluetooth/printing/wine/android/devtools
#   - AURA on-demand activation preserved (no boot-time enable)
#   - Bright Android session-activated (not boot-time)
#   - Calamares preserved
#   - Recovery path (KWin+SDDM) available via optional profile
#   - Optional services are masked by default
# =============================================================================
set -eu

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"
cd "${PROJECT_ROOT}"

# common.sh is a project helper; if it exists source it, otherwise proceed.
if [ -f "${SCRIPT_DIR}/support/common.sh" ]; then
    # shellcheck source=support/common.sh
    source "${SCRIPT_DIR}/support/common.sh"
fi

PASS=0
FAIL=0
pass() { PASS=$((PASS+1)); echo -e "\033[0;32m[PASS]\033[0m $1"; }
fail() { FAIL=$((FAIL+1)); echo -e "\033[0;31m[FAIL]\033[0m $1"; }

CORE=config/package-lists/core.list.chroot
RECOVERY=config/package-lists/optional-recovery-kwin.list.chroot

echo "============================================================"
echo "Phase 6.3: Lightweight Core Architecture"
echo "============================================================"

echo ""
echo "--- Default compositor is labwc ---"
grep -q "^labwc$" "$CORE" && pass "labwc in core (default compositor)" || fail "labwc missing from core"
for pkg in layer-shell-qt xdg-desktop-portal-wlr mako-notifier swaylock swayidle kanshi grim slurp brightnessctl; do
    grep -q "^${pkg}$" "$CORE" && pass "$pkg in core (labwc support)" || fail "$pkg missing from core"
done

echo ""
echo "--- Default display manager is greetd ---"
grep -q "^greetd$" "$CORE" && pass "greetd in core (default DM)" || fail "greetd missing"
grep -q "^gtkgreet$" "$CORE" && pass "gtkgreet in core (GTK greeter)" || fail "gtkgreet missing"
grep -q "^cage$" "$CORE" && pass "cage in core (kiosk compositor for greeter)" || fail "cage missing"
[ -f config/includes.chroot/etc/greetd/config.toml ] && pass "greetd config.toml present" || fail "greetd config.toml missing"
grep -q "cage -s -- gtkgreet" config/includes.chroot/etc/greetd/config.toml \
    && pass "greetd config launches cage + gtkgreet" || fail "greetd config doesn't launch cage/gtkgreet"
[ -f config/includes.chroot/usr/lib/sysusers.d/bright-greeter.conf ] \
    && pass "greeter sysusers.d entry present" || fail "greeter sysusers.d missing"
grep -q "greeter" config/hooks/live/15-display-manager.hook.chroot \
    && pass "display-manager hook handles greetd" || fail "display-manager hook missing greetd"

echo ""
echo "--- Heavy packages NOT in core (moved to optional/recovery) ---"
HEAVY_PKGS="sddm kwin-wayland plasma-desktop plasma-workspace plasma-nm plasma-pa
            bluedevil powerdevil print-manager plasma-discover sddm-theme-debian-breeze
            kde-config-gtk-style breeze-gtk cups bluez wine shim-signed grub-efi-amd64-signed
            plymouth linux-headers-amd64 qemu-system-x86"
for pkg in $HEAVY_PKGS; do
    if grep -v "^#" "$CORE" | grep -q "^${pkg}$"; then
        fail "$pkg still in core (should be optional)"
    else
        pass "$pkg not in core (optional only)"
    fi
done

echo ""
echo "--- Recovery profile (KWin+SDDM) preserved ---"
for pkg in sddm kwin-wayland sddm-theme-debian-breeze; do
    grep -q "^${pkg}$" "$RECOVERY" && pass "$pkg in recovery profile" || fail "$pkg missing from recovery"
done

echo ""
echo "--- Optional profiles exist for separable features ---"
PROFILES="optional-bluetooth optional-printing optional-network-extras optional-wine
          optional-devtools-core optional-secureboot optional-plymouth optional-qemu"
for profile in $PROFILES; do
    [ -f "config/package-lists/${profile}.list.chroot" ] \
        && pass "${profile} exists" \
        || fail "${profile} missing"
done
# Bluetooth profile contains bluez
grep -q "^bluez$" config/package-lists/optional-bluetooth.list.chroot \
    && pass "Bluetooth profile ships bluez" || fail "Bluetooth profile missing bluez"
# Printing profile contains cups
grep -q "^cups$" config/package-lists/optional-printing.list.chroot \
    && pass "Printing profile ships cups" || fail "Printing profile missing cups"
# Wine profile ships wine
grep -q "^wine$" config/package-lists/optional-wine.list.chroot \
    && pass "Wine profile ships wine" || fail "Wine profile missing wine"

echo ""
echo "--- AURA activation is on-demand (NOT started at boot) ---"
AURA_SVC=config/includes.chroot/etc/systemd/system/aura-core.service
if grep -q "^WantedBy=" "$AURA_SVC"; then
    fail "AURA service has WantedBy= (would start at boot)"
else
    pass "AURA service has no WantedBy= (D-Bus activation only)"
fi
grep -q "Alias=aura.service" "$AURA_SVC" && pass "AURA has D-Bus activatable alias" || fail "AURA missing Alias="
# AURA hardening preserved
for s in NoNewPrivileges PrivateTmp ProtectSystem; do
    grep -q "^${s}=" "$AURA_SVC" && pass "AURA hardening: ${s}" || fail "AURA hardening missing: ${s}"
done

echo ""
echo "--- Bright Android is session-activated (not enabled at boot) ---"
BA_SVC=config/includes.chroot/usr/lib/systemd/user/bright-android.service
[ -f "$BA_SVC" ] && pass "Bright Android user service present" || fail "Bright Android user service missing"
# It must NOT be in system-level systemd (WantedBy multi-user)
if grep -rq "WantedBy=multi-user" config/includes.chroot/etc/systemd/system/ 2>/dev/null; then
    : # other services may have it, just check there's no bright-android one
fi
if [ -f config/includes.chroot/etc/systemd/system/bright-android.service ]; then
    fail "Bright Android has a system-level service (should be user/session only)"
else
    pass "Bright Android has no system-level service (session-activated)"
fi

echo ""
echo "--- Installer (Calamares) preserved ---"
for pkg in calamares calamares-settings-debian grub-pc-bin grub-efi-amd64-bin grub-common os-prober parted cryptsetup; do
    grep -q "^${pkg}$" "$CORE" && pass "$pkg in core (installer support)" || fail "$pkg missing from core (needed by installer)"
done
[ -f installer/calamares/modules/displaymanager.conf ] \
    && pass "Calamares displaymanager.conf present" || fail "Calamares displaymanager.conf missing"
grep -q "greetd" installer/calamares/modules/displaymanager.conf \
    && pass "Calamares config knows about greetd" || fail "Calamares doesn't list greetd"

echo ""
echo "--- Non-essential services masked by default ---"
grep -q "bluetooth.service" build/scripts/build.sh \
    && pass "build.sh masks bluetooth.service by default" || fail "bluetooth.service not masked"
grep -q "cups.service" build/scripts/build.sh \
    && pass "build.sh masks cups.service by default" || fail "cups.service not masked"
grep -q "ModemManager.service" build/scripts/build.sh \
    && pass "build.sh masks ModemManager.service by default" || fail "ModemManager not masked"
grep -q "avahi-daemon.service" build/scripts/build.sh \
    && pass "build.sh masks avahi-daemon.service by default" || fail "avahi not masked"

echo ""
echo "--- Components hook enables greetd, not sddm by default ---"
grep -q "systemctl enable greetd" config/hooks/live/10-bright-os-components.hook.chroot \
    && pass "Components hook enables greetd" || fail "greetd not enabled by hook"
# SDDM should NOT be unconditionally enabled
if grep -q "systemctl enable sddm" config/hooks/live/10-bright-os-components.hook.chroot; then
    fail "Components hook unconditionally enables sddm"
else
    pass "Components hook does not unconditionally enable sddm"
fi

echo ""
echo "=== Summary ==="
echo "============================================"
echo "  Results: $PASS passed, $FAIL failed"
echo "============================================"
if [ "$FAIL" -gt 0 ]; then
    echo "Phase 6.3 lightweight checks FAILED."
    exit 1
fi
echo "Phase 6.3 lightweight architecture checks pass."
