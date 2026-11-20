#!/bin/bash
# Bright Desktop session startup script
# Sets required environment variables and launches KWin with our shell

# Set XDG current desktop for XDG integration
export XDG_CURRENT_DESKTOP=Bright
export XDG_SESSION_TYPE="${XDG_SESSION_TYPE:-wayland}"
export DESKTOP_SESSION=bright

# Qt configuration
export QT_QPA_PLATFORM="${QT_QPA_PLATFORM:-wayland;xcb}"
export QT_WAYLAND_DISABLE_WINDOWDECORATION=1
export QT_QPA_PLATFORMTHEME=qt6ct
export QT_STYLE_OVERRIDE=Fusion
export QT_AUTO_SCREEN_SCALE_FACTOR=1

# GTK configuration for consistent theming
export GTK_THEME=Breeze-Dark
export GTK2_RC_FILES=/usr/share/themes/Breeze-Dark/gtk-2.0/gtkrc
export XDG_CURRENT_DESKTOP=Bright:KDE

# Sound server
export PIPEWIRE_LATENCY=128/48000

# Default cursor theme
export XCURSOR_THEME=breeze_cursors
export XCURSOR_SIZE=24

# User directories
[ -x /usr/bin/xdg-user-dirs-update ] && xdg-user-dirs-update --force

# Start keyring if available
if command -v gnome-keyring-daemon &>/dev/null; then
    eval "$(gnome-keyring-daemon --start --components=secrets,ssh,pkcs11)"
    export SSH_AUTH_SOCK
fi

# Launch KWin as Wayland compositor with our shell embedded
# If kwin_wayland is not available (e.g. X11 fallback), run shell directly
if command -v kwin_wayland &> /dev/null && [ "${XDG_SESSION_TYPE}" = "wayland" ]; then
    # Start KWin running our shell as the windowed interface
    exec kwin_wayland --no-lockscreen --no-global-shortcuts --exit-with-session=/usr/share/bright-os/bright-desktop-shell.py
else
    # Fallback: run shell directly on existing X/Wayland session
    exec /usr/share/bright-os/bright-desktop-shell.py
fi
