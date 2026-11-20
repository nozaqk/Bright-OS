#!/bin/bash
# Bright OS default firewall configuration
# Applied on first boot via firewalld

set -e

if ! command -v firewall-cmd &>/dev/null; then
    echo "firewalld not installed, skipping"
    exit 0
fi

# Default zone: public (most restrictive)
firewall-cmd --set-default-zone=public 2>/dev/null || true

# Essential services for desktop
firewall-cmd --permanent --add-service=ssh 2>/dev/null || true
firewall-cmd --permanent --add-service=dhcpv6-client 2>/dev/null || true
firewall-cmd --permanent --add-service=mdns 2>/dev/null || true  # local network discovery
firewall-cmd --permanent --add-service=samba-client 2>/dev/null || true  # file sharing discovery

# Allow mDNS/Bonjour for printer discovery
firewall-cmd --permanent --add-port=5353/udp 2>/dev/null || true

# Block incoming by default (public zone does this)
# No open ports by default besides DHCP/SSH for administration

# Reload to apply
firewall-cmd --reload 2>/dev/null || true

echo "Bright OS firewall defaults applied."
