#!/bin/bash
# =============================================================================
# test-installer.sh - Phase 15 installer reliability tests
# Tests for Calamares installer configuration, partitioning, bootloader,
# LUKS encryption, first-boot integration, and edition detection after install.
# =============================================================================
set -e

REPO_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$REPO_ROOT"

PASS=0
FAIL=0

GREEN='\033[0;32m'
RED='\033[0;31m'
NC='\033[0m'

pass() { echo -e "${GREEN}[PASS]${NC} $1"; PASS=$((PASS+1)); }
fail() { echo -e "${RED}[FAIL]${NC} $1"; FAIL=$((FAIL+1)); }

assert_file() {
    local path="$1" desc="$2"
    if [ -f "$path" ] && [ -s "$path" ]; then
        pass "$desc"
    else
        fail "$desc (missing or empty: $path)"
    fi
}

assert_contains() {
    local file="$1" pattern="$2" desc="$3"
    if grep -q "$pattern" "$file" 2>/dev/null; then
        pass "$desc"
    else
        fail "$desc (pattern not found: $pattern in $file)"
    fi
}

assert_not_contains() {
    local file="$1" pattern="$2" desc="$3"
    if ! grep -q "$pattern" "$file" 2>/dev/null; then
        pass "$desc"
    else
        fail "$desc (unexpected pattern found: $pattern in $file)"
    fi
}

# YAML validation (requires python3 + yaml)
validate_yaml() {
    local file="$1" desc="$2"
    if python3 -c "import yaml; yaml.safe_load(open('$file'))" 2>/dev/null; then
        pass "$desc"
    else
        fail "$desc (YAML parse error: $file)"
    fi
}

echo "============================================"
echo "  Phase 15: Installer Reliability Tests"
echo "============================================"
echo ""

# --- 1. Calamares settings.conf ---
echo "--- 1. Calamares settings.conf ---"

assert_file "installer/calamares/settings.conf" "settings.conf exists"
assert_file "config/includes.chroot/usr/share/bright-os/installer/settings.conf" "settings.conf installed"
validate_yaml "installer/calamares/settings.conf" "settings.conf is valid YAML"

assert_contains "installer/calamares/settings.conf" "branding: bright-os" "Branding set to bright-os"
assert_contains "installer/calamares/settings.conf" "prompt-install: true" "Install confirmation prompt enabled"
assert_contains "installer/calamares/settings.conf" "required-space: 16GB" "Required disk space set to 16GB"
assert_contains "installer/calamares/settings.conf" "required-ram: 2048" "Required RAM set to 2GB"
assert_contains "installer/calamares/settings.conf" "disable-cancel-during-exec: true" "Cancel disabled during exec"
assert_contains "installer/calamares/settings.conf" "width: *1024" "Window width set"

# Helper: check that a YAML list item exists (matches "  - modulename" at start of line)
in_yaml_list() {
    local file="$1" item="$2"
    grep -qE "^[[:space:]]+-[[:space:]]+${item}[[:space:]]*$" "$file"
}

# Module ordering checks (YAML list items are "  - module_name" with whitespace)
in_yaml_list "installer/calamares/settings.conf" "partition" && pass "Partition module in exec sequence" || fail "Partition module in exec sequence"
in_yaml_list "installer/calamares/settings.conf" "mount" && pass "Mount module in exec sequence" || fail "Mount module in exec sequence"
in_yaml_list "installer/calamares/settings.conf" "unpackfs" && pass "Unpackfs module in exec sequence" || fail "Unpackfs module in exec sequence"
in_yaml_list "installer/calamares/settings.conf" "displaymanager" && pass "Displaymanager module in exec sequence" || fail "Displaymanager module in exec sequence"
in_yaml_list "installer/calamares/settings.conf" "packages" && pass "Packages module in exec sequence" || fail "Packages module in exec sequence"
in_yaml_list "installer/calamares/settings.conf" "luksbootkeyfile" && pass "luksbootkeyfile module in sequence" || fail "luksbootkeyfile module in sequence"
in_yaml_list "installer/calamares/settings.conf" "initramfscfg" && pass "initramfscfg module in sequence" || fail "initramfscfg module in sequence"
in_yaml_list "installer/calamares/settings.conf" "initramfs" && pass "initramfs module in sequence" || fail "initramfs module in sequence"
in_yaml_list "installer/calamares/settings.conf" "grubcfg" && pass "grubcfg module in sequence" || fail "grubcfg module in sequence"
in_yaml_list "installer/calamares/settings.conf" "bootloader" && pass "bootloader module in sequence" || fail "bootloader module in sequence"
in_yaml_list "installer/calamares/settings.conf" "shellprocess-post" && pass "shellprocess-post module in sequence" || fail "shellprocess-post module in sequence"
in_yaml_list "installer/calamares/settings.conf" "umount" && pass "umount module in sequence" || fail "umount module in sequence"
! in_yaml_list "installer/calamares/settings.conf" "ucode" && pass "No non-existent 'ucode' module referenced" || fail "Non-existent 'ucode' module referenced"

# Ordering: packages before initramfscfg (required for LUKS)
python3 -c "
import yaml
with open('installer/calamares/settings.conf') as f:
    cfg = yaml.safe_load(f)
exec_mods = []
for seq in cfg['sequence']:
    if 'exec' in seq:
        exec_mods = seq['exec']
        break
pkg_idx = exec_mods.index('packages') if 'packages' in exec_mods else -1
initramfscfg_idx = exec_mods.index('initramfscfg') if 'initramfscfg' in exec_mods else -1
luks_idx = exec_mods.index('luksbootkeyfile') if 'luksbootkeyfile' in exec_mods else -1
umount_idx = exec_mods.index('umount') if 'umount' in exec_mods else -1
dm_idx = exec_mods.index('displaymanager') if 'displaymanager' in exec_mods else -1
assert pkg_idx >= 0 and initramfscfg_idx >= 0, 'required modules missing'
assert pkg_idx < initramfscfg_idx, 'packages must come BEFORE initramfscfg'
assert luks_idx < initramfscfg_idx, 'luksbootkeyfile must come BEFORE initramfscfg'
assert dm_idx >= 0, 'displaymanager must be present'
assert umount_idx == len(exec_mods) - 1, 'umount must be last'
print('order OK')
" && pass "Module ordering correct (packages before initramfs, luksbootkeyfile before initramfscfg, umount last)" || fail "Module ordering incorrect"

echo ""

# --- 2. Bootloader configuration ---
echo "--- 2. Bootloader Configuration ---"

assert_file "installer/calamares/modules/bootloader.conf" "bootloader.conf exists"
validate_yaml "installer/calamares/modules/bootloader.conf" "bootloader.conf is valid YAML"

assert_contains "installer/calamares/modules/bootloader.conf" "grubUseCryptodisk: true" "GRUB cryptodisk enabled for LUKS"
assert_contains "installer/calamares/modules/bootloader.conf" 'efiBootLoader: "grubx64.efi"' "EFI bootloader set to grubx64.efi"
assert_contains "installer/calamares/modules/bootloader.conf" 'efiBootLoaderId: "BrightOS"' "EFI boot entry ID set"
assert_contains "installer/calamares/modules/bootloader.conf" "update: true" "GRUB update enabled"
assert_not_contains "installer/calamares/modules/bootloader.conf" 'installPath: "any"' "installPath not set to invalid 'any'"
assert_not_contains "installer/calamares/modules/bootloader.conf" "keepLinuxUpdate" "No invalid keepLinuxUpdate key"
assert_contains "installer/calamares/modules/bootloader.conf" "efiBootLoaderEntry: \"Bright OS\"" "EFI boot entry name set"

echo ""

# --- 3. GRUB configuration ---
echo "--- 3. GRUB Configuration ---"

assert_file "installer/calamares/modules/grubcfg.conf" "grubcfg.conf exists"
validate_yaml "installer/calamares/modules/grubcfg.conf" "grubcfg.conf is valid YAML"

assert_contains "installer/calamares/modules/grubcfg.conf" "GRUB_ENABLE_CRYPTODISK: \"y\"" "Cryptodisk enabled in GRUB defaults"
assert_contains "installer/calamares/modules/grubcfg.conf" 'grubDistributor: "Bright OS"' "GRUB distributor is Bright OS"
assert_contains "installer/calamares/modules/grubcfg.conf" "GRUB_TIMEOUT: \"5\"" "GRUB timeout set"
assert_contains "installer/calamares/modules/grubcfg.conf" "overwrite: false" "Does not overwrite all GRUB defaults"
assert_contains "installer/calamares/modules/grubcfg.conf" "grubTheme:" "Bright GRUB theme referenced"

echo ""

# --- 4. Partition configuration ---
echo "--- 4. Partition Configuration ---"

assert_file "installer/calamares/modules/partition.conf" "partition.conf exists"
validate_yaml "installer/calamares/modules/partition.conf" "partition.conf is valid YAML"

assert_contains "installer/calamares/modules/partition.conf" "initialPartitioningChoice: none" "Default partition choice is 'none' (no auto-erase)"
assert_contains "installer/calamares/modules/partition.conf" "allowManualPartitioning: true" "Manual partitioning allowed"
assert_contains "installer/calamares/modules/partition.conf" "enableLuksAutomatedPartitioning: true" "LUKS enabled in automatic partitioning"
assert_contains "installer/calamares/modules/partition.conf" "defaultFileSystemType: \"ext4\"" "Default filesystem is ext4"
assert_contains "installer/calamares/modules/partition.conf" "efiSystemPartitionSize: 512MiB" "EFI partition size set to 512MiB"
assert_contains "installer/calamares/modules/partition.conf" "availableFileSystemTypes:" "Available filesystems listed"
grep -qE '"ext4"' "installer/calamares/modules/partition.conf" && pass "ext4 available" || fail "ext4 available"
grep -qE '"btrfs"' "installer/calamares/modules/partition.conf" && pass "btrfs available" || fail "btrfs available"
assert_contains "installer/calamares/modules/partition.conf" "partitionLayout:" "Automatic partition layout defined"
assert_contains "installer/calamares/modules/partition.conf" 'mountPoint: "/boot/efi"' "EFI mount point set"
assert_contains "installer/calamares/modules/partition.conf" 'mountPoint: "/"' "Root mount point set"

echo ""

# --- 5. LUKS / Encryption ---
echo "--- 5. LUKS / Encryption Configuration ---"

assert_file "installer/calamares/modules/luksbootkeyfile.conf" "luksbootkeyfile.conf exists"
assert_file "installer/calamares/modules/initramfscfg.conf" "initramfscfg.conf exists"
assert_file "installer/calamares/modules/initramfs.conf" "initramfs.conf exists"

# CRITICAL: crypttabOptions must NOT use deprecated keyscript= (check only active config line, not comments)
# Active line pattern: line starts with "crypttabOptions:" followed by the value
CRYPTTAB_LINE=$(grep "^crypttabOptions:" "installer/calamares/modules/fstab.conf" || true)
if echo "$CRYPTTAB_LINE" | grep -q "keyscript"; then
    fail "fstab.conf crypttabOptions uses deprecated keyscript (Trixie incompatibility)"
else
    pass "fstab.conf crypttabOptions does NOT use deprecated keyscript"
fi
if echo "$CRYPTTAB_LINE" | grep -q "decrypt_keyctl"; then
    fail "fstab.conf crypttabOptions uses deprecated decrypt_keyctl"
else
    pass "fstab.conf crypttabOptions does NOT use deprecated decrypt_keyctl"
fi
if echo "$CRYPTTAB_LINE" | grep -q "^crypttabOptions: luks$"; then
    pass "crypttabOptions uses plain 'luks'"
else
    fail "crypttabOptions not set correctly (found: $CRYPTTAB_LINE)"
fi

# Packages must remove live-boot before initramfs
assert_contains "installer/calamares/modules/packages.conf" "live-boot" "packages.conf removes live-boot"
assert_contains "installer/calamares/modules/packages.conf" "live-boot-initramfs-tools" "packages.conf removes live-boot-initramfs-tools"

echo ""

# --- 6. fstab configuration ---
echo "--- 6. Filesystem Configuration ---"

assert_file "installer/calamares/modules/fstab.conf" "fstab.conf exists"
validate_yaml "installer/calamares/modules/fstab.conf" "fstab.conf is valid YAML"

# Discard mount option is NOT used in active config (fstrim.timer is preferred)
# Check only non-comment lines
SSD_LINES=$(grep "^[[:space:]]*[a-z0-9]*:" "installer/calamares/modules/fstab.conf" | grep -i "ssdExtraMount\|btrfs\|ext4\|f2fs\|xfs" || true)
if echo "$SSD_LINES" | grep -q "discard" && ! echo "$SSD_LINES" | grep -q "^#"; then
    fail "fstab.conf uses continuous discard in active config (fstrim preferred)"
else
    pass "fstab.conf does not use continuous discard (fstrim preferred)"
fi
assert_contains "installer/calamares/modules/fstab.conf" "efiMountOptions:" "EFI mount options set"
assert_contains "installer/calamares/modules/fstab.conf" "btrfsMountOptions:" "Btrfs mount options set (safe defaults)"

echo ""

# --- 7. Display Manager ---
echo "--- 7. Display Manager (SDDM) Configuration ---"

assert_file "installer/calamares/modules/displaymanager.conf" "displaymanager.conf exists"
validate_yaml "installer/calamares/modules/displaymanager.conf" "displaymanager.conf is valid YAML"

grep -qE "^[[:space:]]+-[[:space:]]+sddm" "installer/calamares/modules/displaymanager.conf" && pass "SDDM set as display manager" || fail "SDDM set as display manager"
assert_contains "installer/calamares/modules/displaymanager.conf" 'defaultDesktopSession: "bright.desktop"' "Default session is bright.desktop"
assert_contains "installer/calamares/modules/displaymanager.conf" "basicSetup: true" "Basic DM setup enabled"
assert_contains "installer/calamares/modules/displaymanager.conf" "theme: breeze" "SDDM theme is Breeze (matches branding)"

echo ""

# --- 8. Packages module ---
echo "--- 8. Packages Module ---"

assert_file "installer/calamares/modules/packages.conf" "packages.conf exists"
validate_yaml "installer/calamares/modules/packages.conf" "packages.conf is valid YAML"

assert_contains "installer/calamares/modules/packages.conf" "backend: apt" "APT backend configured"
assert_contains "installer/calamares/modules/packages.conf" "try_remove: true" "Package removal is non-fatal"
assert_contains "installer/calamares/modules/packages.conf" "live-config" "live-config in remove list"
assert_contains "installer/calamares/modules/packages.conf" "live-tools" "live-tools in remove list"

echo ""

# --- 9. Services ---
echo "--- 9. System Services ---"

assert_file "installer/calamares/modules/services-systemd.conf" "services-systemd.conf exists"
validate_yaml "installer/calamares/modules/services-systemd.conf" "services-systemd.conf valid YAML"

assert_contains "installer/calamares/modules/services-systemd.conf" "sddm.service" "SDDM service enabled"
assert_contains "installer/calamares/modules/services-systemd.conf" "NetworkManager.service" "NetworkManager enabled"
assert_contains "installer/calamares/modules/services-systemd.conf" "bright-os-firstboot.service" "Bright firstboot service enabled"
assert_contains "installer/calamares/modules/services-systemd.conf" "fstrim.timer" "fstrim.timer enabled (SSD TRIM)"
assert_contains "installer/calamares/modules/services-systemd.conf" "graphical.target" "Graphical target enabled"
assert_contains "installer/calamares/modules/services-systemd.conf" "mandatory: true" "Critical services marked mandatory"

echo ""

# --- 10. UnpackFS / Exclude list ---
echo "--- 10. UnpackFS and Exclude List ---"

assert_file "installer/calamares/modules/unpackfs.conf" "unpackfs.conf exists"
validate_yaml "installer/calamares/modules/unpackfs.conf" "unpackfs.conf valid YAML"
assert_file "installer/calamares/modules/exclude-list" "exclude-list exists"

assert_contains "installer/calamares/modules/unpackfs.conf" 'sourcefs: "rsync"' "Uses rsync source filesystem"
assert_contains "installer/calamares/modules/exclude-list" "/home/user/" "Excludes live user home"
assert_contains "installer/calamares/modules/exclude-list" "/etc/machine-id" "Excludes machine-id (regenerated)"
assert_contains "installer/calamares/modules/exclude-list" "/var/lib/dbus/machine-id" "Excludes dbus machine-id"
assert_contains "installer/calamares/modules/exclude-list" "/etc/sudoers.d/bright-live" "Excludes live sudoers config"
assert_contains "installer/calamares/modules/exclude-list" "bright-live-autologin" "Excludes live autologin config"
assert_contains "installer/calamares/modules/exclude-list" "/swapfile" "Excludes swapfile"
assert_contains "installer/calamares/modules/exclude-list" "/root/" "Excludes root home"
assert_not_contains "installer/calamares/modules/exclude-list" "bright-os/firstboot" "Does not exclude firstboot script"

echo ""

# --- 11. Network config ---
echo "--- 11. Network Configuration ---"

assert_file "installer/calamares/modules/networkcfg.conf" "networkcfg.conf exists"
validate_yaml "installer/calamares/modules/networkcfg.conf" "networkcfg.conf valid YAML"

assert_contains "installer/calamares/modules/networkcfg.conf" "saveHostname: true" "Hostname saving enabled"
assert_contains "installer/calamares/modules/networkcfg.conf" 'hostname: "bright-os"' "Default hostname set"
assert_contains "installer/calamares/modules/networkcfg.conf" "copyNetworkConfigurations: false" "Wi-Fi passwords NOT copied (privacy)"

echo ""

# --- 12. Welcome screen ---
echo "--- 12. Welcome Screen ---"

assert_file "installer/calamares/modules/welcome.conf" "welcome.conf exists"
validate_yaml "installer/calamares/modules/welcome.conf" "welcome.conf valid YAML"

assert_contains "installer/calamares/modules/welcome.conf" "enumeration: 2048" "RAM requirement: 2GB"
assert_contains "installer/calamares/modules/welcome.conf" "enumeration: 16" "Storage requirement: 16GB"
assert_contains "installer/calamares/modules/welcome.conf" 'name: internet' "Internet check present (not required)"
assert_contains "installer/calamares/modules/welcome.conf" "showWelcomeLanguage: true" "Language selector shown"

echo ""

# --- 13. Users module ---
echo "--- 13. Users Module ---"

assert_file "installer/calamares/modules/users.conf" "users.conf exists"
validate_yaml "installer/calamares/modules/users.conf" "users.conf valid YAML"

assert_contains "installer/calamares/modules/users.conf" "sudo" "Default groups include sudo"
assert_contains "installer/calamares/modules/users.conf" "dialout" "dialout group (Arduino/electronics)"
assert_contains "installer/calamares/modules/users.conf" "kvm" "kvm group (virtualization)"
assert_contains "installer/calamares/modules/users.conf" "docker" "docker group"
assert_contains "installer/calamares/modules/users.conf" "userShell: \"/bin/bash\"" "Default shell is bash"
assert_contains "installer/calamares/modules/users.conf" "setRootPassword: true" "Root password setup enabled"
assert_contains "installer/calamares/modules/users.conf" "allowWeakPasswords:" "Weak passwords allowed (convenience)"

echo ""

# --- 14. Post-install script ---
echo "--- 14. Post-Install Script ---"

assert_file "installer/calamares/modules/postcfg.sh" "postcfg.sh exists"
assert_file "config/includes.chroot/usr/share/bright-os/installer/postcfg.sh" "postcfg.sh installed"

bash -n "installer/calamares/modules/postcfg.sh" && pass "postcfg.sh shell syntax valid" || fail "postcfg.sh shell syntax error"

# Check that set -e is NOT active (ignore comment lines)
if grep -v "^#" "installer/calamares/modules/postcfg.sh" | grep -q "^set -e"; then
    fail "postcfg.sh uses set -e (non-critical failures may abort install)"
else
    pass "postcfg.sh does NOT use set -e (non-critical failures must not abort)"
fi
assert_contains "installer/calamares/modules/postcfg.sh" "DEBIAN_CODENAME=trixie" "postcfg.sh sets DEBIAN_CODENAME=trixie (not bookworm)"
assert_contains "installer/calamares/modules/postcfg.sh" "EDITION_PRETTY" "postcfg.sh properly formats edition name (not buggy ^ capitalization)"
assert_contains "installer/calamares/modules/postcfg.sh" "update-grub" "postcfg.sh runs update-grub"
assert_contains "installer/calamares/modules/postcfg.sh" "update-initramfs" "postcfg.sh runs update-initramfs safety net"
assert_contains "installer/calamares/modules/postcfg.sh" "rm -f /etc/bright-os/firstboot-done" "postcfg.sh removes firstboot-done marker"
assert_contains "installer/calamares/modules/postcfg.sh" "sddm.conf.d/bright-live-autologin" "postcfg.sh removes live autologin"
assert_contains "installer/calamares/modules/postcfg.sh" "systemctl set-default graphical.target" "postcfg.sh sets graphical target"
assert_contains "installer/calamares/modules/postcfg.sh" "exit 0" "postcfg.sh always exits 0"

echo ""

# --- 15. Shellprocess post config ---
echo "--- 15. Shellprocess Post Configuration ---"

assert_file "installer/calamares/modules/shellprocess-post.conf" "shellprocess-post.conf exists"
validate_yaml "installer/calamares/modules/shellprocess-post.conf" "shellprocess-post.conf valid YAML"

assert_contains "installer/calamares/modules/shellprocess-post.conf" "postcfg.sh" "shellprocess-post runs postcfg.sh"
assert_contains "installer/calamares/modules/shellprocess-post.conf" "dontChroot: false" "shellprocess runs in chroot"

echo ""

# --- 16. First-boot service ---
echo "--- 16. First-Boot Service Integration ---"

assert_file "system/services/bright-os-firstboot.service" "bright-os-firstboot.service exists"
assert_file "config/includes.chroot/usr/lib/bright-os/firstboot-setup" "firstboot-setup script exists"

assert_contains "system/services/bright-os-firstboot.service" "Before=display-manager.service" "Firstboot runs before display manager"
assert_contains "system/services/bright-os-firstboot.service" "ConditionPathExists=!/etc/bright-os/firstboot-done" "Firstboot conditional on marker absence"
assert_contains "system/services/bright-os-firstboot.service" "Type=oneshot" "Firstboot is a oneshot service"
assert_contains "system/services/bright-os-firstboot.service" "FailureAction=none" "Firstboot failure does not block boot"
assert_contains "system/services/bright-os-firstboot.service" "WantedBy=graphical.target" "Firstboot wanted by graphical target"
assert_contains "system/services/bright-os-firstboot.service" "TimeoutStartSec=120" "Firstboot has timeout"

bash -n "config/includes.chroot/usr/lib/bright-os/firstboot-setup" && pass "firstboot-setup shell syntax valid" || fail "firstboot-setup shell syntax error"

# Firstboot must be idempotent
assert_contains "config/includes.chroot/usr/lib/bright-os/firstboot-setup" "if-not-exists" "firstboot uses --if-not-exists for flatpak (idempotent)"
assert_contains "config/includes.chroot/usr/lib/bright-os/firstboot-setup" "firstboot-done" "firstboot creates firstboot-done marker"
assert_contains "config/includes.chroot/usr/lib/bright-os/firstboot-setup" "|| true" "firstboot has || true guards on non-critical operations"

echo ""

# --- 17. Edition detection after installation ---
echo "--- 17. Edition Detection and Profile Loading ---"

assert_file "config/includes.chroot/etc/bright-os/edition" "Edition marker file exists"
EDITION_VAL=$(cat config/includes.chroot/etc/bright-os/edition 2>/dev/null)
if echo "$EDITION_VAL" | grep -qE "^(home|developer|lite)$"; then
    pass "Edition marker has valid value: $EDITION_VAL"
else
    fail "Edition marker has invalid value: '$EDITION_VAL'"
fi

# Python backend edition detection
assert_contains "desktop/shell/bright-desktop-shell.py" 'VALID_EDITIONS' "Python backend defines valid editions"
assert_contains "desktop/shell/bright-desktop-shell.py" "detect_edition" "Python backend has detect_edition function"
assert_contains "desktop/shell/bright-desktop-shell.py" "/etc/bright-os/edition" "Python backend reads /etc/bright-os/edition"
assert_contains "desktop/shell/bright-desktop-shell.py" "'home'" "Python backend falls back to home"
assert_contains "desktop/shell/bright-desktop-shell.py" "EditionId" "Python backend exposes EditionId to QML"
assert_contains "desktop/shell/bright-desktop-shell.py" "editionDisplayName" "Python backend exposes editionDisplayName"

# Edition profiles in JavaScript
assert_file "desktop/shell/profiles/EditionProfiles.js" "EditionProfiles.js exists"
assert_contains "desktop/shell/profiles/EditionProfiles.js" "function getProfile" "getProfile function exists"
assert_contains "desktop/shell/profiles/EditionProfiles.js" "var Home" "Home profile defined"
assert_contains "desktop/shell/profiles/EditionProfiles.js" "var Developer" "Developer profile defined"
assert_contains "desktop/shell/profiles/EditionProfiles.js" "var Lite" "Lite profile defined"

# Session script edition detection
assert_contains "desktop/shell/bright-desktop-session.sh" "EDITION=" "Session script detects edition"
assert_contains "desktop/shell/bright-desktop-session.sh" "qt6ct" "Lite edition uses qt6ct"

echo ""

# --- 18. Installer branding ---
echo "--- 18. Installer Branding ---"

assert_file "installer/calamares/branding/bright-os/branding.desc" "Branding descriptor exists"
assert_file "installer/calamares/branding/bright-os/show.qml" "Slideshow QML exists"
assert_file "branding/icons/bright-os-logo.svg" "Bright OS logo SVG exists"

assert_contains "installer/calamares/branding/bright-os/branding.desc" "productName: \"Bright OS\"" "Branding product name set"
assert_contains "installer/calamares/branding/bright-os/branding.desc" "bootloaderEntryName: \"Bright OS\"" "Bootloader entry name set"
assert_contains "installer/calamares/branding/bright-os/branding.desc" 'sidebarBackground: "#0f172a"' "Sidebar matches Dark theme base color"
assert_contains "installer/calamares/branding/bright-os/branding.desc" 'sidebarTextSelect: "#3b82f6"' "Sidebar selection uses brand blue"
assert_contains "installer/calamares/branding/bright-os/branding.desc" "slideshow: \"show.qml\"" "Slideshow referenced"
assert_not_contains "installer/calamares/branding/bright-os/branding.desc" "placeholder" "No placeholder text in branding"

echo ""

# --- 19. Installer file installation into live system ---
echo "--- 19. Installer Files Present in Chroot Includes ---"

# All module configs must be present in chroot
for mod in bootloader displaymanager finished fstab grubcfg hwclock initramfs initramfscfg keyboard locale localecfg luksbootkeyfile machineid mount networkcfg packages partition services-systemd shellprocess-post summary unpackfs users welcome; do
    assert_file "config/includes.chroot/usr/share/bright-os/installer/modules/${mod}.conf" "${mod}.conf installed in chroot"
done
assert_file "config/includes.chroot/usr/share/bright-os/installer/modules/exclude-list" "exclude-list installed in chroot"
assert_file "config/includes.chroot/usr/share/bright-os/installer/modules/postcfg.sh" "postcfg.sh installed in chroot"
assert_file "config/includes.chroot/usr/share/bright-os/installer/postcfg.sh" "top-level postcfg.sh installed in chroot"
assert_file "config/includes.chroot/usr/share/bright-os/installer/branding/bright-os/branding.desc" "branding.desc installed in chroot"
assert_file "config/includes.chroot/usr/share/bright-os/installer/branding/bright-os/show.qml" "show.qml installed in chroot"
assert_file "config/includes.chroot/usr/share/bright-os/installer/settings.conf" "settings.conf installed in chroot"

# Calamares package must be in core packages
assert_contains "config/package-lists/core.list.chroot" "^calamares$" "calamares package in core list"
assert_contains "config/package-lists/core.list.chroot" "^cryptsetup$" "cryptsetup package in core list"

# Desktop file for launching installer
assert_file "config/includes.chroot/etc/skel/Desktop/install-bright-os.desktop" "Install desktop shortcut exists"
assert_contains "config/includes.chroot/etc/skel/Desktop/install-bright-os.desktop" "Exec=pkexec calamares" "Install shortcut runs calamares with pkexec"

echo ""

# --- 20. Live config consistency ---
echo "--- 20. Live Environment Configuration ---"

assert_file "config/includes.chroot/lib/live/config/05-bright-os" "Live config script exists"
assert_contains "config/includes.chroot/lib/live/config/05-bright-os" "DEBIAN_CODENAME=trixie" "Live config uses trixie codename"
assert_not_contains "config/includes.chroot/lib/live/config/05-bright-os" "DEBIAN_CODENAME=bookworm" "Live config does not use bookworm codename"
assert_contains "config/includes.chroot/lib/live/config/05-bright-os" "SDDM" "Live config sets up SDDM autologin"
assert_contains "config/includes.chroot/lib/live/config/05-bright-os" "bright-live-autologin" "Live autologin config filename correct"

echo ""

# --- 21. Build hook integration ---
echo "--- 21. Build Hook Integration ---"

assert_file "config/hooks/live/20-installer-setup.hook.chroot" "Installer setup hook exists"
assert_contains "config/hooks/live/20-installer-setup.hook.chroot" "calamares" "Installer hook references calamares"
assert_contains "config/hooks/live/10-bright-os-components.hook.chroot" "firstboot" "Components hook handles firstboot service"
assert_contains "config/hooks/live/10-bright-os-components.hook.chroot" "DEFAULT_PANEL_HEIGHT" "Components hook sets edition-specific defaults"

echo ""

# --- 22. All three editions build correctly ---
echo "--- 22. Three Edition Configurations ---"

for edition in home developer lite; do
    assert_file "editions/${edition}/packages.list" "${edition} edition packages.list exists"
done

# Check desktop package lists
assert_file "config/package-lists/desktop.list.chroot" "Home/Developer desktop package list exists"
assert_file "config/package-lists/desktop-lite.list.chroot" "Lite desktop package list exists"
assert_contains "config/package-lists/desktop.list.chroot" "plasma-desktop" "Home/Developer uses Plasma desktop"
assert_contains "config/package-lists/desktop-lite.list.chroot" "lxqt-core" "Lite uses LXQt"
assert_contains "config/package-lists/desktop-lite.list.chroot" "openbox" "Lite includes Openbox"
# Check that plasma-desktop is NOT a package dependency (ignoring comment lines)
if grep -v "^#" "config/package-lists/desktop-lite.list.chroot" | grep -q "^plasma-desktop$"; then
    fail "Lite includes plasma-desktop as a package"
else
    pass "Lite does not include plasma-desktop package"
fi

echo ""

# --- 23. Build script required files check ---
echo "--- 23. Build Script Checks ---"
assert_contains "build/scripts/build.sh" "settings.conf" "build.sh checks for settings.conf"
bash -n "build/scripts/build.sh" && pass "build.sh syntax valid" || fail "build.sh syntax error"
bash -n "build/scripts/build-all.sh" && pass "build-all.sh syntax valid" || fail "build-all.sh syntax error"
bash -n "build/scripts/publish-release.sh" && pass "publish-release.sh syntax valid" || fail "publish-release.sh syntax error"
bash -n "build/scripts/validate-iso.sh" && pass "validate-iso.sh syntax valid" || fail "validate-iso.sh syntax error"

echo ""

# --- 24. Python backend syntax ---
echo "--- 24. Python Shell Backend Syntax ---"
python3 -c "import py_compile; py_compile.compile('desktop/shell/bright-desktop-shell.py', doraise=True)" 2>/dev/null && pass "bright-desktop-shell.py syntax valid" || fail "bright-desktop-shell.py syntax error"
python3 -c "import py_compile; py_compile.compile('applications/bright-about/bright-about', doraise=True)" 2>/dev/null && pass "bright-about syntax valid" || fail "bright-about syntax error"

echo ""

# --- Results ---
echo "============================================"
echo "  Results: $PASS passed, $FAIL failed"
echo "============================================"
if [ $FAIL -eq 0 ]; then
    echo -e "${GREEN}All installer reliability tests passed!${NC}"
    exit 0
else
    echo -e "${RED}$FAIL test(s) failed.${NC}"
    exit 1
fi
