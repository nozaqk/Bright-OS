#!/bin/sh
# Bright OS post-installation script
# Runs in chroot after Calamares copies files and installs packages/bootloader.
# This is called from Calamares shellprocess module.
#
# IMPORTANT: Do NOT use `set -e` here. Any non-critical failure (e.g.,
# a missing icon cache or font that wasn't installed for Lite) must not
# abort the installation. Check return codes explicitly for critical steps.

echo "Running Bright OS post-installation setup..."

POSTCFG_LOG=/var/log/bright-postcfg.log
exec >> "$POSTCFG_LOG" 2>&1
echo "=== Bright OS postcfg started at $(date) ==="

# --- Remove live user (if any was copied over despite exclude list) ---
if id user >/dev/null 2>&1; then
    echo "Removing live user 'user'..."
    userdel -r user 2>/dev/null || true
    # Also remove from group files if userdel didn't fully clean up
    sed -i '/^user:/d' /etc/passwd 2>/dev/null || true
    sed -i '/^user:/d' /etc/shadow 2>/dev/null || true
    sed -i '/^user:/d' /etc/group 2>/dev/null || true
    rm -rf /home/user 2>/dev/null || true
fi

# --- Remove live sudoers config ---
rm -f /etc/sudoers.d/bright-live
chmod 440 /etc/sudoers.d/README 2>/dev/null || true

# --- Remove SDDM autologin config (displaymanager module handles proper setup) ---
rm -f /etc/sddm.conf.d/bright-live-autologin.conf

# --- Initialize Flatpak (safe to repeat) ---
if command -v flatpak >/dev/null 2>&1; then
    echo "Initializing Flatpak Flathub repository..."
    flatpak remote-add --if-not-exists --system flathub https://dl.flathub.org/repo/flathub.flatpakrepo 2>/dev/null || true
fi

# --- Generate locales ---
if [ -x /usr/sbin/locale-gen ]; then
    echo "Generating locales..."
    locale-gen 2>/dev/null || true
fi

# --- Update font caches (optional, non-critical) ---
echo "Updating font/icon caches..."
fc-cache -f 2>/dev/null || true
update-desktop-database 2>/dev/null || true
gtk-update-icon-cache -q -t -f /usr/share/icons/hicolor 2>/dev/null || true
gtk-update-icon-cache -q -t -f /usr/share/icons/breeze 2>/dev/null || true
gtk-update-icon-cache -q -t -f /usr/share/icons/breeze-dark 2>/dev/null || true

# --- Update shared MIME database ---
update-mime-database /usr/share/mime 2>/dev/null || true

# --- Remove firstboot-done marker so installed system runs first-boot ---
rm -f /etc/bright-os/firstboot-done
mkdir -p /etc/bright-os

# --- Ensure edition file exists (fallback to home if not present) ---
EDITION="home"
if [ -f /etc/bright-os/edition ]; then
    EDITION=$(cat /etc/bright-os/edition 2>/dev/null | tr -d '[:space:]')
    case "$EDITION" in
        home|developer|lite) ;; # valid
        *) EDITION="home" ;;
    esac
fi
echo "$EDITION" > /etc/bright-os/edition

# --- Write /etc/os-release correctly for the installed system ---
echo "Writing os-release for edition: $EDITION"
EDITION_PRETTY=$(echo "$EDITION" | sed 's/^h/H/;s/^d/D/;s/^l/L')
case "$EDITION" in
    home) EDITION_PRETTY="Home" ;;
    developer) EDITION_PRETTY="Developer" ;;
    lite) EDITION_PRETTY="Lite" ;;
esac

cat > /etc/os-release << EOF
PRETTY_NAME="Bright OS ${EDITION_PRETTY} Edition (0.1.0-alpha)"
NAME="Bright OS"
VERSION_ID="0.1"
VERSION="0.1.0-alpha (${EDITION})"
VERSION_CODENAME=dawn
ID=bright
ID_LIKE=debian
HOME_URL="https://github.com/nozaqk/Bright-OS"
SUPPORT_URL="https://github.com/nozaqk/Bright-OS/issues"
BUG_REPORT_URL="https://github.com/nozaqk/Bright-OS/issues"
BRIGHT_EDITION="${EDITION}"
BRIGHT_VERSION="0.1.0-alpha"
DEBIAN_CODENAME=trixie
EOF

# Also update /etc/issue for TTY login
cat > /etc/issue << EOF
Bright OS ${EDITION_PRETTY} Edition \n \l

EOF

cat > /etc/issue.net << EOF
Bright OS ${EDITION_PRETTY} Edition
EOF

# --- Initialize machine-id if it was cleared by unpackfs exclude ---
if [ ! -s /etc/machine-id ]; then
    echo "Generating fresh machine-id..."
    dbus-uuidgen --ensure=/etc/machine-id 2>/dev/null || true
fi
if [ ! -s /var/lib/dbus/machine-id ]; then
    cp /etc/machine-id /var/lib/dbus/machine-id 2>/dev/null || true
fi

# --- Update GRUB configuration (final, with correct os-release) ---
if command -v update-grub >/dev/null 2>&1; then
    echo "Updating GRUB configuration..."
    update-grub 2>/dev/null || true
fi

# --- Update initramfs to include any post-install changes ---
# (This is a safety net; Calamares initramfs module already runs update-initramfs.)
if command -v update-initramfs >/dev/null 2>&1; then
    echo "Updating initramfs (postcfg safety net)..."
    update-initramfs -u -k all 2>/dev/null || true
fi

# --- Ensure systemd target is graphical ---
if command -v systemctl >/dev/null 2>&1; then
    systemctl set-default graphical.target 2>/dev/null || true
fi

# --- Set up skel config directories for new users ---
mkdir -p /etc/skel/.config/bright-os
mkdir -p /etc/skel/.config/qt6ct/colors
mkdir -p /etc/skel/.config/qt5ct/colors

# Write edition-appropriate default shell config
case "$EDITION" in
    developer)
        DEFAULT_PANEL_HEIGHT=36
        DEFAULT_DOCK_POSITION="left"
        DEFAULT_DOCK_ICON_SIZE=40
        DEFAULT_ANIMATIONS="true"
        ;;
    lite)
        DEFAULT_PANEL_HEIGHT=28
        DEFAULT_DOCK_POSITION="none"
        DEFAULT_DOCK_ICON_SIZE=32
        DEFAULT_ANIMATIONS="false"
        ;;
    home|*)
        DEFAULT_PANEL_HEIGHT=40
        DEFAULT_DOCK_POSITION="bottom"
        DEFAULT_DOCK_ICON_SIZE=48
        DEFAULT_ANIMATIONS="true"
        ;;
esac

cat > /etc/skel/.config/bright-os/shell.conf << EOF
# Bright OS Shell Configuration (default for new users)
# Edition: ${EDITION}
theme=dark
wallpaper=/usr/share/bright-os/wallpapers/bright-default-dark.svg
panel_position=$([ "$EDITION" = "lite" ] && echo "bottom" || echo "top")
panel_height=${DEFAULT_PANEL_HEIGHT}
dock_position=${DEFAULT_DOCK_POSITION}
dock_icon_size=${DEFAULT_DOCK_ICON_SIZE}
dock_auto_hide=false
animations=${DEFAULT_ANIMATIONS}
EOF

# --- Ensure Bright Desktop session appears in SDDM sessions ---
# (displaymanager module should handle this, but verify)
if [ ! -f /usr/share/wayland-sessions/bright.desktop ]; then
    echo "WARNING: bright.desktop session file missing; creating fallback..."
    cat > /usr/share/wayland-sessions/bright.desktop << 'SESS'
[Desktop Entry]
Name=Bright Desktop
Comment=Bright OS Desktop Environment
Exec=/usr/bin/bright-desktop-shell
TryExec=/usr/bin/bright-desktop-shell
Type=Application
DesktopNames=Bright
SESS
fi

# --- Clean up any apt locks left from chroot operations ---
rm -f /var/lib/apt/lists/lock /var/lib/dpkg/lock-frontend /var/lib/dpkg/lock /var/cache/apt/archives/lock 2>/dev/null || true

echo "=== Bright OS postcfg completed at $(date) ==="
echo "Post-installation setup complete. Edition: ${EDITION}"

exit 0
