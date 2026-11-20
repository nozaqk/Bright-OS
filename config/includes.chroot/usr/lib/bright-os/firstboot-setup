#!/bin/bash
# Bright OS first-boot setup script
# Runs ONCE on the first boot of a freshly installed system (before login).
# Triggered by bright-os-firstboot.service which runs Before=display-manager.service.
#
# IMPORTANT: This script MUST be idempotent (safe to run multiple times).
# It MUST NOT block desktop startup if non-critical operations fail.
# The firstboot-done marker prevents future executions.

echo "Bright OS: running first-boot setup..." | systemd-cat -t bright-os-firstboot -p info

# --- Read edition ---
EDITION=$(cat /etc/bright-os/edition 2>/dev/null || echo "home")
case "$EDITION" in
    home|developer|lite) ;;
    *) EDITION="home" ;;
esac

# --- Generate machine-id if empty (should already exist from postcfg) ---
if [ ! -s /etc/machine-id ]; then
    dbus-uuidgen --ensure=/etc/machine-id 2>/dev/null || true
fi
if [ ! -s /var/lib/dbus/machine-id ]; then
    ln -sf /etc/machine-id /var/lib/dbus/machine-id 2>/dev/null || cp /etc/machine-id /var/lib/dbus/machine-id 2>/dev/null || true
fi

# --- Initialize Flatpak (safe to repeat, doesn't fail if already configured) ---
if command -v flatpak >/dev/null 2>&1; then
    echo "Initializing Flatpak..." | systemd-cat -t bright-os-firstboot -p info
    flatpak remote-add --if-not-exists --system flathub https://dl.flathub.org/repo/flathub.flatpakrepo 2>/dev/null || true
fi

# --- Enable Flathub for the first user when created (handled by user systemd later) ---

# --- Update font cache (idempotent, non-critical) ---
fc-cache -f 2>/dev/null || true

# --- Update desktop database (idempotent, non-critical) ---
update-desktop-database /usr/share/applications 2>/dev/null || true

# --- Update icon caches ---
for theme in hicolor breeze breeze-dark; do
    if [ -d "/usr/share/icons/${theme}" ]; then
        gtk-update-icon-cache -q -t -f "/usr/share/icons/${theme}" 2>/dev/null || true
    fi
done

# --- Update MIME database ---
update-mime-database /usr/share/mime 2>/dev/null || true

# --- Enable fstrim.timer for SSDs if present (safe even on non-SSD) ---
if command -v systemctl >/dev/null 2>&1; then
    # Check if any non-rotational disks are present
    if lsblk -nr -o rota 2>/dev/null | grep -q '^0$'; then
        systemctl enable fstrim.timer 2>/dev/null || true
    fi
fi

# --- Create user config directory skeleton for the user that will be created ---
# (Users module in Calamares creates the user account; skel files handle defaults.)
mkdir -p /etc/skel/.config/bright-os
mkdir -p /etc/skel/Desktop

# Install desktop shortcut for documentation if live install icon is still there
# (it shouldn't be after install; remove it if present)
rm -f /etc/skel/Desktop/install-bright-os.desktop 2>/dev/null || true

# --- Mark first boot complete ---
mkdir -p /etc/bright-os
touch /etc/bright-os/firstboot-done

echo "Bright OS: first-boot setup complete (edition: ${EDITION})" | systemd-cat -t bright-os-firstboot -p info
exit 0
