#!/bin/bash
# =============================================================================
# Bright OS Component Installer
# Installs Bright Desktop shell, applications, themes, and branding
# onto an existing Debian Bookworm system.
#
# Usage: sudo ./install-bright-os.sh [--edition home|developer|lite]
# =============================================================================

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(dirname "$SCRIPT_DIR")"

EDITION="home"
while [[ $# -gt 0 ]]; do
    case "$1" in
        --edition) EDITION="$2"; shift 2 ;;
        home|developer|lite) EDITION="$1"; shift ;;
        -h|--help)
            echo "Usage: sudo $0 [--edition home|developer|lite]"
            exit 0 ;;
        *) echo "Unknown option: $1"; exit 1 ;;
    esac
done

if [ "$(id -u)" -ne 0 ]; then
    echo "Please run as root (sudo)." >&2
    exit 1
fi

echo "=== Installing Bright OS components (edition: ${EDITION}) ==="

# Install base dependencies
echo "[1/8] Installing base dependencies..."
apt-get update
apt-get install -y --no-install-recommends \
    python3 python3-pip python3-pyqt6 python3-pyqt6.qtsvg \
    python3-pyqt6.qtquick python3-pyqt6.qtqml python3-dbus \
    python3-gi python3-apt python3-yaml python3-pil \
    kwin-wayland plasma-workspace sddm plasma-nm plasma-pa \
    breeze breeze-icon-theme \
    xdg-desktop-portal xdg-desktop-portal-kde \
    xdg-user-dirs xdg-utils \
    network-manager network-manager-gnome \
    pipewire wireplumber pavucontrol-qt \
    udisks2 gvfs gvfs-backends gvfs-fuse \
    firewalld upower powerdevil \
    fonts-dejavu fonts-noto fonts-hack fonts-liberation2 \
    flatpak \
    firefox-esr vlc \
    gnome-disk-utility parted gparted \
    htop neofetch

# Install edition-specific packages
if [ "$EDITION" = "developer" ]; then
    echo "[2/8] Installing Developer edition packages..."
    apt-get install -y --no-install-recommends \
        build-essential gcc g++ gdb clang cmake make autoconf automake \
        python3-dev python3-venv python3-pip \
        git git-lfs \
        docker.io qemu-system-x86 libvirt-daemon-system virt-manager \
        vim neovim \
        arduino esptool minicom kicad freecad \
        wireshark nmap tcpdump strace valgrind \
        wine wine64 winetricks
elif [ "$EDITION" = "lite" ]; then
    echo "[2/8] Installing Lite edition packages..."
    apt-get install -y --no-install-recommends \
        lxqt-core openbox pcmanfm-qt qterminal \
        featherpad abiword gnumeric mpv viewnior galculator
else
    echo "[2/8] Installing Home edition packages..."
    apt-get install -y --no-install-recommends \
        thunderbird gimp inkscape libreoffice-writer libreoffice-calc \
        libreoffice-impress simple-scan transmission-gtk \
        wine winetricks
fi

# Create Bright OS directories
echo "[3/8] Creating directory structure..."
mkdir -p /usr/share/bright-os/{shell,icons,wallpapers,themes,sounds}
mkdir -p /usr/lib/bright-os
mkdir -p /etc/bright-os
mkdir -p /usr/share/applications
mkdir -p /usr/share/wayland-sessions
mkdir -p /usr/share/xsessions

# Install desktop shell
echo "[4/8] Installing Bright Desktop Shell..."
install -m755 "${PROJECT_ROOT}/desktop/shell/bright-desktop-shell.py" /usr/bin/bright-desktop-shell
install -m644 "${PROJECT_ROOT}/desktop/shell/Shell.qml" /usr/share/bright-os/shell/Shell.qml

# Install applications
echo "[5/8] Installing Bright applications..."
for app in bright-files bright-settings bright-terminal bright-monitor \
           bright-control-center bright-launcher bright-update bright-store; do
    APP_SRC="${PROJECT_ROOT}/applications/${app}/${app}"
    if [ -f "$APP_SRC" ]; then
        install -m755 "$APP_SRC" "/usr/bin/${app}"
    fi
    
    # Install .desktop file if exists
    DESKTOP_SRC="${PROJECT_ROOT}/applications/${app}/${app}.desktop"
    if [ -f "$DESKTOP_SRC" ]; then
        install -m644 "$DESKTOP_SRC" "/usr/share/applications/${app}.desktop"
    fi
done

# Install branding
echo "[6/8] Installing branding..."
for wp in "${PROJECT_ROOT}/branding/wallpapers/"*.svg; do
    install -m644 "$wp" /usr/share/bright-os/wallpapers/
done
install -m644 "${PROJECT_ROOT}/branding/icons/bright-os-logo.svg" /usr/share/bright-os/icons/

# Also copy wallpapers to standard location
mkdir -p /usr/share/backgrounds/bright-os
cp /usr/share/bright-os/wallpapers/* /usr/share/backgrounds/bright-os/ 2>/dev/null || true

# Install session entries
echo "[7/8] Installing session entries..."
cat > /usr/share/wayland-sessions/bright.desktop <<EOF
[Desktop Entry]
Name=Bright Desktop
Comment=Bright OS Desktop Environment (Wayland)
Exec=/usr/bin/bright-desktop-shell
TryExec=/usr/bin/bright-desktop-shell
Type=Application
DesktopNames=Bright
EOF

cat > /usr/share/xsessions/bright.desktop <<EOF
[Desktop Entry]
Name=Bright Desktop (X11)
Comment=Bright OS Desktop Environment (X11 fallback)
Exec=/usr/bin/bright-desktop-shell
TryExec=/usr/bin/bright-desktop-shell
Type=Application
DesktopNames=Bright
EOF

# Install firstboot service
install -m755 "${PROJECT_ROOT}/system/services/firstboot-setup.sh" /usr/lib/bright-os/firstboot-setup
install -m644 "${PROJECT_ROOT}/system/services/bright-os-firstboot.service" /etc/systemd/system/
systemctl enable bright-os-firstboot.service 2>/dev/null || true

# Set edition marker
echo "$EDITION" > /etc/bright-os/edition

# Set up default user config
echo "[8/8] Configuring defaults..."
mkdir -p /etc/skel/.config/bright-os
cat > /etc/skel/.config/bright-os/shell.conf <<EOF
# Bright OS Shell Configuration
theme=dark
wallpaper=/usr/share/bright-os/wallpapers/bright-default-dark.svg
panel_height=40
dock_icon_size=48
dock_position=bottom
animations=true
EOF

# SDDM configuration
mkdir -p /etc/sddm.conf.d
cat > /etc/sddm.conf.d/bright-os.conf <<EOF
[Theme]
Current=breeze
CursorTheme=breeze_cursors

[Wayland]
EnableHiDPI=true
SessionDir=/usr/share/wayland-sessions

[X11]
EnableHiDPI=true
SessionDir=/usr/share/xsessions
EOF

# Set default target
systemctl set-default graphical.target 2>/dev/null || true

# Enable services
systemctl enable NetworkManager.service 2>/dev/null || true
systemctl enable sddm.service 2>/dev/null || true
systemctl enable firewalld.service 2>/dev/null || true
systemctl enable bluetooth.service 2>/dev/null || true
systemctl enable cups.service 2>/dev/null || true
systemctl enable udisks2.service 2>/dev/null || true

# Firewall defaults
if command -v firewall-cmd &>/dev/null; then
    firewall-cmd --add-service=ssh --permanent 2>/dev/null || true
    firewall-cmd --add-service=mdns --permanent 2>/dev/null || true
    firewall-cmd --add-service=dhcpv6-client --permanent 2>/dev/null || true
fi

# Create .desktop files for apps that need them
for app_info in \
    "bright-files:Bright Files:system-file-manager:📁" \
    "bright-settings:Bright Settings:preferences-system:⚙️" \
    "bright-terminal:Bright Terminal:utilities-terminal:🖥️" \
    "bright-monitor:Bright Monitor:utilities-system-monitor:📊" \
    "bright-control-center:Bright Control Center:preferences-system:🎛️" \
    "bright-launcher:Bright Launcher:system-search:🔍" \
    "bright-update:Bright Updates:system-software-update:🔄" \
    "bright-store:Bright Store:system-software-install:🛒"
do
    IFS=: read -r cmd name icon emoji <<< "$app_info"
    cat > "/usr/share/applications/${cmd}.desktop" <<EOF
[Desktop Entry]
Name=${name}
Comment=${name} for Bright OS
Exec=${cmd}
Icon=${icon}
Terminal=false
Type=Application
Categories=System;Settings;Utility;
StartupNotify=true
EOF
done

echo ""
echo "============================================"
echo "  Bright OS ${EDITION^} installation complete!"
echo "============================================"
echo ""
echo "Log out and select 'Bright Desktop' from the SDDM session menu,"
echo "or set it as your default session."
echo ""
echo "For the live build system, run: ./build/scripts/build.sh ${EDITION}"
echo ""
