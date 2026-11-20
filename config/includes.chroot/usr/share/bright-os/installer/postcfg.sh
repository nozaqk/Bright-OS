#!/bin/sh
# Bright OS post-installation script
# Runs in chroot after Calamares copies files
# This is called from Calamares shellprocess module

set -e

echo "Running Bright OS post-installation setup..."

# Remove live user that was copied from the live medium
if id user &>/dev/null; then
    userdel -r user 2>/dev/null || true
fi

# Remove live sudoers config
rm -f /etc/sudoers.d/bright-live

# Remove SDDM autologin config (set up in services for installed system)
rm -f /etc/sddm.conf.d/bright-live-autologin.conf

# Enable Flathub if flatpak is installed
if command -v flatpak &>/dev/null; then
    flatpak remote-add --if-not-exists --system flathub https://dl.flathub.org/repo/flathub.flatpakrepo 2>/dev/null || true
fi

# Generate locales
if [ -x /usr/sbin/locale-gen ]; then
    locale-gen 2>/dev/null || true
fi

# Update font cache
fc-cache -f 2>/dev/null || true

# Update desktop database
update-desktop-database 2>/dev/null || true

# Update icon cache
gtk-update-icon-cache -q -t -f /usr/share/icons/hicolor 2>/dev/null || true
gtk-update-icon-cache -q -t -f /usr/share/icons/breeze 2>/dev/null || true

# Remove firstboot-done marker so installed system runs firstboot
rm -f /etc/bright-os/firstboot-done

# Make sure os-release is correct (it should be, but just in case)
cat > /etc/os-release << EOF
PRETTY_NAME="Bright OS $(cat /etc/bright-os/edition 2>/dev/null | tr 'a-z' 'A-Z' | head -c1) Edition"
NAME="Bright OS"
VERSION_ID="0.1"
VERSION="0.1.0-alpha"
VERSION_CODENAME=dawn
ID=bright
ID_LIKE=debian
HOME_URL="https://github.com/nozaqk/Bright-OS"
SUPPORT_URL="https://github.com/nozaqk/Bright-OS/issues"
BUG_REPORT_URL="https://github.com/nozaqk/Bright-OS/issues"
BRIGHT_EDITION="$(cat /etc/bright-os/edition 2>/dev/null || echo home)"
BRIGHT_VERSION="0.1.0-alpha"
DEBIAN_CODENAME=bookworm
EOF

echo "Bright OS post-installation setup complete."
exit 0
