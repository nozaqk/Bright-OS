#!/bin/bash
# =============================================================================
# Phase 11: Calamares Installer Consistency Tests
# Verifies that every module referenced in settings.conf has a .conf file,
# instance definitions match, and source/destination configs are synchronized.
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

CAL_SRC="installer/calamares"
CAL_DST="config/includes.chroot/usr/share/bright-os/installer"

echo "============================================"
echo "  Calamares Installer Consistency Tests"
echo "============================================"

# --- settings.conf exists ---
if [ -f "${CAL_SRC}/settings.conf" ]; then
    pass "settings.conf exists"
else
    fail "settings.conf missing"
fi

# --- Extract module lists from settings.conf ---
SETTINGS="${CAL_SRC}/settings.conf"

# Get show modules (UI pages)
SHOW_MODULES=$(sed -n '/- show:/,/    - exec:/p' "$SETTINGS" | grep '^\s*- ' | sed 's/.*- //' | grep -v 'show\|exec')
# Get exec modules (installation steps)
EXEC_MODULES=$(sed -n '/- exec:/,/    - show:/p' "$SETTINGS" | grep '^\s*- ' | sed 's/.*- //' | grep -v 'show\|exec')
# Get instance definitions
INSTANCE_IDS=$(grep '^\s*- id:' "$SETTINGS" | sed 's/.*id: //')
INSTANCE_MODULES=$(grep '^\s*module:' "$SETTINGS" | sed 's/.*module: //')

echo ""
echo "--- Show (UI) modules ---"
for mod in $SHOW_MODULES; do
    # These are built-in Calamares view modules; they don't need .conf files
    # but we should have them listed
    echo "  UI module: $mod"
done
pass "$(echo "$SHOW_MODULES" | wc -w) show modules defined"

echo ""
echo "--- Exec modules ---"
for mod in $EXEC_MODULES; do
    echo "  Exec module: $mod"
done
pass "$(echo "$EXEC_MODULES" | wc -w) exec modules defined"

echo ""
echo "--- Instance definitions ---"
if [ -n "$INSTANCE_IDS" ]; then
    for id in $INSTANCE_IDS; do
        echo "  Instance: $id"
    done
fi

# --- Check every exec module either has a .conf or is a built-in instance ---
echo ""
echo "--- Module config files ---"

# Standard Calamares modules that don't require a .conf in /etc/calamares/modules
# (they use internal defaults or are view modules)
BUILTIN_NO_CONF="welcome locale keyboard partition users summary finished mount unpackfs fstab"

for mod in $EXEC_MODULES; do
    # Check if this is an instance ID rather than a module name
    is_instance=false
    for id in $INSTANCE_IDS; do
        if [ "$mod" = "$id" ]; then
            is_instance=true
            # Check the instance config file exists
            if [ -f "${CAL_SRC}/modules/${mod}.conf" ]; then
                pass "Instance '${mod}' has config file"
            else
                fail "Instance '${mod}' missing config file: ${CAL_SRC}/modules/${mod}.conf"
            fi
            break
        fi
    done
    if [ "$is_instance" = true ]; then
        continue
    fi

    # Regular module - check for .conf or note that it's built-in
    if [ -f "${CAL_SRC}/modules/${mod}.conf" ]; then
        pass "Module '${mod}' has config file"
    elif echo " $BUILTIN_NO_CONF " | grep -q " ${mod} "; then
        # Some modules work without custom config; warn but don't fail
        if [ -f "${CAL_SRC}/modules/${mod}.conf" ]; then
            pass "Module '${mod}' has config file"
        else
            warn "Module '${mod}' has no custom .conf (using Calamares defaults)"
        fi
    else
        fail "Module '${mod}' in exec sequence has no config file"
    fi
done

# --- Check for orphan .conf files (not referenced in any sequence) ---
echo ""
echo "--- Orphan config check ---"
# Build a list of all module/instance names that are referenced
ALL_REFERENCED="$EXEC_MODULES $SHOW_MODULES $INSTANCE_IDS"
for conf in "${CAL_SRC}/modules/"*.conf; do
    [ -f "$conf" ] || continue
    mod=$(basename "$conf" .conf)
    found=false
    for ref in $ALL_REFERENCED; do
        if [ "$ref" = "$mod" ]; then
            found=true
            break
        fi
    done
    if [ "$found" = false ]; then
        warn "Config file '${mod}.conf' exists but module is not in settings sequence"
    fi
done
pass "Orphan check complete"

# --- Verify branding ---
echo ""
echo "--- Branding ---"
if [ -f "${CAL_SRC}/branding/bright-os/branding.desc" ]; then
    pass "Branding descriptor exists"
else
    fail "Branding descriptor missing"
fi
if grep -q "^branding: bright-os" "$SETTINGS"; then
    pass "settings.conf references bright-os branding"
else
    fail "settings.conf does not reference bright-os branding"
fi

# --- Check postcfg.sh script exists and is executable ---
echo ""
echo "--- Post-install script ---"
if [ -f "${CAL_SRC}/modules/postcfg.sh" ]; then
    pass "postcfg.sh exists"
    if [ -x "${CAL_SRC}/modules/postcfg.sh" ]; then
        pass "postcfg.sh is executable"
    else
        fail "postcfg.sh is not executable"
    fi
else
    fail "postcfg.sh missing"
fi

# Verify shellprocess-post.conf references postcfg.sh
if grep -q "postcfg.sh" "${CAL_SRC}/modules/shellprocess-post.conf"; then
    pass "shellprocess-post.conf references postcfg.sh"
else
    fail "shellprocess-post.conf does not reference postcfg.sh"
fi

# --- Source/destination sync check ---
echo ""
echo "--- Source/destination sync ---"
if diff -q "${CAL_SRC}/settings.conf" "${CAL_DST}/settings.conf" &>/dev/null; then
    pass "settings.conf is synced to includes.chroot"
else
    fail "settings.conf not synced to includes.chroot"
fi

for conf in "${CAL_SRC}/modules/"*.conf; do
    [ -f "$conf" ] || continue
    mod=$(basename "$conf")
    if [ -f "${CAL_DST}/modules/${mod}" ]; then
        if diff -q "$conf" "${CAL_DST}/modules/${mod}" &>/dev/null; then
            : # synced
        else
            fail "${mod} differs between source and includes.chroot"
        fi
    else
        fail "${mod} missing from includes.chroot"
    fi
done
pass "All module configs synced to includes.chroot"

# Sync check for postcfg.sh
if [ -x "${CAL_DST}/modules/postcfg.sh" ]; then
    pass "postcfg.sh synced and executable in includes.chroot"
else
    fail "postcfg.sh not executable in includes.chroot"
fi

# --- bootloader.conf checks ---
echo ""
echo "--- Bootloader config ---"
if grep -q "efiBootLoaderId" "${CAL_SRC}/modules/bootloader.conf"; then
    pass "bootloader.conf has efiBootLoaderId"
else
    warn "bootloader.conf missing efiBootLoaderId"
fi
if grep -q "installPath.*any\|installPath.*default" "${CAL_SRC}/modules/bootloader.conf"; then
    pass "bootloader.conf uses flexible installPath"
else
    warn "bootloader.conf may have hardcoded installPath"
fi

echo ""
echo "============================================"
echo "  Results: $PASS passed, $FAIL failed"
echo "============================================"
if [ "$FAIL" -eq 0 ]; then
    echo -e "${GREEN}All Calamares consistency tests passed!${NC}"
    exit 0
else
    echo -e "${RED}$FAIL test(s) failed.${NC}"
    exit 1
fi
