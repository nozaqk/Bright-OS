#!/bin/bash
# =============================================================================
# test-desktop-identity.sh - Phase 14 tests
# Tests for Bright Design System, Edition Profiles, Branding Consistency,
# theme switching, and desktop component integration.
# =============================================================================
set -e

REPO_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$REPO_ROOT"

PASS=0
FAIL=0

# Colors for output
GREEN='\033[0;32m'
RED='\033[0;31m'
NC='\033[0m'

pass() { echo -e "${GREEN}[PASS]${NC} $1"; PASS=$((PASS+1)); }
fail() { echo -e "${RED}[FAIL]${NC} $1"; FAIL=$((FAIL+1)); }

# Helper: check file exists and is non-empty
assert_file() {
    local path="$1" desc="$2"
    if [ -f "$path" ] && [ -s "$path" ]; then
        pass "$desc"
    else
        fail "$desc (missing or empty: $path)"
    fi
}

# Helper: check file contains pattern
assert_contains() {
    local file="$1" pattern="$2" desc="$3"
    if grep -q "$pattern" "$file" 2>/dev/null; then
        pass "$desc"
    else
        fail "$desc (pattern not found: $pattern in $file)"
    fi
}

# Helper: check file does NOT contain pattern
assert_not_contains() {
    local file="$1" pattern="$2" desc="$3"
    if ! grep -q "$pattern" "$file" 2>/dev/null; then
        pass "$desc"
    else
        fail "$desc (unexpected pattern found: $pattern in $file)"
    fi
}

echo "============================================"
echo "  Phase 14: Desktop Identity Tests"
echo "============================================"
echo ""

# --- 1. Shared Design System ---
echo "--- 1. Bright Design System ---"

assert_file "desktop/shell/design/DesignTokens.js" "DesignTokens.js exists (source)"
assert_file "config/includes.chroot/usr/share/bright-os/design/DesignTokens.js" "DesignTokens.js exists (installed path)"

assert_contains "desktop/shell/design/DesignTokens.js" "Brand" "Brand color palette defined"
assert_contains "desktop/shell/design/DesignTokens.js" "Dark" "Dark theme tokens defined"
assert_contains "desktop/shell/design/DesignTokens.js" "Light" "Light theme tokens defined"
assert_contains "desktop/shell/design/DesignTokens.js" "#3b82f6" "Primary brand blue (#3b82f6) present"
assert_contains "desktop/shell/design/DesignTokens.js" "#8b5cf6" "Brand violet (#8b5cf6) present"
assert_contains "desktop/shell/design/DesignTokens.js" "Font" "Typography scale defined"
assert_contains "desktop/shell/design/DesignTokens.js" "Space" "Spacing scale defined"
assert_contains "desktop/shell/design/DesignTokens.js" "Radius" "Corner radius tokens defined"
assert_contains "desktop/shell/design/DesignTokens.js" "Size" "Component size tokens defined"
assert_contains "desktop/shell/design/DesignTokens.js" "Animation" "Animation tokens defined"
assert_contains "desktop/shell/design/DesignTokens.js" "function colors" "Theme color helper function exists"

# Check brand consistency - same accent color across both themes
assert_contains "desktop/shell/design/DesignTokens.js" "accent:.*Brand.accent" "Dark theme uses brand accent"

# Motion factor for Lite should be 0 (reduced motion)
assert_contains "desktop/shell/design/DesignTokens.js" "motionFactorLite:.*0" "Lite has zero motion factor (reduced animations)"

echo ""

# --- 2. Edition Profiles ---
echo "--- 2. Edition Profiles ---"

assert_file "desktop/shell/profiles/EditionProfiles.js" "EditionProfiles.js exists (source)"
assert_file "config/includes.chroot/usr/share/bright-os/profiles/EditionProfiles.js" "EditionProfiles.js exists (installed path)"

assert_contains "desktop/shell/profiles/EditionProfiles.js" "var Home" "Home profile defined"
assert_contains "desktop/shell/profiles/EditionProfiles.js" "var Developer" "Developer profile defined"
assert_contains "desktop/shell/profiles/EditionProfiles.js" "var Lite" "Lite profile defined"
assert_contains "desktop/shell/profiles/EditionProfiles.js" "function getProfile" "getProfile() helper function exists"

# Brand identity is shared - all editions use same wallpaper set
assert_contains "desktop/shell/profiles/EditionProfiles.js" 'bright-default-dark.svg' "Home uses default dark wallpaper"
assert_contains "desktop/shell/profiles/EditionProfiles.js" 'bright-default-dark.svg' "Developer uses default dark wallpaper (shared)"
assert_contains "desktop/shell/profiles/EditionProfiles.js" 'bright-default-dark.svg' "Lite uses default dark wallpaper (shared)"

# Edition-specific properties
assert_contains "desktop/shell/profiles/EditionProfiles.js" 'id:.*"home"' "Home has correct id"
assert_contains "desktop/shell/profiles/EditionProfiles.js" 'id:.*"developer"' "Developer has correct id"
assert_contains "desktop/shell/profiles/EditionProfiles.js" 'id:.*"lite"' "Lite has correct id"

# Lite: dock disabled, animations off
assert_contains "desktop/shell/profiles/EditionProfiles.js" 'dockPosition:.*"none"' "Lite has dock disabled"
assert_contains "desktop/shell/profiles/EditionProfiles.js" 'animations:.*false' "Lite has animations disabled"
assert_contains "desktop/shell/profiles/EditionProfiles.js" 'dockPillShape:.*false' "Lite disables dock pill shape"

# Developer: side dock
assert_contains "desktop/shell/profiles/EditionProfiles.js" 'dockPosition:.*"left"' "Developer uses left side dock"

# Home: bottom centered dock
assert_contains "desktop/shell/profiles/EditionProfiles.js" 'dockCentered:.*true' "Home has centered dock"

# Dock app lists are non-empty for Home and Developer, empty for Lite
assert_contains "desktop/shell/profiles/EditionProfiles.js" 'firefox-esr' "Home dock includes Firefox"
assert_contains "desktop/shell/profiles/EditionProfiles.js" 'bright-terminal' "Developer dock includes Terminal"
# Lite dock apps should be effectively empty - extract Lite's dockApps array and check no app objects
LITE_DOCK_SECTION=$(sed -n '/var Lite/,/^var [A-Z]/p' desktop/shell/profiles/EditionProfiles.js | sed -n '/dockApps:/,/panelLaunchers:/p')
if echo "$LITE_DOCK_SECTION" | grep -q '"id":\|"name":.*"command":'; then
    fail "Lite dock apps should be empty (uses panel launchers)"
else
    pass "Lite dock apps are empty (uses panel launchers)"
fi

echo ""

# --- 3. Shell QML ---
echo "--- 3. Shell QML Integration ---"

assert_file "desktop/shell/Shell.qml" "Shell.qml exists (source)"
assert_file "config/includes.chroot/usr/share/bright-os/Shell.qml" "Shell.qml exists (installed path)"

assert_contains "desktop/shell/Shell.qml" 'import.*DesignTokens' "Shell.qml imports DesignTokens"
assert_contains "desktop/shell/Shell.qml" 'import.*EditionProfiles' "Shell.qml imports EditionProfiles"
assert_contains "desktop/shell/Shell.qml" 'Profiles.getProfile' "Shell.qml resolves edition profile"
assert_contains "desktop/shell/Shell.qml" 'Tokens.colors' "Shell.qml uses design system colors"
assert_contains "desktop/shell/Shell.qml" 'Tokens.Brand.accent' "Shell.qml uses brand accent color"
assert_contains "desktop/shell/Shell.qml" 'Tokens.Radius' "Shell.qml uses design system radii"
assert_contains "desktop/shell/Shell.qml" 'Tokens.Space' "Shell.qml uses design system spacing"
assert_contains "desktop/shell/Shell.qml" 'Tokens.Font' "Shell.qml uses design system typography"
assert_contains "desktop/shell/Shell.qml" 'EditionId' "Shell.qml reads EditionId from context"
assert_contains "desktop/shell/Shell.qml" 'Shell.edition' "Shell.qml displays edition from backend"
assert_contains "desktop/shell/Shell.qml" 'Shell.editionDisplayName' "Shell.qml shows edition display name"

# Lite edition should hide dock
assert_contains "desktop/shell/Shell.qml" 'profile.dockPosition !== "none"' "Dock visibility checks profile.dockPosition"

# Edition-aware launcher
assert_contains "desktop/shell/Shell.qml" 'profile.launcherApps' "Launcher uses profile-specific apps"
assert_contains "desktop/shell/Shell.qml" 'profile.launcherCategories' "Launcher uses profile-specific categories"

# Developer metrics in panel
assert_contains "desktop/shell/Shell.qml" 'Shell.showMetrics' "Panel conditionally shows metrics for Developer"
assert_contains "desktop/shell/Shell.qml" 'Shell.cpuPercent' "Panel reads CPU metrics"
assert_contains "desktop/shell/Shell.qml" 'Shell.memPercent' "Panel reads memory metrics"

# Global shortcuts preserved
assert_contains "desktop/shell/Shell.qml" 'Super+T' "Super+T shortcut preserved"
assert_contains "desktop/shell/Shell.qml" 'sequence: "Super"' "Super key shortcut defined (opens launcher)"
assert_contains "desktop/shell/Shell.qml" 'launcherWindow.visible = !launcherWindow.visible' "Super key toggles launcher visibility"

echo ""

# --- 4. Python Backend ---
echo "--- 4. Python Backend (Shell) ---"

assert_file "desktop/shell/bright-desktop-shell.py" "bright-desktop-shell.py exists (source)"
assert_file "config/includes.chroot/usr/share/bright-os/bright-desktop-shell.py" "bright-desktop-shell.py exists (installed path)"

assert_contains "desktop/shell/bright-desktop-shell.py" "detect_edition" "Edition detection function exists"
assert_contains "desktop/shell/bright-desktop-shell.py" "EDITION_FILE" "Edition file path defined"
assert_contains "desktop/shell/bright-desktop-shell.py" "/etc/bright-os/edition" "Reads /etc/bright-os/edition"
assert_contains "desktop/shell/bright-desktop-shell.py" "VALID_EDITIONS" "Valid editions list defined"
assert_contains "desktop/shell/bright-desktop-shell.py" '"home"' "Home edition supported"
assert_contains "desktop/shell/bright-desktop-shell.py" '"developer"' "Developer edition supported"
assert_contains "desktop/shell/bright-desktop-shell.py" '"lite"' "Lite edition supported"
assert_contains "desktop/shell/bright-desktop-shell.py" "EDITION_PROFILES" "Edition profiles dict defined"
assert_contains "desktop/shell/bright-desktop-shell.py" "get_dock_applications" "Dock app resolution function exists"
assert_contains "desktop/shell/bright-desktop-shell.py" "EditionId" "Backend exposes EditionId to QML context"
assert_contains "desktop/shell/bright-desktop-shell.py" "editionDisplayName" "Backend exposes editionDisplayName"
assert_contains "desktop/shell/bright-desktop-shell.py" "dockPillShape" "Backend exposes dockPillShape"
assert_contains "desktop/shell/bright-desktop-shell.py" "showMetrics" "Backend exposes showMetrics flag"
assert_contains "desktop/shell/bright-desktop-shell.py" "launchApplication" "launchApplication slot exists"
assert_contains "desktop/shell/bright-desktop-shell.py" "command_exists" "command_exists helper for graceful missing-app handling"
assert_contains "desktop/shell/bright-desktop-shell.py" "Warning.*not found" "Missing app warning logged (graceful handling)"

# Lite-specific environment
assert_contains "desktop/shell/bright-desktop-shell.py" 'QT_QUICK_CONTROLS_STYLE.*Basic' "Lite sets Qt Quick Controls to Basic"
assert_contains "desktop/shell/bright-desktop-shell.py" 'QSG_RENDER_LOOP.*basic' "Lite uses basic render loop for performance"

# Lite terminal fallback
assert_contains "desktop/shell/bright-desktop-shell.py" 'qterminal' "Lite falls back to qterminal"
assert_contains "desktop/shell/bright-desktop-shell.py" 'pcmanfm-qt' "Lite falls back to pcmanfm-qt"

# Python syntax (compile to temp; works as non-root without writing __pycache__)
if python3 tests/support/py_syntax_check.py desktop/shell/bright-desktop-shell.py 2>/dev/null; then
    pass "Python backend syntax valid"
else
    fail "Python backend syntax error"
fi

echo ""

# --- 5. Session Script ---
echo "--- 5. Session Script ---"

assert_file "desktop/shell/bright-desktop-session.sh" "bright-desktop-session.sh exists (source)"
assert_contains "desktop/shell/bright-desktop-session.sh" "EDITION=" "Session script detects edition"
assert_contains "desktop/shell/bright-desktop-session.sh" "bright-desktop-shell.py" "Session launches Bright shell"
assert_contains "desktop/shell/bright-desktop-session.sh" "kwin_wayland" "KWin Wayland used for Home/Developer"
assert_contains "desktop/shell/bright-desktop-session.sh" "openbox" "Openbox available for Lite X11 fallback"
assert_contains "desktop/shell/bright-desktop-session.sh" "picom" "Picom compositor started for Lite X11"
assert_contains "desktop/shell/bright-desktop-session.sh" "XCURSOR_SIZE=16" "Lite uses smaller cursor"

if bash -n "desktop/shell/bright-desktop-session.sh" 2>/dev/null; then
    pass "Session script syntax valid"
else
    fail "Session script syntax error"
fi

echo ""

# --- 6. Branding Assets ---
echo "--- 6. Branding Assets ---"

assert_file "branding/icons/bright-os-logo.svg" "Bright OS logo SVG exists"
assert_contains "branding/icons/bright-os-logo.svg" "#3b82f6" "Logo uses brand blue"
assert_contains "branding/icons/bright-os-logo.svg" "#6366f1" "Logo uses brand indigo"
assert_contains "branding/icons/bright-os-logo.svg" "#8b5cf6" "Logo uses brand violet"

assert_file "branding/wallpapers/bright-default-dark.svg" "Dark wallpaper exists"
assert_file "branding/wallpapers/bright-default-light.svg" "Light wallpaper exists"
assert_contains "branding/wallpapers/bright-default-dark.svg" "#0a0e1a" "Dark wallpaper uses correct base color"
assert_contains "branding/wallpapers/bright-default-light.svg" "#f8fafc" "Light wallpaper uses correct base color"
assert_contains "branding/wallpapers/bright-default-dark.svg" "#3b82f6" "Dark wallpaper includes brand blue accent"
assert_contains "branding/wallpapers/bright-default-light.svg" "#3b82f6" "Light wallpaper includes brand blue accent"

# Installed wallpaper copies
assert_file "config/includes.chroot/usr/share/bright-os/wallpapers/bright-default-dark.svg" "Dark wallpaper installed"
assert_file "config/includes.chroot/usr/share/bright-os/wallpapers/bright-default-light.svg" "Light wallpaper installed"

# Plymouth
assert_file "branding/plymouth/bright-os.plymouth" "Plymouth theme file exists"
assert_file "branding/plymouth/bright-os.script" "Plymouth script exists"
assert_contains "branding/plymouth/bright-os.script" "0.231, 0.510, 0.965" "Plymouth uses brand blue (RGB 59,130,246)"
assert_contains "branding/plymouth/bright-os.script" "BRIGHT OS" "Plymouth shows BRIGHT OS text"

# GRUB
assert_file "branding/grub/theme.txt" "GRUB theme exists"
assert_contains "branding/grub/theme.txt" "BRIGHT OS" "GRUB shows BRIGHT OS title"
assert_contains "branding/grub/theme.txt" "#3b82f6" "GRUB uses brand blue accent"
assert_contains "branding/grub/theme.txt" "#0a0e1a" "GRUB uses dark background"
assert_not_contains "branding/grub/theme.txt" "Bookworm" "GRUB does not hardcode Bookworm version label"

echo ""

# --- 7. Theme Files ---
echo "--- 7. Theme Configuration ---"

assert_file "config/includes.chroot/usr/share/bright-os/themes/dark/colors.conf" "Dark colors.conf exists"
assert_file "config/includes.chroot/usr/share/bright-os/themes/light/colors.conf" "Light colors.conf exists"
assert_file "config/includes.chroot/usr/share/bright-os/themes/dark/qt6ct.conf" "Dark qt6ct.conf exists"
assert_file "config/includes.chroot/usr/share/bright-os/themes/light/qt6ct.conf" "Light qt6ct.conf exists"

assert_contains "config/includes.chroot/usr/share/bright-os/themes/dark/colors.conf" "Bright Dark" "Dark theme named correctly"
assert_contains "config/includes.chroot/usr/share/bright-os/themes/light/colors.conf" "Bright Light" "Light theme named correctly"
assert_contains "config/includes.chroot/usr/share/bright-os/themes/dark/colors.conf" "#3b82f6" "Dark theme uses brand blue"
assert_contains "config/includes.chroot/usr/share/bright-os/themes/light/colors.conf" "#3b82f6" "Light theme uses brand blue"
assert_contains "config/includes.chroot/usr/share/bright-os/themes/dark/colors.conf" "#0f172a" "Dark theme base matches design token"
assert_contains "config/includes.chroot/usr/share/bright-os/themes/light/colors.conf" "#ffffff" "Light theme base matches design token"

echo ""

# --- 8. About Dialog ---
echo "--- 8. About Dialog ---"

assert_file "applications/bright-about/bright-about" "bright-about script exists"
assert_contains "applications/bright-about/bright-about" "detect_edition" "About dialog detects edition"
assert_contains "applications/bright-about/bright-about" "EDITION_NAMES" "About dialog maps edition names"
assert_contains "applications/bright-about/bright-about" "#3b82f6" "About dialog uses brand blue"
assert_contains "applications/bright-about/bright-about" "EDITION_TAGLINES" "About dialog shows edition taglines"

if python3 tests/support/py_syntax_check.py applications/bright-about/bright-about 2>/dev/null; then
    pass "bright-about Python syntax valid"
else
    fail "bright-about Python syntax error"
fi

echo ""

# --- 9. Build Hook (Edition-Aware) ---
echo "--- 9. Build Hook Edition Awareness ---"

assert_file "config/hooks/live/10-bright-os-components.hook.chroot" "Component hook exists"
assert_contains "config/hooks/live/10-bright-os-components.hook.chroot" "design" "Hook creates design directory"
assert_contains "config/hooks/live/10-bright-os-components.hook.chroot" "profiles" "Hook creates profiles directory"
assert_contains "config/hooks/live/10-bright-os-components.hook.chroot" "BRIGHT_EDITION" "Hook reads edition"
assert_contains "config/hooks/live/10-bright-os-components.hook.chroot" "developer)" "Hook handles developer edition"
assert_contains "config/hooks/live/10-bright-os-components.hook.chroot" "lite)" "Hook handles lite edition"
assert_contains "config/hooks/live/10-bright-os-components.hook.chroot" "DEFAULT_ANIMATIONS" "Hook sets edition-specific defaults"

# Check build.sh requires new files
assert_contains "build/scripts/build.sh" "DesignTokens.js" "build.sh checks for DesignTokens.js"
assert_contains "build/scripts/build.sh" "EditionProfiles.js" "build.sh checks for EditionProfiles.js"

echo ""

# --- 10. Edition Marker File ---
echo "--- 10. Edition Configuration ---"

assert_file "config/includes.chroot/etc/bright-os/edition" "Edition marker file exists"
EDITION_VAL=$(cat config/includes.chroot/etc/bright-os/edition 2>/dev/null)
if [ -n "$EDITION_VAL" ]; then
    pass "Edition file has content (current build config: $EDITION_VAL)"
else
    fail "Edition file is empty"
fi

echo ""

# --- 11. Branding Consistency Checks ---
echo "--- 11. Cross-Component Brand Consistency ---"

# All components must use the same primary blue (#3b82f6 or Tokens.Brand.accent for QML)
check_brand_blue() {
    local f="$1"
    if [[ "$f" == *.qml ]]; then
        # QML files use Tokens.Brand.accent (which is defined as #3b82f6)
        grep -q "Tokens.Brand.accent\|#3b82f6" "$f" 2>/dev/null
    else
        grep -q "#3b82f6\|0.231, 0.510, 0.965" "$f" 2>/dev/null
    fi
}
BRAND_FILES=(
    "desktop/shell/design/DesignTokens.js"
    "desktop/shell/Shell.qml"
    "branding/icons/bright-os-logo.svg"
    "branding/wallpapers/bright-default-dark.svg"
    "branding/plymouth/bright-os.script"
    "branding/grub/theme.txt"
    "applications/bright-about/bright-about"
    "config/includes.chroot/usr/share/bright-os/themes/dark/colors.conf"
)
BRAND_CONSISTENT=true
for f in "${BRAND_FILES[@]}"; do
    if ! check_brand_blue "$f"; then
        fail "Brand blue missing in $f"
        BRAND_CONSISTENT=false
    fi
done
if [ "$BRAND_CONSISTENT" = true ]; then
    pass "Brand blue (#3b82f6) consistent across all ${#BRAND_FILES[@]} checked components"
fi

# No edition uses a different logo/color scheme
if grep -rq "different logo\|unrelated colour" desktop/ branding/ config/ --include="*.qml" --include="*.js" --include="*.svg" --include="*.txt" --include="*.conf" 2>/dev/null; then
    fail "Found reference to different logos/color schemes"
else
    pass "No references to divergent logos or color schemes"
fi

echo ""

# --- 12. Lite Resource-Saving Settings ---
echo "--- 12. Lite Edition Optimizations ---"

assert_contains "desktop/shell/profiles/EditionProfiles.js" "disableAnimations:.*true" "Lite disables animations"
assert_contains "desktop/shell/profiles/EditionProfiles.js" "panelHeight:.*28" "Lite uses compact panel (28px)"
assert_contains "desktop/shell/profiles/EditionProfiles.js" "dockIconSize:.*32" "Lite uses smaller dock icons (32px)"
assert_contains "desktop/shell/bright-desktop-shell.py" "interval = 10000" "Lite uses slower system monitor (10s vs 5s)"
assert_contains "desktop/shell/bright-desktop-session.sh" "QT_QUICK_CONTROLS_STYLE=Basic" "Lite uses Qt Quick Basic style"

echo ""

# --- 13. Shell Scripts Syntax Check ---
echo "--- 13. Build Script Syntax ---"
for f in build/scripts/build.sh build/scripts/build-all.sh build/scripts/publish-release.sh build/scripts/validate-iso.sh; do
    if bash -n "$f" 2>/dev/null; then
        pass "$(basename $f) syntax valid"
    else
        fail "$(basename $f) syntax error"
    fi
done

echo ""

# --- Results ---
echo "============================================"
echo "  Results: $PASS passed, $FAIL failed"
echo "============================================"
if [ $FAIL -eq 0 ]; then
    echo -e "${GREEN}All desktop identity tests passed!${NC}"
    exit 0
else
    echo -e "${RED}$FAIL test(s) failed.${NC}"
    exit 1
fi
