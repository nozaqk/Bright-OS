#!/bin/bash
# Bright OS first-boot setup script
# Runs once on first system boot after installation

set -e

echo "Running Bright OS first boot setup..."

# Generate machine ID if needed
if [ ! -s /etc/machine-id ]; then
    dbus-uuidgen --ensure=/etc/machine-id
fi

# Initialize Flatpak
if command -v flatpak &>/dev/null; then
    flatpak remote-add --if-not-exists --system flathub https://dl.flathub.org/repo/flathub.flatpakrepo 2>/dev/null || true
fi

# Update font cache
fc-cache -f 2>/dev/null || true

# Update desktop database
update-desktop-database 2>/dev/null || true

# Mark first boot complete
mkdir -p /etc/bright-os
touch /etc/bright-os/firstboot-done

echo "Bright OS first boot setup complete."
